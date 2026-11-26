"""SWIG's manual (swig.org -- the documentation that ships with SWIG, under
SWIG's own licence, GPL-3.0-or-later) fetched once AT INSTALL TIME into
ia/corpus/swig (git-ignored), for the developer's corpus of the RAG
(fespp_ia.corpus --developer). The service never downloads anything.

    python -m fespp_ia.swig_docs --out /corpus/swig --cache /cache/swig_raw [--version 4.4]

Why: fesapi and fetpapi reach Python, Java and C# through SWIG. What a
typemap, a director or %nspace does is in this manual and nowhere in their
sources, which only use them.

What is taken (CHAPTERS): what a C++ library wrapped for Python, Java and
C# needs -- the introduction, SWIG's basics, its C++ support (C++11 to
C++20), the preprocessor, the library, argument handling, typemaps,
customization, contracts, variable arguments, Doxygen comments, warnings,
modules, and the three target languages. Left out: the other target
languages, the preface, the Windows and scripting primers, ccache, Android
and "Extending SWIG" (how to write a language module). One Markdown file
per chapter: the headings keep the manual's section numbers ("33.3.2
Functions"), the listings are indented code, the table of contents at the
head of a chapter is dropped. The raw pages are cached: a re-run fetches
nothing.
"""
import argparse
import os
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

SITE = "https://www.swig.org/"
UA = "fespp_ia-docs/1.0 (local documentation index of an internal viewer)"
DELAY = 0.3
LICENSE = "GPL-3.0-or-later"
CHAPTERS = ("Introduction", "SWIG", "SWIGPlus", "CPlusPlus11", "CPlusPlus14", "CPlusPlus17", "CPlusPlus20",
            "Preprocessor", "Library", "Arguments", "Typemaps", "Customization", "Contract", "Varargs",
            "Doxygen", "Warnings", "Modules", "CSharp", "Java", "Python")

# elements read past, whatever they hold, and the div classes read past
_SKIP_TAGS = {"head", "script", "style"}
_SKIP_CLASSES = {"sectiontoc"}
# where a paragraph of text ends
_BLOCK = {"p", "div", "ul", "ol", "dl", "dd", "dt", "li", "table", "tr", "blockquote", "center"}
_HEADING = re.compile(r"^h([1-6])$")


class ManualText(HTMLParser):
    """A chapter of the manual as Markdown blocks (`blocks`): a heading is
    "#" to "####" and its text, a <pre> listing is code indented by four
    spaces, a list item starts with "- ", the cells of a table row are
    joined by " | "; the rest is paragraphs of plain text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.text = []        # the paragraph being read
        self.pre = None       # the listing being read, None outside one
        self.level = 0        # the heading being read, 0 outside one
        self.bullet = ""
        self.skipped = None   # [tag, depth] of the element being read past

    def _flush(self):
        text = " ".join("".join(self.text).split())
        if text:
            self.blocks.append(self.bullet + text)
        self.text, self.bullet = [], ""

    def handle_starttag(self, tag, attrs):
        if self.skipped:
            if tag == self.skipped[0]:
                self.skipped[1] += 1
            return
        classes = set((dict(attrs).get("class") or "").split())
        if tag in _SKIP_TAGS or (tag == "div" and classes & _SKIP_CLASSES):
            self._flush()
            self.skipped = [tag, 1]
            return
        if self.pre is not None:
            return
        m = _HEADING.match(tag)
        if m:
            self._flush()
            self.level = int(m.group(1))
        elif tag == "pre":
            self._flush()
            self.pre = []
        elif tag in ("td", "th"):
            if "".join(self.text).strip():
                self.text.append(" | ")
        elif tag == "br":
            self.text.append(" ")
        elif tag in _BLOCK:
            self._flush()
            if tag == "li":
                self.bullet = "- "

    def handle_endtag(self, tag):
        if self.skipped:
            if tag == self.skipped[0]:
                self.skipped[1] -= 1
                if self.skipped[1] == 0:
                    self.skipped = None
            return
        if tag == "pre" and self.pre is not None:
            lines = "".join(self.pre).strip("\n").split("\n")
            if any(line.strip() for line in lines):
                self.blocks.append("\n".join(("    " + line.rstrip()) if line.strip() else "" for line in lines))
            self.pre = None
        elif self.pre is not None:
            return
        elif _HEADING.match(tag) and self.level:
            text = " ".join("".join(self.text).split())
            if text:
                self.blocks.append("#" * min(self.level, 4) + " " + text)
            self.text, self.level = [], 0
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if self.skipped:
            return
        if self.pre is not None:
            self.pre.append(data)
        else:
            self.text.append(data)


def chapter_markdown(raw_html, version, url):
    """The Markdown of one chapter, or "" when the page holds no chapter
    title: "# SWIG <version> manual — <chapter title>", the attribution
    line, then the chapter's sections."""
    p = ManualText()
    p.feed(raw_html)
    p.close()
    p._flush()
    blocks = p.blocks
    first = next((k for k, b in enumerate(blocks) if b.startswith("# ")), None)
    if first is None:
        return ""
    title = f"# SWIG {version} manual — {blocks[first][2:]}"
    source = f"Source : SWIG {version} Documentation, {url} — licence {LICENSE}"
    return "\n\n".join([title, source] + blocks[first + 1:]) + "\n"


def fetch(url, retries=3):
    """The page at `url`, as text, retried with a growing pause; the last
    failure is raised."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"[swig] retry {url}: {exc}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))


def page(chapter, version, cache):
    """(html, url) of a chapter, from the cache when it is there, else
    fetched and written to the cache."""
    url = f"{SITE}Doc{version}/{chapter}.html"
    local = os.path.join(cache, version, f"{chapter}.html")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return f.read(), url
    text = fetch(url)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w", encoding="utf-8") as f:
        f.write(text)
    time.sleep(DELAY)
    return text, url


def main(argv=None):
    """Fetch the chapters and write one Markdown file per chapter."""
    ap = argparse.ArgumentParser(description="Fetch SWIG's manual for the developer's corpus.")
    ap.add_argument("--out", required=True, help="ia/corpus/swig")
    ap.add_argument("--cache", required=True, help="where the raw pages are kept (re-runs read them)")
    ap.add_argument("--version", default="4.4", help="the manual's version, as in swig.org/Doc<version>/")
    ap.add_argument("--chapters", default=",".join(CHAPTERS), help="the chapters' page names, comma-separated")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    written, chars = 0, 0
    for chapter in [c.strip() for c in a.chapters.split(",") if c.strip()]:
        raw_html, url = page(chapter, a.version, a.cache)
        md = chapter_markdown(raw_html, a.version, url)
        if not md:
            print(f"[swig] {chapter}: no chapter title in the page, skipped", file=sys.stderr)
            continue
        with open(os.path.join(a.out, f"swig-{chapter}.md"), "w", encoding="utf-8") as f:
            f.write(md)
        written += 1
        chars += len(md)
    print(f"[swig] manual {a.version}: {written} chapters, {chars} characters -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
