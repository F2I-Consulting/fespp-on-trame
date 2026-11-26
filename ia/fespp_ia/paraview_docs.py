"""The documentation of the ParaView proxies -- the filters, the generic
sources, the representations, the views -- and of the FESPP plugin's
readers, read from the servermanager XML definitions shipped in the
application image and written as Markdown into ia/corpus/paraview
(git-ignored), for the RAG to read. Built AT INSTALL TIME (ia/build-index.ps1);
the service never reads ParaView.

    docker run --rm -v "<repo>:/repo" --entrypoint /opt/paraview/bin/pvpython fespp_on_trame:local \\
        /repo/ia/fespp_ia/paraview_docs.py /repo/ia/corpus/paraview \\
        [--plugin <path or glob of Fespp.so, PLUGIN_GLOB by default>]

Why the XML and not the docstrings of paraview.simple (ia/corpus_cache/
paraview_simple.jsonl): most of those docstrings are only the boilerplate
"This function creates a new proxy..."; the <Documentation> of the XML
carries the text of nearly every filter and of thousands of properties --
what a filter does, what each of its settings means. One file per group,
"## <label>" per proxy, one paragraph per property: the corpus builder
cuts on the headings, then on the paragraphs (~900 characters), so a long
representation becomes several chunks that all carry the proxy's name in
their title.

Left out: the readers of the sources group (the application reads EPC and
ETP through FESPP, not through ParaView's own readers), the selection
sources and trivial producers (plumbing), the writers, exporters and every
other group. The FESPP plugin, when given, adds its proxies in a file of
their own, whatever their group.

It runs under pvpython, which has no third-party package: stdlib only, and
ParaView is imported in main() so that the pure functions (cleaning,
Markdown) import and test in plain Python.

Licence: the XML is part of ParaView (Kitware, BSD-3: /opt/paraview/share/
licenses/ParaView/Copyright.txt in the image); the FESPP plugin is
Apache-2.0 (F2I-Consulting). Each file names its source on its first line.
"""
import argparse
import glob
import os
import re
import sys

GROUPS = ("filters", "sources", "representations", "views")
KIND = {"filters": "filter", "sources": "source", "representations": "representation",
        "views": "view", "writers": "writer"}
FILE_TITLE = {"filters": "ParaView -- filtres", "sources": "ParaView -- sources",
              "representations": "ParaView -- représentations", "views": "ParaView -- vues"}
FILE_TITLE_PLUGIN = "FESPP -- lecteurs ParaView"
PLUGIN_GLOB = "/work/ttl/install-fespp/lib/paraview*/plugins/Fespp/Fespp.so"
# a source that reads a file: the ReaderFactory hint registers it in the
# Open dialog; a few readers (ExodusII, TIFF...) have no hint but a file
# property or the name
_FILE_PROPERTIES = {"FileName", "FileNames", "FilePrefix", "FilePattern"}
# the sources that are pipeline plumbing, never chosen by a reader
_SOURCE_INTERNAL = re.compile(r"Selection\w*Source|TrivialProducer|MultiServerProxy|Test3DWidget")
# "This property specifies the input to the Threshold filter.": every filter
# says it, it teaches nothing
_INPUT_BOILERPLATE = re.compile(r"^This property specifies the input (to|of) the .{0,80}(filter|source)\.?$")


