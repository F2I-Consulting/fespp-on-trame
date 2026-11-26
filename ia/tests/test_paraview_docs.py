"""The ParaView proxy documentation as Markdown (fespp_ia.paraview_docs):
the pure functions on a fixture of proxy dicts -- what pvpython would read
from the XML definitions -- and the way the corpus builder cuts the result."""
from fespp_ia.corpus import dropped_files
from fespp_ia.paraview_docs import clean, file_markdown, kept, paragraphs, proxy_markdown, proxy_texts, render

LONG_HELP = """This filter extracts cells that have point or cell
                    scalars in the specified range."""
BODY = """
                    The Threshold filter extracts the portions of the input
                    dataset whose scalars lie within the specified range.
                    """

THRESHOLD = {
    "group": "filters", "name": "Threshold", "label": "Threshold",
    "short_help": "Extract cells that satisfy a threshold criterion.", "long_help": LONG_HELP, "body": BODY,
    "hints": [], "plugin": False,
    "properties": [
        {"name": "Input", "label": "Input", "doc": "This property specifies the input to the Threshold filter."},
        {"name": "SelectInputScalars", "label": "Scalars",
         "doc": "The value of this property contains the name of the array\n                    from which to perform thresholding."},
        {"name": "LowerThreshold", "label": "Lower Threshold", "doc": "The lower bound of the thresholding operation."},
        {"name": "Invert", "label": "Invert", "doc": ""},
    ],
}
SLICE = {
    "group": "filters", "name": "Cut", "label": "Slice",
    "short_help": "Slice datasets with planes.", "long_help": "", "body": "This filter slices a data set with a plane.",
    "hints": [], "plugin": False,
    "properties": [{"name": "CutFunction", "label": "Slice Type", "doc": "The implicit function used to slice."}],
}
CLIP = {
    "group": "filters", "name": "Clip", "label": "Clip",
    "short_help": "Clip with an implicit function.", "long_help": "Clip with an implicit function.",
    "body": "Clip with an implicit function. Clipping does not reduce the dimensionality of the data set.",
    "hints": [], "plugin": False, "properties": [],
}
SILENT = {"group": "filters", "name": "Silent", "label": "", "short_help": "", "long_help": "", "body": "",
          "hints": [], "plugin": False, "properties": [{"name": "X", "label": "X", "doc": ""}]}
SPHERE = {"group": "sources", "name": "SphereSource", "label": "Sphere", "short_help": "Create a 3D sphere.",
          "long_help": "", "body": "", "hints": [], "plugin": False,
          "properties": [{"name": "Radius", "label": "Radius", "doc": "The radius of the sphere."}]}
XML_READER = {"group": "sources", "name": "XMLPolyDataReader", "label": "XML PolyData Reader",
              "short_help": "Read a VTK XML file.", "long_help": "", "body": "", "hints": ["ReaderFactory"],
              "plugin": False, "properties": [{"name": "FileName", "label": "File Name", "doc": "The file to read."}]}
TIFF = {"group": "sources", "name": "TIFFSeries", "label": "TIFF series", "short_help": "Read TIFF images.",
        "long_help": "", "body": "", "hints": [], "plugin": False,
        "properties": [{"name": "FileNames", "label": "File Names", "doc": "The files."}]}
ID_SELECTION = {"group": "sources", "name": "IDSelectionSource", "label": "IDSelectionSource",
                "short_help": "A selection by ids.", "long_help": "", "body": "", "hints": [], "plugin": False,
                "properties": []}
WRITER = {"group": "writers", "name": "XMLPWriter", "label": "XML Writer", "short_help": "Write a VTK XML file.",
          "long_help": "", "body": "", "hints": [], "plugin": False, "properties": []}
EPC_READER = {"group": "sources", "name": "EPCReader", "label": "Energistics Packaging Conventions (EPC) Reader",
              "short_help": "A reader for an Energistics standard data format.", "long_help": "", "body": "",
              "hints": ["ReaderFactory"], "plugin": True,
              "properties": [{"name": "FileName", "label": "File Name", "doc": "The .epc file."}]}
EPC_WRITER = {"group": "writers", "name": "EPCWriter", "label": "", "short_help": "Writes an EPC file.",
              "long_help": "", "body": "", "hints": [], "plugin": True, "properties": []}
ALL = [THRESHOLD, SLICE, CLIP, SILENT, SPHERE, XML_READER, TIFF, ID_SELECTION, WRITER, EPC_READER, EPC_WRITER]


def test_clean_collapses_the_xml_indentation():
    assert clean(BODY) == ("The Threshold filter extracts the portions of the input dataset whose scalars lie "
                           "within the specified range.")
    assert clean(None) == ""


def test_the_three_texts_of_a_proxy_are_kept_once_and_in_order():
    assert proxy_texts("a", "a", "a") == ["a"]
    assert proxy_texts("Clip with an implicit function.", "", CLIP["body"]) == [CLIP["body"]]   # the short help is in the body
    assert proxy_texts("short", "long", "") == ["short", "long"]


