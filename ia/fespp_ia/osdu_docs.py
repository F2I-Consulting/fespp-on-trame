"""The OSDU Data Definitions documentation (The Open Group OSDU Forum,
Apache-2.0) -- the schema usage guide, its glossary and its worked
examples -- fetched once AT INSTALL TIME into ia/corpus/osdu (git-ignored)
for the RAG to read. The service never downloads anything.

    python -m fespp_ia.osdu_docs --out /corpus/osdu --cache /cache/osdu_raw [--ref release/0.19]

Why: the application can load its data from an OSDU Reservoir DDMS over
ETP; the OSDU vocabulary (work-product-component, master data, reference
data, Wellbore, vertical measurements, frame of reference) and its mapping
of the RESQML objects to the OSDU types are what a question about the
platform needs.

What is taken: Guides/Chapters (the usage guide; the references, proposals
and schema list are left out), the glossary (one "### term" section per
entry, the links to the schema pages reduced to the type names), and the
README of every worked example (Examples/WorkedExamples). Left out: the
thousands of schema pages (E-R/), the migration guides, the JSON of the
examples. The web site answers scripted clients with a browser check, the
GitLab API does not, so the files are read through the API. The raw files
are cached: a re-run fetches nothing.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://community.opengroup.org/api/v4/projects/osdu%2Fdata%2Fdata-definitions"
SITE = "https://community.opengroup.org/osdu/data/data-definitions"
UA = "fespp_ia-docs/1.0 (local documentation index of an internal viewer)"
DELAY = 0.3
LICENSE = "Apache-2.0"
# chapters that are lists, not prose: the references, the proposals, the
# table of every schema
_SKIP_CHAPTERS = re.compile(r"^(90|92|93)-")
# a fenced block longer than this is a JSON record of an example: dropped
_CODE_LINES = 12

# the inline Markdown/HTML that inline() strips, the navigation lines of the
# guide's pages, and the entities the guide uses
_ANCHOR = re.compile(r"<a\s+name=\"[^\"]*\"\s*>\s*</a>", re.I)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_NAV = re.compile(r"^\s*(Previous Chapter:|Quick Navigation:|\[\[_TOC_\]\]|Return to the |Next Chapter:|Browse to the )", re.I)
_ENTITIES = {"&rarr;": "→", "&larr;": "←", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ", "&quot;": '"'}


def api_get(url, retries=4):
    """The body of a GET on `url`, as bytes, retried with a growing pause;
    the last failure is raised."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"[osdu] retry {url}: {exc}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))


def tree(path, ref):
    """Every Markdown file under `path` of the repository at `ref`,
    recursively, read page by page from the GitLab tree API."""
    files, page = [], 1
    while True:
        q = urllib.parse.urlencode({"path": path, "ref": ref, "recursive": "true", "per_page": 100, "page": page})
        rows = json.loads(api_get(f"{API}/repository/tree?{q}"))
        files += [r["path"] for r in rows if r.get("type") == "blob" and r["path"].endswith(".md")]
        if len(rows) < 100:
            return files
        page += 1
        time.sleep(DELAY)


def raw(path, ref, cache):
    """The file's text at `ref`, from the cache when it is there, else
    fetched and written to the cache."""
    local = os.path.join(cache, ref.replace("/", "_"), path)
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return f.read()
    q = urllib.parse.quote(path, safe="")
    text = api_get(f"{API}/repository/files/{q}/raw?ref={urllib.parse.quote(ref, safe='')}").decode("utf-8")
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w", encoding="utf-8") as f:
        f.write(text)
    time.sleep(DELAY)
    return text


def inline(text):
    """Markdown/HTML of a line down to plain text: links to their label,
    images, anchors, tags and bold marks out, the few entities the guide
    uses decoded."""
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = _ANCHOR.sub("", text)
    text = _TAG.sub("", text).replace("**", "")
    for k, v in _ENTITIES.items():
        text = text.replace(k, v)
    return text


