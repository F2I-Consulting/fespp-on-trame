"""The FESPP plugin's own documentation, read from its source tree when the
corpus is built (corpus.build --fespp; nothing is written to disk):

- Energistics.xml, the ParaView server-manager description of the plugin's
  proxies (EPCReader, EPCCollector, the ETP store, the extractor, the
  writer): one chunk per proxy -- its label, its help, then one line per
  property with its documentation, its default and its enumerated values.
  These proxies are the ones the application drives, and the
  paraview.simple extraction run under pvpython does not load the plugin,
  so nothing else in the corpus says what "EPCCollector" or
  "TreeHierarchyMode" is;
- the headers of Plugin/Energistics (Mapping/*.h, vtk*.h): one chunk per
  class -- its @brief (it sits before the #includes in the Mapping headers,
  where corpus.cpp_doxygen would take a "#include" for its declaration) and
  one line per documented method (including the one-liners below the
  120-character floor under which cpp_doxygen drops a block);
- Tools/enum.h: one chunk per enum, every value with its integer and its
  // comment -- TreeViewNodeType is the typeCode the application reads on
  every node of the data assembly.
"""
import os
import re
import xml.etree.ElementTree as ET

from fespp_ia.corpus import CHUNK, _read

# a Doxygen block ("/**" then a space or a newline) and the declaration
# that follows it; the leading "* " of its lines
_DOXY = re.compile(r"/\*\*(?=\s)(.*?)\*/\s*([^\n;{}]*)", re.S)
_STRIP = re.compile(r"^\s*\*\s?", re.M)
_ENUM = re.compile(r"((?:^[ \t]*//[^\n]*\n)*)[ \t]*enum\s+class\s+(\w+)\s*\{(.*?)\};", re.S | re.M)
_ENUMERATOR = re.compile(r"^\s*(\w+)\s*(?:=\s*(\d+))?\s*,?\s*$")
# the bookkeeping notes of enum.h, not a value's meaning
_ENUM_NOISE = re.compile(r"^(Appended on purpose|KEEP LAST)", re.I)
# the longest method summary, in characters: a longer one is cut at a word
_ONE_LINER = 160
# the folders of Plugin/Energistics whose headers are read ("." for the
# vtk*.h at the top)
HEADERS = ("Mapping", "Tools", ".")


def _norm(s):
    """The text on one line, runs of whitespace collapsed; "" for None."""
    return re.sub(r"\s+", " ", s or "").strip()


def cut_lines(lines, size=CHUNK):
    """The lines grouped in pieces of about `size` characters, a line
    never split (a property's documentation stays whole)."""
    out, cur = [], []
    for line in lines:
        if cur and sum(len(x) + 1 for x in cur) + len(line) > size:
            out.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    if len(out) > 1 and len(out[-1]) < size // 4:
        out[-2] += "\n" + out.pop()      # a short tail joins the piece before it
    return out


def _pieces(source, path, title, lines):
    """The chunk dicts of one document: its lines cut in pieces, each piece
    numbered in its title when there are several. The title also heads the
    text of every piece, so the search weighs it twice."""
    pieces = cut_lines(lines)
    for k, piece in enumerate(pieces, 1):
        t = title if len(pieces) == 1 else f"{title} ({k})"
        yield {"source": source, "path": path, "title": t, "text": f"{title}\n\n{piece}"}


def _property_line(el):
    """(line, says) for a property of a proxy: one line with its label,
    what marks it (read-only, default, enumerated values) and its
    documentation; `says` is true when it has a documentation or
    enumerated values."""
    name = el.get("name")
    label = el.get("label") or name
    marks = []
    if el.get("information_only") == "1":
        marks.append("read-only")
    if el.get("default_values") is not None:
        marks.append(f"default {el.get('default_values')}")
    enum = el.find("EnumerationDomain")
    if enum is not None:
        marks.append("values " + ", ".join(f"{e.get('value')} = {e.get('text')}" for e in enum.findall("Entry")))
    doc = el.find("Documentation")
    text = _norm("".join(doc.itertext())) if doc is not None else ""
    head = label if label == name else f"{label} ({name})"
    if marks:
        head += " [" + "; ".join(marks) + "]"
    return (f"- {head}: {text}" if text else f"- {head}"), bool(text or enum is not None)


