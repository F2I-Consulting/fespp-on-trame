"""The PWLS 4.0 property-kind dictionary, written once AT INSTALL TIME as
Markdown into ia/corpus/pwls (git-ignored), for the RAG to read. The
service never reads the EPC.

    python3 -m fespp_ia.pwls_docs <eml23_pwls40.epc> ia/corpus/pwls

PWLS 4.0 (Practical Well Log Standard) is the Energistics dictionary of the
kinds a RESQML property names: some 3 900 PropertyKind parts in one EPC,
each with a title, a definition, its aliases (PWLS v1, PWLS v2, the RESQML
2.0.1 enumeration), a parent kind and a quantity class. The parts are read
the way scripts/gen_pwls_kinds.py derives the app's hierarchy from the same
file: zipfile + regex, no fesapi -- they are small and regular.

One kind = one "### <title>" section of one to four lines (definition,
"Alias : ...", "Parent : ... ; classe de grandeur : ..."), the kinds split
by the first letter of their title into 21 files headed "# PWLS 4.0 -- P-Q":
the corpus builder cuts a Markdown file on its headings, so a kind is one
chunk titled "PWLS 4.0 -- P-Q › porosity". The H1 stays short because it
prefixes every chunk. An abstract kind without a definition is left out.
The folder's files are rewritten on each run.

Licence: the Energistics Product License Agreement
(https://www.energistics.org/product-license-agreement), free use with
Energistics named as the source -- each file says so in its header line.
"""
import html
import os
import re
import sys
import zipfile

SOURCE_LINE = ("Source : Energistics, PWLS 4.0 (Practical Well Log Standard), https://www.energistics.org/ "
               "-- Energistics Product License Agreement : free use, Energistics cited as the source.")
# the files, by the first character of the title: the rare letters grouped
# (J, Q and X hold only a handful of kinds each) and the few titles that
# start with a digit put with A, so that no file is tiny -- the corpus
# builder reads a small Markdown file as ONE chunk whatever its headings
GROUPS = (("A", "0123456789A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"), ("F", "F"), ("G", "G"),
          ("H", "H"), ("I-J", "IJ"), ("K-L", "KL"), ("M", "M"), ("N", "N"), ("O", "O"), ("P-Q", "PQ"),
          ("R", "R"), ("S", "S"), ("T", "T"), ("U", "U"), ("V", "V"), ("W", "W"), ("X-Z", "XYZ"))
_GROUP_OF = {c: label for label, chars in GROUPS for c in chars}

# the EPC holds the part namespace_eml23/PropertyKind_<uuid>.xml and, next
# to it, its .rels: only the XML is a kind
_PART = re.compile(r"PropertyKind_[0-9a-fA-F-]{36}\.xml$")
# the fields of a part; the title and description are read inside its
# Citation, the parent's title and uuid inside its Parent
_UUID = re.compile(r'uuid="([0-9a-fA-F-]{36})"')
_CITATION = re.compile(r"<eml23:Citation\b.*?</eml23:Citation>", re.S)
_TITLE = re.compile(r"<eml23:Title[^>]*>([^<]*)</eml23:Title>")
_DESCRIPTION = re.compile(r"<eml23:Description[^>]*>([^<]*)</eml23:Description>")
_ALIAS = re.compile(r"<eml23:Aliases\b([^>]*)>(.*?)</eml23:Aliases>", re.S)
_AUTHORITY = re.compile(r'authority="([^"]*)"')
_IDENTIFIER = re.compile(r"<eml23:Identifier[^>]*>([^<]*)</eml23:Identifier>")
_PARENT = re.compile(r"<eml23:Parent\b.*?</eml23:Parent>", re.S)
_PARENT_UUID = re.compile(r"<eml23:Uuid[^>]*>([0-9a-fA-F-]{36})</eml23:Uuid>")
_QUANTITY = re.compile(r"<eml23:QuantityClass[^>]*>([^<]*)<")
_ABSTRACT = re.compile(r"<eml23:IsAbstract[^>]*>\s*true\s*<")


def _text(pattern, xml):
    """The first group of `pattern` in `xml`, entities decoded and stripped;
    "" when it does not match."""
    m = pattern.search(xml)
    return html.unescape(m.group(1)).strip() if m else ""


