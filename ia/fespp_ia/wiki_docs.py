"""Articles of an open-licensed MediaWiki (the AAPG Wiki: petroleum geology,
CC BY-SA 3.0), fetched once AT INSTALL TIME into ia/corpus/<folder>
(git-ignored), for the RAG to read. The service never downloads anything.

    python -m fespp_ia.wiki_docs --api https://wiki.aapg.org/api.php --label "AAPG Wiki" \
        --license "CC BY-SA 3.0" --out /ia/corpus/geologie/aapg --cache /ia/corpus_cache/aapg

One article = one Markdown file: "# <label> › <title>", then its source
URL and licence (CC BY-SA asks for the title, a link and the licence: the
RAG cites the chunk title, the file keeps the link), then the article cut
on its own section headings. Left out: the table of contents, edit links,
footnote marks, reference lists and the "References", "See also" and
"External links" sections.

--titles <file> keeps only the articles listed there (one title a line,
"#" starts a comment line): a targeted selection instead of the whole wiki.
Polite: WORKERS workers, DELAY seconds between two requests of a worker,
the raw pages cached (a re-run fetches nothing).
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "fespp_ia-docs/1.0 (local documentation index of an internal viewer)"
DELAY = 0.5
WORKERS = 2
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
         "track", "wbr"}
_SKIP_TAGS = {"script", "style", "sup", "math"}
_SKIP_CLASSES = {"toc", "mw-editsection", "reference", "references", "reflist", "navbox", "noprint",
                 "printfooter", "catlinks", "mw-empty-elt", "thumb", "gallery", "mw-references-wrap"}
_STOP_SECTIONS = re.compile(r"^(references?|see also|external links?|further reading|related articles?|notes)$",
                            re.I)
_BLOCK_END = {"p", "li", "dd", "dt", "tr", "div", "blockquote", "pre", "table", "ul", "ol", "dl"}


class ArticleText(HTMLParser):
    """The readable text of a rendered MediaWiki article: headings as
    Markdown "##", paragraphs, list items, table rows (cells " | ").
    A subclass tunes what is skipped and where the article stops (the
    Wikipedia fetcher, whose chrome is richer)."""
    skip_tags = _SKIP_TAGS
    skip_classes = _SKIP_CLASSES
    stop_sections = _STOP_SECTIONS

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self._stack = []
        self._cur = []
        self._cells = None
        self._heading = None
        self._stopped = False

    def _skipping(self):
        return self._stopped or (bool(self._stack) and self._stack[-1][1])

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._cur)).strip()
        self._cur = []
        if text and text != "-":
            self.lines.append(text)

    def handle_starttag(self, tag, attrs):
        cls = set((dict(attrs).get("class") or "").split())
        skip = self._skipping() or tag in self.skip_tags or bool(cls & self.skip_classes)
        if tag not in _VOID:
            self._stack.append((tag, skip))
        if skip:
            return
        if tag in ("h2", "h3", "h4"):
            self._flush()
            self._heading = tag
        elif tag == "tr":
            self._flush()
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._cur = []
        elif self._cells is not None:
            self._cur.append(" ")
        elif tag == "li":
            self._flush()
            self._cur.append("- ")
        elif tag == "br":
            self._flush()

    def handle_endtag(self, tag):
        skipping = self._skipping()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if skipping:
            return
        if tag == self._heading:
            head = re.sub(r"\s+", " ", "".join(self._cur)).strip()
            self._cur = []
            self._heading = None
            if self.stop_sections.match(head):
                self._stopped = True        # the rest is references and links
            elif head:
                self.lines.append("#" * (2 if tag == "h2" else 3) + " " + head)
            return
        if tag in ("td", "th") and self._cells is not None:
            self._cells.append(re.sub(r"\s+", " ", "".join(self._cur)).strip())
            self._cur = []
        elif tag == "tr" and self._cells is not None:
            row = " | ".join(c for c in self._cells if c)
            self._cells = None
            if row and not re.match(r"^(Link|Store) \|", row):   # the infobox's shop links
                self.lines.append(row)
        elif self._cells is not None:
            self._cur.append(" ")
        elif tag in _BLOCK_END:
            self._flush()

    def handle_data(self, data):
        if not self._skipping():
            self._cur.append(data)

    def close(self):
        super().close()
        self._flush()


def article_markdown(title, rendered_html, label, url, license_name, parser=ArticleText):
    """The Markdown file of one article, or None when it says almost nothing."""
    p = parser()
    p.feed(rendered_html)
    p.close()
    body = [ln for ln in p.lines if ln.strip()]
    if sum(len(ln) for ln in body if not ln.startswith("#")) < 200:
        return None
    head = f"# {label} › {title}\n\nSource : {label}, {url} — licence {license_name} (auteurs : historique de la page)\n\n"
    return head + "\n\n".join(body) + "\n"


def api_get(api, params, retries=5):
    """The JSON answer of one MediaWiki API call, retried on any error."""
    url = api + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"[wiki] retry {params.get('page') or params.get('list')}: {exc}", file=sys.stderr)
            # Wikipedia answers 429 to an anonymous client that goes too
            # fast: wait what it asks (Retry-After), else longer each time
            wait = 2 * (attempt + 1)
            if getattr(exc, "code", None) == 429:
                try:
                    wait = max(15 * (attempt + 1), int(exc.headers.get("Retry-After", 0)))
                except (TypeError, ValueError):
                    wait = 15 * (attempt + 1)
            time.sleep(wait)


def all_titles(api):
    """Every article (namespace 0, redirects left out) of the wiki."""
    titles, cont = [], {}
    while True:
        d = api_get(api, {"action": "query", "list": "allpages", "apnamespace": 0,
                          "apfilterredir": "nonredirects", "aplimit": 500, **cont})
        titles += [p["title"] for p in d["query"]["allpages"]]
        if "continue" not in d:
            return titles
        cont = {k: v for k, v in d["continue"].items() if k != "continue"}
        time.sleep(DELAY)


def safe_name(title):
    """A file name for a title: ASCII letters, digits, ".", "_" and "-", at most 120 characters."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_")[:120] or "page"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch the articles of an open-licensed MediaWiki for the RAG.")
    ap.add_argument("--api", required=True, help="the wiki's api.php")
    ap.add_argument("--label", required=True, help="how the chunks name the source, e.g. 'AAPG Wiki'")
    ap.add_argument("--license", required=True, help="the licence of the wiki's text, e.g. 'CC BY-SA 3.0'")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--titles", help="a file with one title a line: only those articles")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.cache, exist_ok=True)
    base = a.api.rsplit("/api.php", 1)[0]

    tpath = os.path.join(a.cache, "_titles.json")
    if not os.path.exists(tpath):
        json.dump(all_titles(a.api), open(tpath, "w", encoding="utf-8"), ensure_ascii=False)
    titles = json.load(open(tpath, encoding="utf-8"))
    if a.titles:
        wanted = [ln.strip() for ln in open(a.titles, encoding="utf-8") if ln.strip() and not ln.startswith("#")]
        known = set(titles)
        missing = [t for t in wanted if t not in known]
        if missing:
            print(f"[wiki] not in the wiki, skipped: {missing}", file=sys.stderr)
        titles = [t for t in wanted if t in known]

    def cpath(title):
        return os.path.join(a.cache, safe_name(title) + ".json")

    def get(title):
        if os.path.exists(cpath(title)):
            return
        d = api_get(a.api, {"action": "parse", "page": title, "prop": "text", "disabletoc": 1,
                            "disableeditsection": 1})
        tmp = cpath(title) + ".part"
        json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, cpath(title))
        time.sleep(DELAY)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for n, _ in enumerate(pool.map(get, titles), 1):
            if n % 100 == 0:
                print(f"[wiki] {n}/{len(titles)} articles fetched", flush=True)

    written = empty = 0
    for title in titles:
        d = json.load(open(cpath(title), encoding="utf-8"))
        rendered = d.get("parse", {}).get("text", {}).get("*", "")
        url = f"{base}/{urllib.parse.quote(title.replace(' ', '_'))}"
        md = article_markdown(title, rendered, a.label, url, a.license)
        if not md:
            empty += 1
            continue
        with open(os.path.join(a.out, safe_name(title) + ".md"), "w", encoding="utf-8") as f:
            f.write(md)
        written += 1
    print(f"[wiki] {written} articles written, {empty} too short, from {len(titles)} titles -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