def clean(text):
    """One line: the XML's indentation (deep in the long_help of most
    filters) and line breaks collapsed to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def paragraphs(text, limit=800):
    """A documentation cut on sentence ends into paragraphs of at most
    `limit` characters: a chunk of the corpus (~900, cut on paragraph ends)
    then holds whole sentences, not the head of a long body (Calculator,
    Delaunay 3D) that the prompt would truncate (server.EXTRACT_CHARS)."""
    text = clean(text)
    if len(text) <= limit:
        return [text] if text else []
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + 1 + len(s) > limit:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def proxy_texts(short_help, long_help, body):
    """The paragraphs of a proxy's own documentation, in the XML's order
    (short_help, long_help, the element's body), the duplicates left out:
    a text repeated, or contained in another (Clip's short_help is the first
    sentence of its body); a long text cut into several paragraphs."""
    texts = [clean(t) for t in (short_help, long_help, body)]
    texts = [t for t in texts if t]
    out = []
    for t in texts:
        if any(t != o and t in o for o in texts) or t in out:
            continue
        out.append(t)
    return [p for t in out for p in paragraphs(t)]


def is_reader(proxy):
    """Whether a proxy reads a file: the ReaderFactory hint, a file property
    or a name ending in "Reader"."""
    return ("ReaderFactory" in proxy.get("hints", ())
            or any(p["name"] in _FILE_PROPERTIES for p in proxy.get("properties", ()))
            or proxy["name"].endswith("Reader"))


def kept(proxy):
    """Whether a ParaView proxy goes into the corpus (a plugin proxy always
    does): the four groups, without the readers and the plumbing of the
    sources group."""
    if proxy.get("plugin"):
        return True
    if proxy["group"] not in GROUPS:
        return False
    if proxy["group"] == "sources" and (is_reader(proxy) or _SOURCE_INTERNAL.search(proxy["name"])):
        return False
    return True


def proxy_markdown(proxy):
    """The "## <label>" section of one proxy: its documentation as
    paragraphs, then one paragraph per documented property ("- <label>
    (<name>): <doc>"); "" when the XML says nothing about it."""
    texts = proxy_texts(proxy.get("short_help"), proxy.get("long_help"), proxy.get("body"))
    props = []
    for p in proxy.get("properties", ()):
        doc = clean(p.get("doc"))
        if not doc or _INPUT_BOILERPLATE.match(doc):
            continue
        label = clean(p.get("label")) or p["name"]
        name = "" if label == p["name"] else " (%s)" % p["name"]
        props.append("- %s%s: %s" % (label, name, doc))
    if not texts and not props:
        return ""
    label = clean(proxy.get("label")) or proxy["name"]
    kind = KIND.get(proxy["group"], proxy["group"])
    origin = "FESPP, ParaView %s" % kind if proxy.get("plugin") else "ParaView %s" % kind
    head = "## %s (%s%s)" % (label, origin, "" if label == proxy["name"] else ", proxy %s" % proxy["name"])
    parts = [head] + texts
    if props:
        parts.append("Properties:")
        parts.extend(props)
    return "\n\n".join(parts) + "\n"


def file_markdown(title, source_line, proxies):
    """One Markdown file: the H1, the source and licence line with the count,
    then one section per proxy, in the order of their labels. No list of the
    names up front: the labels of a whole group make a paragraph the corpus
    cannot cut."""
    sections = [proxy_markdown(p) for p in sorted(proxies, key=lambda p: (clean(p.get("label")) or p["name"]).lower())]
    sections = [s for s in sections if s]
    if not sections:
        return ""
    return "# %s\n\n%s %d proxies.\n\n" % (title, source_line, len(sections)) + "\n".join(sections)


def render(proxies, version):
    """{file name: Markdown} -- one file per ParaView group that has
    something to say, plus fespp.md for the plugin's proxies."""
    pv = ("Source : ParaView %s, Kitware, licence BSD-3 -- définitions XML des proxys (servermanager) "
          "livrées avec ParaView dans l'image de l'application." % version)
    fespp = ("Source : plugin FESPP, F2I-Consulting, licence Apache-2.0 -- définitions XML des proxys du plugin "
             "(Energistics.xml), chargé dans ParaView %s dans l'image de l'application." % version)
    out = {}
    for group in GROUPS:
        md = file_markdown(FILE_TITLE[group], pv, [p for p in proxies if not p.get("plugin") and p["group"] == group and kept(p)])
        if md:
            out[group + ".md"] = md
    md = file_markdown(FILE_TITLE_PLUGIN, fespp, [p for p in proxies if p.get("plugin")])
    if md:
        out["fespp.md"] = md
    return out


# --- what follows needs pvpython -----------------------------------------

def _children(elem):
    for i in range(elem.GetNumberOfNestedElements()):
        yield elem.GetNestedElement(i)


def _doc_of(elem):
    """(short_help, long_help, body) of the <Documentation> child, raw."""
    for c in _children(elem):
        if c.GetName() == "Documentation":
            return c.GetAttribute("short_help") or "", c.GetAttribute("long_help") or "", c.GetCharacterData() or ""
    return "", "", ""


def _properties_of(elem, seen, depth=0):
    """The *Property children, and those of the nested SubProxy/Proxy blocks
    the collapsed definition keeps (a representation's sub-representations)."""
    for c in _children(elem):
        name = c.GetName() or ""
        if name.endswith("Property"):
            key = c.GetAttribute("name") or ""
            if key and key not in seen:
                seen.add(key)
                yield c
        elif name in ("SubProxy", "Proxy") and depth < 3:
            for p in _properties_of(c, seen, depth + 1):
                yield p


def _definitions(pdm):
    """Every (group, name) the definition manager knows."""
    out = []
    it = pdm.NewIterator()
    it.InitTraversal()
    while not it.IsDoneWithTraversal():
        out.append((it.GetGroupName(), it.GetProxyName()))
        it.GoToNextItem()
    return out


def read_proxy(pdm, group, name, plugin=False):
    """One proxy as a plain dict, from its collapsed definition (the
    base_proxy inheritance flattened)."""
    elem = pdm.GetCollapsedProxyDefinition(group, name, None, True)
    if elem is None:
        return None
    short_help, long_help, body = _doc_of(elem)
    hints = [h.GetName() for c in _children(elem) if c.GetName() == "Hints" for h in _children(c)]
    props = []
    for p in _properties_of(elem, set()):
        psh, plh, pbody = _doc_of(p)
        props.append({"name": p.GetAttribute("name") or "", "label": p.GetAttribute("label") or "",
                      "doc": pbody or plh or psh})
    return {"group": group, "name": name, "label": elem.GetAttribute("label") or "", "short_help": short_help,
            "long_help": long_help, "body": body, "hints": hints, "properties": props, "plugin": plugin}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write the ParaView proxy documentation as Markdown (run with pvpython).")
    ap.add_argument("out_dir", help="ia/corpus/paraview")
    ap.add_argument("--plugin", default=PLUGIN_GLOB,
                    help="the FESPP plugin (a path or a glob; 'none' to skip it)")
    a = ap.parse_args(argv)
    from paraview import servermanager, simple   # connects a builtin session

    pxm = servermanager.ProxyManager().SMProxyManager
    pdm = pxm.GetProxyDefinitionManager()
    m = re.search(r"\d+\.\d+\.\d+", servermanager.vtkSMProxyManager.GetParaViewSourceVersion() or "")
    version = m.group(0) if m else "%d.%d.%d" % (servermanager.vtkSMProxyManager.GetVersionMajor(),
                                                 servermanager.vtkSMProxyManager.GetVersionMinor(),
                                                 servermanager.vtkSMProxyManager.GetVersionPatch())
    before = set(_definitions(pdm))
    plugin_path = None
    if a.plugin.lower() != "none":
        found = sorted(glob.glob(a.plugin))
        if found:
            plugin_path = found[0]
            simple.LoadPlugin(plugin_path, remote=False)
        else:
            print("[paraview] no plugin at %s: FESPP proxies left out" % a.plugin, file=sys.stderr)
    pairs = sorted(set(_definitions(pdm)))
    proxies = []
    for group, name in pairs:
        plugin = (group, name) not in before
        if not plugin and group not in GROUPS:
            continue
        p = read_proxy(pdm, group, name, plugin)
        if p is not None:
            proxies.append(p)

    files = render(proxies, version)
    os.makedirs(a.out_dir, exist_ok=True)
    stale = os.path.join(a.out_dir, "fespp.md")
    if "fespp.md" not in files and os.path.exists(stale):
        os.remove(stale)     # left by a run that had the plugin
    total = 0
    for name, md in sorted(files.items()):
        with open(os.path.join(a.out_dir, name), "w", encoding="utf-8") as f:
            f.write(md)
        n = md.count("\n## ")
        total += len(md)
        print("[paraview] %s: %d proxies, %d characters" % (name, n, len(md)), flush=True)
    print("[paraview] ParaView %s, plugin %s, %d files, %d characters -> %s"
          % (version, plugin_path or "none", len(files), total, a.out_dir), flush=True)


if __name__ == "__main__":
    main()