def test_a_long_body_is_cut_on_sentence_ends_into_paragraphs():
    body = " ".join("Sentence number %d says something about the filter." % i for i in range(60))
    parts = paragraphs(body)
    assert len(parts) >= 4 and all(len(p) <= 800 for p in parts)
    assert all(p.endswith(".") and p.startswith("Sentence number") for p in parts)
    assert " ".join(parts) == body
    assert paragraphs("short.") == ["short."] and paragraphs("   ") == []
    assert proxy_texts("short.", "", body) == ["short."] + parts


def test_a_filter_section_has_its_heading_texts_and_documented_properties():
    md = proxy_markdown(THRESHOLD)
    paragraphs = md.strip().split("\n\n")
    assert paragraphs[0] == "## Threshold (ParaView filter)"
    assert paragraphs[1] == "Extract cells that satisfy a threshold criterion."
    assert paragraphs[2] == "This filter extracts cells that have point or cell scalars in the specified range."
    assert paragraphs[3].startswith("The Threshold filter extracts")
    assert paragraphs[4] == "Properties:"
    assert paragraphs[5] == ("- Scalars (SelectInputScalars): The value of this property contains the name of the "
                             "array from which to perform thresholding.")
    assert paragraphs[6] == "- Lower Threshold (LowerThreshold): The lower bound of the thresholding operation."
    assert "Invert" not in md            # undocumented: left out
    assert "specifies the input" not in md   # the boilerplate every filter repeats


def test_the_heading_names_the_xml_proxy_when_it_differs_from_the_label():
    assert proxy_markdown(SLICE).startswith("## Slice (ParaView filter, proxy Cut)\n")
    assert proxy_markdown(CLIP).startswith("## Clip (ParaView filter)\n")
    assert proxy_markdown(SILENT) == ""


def test_readers_and_plumbing_leave_the_sources_group_but_not_the_plugin():
    """File readers, selection sources and writers would fill the corpus with
    proxies no question is about; the FESPP plugin's own reader and writer
    stay."""
    assert kept(SPHERE)
    assert not kept(XML_READER)        # ReaderFactory hint
    assert not kept(TIFF)              # a FileNames property, no hint
    assert not kept(ID_SELECTION)      # a selection source
    assert not kept(WRITER)            # the writers group
    assert kept(EPC_READER) and kept(EPC_WRITER)


def test_one_file_per_group_and_one_for_the_plugin():
    files = render(ALL, "6.1.1")
    assert sorted(files) == ["fespp.md", "filters.md", "sources.md"]
    filters = files["filters.md"]
    assert filters.startswith("# ParaView -- filtres\n\nSource : ParaView 6.1.1, Kitware, licence BSD-3")
    assert filters.split("\n\n")[1].endswith(" 3 proxies.")
    assert filters.index("## Clip") < filters.index("## Slice") < filters.index("## Threshold")
    assert "Silent" not in filters
    sources = files["sources.md"]
    assert "## Sphere (ParaView source, proxy SphereSource)" in sources
    assert "Reader" not in sources and "TIFF" not in sources and "IDSelection" not in sources
    fespp = files["fespp.md"]
    assert fespp.startswith("# FESPP -- lecteurs ParaView\n\nSource : plugin FESPP, F2I-Consulting, licence Apache-2.0")
    assert "## Energistics Packaging Conventions (EPC) Reader (FESPP, ParaView source, proxy EPCReader)" in fespp
    assert "## EPCWriter (FESPP, ParaView writer)" in fespp
    assert file_markdown("x", "y", [SILENT]) == ""


def test_the_corpus_cuts_a_file_on_its_proxies_and_titles_every_piece(tmp_path):
    many = dict(THRESHOLD, properties=[{"name": "P%d" % i, "label": "Property %d" % i,
                                        "doc": "Sentence number %d of a long documentation. " % i * 6}
                                       for i in range(12)])
    (tmp_path / "paraview").mkdir()
    for name, md in render([many, SLICE], "6.1.1").items():
        (tmp_path / "paraview" / name).write_text(md, encoding="utf-8")
    rows = list(dropped_files(str(tmp_path)))
    titles = [r["title"] for r in rows]
    assert "ParaView -- filtres › Slice (ParaView filter, proxy Cut)" in titles
    pieces = [r for r in rows if r["title"].startswith("ParaView -- filtres › Threshold (ParaView filter) (")]
    assert len(pieces) >= 3                                   # ~900 characters a chunk, cut between properties
    assert all(r["text"].startswith(r["title"] + "\n\n") for r in rows)
    assert all(len(r["text"]) < 1500 for r in rows)
    assert pieces[1]["text"].count("- Property") >= 2 and "## " not in pieces[1]["text"]
