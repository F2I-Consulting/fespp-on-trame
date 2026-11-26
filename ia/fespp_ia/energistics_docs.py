"""The official Energistics documentation, fetched once AT INSTALL TIME into
ia/corpus/energistics (git-ignored), for the RAG to read. The service never
downloads anything.

    python -m fespp_ia.energistics_docs --out /ia/corpus/energistics --cache /ia/corpus_cache/eo_html

What it takes, all public and without an account:

- Energistics Online (https://docs.energistics.org), the documentation of
  RESQML v2.0.1 -- the version the application reads -- with Energistics
  common v2.0, EPC v1.0 and the Common Technical Architecture. Its reference
  topics are generated from the UML/XSD model: one topic per class, with its
  definition, its attributes (name, type, notes), its parent class and its
  relationships -- the content of the XSD schemas, in the right version.
  One topic becomes one Markdown file "# <standard> › <topic title>".
- Two PDF specifications linked from Energistics Online: ETP v1.2 (the
  protocol the application speaks; skipped when the official ETP package
  sits in ia/corpus, see PDFS) and the Energistics Unit of Measure Usage
  Guide. The corpus builder reads them page by page.

Licence: Energistics material is free to use under the Energistics Product
License Agreement (https://www.energistics.org/product-license-agreement);
"anyone may copy and share the materials but must always acknowledge
Energistics as the source" -- every chunk carries its source URL, and the
files stay out of git. The official XSD packages (RESQML v2.2, ETP) sit
behind a free Open Group account: drop the zip in ia/corpus and the corpus
builder reads the XSD inside it.
"""
import argparse
import html
import os
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

EO = "https://docs.energistics.org/"
FAMILIES = {
    "RESQML": "RESQML v2.0.1",
    "ECOM2": "Energistics common v2.0",
    "EPC": "EPC v1.0",
    "CTA": "Energistics Common Technical Architecture",
}
# (url, file name, a glob in ia/corpus that makes it redundant): the official
# ETP package, when dropped, carries a newer revision of the same specification
PDFS = [
    ("https://docs.energistics.org/EO_Resources/ETP_Specification_v1.2_Doc_v1.1.pdf",
     "ETP_Specification_v1.2.pdf", "etp*.zip"),
    ("https://docs.energistics.org/EO_Resources/Energistics_Unit_of_Measure_Usage_Guide_v1.pdf",
     "Energistics_Unit_of_Measure_Usage_Guide_v1.pdf", None),
]
UA = "fespp_ia-docs/1.0 (local documentation index of an internal viewer)"
DELAY = 0.3
WORKERS = 4

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
         "track", "wbr"}
_SKIP_TAGS = {"script", "style", "head", "noscript", "button", "svg"}
_SKIP_CLASSES = ("topicMeta", "changehistory", "navfooter", "nav", "related-links", "familylinks")
_BLOCK_END = {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "caption", "pre", "div",
              "figcaption", "section", "table", "ul", "ol", "dl"}
_DROP_LINE = re.compile(r"^(Parent topic\b|Stereotypes:|Topic Version\b|Figure \d)", re.I)