def read_kinds(epc_path):
    """[kind] for every PropertyKind part of the EPC, in file order -- a
    dict: title, description, aliases [(authority, identifier)], parent
    (its title; None for the root, which names itself), quantity_class,
    abstract. A part without a citation title is skipped."""
    kinds = []
    with zipfile.ZipFile(epc_path) as z:
        for name in z.namelist():
            if not _PART.search(name):
                continue
            xml = z.read(name).decode("utf-8", "replace")
            citation, uuid = _CITATION.search(xml), _UUID.search(xml)
            if not citation or not uuid:
                continue
            title = _text(_TITLE, citation.group(0))
            if not title:
                continue
            parent_title = None
            parent = _PARENT.search(xml)
            if parent and _text(_PARENT_UUID, parent.group(0)).lower() != uuid.group(1).lower():
                parent_title = _text(_TITLE, parent.group(0)) or None
            aliases = []
            for attrs, body in _ALIAS.findall(xml):
                identifier = _text(_IDENTIFIER, body)
                if identifier:
                    aliases.append((_text(_AUTHORITY, attrs), identifier))
            kinds.append({"title": title, "description": _text(_DESCRIPTION, citation.group(0)),
                          "aliases": aliases, "parent": parent_title,
                          "quantity_class": _text(_QUANTITY, xml), "abstract": bool(_ABSTRACT.search(xml))})
    return kinds


def alias_line(aliases):
    """"Alias : Porosity (PWLS v1, PWLS v2), porosity (RESQML 2.0.1)": each
    identifier once, with the standards that use it ("Energistics:" is
    every authority's prefix, dropped); "" without an alias."""
    standards = {}
    for authority, identifier in aliases:
        short = authority.split(":", 1)[-1].strip()
        used = standards.setdefault(identifier, [])
        if short and short not in used:
            used.append(short)
    if not standards:
        return ""
    return "Alias : " + ", ".join(f"{i} ({', '.join(s)})" if s else i for i, s in standards.items())


def kind_markdown(kind):
    """The "### <title>" section of one kind -- its definition, its
    aliases, its parent and quantity class -- or "" for an abstract kind
    that says nothing (a node of the hierarchy, defined by its children)."""
    if kind["abstract"] and not kind["description"]:
        return ""
    lines = [f"### {kind['title']}"]
    if kind["description"]:
        lines.append(kind["description"])
    alias = alias_line(kind["aliases"])
    if alias:
        lines.append(alias)
    lineage = []
    if kind["parent"]:
        lineage.append(f"Parent : {kind['parent']}")
    if kind["quantity_class"]:
        lineage.append(f"classe de grandeur : {kind['quantity_class']}")
    if lineage:
        lines.append(" ; ".join(lineage))
    return "\n".join(lines) + "\n"


def group_of(title):
    """The file a kind goes to (GROUPS), by the first character of its
    title; "A" for a title that starts with none of them."""
    return _GROUP_OF.get(title[:1].upper(), "A")


def write_files(kinds, out_dir):
    """One pwls-<group>.md per group in `out_dir`, the kinds sorted by
    title; the pwls*.md of a previous run are removed first. Returns
    {file name: number of kinds written}."""
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        if name.startswith("pwls") and name.endswith(".md"):
            os.remove(os.path.join(out_dir, name))
    groups = {}
    for kind in sorted(kinds, key=lambda k: k["title"].lower()):
        section = kind_markdown(kind)
        if section:
            groups.setdefault(group_of(kind["title"]), []).append(section)
    counts = {}
    for group, sections in sorted(groups.items()):
        name = f"pwls-{group.lower()}.md"
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(f"# PWLS 4.0 -- {group}\n\n{SOURCE_LINE}\n\n" + "\n".join(sections))
        counts[name] = len(sections)
    return counts


def main(argv=None):
    """Command line: read the EPC, write the files, return the exit status."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python3 -m fespp_ia.pwls_docs <eml23_pwls40.epc> <out_dir>", file=sys.stderr)
        return 2
    epc, out_dir = argv
    kinds = read_kinds(epc)
    counts = write_files(kinds, out_dir)
    written = sum(counts.values())
    chars = sum(os.path.getsize(os.path.join(out_dir, name)) for name in counts)
    print(f"[pwls] {written} kinds of {len(kinds)} in {len(counts)} files ({chars} bytes) -> {out_dir}; "
          f"largest: " + ", ".join(f"{n} {c}" for n, c in sorted(counts.items(), key=lambda kv: -kv[1])[:3]),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