def xml_chunks(xml, path="Plugin/Energistics/Energistics.xml"):
    """The chunks of a server-manager XML (a path, or the XML text itself):
    one per proxy, titled "FESPP plugin › <label>"."""
    text = xml if xml.lstrip().startswith("<") else _read(xml)
    if not text.strip():
        return
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        print(f"[fespp_docs] {path}: {exc}")
        return
    for group in root.iter("ProxyGroup"):
        kind = (group.get("name") or "").rstrip("s")
        for proxy in group:
            name = proxy.get("name")
            if not proxy.tag.endswith("Proxy") or not name:
                continue
            label = proxy.get("label") or name
            title = f"FESPP plugin › {label}"
            head = f"{label}: ParaView {kind} {name}"
            if proxy.get("class"):
                head += f" (class {proxy.get('class')})"
            lines = [head]
            doc = proxy.find("Documentation")
            if doc is not None:
                # the short help is usually the first sentence of the text:
                # a help repeated inside another is left out
                helps = [_norm(s) for s in (doc.get("short_help"), doc.get("long_help"), "".join(doc.itertext()))]
                for s in helps:
                    if s and s not in lines and not any(s in o for o in helps if o != s):
                        lines.append(s)
            documented, others = [], []
            for el in proxy:
                if not el.tag.endswith("Property") or not el.get("name"):
                    continue
                line, says = _property_line(el)
                if says:
                    documented.append(line)
                else:
                    others.append(el.get("label") or el.get("name"))
            if documented:
                lines.append("Properties:")
                lines.extend(documented)
            if others:
                lines.append("Other properties: " + ", ".join(others))
            yield from _pieces("fespp", f"{path}#{name}", title, lines)


def _one_liner(body):
    """The first sentence of a Doxygen body, on one line."""
    s = _norm(re.sub(r"@brief\s*", "", body))
    s = re.split(r"(?<=[.!?])\s+", s, 1)[0]
    return s if len(s) <= _ONE_LINER else s[:_ONE_LINER].rsplit(" ", 1)[0] + "…"


def header_summary(text, name):
    """[lines] summing up one header: the class (the file's stem), its
    @brief -- the last Doxygen block above its declaration -- its base
    class, then one line per documented method. None when the header
    declares no such class and documents nothing."""
    stem = os.path.splitext(name)[0]
    decl = re.search(r"\bclass\s+(?:\w+_EXPORT\s+)?" + re.escape(stem) + r"\b([^{;]*)\{", text)
    at = decl.start() if decl else len(text)
    brief, methods = "", []
    for m in _DOXY.finditer(text):
        body = _STRIP.sub("", m.group(1)).strip()
        after = " ".join(m.group(2).split())
        if m.start() < at:
            brief = _norm(re.sub(r"@brief\s*", "", body))
            continue
        if not body or not after or "~" in after or re.match(r"(explicit\s+)?" + re.escape(stem) + r"\s*\(", after) \
                or body.startswith(("Constructor", "Destructor")):
            continue
        methods.append(f"- {after[:90]}: {_one_liner(body)}")
    if not brief and not methods and not decl:
        return None
    lines = [f"{stem}: {brief}" if brief else f"{stem} (a class of the FESPP plugin)"]
    base = re.search(r":\s*public\s+([\w:]+)", decl.group(1)) if decl else None
    if base:
        lines.append(f"Derives from {base.group(1)}.")
    if methods:
        lines.append("Methods:")
        lines.extend(methods)
    return lines


def enum_summaries(text):
    """[(enum name, lines)] of a header of enums: every value with its
    integer and the // comment above it. A value whose name starts with
    "_" is internal and left out (it still counts for the integers)."""
    out = []
    for m in _ENUM.finditer(text):
        intro = _norm(" ".join(ln.strip().lstrip("/").strip() for ln in m.group(1).split("\n")))
        lines = [f"{m.group(2)}: {intro}" if intro else f"{m.group(2)} (enum of the FESPP plugin)", "Values:"]
        comment, value = [], -1
        for ln in m.group(3).split("\n"):
            s = ln.strip()
            if s.startswith("//"):
                c = s.lstrip("/").strip()
                if c and not _ENUM_NOISE.match(c):
                    comment.append(c)
                continue
            e = _ENUMERATOR.match(s)
            if not e:
                continue
            value = int(e.group(2)) if e.group(2) is not None else value + 1
            if not e.group(1).startswith("_"):
                lines.append(f"- {e.group(1)} = {value}" + (f": {' '.join(comment)}" if comment else ""))
            comment = []
        out.append((m.group(2), lines))
    return out


def header_summaries(root, folder="Plugin/Energistics"):
    """One chunk per header of the plugin (HEADERS: Mapping/*.h, the vtk*.h
    at the top, Tools/enum.h), titled "FESPP › <ClassName>" -- "FESPP ›
    <EnumName>" for the enums."""
    top = os.path.join(root, folder)
    for sub in HEADERS:
        d = os.path.join(top, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".h"):
                continue
            path = os.path.join(d, name)
            rel = os.path.relpath(path, root).replace("\\", "/")
            text = _read(path)
            if name == "enum.h":
                for ename, lines in enum_summaries(text):
                    yield from _pieces("fespp", f"{rel}#{ename}", f"FESPP › {ename}", lines)
                continue
            lines = header_summary(text, name)
            if lines:
                yield from _pieces("fespp", rel, f"FESPP › {os.path.splitext(name)[0]}", lines)


def fespp_chunks(root):
    """Every chunk of the plugin's documentation: the proxies of
    Energistics.xml, then the headers."""
    xml = os.path.join(root, "Plugin", "Energistics", "Energistics.xml")
    if os.path.isfile(xml):
        yield from xml_chunks(xml)
    yield from header_summaries(root)