class TopicText(HTMLParser):
    """The useful text of one Energistics Online topic: its title, then
    every paragraph, list item and table row of its body, one per line
    (table cells joined by " | "). The navigation, the topic metadata and
    the change history are skipped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.lines = []
        self._stack = []          # (tag, skipping)
        self._capture = False     # starts at the topic title
        self._in_title = False
        self._cur = []
        self._cells = None

    def _skipping(self):
        return bool(self._stack) and self._stack[-1][1]

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._cur)).strip()
        self._cur = []
        if text and text != "-" and not _DROP_LINE.match(text):
            self.lines.append(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        skip = (self._skipping() or tag in _SKIP_TAGS
                or any(c in cls.split() for c in _SKIP_CLASSES))
        if tag == "h1" and "topictitle1" in cls:
            self._capture = True
            self._in_title = True
        if tag not in _VOID:
            self._stack.append((tag, skip))
        if not self._capture or skip:
            return
        if tag == "tr":
            self._flush()
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._cur = []
        elif self._cells is not None:
            # inside a table cell: its paragraphs and breaks stay in the cell
            self._cur.append(" ")
        elif tag == "li":
            self._flush()
            self._cur.append("- ")
        elif tag == "br":
            self._flush()

    def handle_endtag(self, tag):
        skipping = self._skipping()
        # pop up to the matching tag (tolerant of a missing close)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if not self._capture or skipping:
            return
        if tag == "h1" and self._in_title:
            self.title = re.sub(r"\s+", " ", "".join(self._cur)).strip()
            self._cur = []
            self._in_title = False
            return
        if tag in ("td", "th") and self._cells is not None:
            self._cells.append(re.sub(r"\s+", " ", "".join(self._cur)).strip())
            self._cur = []
        elif tag == "tr" and self._cells is not None:
            row = " | ".join(c for c in self._cells if c)
            self._cells = None
            if row:
                self.lines.append(row)
        elif self._cells is not None:
            self._cur.append(" ")
        elif tag in _BLOCK_END:
            self._flush()

    def handle_data(self, data):
        if self._capture and not self._skipping():
            self._cur.append(data)


def topic_markdown(raw_html, standard, url):
    """(title, markdown) of one topic, or (None, None) when it has no body."""
    p = TopicText()
    p.feed(raw_html)
    p.close()
    if not p.title:
        return None, None
    body = [ln for ln in p.lines if ln != p.title]
    if not body:
        return None, None
    title = f"{standard} › {p.title}"
    return title, f"# {title}\n\nSource : Energistics, {url}\n\n" + "\n\n".join(body) + "\n"


def nav_topics(root_html, families=FAMILIES):
    """[(family, relative url, link text)] of every topic of the chosen
    families, in the order of the navigation tree of Energistics Online."""
    out, seen = [], set()
    pat = re.compile(r'href="((%s)/\2_TOPICS/[^"#]+\.html)"[^>]*>([^<]*)<' % "|".join(families))
    for m in pat.finditer(root_html):
        rel = m.group(1)
        if rel in seen:
            continue
        seen.add(rel)
        out.append((m.group(2), rel, html.unescape(m.group(3)).strip()))
    return out


def fetch(url, retries=3):
    """The bytes at `url`, retried with a growing pause on any error."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"[docs] retry {url}: {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch the public Energistics documentation for the RAG.")
    ap.add_argument("--out", required=True, help="ia/corpus/energistics")
    ap.add_argument("--cache", required=True, help="where the raw HTML pages are kept (re-runs read them)")
    ap.add_argument("--families", default=",".join(FAMILIES), help="comma list among " + ", ".join(FAMILIES))
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="at most N topics per family (tests)")
    a = ap.parse_args(argv)
    fams = {k: FAMILIES[k] for k in a.families.split(",") if k in FAMILIES}
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.cache, exist_ok=True)

    root_path = os.path.join(a.cache, "_root.html")
    if not os.path.exists(root_path):
        open(root_path, "wb").write(fetch(EO))
    topics = nav_topics(open(root_path, encoding="utf-8", errors="replace").read(), fams)
    per, chosen = {}, []
    for fam, rel, _text in topics:
        per[fam] = per.get(fam, 0) + 1
        if not a.limit or per[fam] <= a.limit:
            chosen.append((fam, rel))

    def cache_path(rel):
        return os.path.join(a.cache, rel.replace("/", "__"))

    # the pages not cached yet, WORKERS at a time (the server is slow to
    # serve a page), each worker pausing DELAY between two of its requests
    missing = [rel for _fam, rel in chosen if not os.path.exists(cache_path(rel))]

    def get(rel):
        data = fetch(EO + rel)
        tmp = cache_path(rel) + ".part"
        open(tmp, "wb").write(data)
        os.replace(tmp, cache_path(rel))
        time.sleep(DELAY)

    fetched = 0
    if missing:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for _ in pool.map(get, missing):
                fetched += 1
                if fetched % 100 == 0:
                    print(f"[docs] {fetched}/{len(missing)} pages fetched", flush=True)

    written = empty = 0
    for fam, rel in chosen:
        cpath = cache_path(rel)
        title, md = topic_markdown(open(cpath, encoding="utf-8", errors="replace").read(), fams[fam], EO + rel)
        if not md:
            empty += 1
            continue
        folder = os.path.join(a.out, fam)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, os.path.basename(rel)[:-5] + ".md"), "w", encoding="utf-8") as f:
            f.write(md)
        written += 1
        if written % 100 == 0:
            print(f"[docs] {written} topics written ({fetched} fetched)", flush=True)
    print(f"[docs] topics: {written} written, {empty} without body, {fetched} fetched, "
          + ", ".join(f"{k} {v}" for k, v in per.items()), flush=True)

    if not a.no_pdf:
        import glob
        folder = os.path.join(a.out, "pdf")
        os.makedirs(folder, exist_ok=True)
        corpus_dir = os.path.dirname(os.path.abspath(a.out))
        for url, name, redundant_if in PDFS:
            path = os.path.join(folder, name)
            if redundant_if and glob.glob(os.path.join(corpus_dir, redundant_if)):
                if os.path.exists(path):
                    os.replace(path, os.path.join(a.cache, name))   # kept aside, out of the corpus
                print(f"[docs] {name}: skipped, the official package ({redundant_if}) carries it", flush=True)
                continue
            if not os.path.exists(path):
                open(path, "wb").write(fetch(url))
                time.sleep(DELAY)
            print(f"[docs] {name}: {os.path.getsize(path) // 1024} KB", flush=True)


if __name__ == "__main__":
    main()