def clean_markdown(text):
    """A guide page for the corpus: navigation lines and the closing
    "Links" section out, long fenced blocks (JSON records) replaced by a
    mention, table cells unpadded, links reduced to their label."""
    out, fence, block = [], None, []
    for line in text.splitlines():
        if fence is not None:
            if line.strip().startswith("```"):
                if len(block) <= _CODE_LINES:
                    out += [fence] + block + ["```"]
                else:
                    out.append("(exemple JSON omis / JSON example left out)")
                fence, block = None, []
            else:
                block.append(line)
            continue
        if line.strip().startswith("```"):
            fence = line.strip()
            continue
        if re.match(r"^#{1,6}\s+Links\s*$", line.strip()):
            break
        line = inline(line)
        if _NAV.match(line) or line.strip() == "---":
            continue
        if line.lstrip().startswith("|"):
            line = re.sub(r"\s{2,}", " ", line)
            if re.fullmatch(r"\|?[\s:|-]+\|?", line.strip()):
                continue
        out.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# a glossary entry: a bullet whose whole line is a bold term
_ENTRY = re.compile(r"^\*\s+\*\*(.+?)\*\*\s*(?:<br\s*/?>)?\s*$")


def glossary_markdown(text, header):
    """(markdown, number of entries) of the glossary: `header`, then one
    "### term" section per entry with its definition and the OSDU types it
    points at, by name. An entry without a definition is left out of the
    Markdown but counted."""
    entries, current = [], None
    for line in text.splitlines():
        m = _ENTRY.match(line.strip())
        if m:
            current = [inline(m.group(1)).strip(), []]
            entries.append(current)
            continue
        if current is None or not line.strip() or line.lstrip().startswith(("<a name", "Quick Navigation", "##")):
            continue
        body = inline(line).strip()
        body = body.replace("_OSDU types/schemas:_", "Types OSDU :").replace("→ ", "")
        if body:
            current[1].append(body.replace("_", ""))
    parts = [header]
    for term, lines in entries:
        if lines:
            parts.append(f"### {term}\n\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n", len(entries)


def page_name(path):
    """The output file name of a page: a README is named after its folder,
    any other page after its file; unsafe characters become "_"."""
    base = path.split("/")
    if base[-1].lower() == "readme.md" and len(base) > 1:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", base[-2]) + ".md"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", base[-1])


def source_line(path, ref):
    """The attribution written under the title of every page: source,
    release, URL of the original file and licence."""
    return (f"Source : OSDU Data Definitions ({ref}), The Open Group OSDU Forum, "
            f"{SITE}/-/blob/{ref}/{urllib.parse.quote(path)} — licence {LICENSE}")


def main(argv=None):
    """Fetch the chapters and worked examples and write one Markdown file
    per page (a page shorter than 200 characters once cleaned is skipped)."""
    ap = argparse.ArgumentParser(description="Fetch the OSDU Data Definitions guide, glossary and worked examples.")
    ap.add_argument("--out", required=True, help="ia/corpus/osdu")
    ap.add_argument("--cache", required=True, help="where the raw files are kept (re-runs read them)")
    ap.add_argument("--ref", default="release/0.19")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    chapters = [p for p in tree("Guides/Chapters", a.ref) if p.count("/") == 2
                and not _SKIP_CHAPTERS.match(os.path.basename(p))]
    examples = [p for p in tree("Examples/WorkedExamples", a.ref) if os.path.basename(p).lower() == "readme.md"]
    written, chars = 0, 0
    for path in chapters + examples:
        text = raw(path, a.ref, a.cache)
        if path.endswith("91-Glossary.md"):
            md, n = glossary_markdown(text, "# OSDU — glossaire\n\n" + source_line(path, a.ref))
            name = "glossaire-osdu.md"
            print(f"[osdu] glossary: {n} entries", flush=True)
        else:
            body = clean_markdown(text)
            if len(body) < 200:
                continue
            if not body.lstrip().startswith("# "):
                title = "OSDU — " + os.path.splitext(page_name(path))[0].replace("_", " ")
                body = f"# {title}\n\n{body}"
            first, _, rest = body.partition("\n")
            md = f"{first}\n\n{source_line(path, a.ref)}\n{rest}\n"
            name = ("exemple-" if path.startswith("Examples/") else "") + page_name(path)
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            f.write(md)
        written += 1
        chars += len(md)
    print(f"[osdu] {len(chapters)} chapters + {len(examples)} worked examples -> {written} files, "
          f"{chars} characters -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
