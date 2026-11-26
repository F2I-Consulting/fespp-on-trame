"""The corpus sources of the RAG and how each one is cut into chunks.

Covers the XSD extractor, the documents dropped in ia/corpus (subfolders,
official zips, PDFs), the Energistics Online topic converter, the Doxygen
blocks of the C++ headers, the ParaView docstrings, the project's Markdown
and glossaries, the assistant's command catalogue, and the developer's
sources (the SWIG interfaces and the examples). A chunk's title and
text are what retrieval scores and what the prompt quotes, so the tests pin
them exactly."""
import zipfile

from fespp_ia.corpus import dropped_files, xsd_chunks
from fespp_ia.energistics_docs import nav_topics, topic_markdown

XSD = b"""<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
    targetNamespace="http://www.energistics.org/energyml/data/resqmlv2" version="2.2">
  <xs:complexType name="IjkGridRepresentation">
    <xs:annotation><xs:documentation>Grid whose topology is characterized
      by structured column indices (I,J) and a layer index, K.</xs:documentation></xs:annotation>
    <xs:complexContent>
      <xs:extension base="resqml:AbstractColumnLayerGridRepresentation">
        <xs:sequence>
          <xs:element name="Ni" type="eml:PositiveLong" minOccurs="1" maxOccurs="1">
            <xs:annotation><xs:documentation>Count of cells in the I-direction.</xs:documentation></xs:annotation>
          </xs:element>
          <xs:element name="Geometry" type="resqml:IjkGridGeometry" minOccurs="0" maxOccurs="unbounded"/>
        </xs:sequence>
      </xs:extension>
    </xs:complexContent>
  </xs:complexType>
  <xs:simpleType name="ResqmlPropertyKind">
    <xs:annotation><xs:documentation>Standard property kinds.</xs:documentation></xs:annotation>
    <xs:restriction base="eml:TypeEnum">
      <xs:enumeration value="porosity">
        <xs:annotation><xs:documentation>Pore volume over bulk volume.</xs:documentation></xs:annotation>
      </xs:enumeration>
      <xs:enumeration value="permeability rock"/>
    </xs:restriction>
  </xs:simpleType>
  <xs:element name="IjkGridRepresentation" type="resqml:IjkGridRepresentation"/>
</xs:schema>
"""


def test_a_complex_type_gives_its_definition_parent_and_fields():
    chunks = dict(xsd_chunks(XSD, "Grids.xsd"))
    text = chunks["RESQML v2.2 (XSD) › IjkGridRepresentation"]
    assert "derives from resqml:AbstractColumnLayerGridRepresentation" in text
    assert "structured column indices (I,J)" in text
    assert "- Ni (eml:PositiveLong, 1..1) : Count of cells in the I-direction." in text
    assert "- Geometry (resqml:IjkGridGeometry, 0..*)" in text


def test_an_enumeration_lists_every_value_with_its_definition():
    chunks = dict(xsd_chunks(XSD, "Properties.xsd"))
    text = chunks["RESQML v2.2 (XSD) › ResqmlPropertyKind"]
    assert "- porosity : Pore volume over bulk volume." in text
    assert "- permeability rock" in text


def test_an_undocumented_top_level_element_is_not_a_chunk():
    """A top-level element that only names its type adds no second chunk
    beside the type's own."""
    titles = [t for t, _ in xsd_chunks(XSD, "Grids.xsd")]
    assert titles.count("RESQML v2.2 (XSD) › IjkGridRepresentation") == 1


def test_a_file_that_is_not_a_schema_gives_nothing():
    assert xsd_chunks(b"<root/>", "x.xsd") == []
    assert xsd_chunks(b"not xml", "x.xsd") == []


def test_dropped_files_walk_subfolders_and_read_an_official_zip(tmp_path):
    (tmp_path / "energistics" / "RESQML").mkdir(parents=True)
    (tmp_path / "energistics" / "RESQML" / "grid.md").write_text(
        "# RESQML v2.0.1 › IjkGridRepresentation\n\nGrid whose topology is characterized.\n", encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "RESQML_v2.2.zip", "w") as z:
        z.writestr("resqml/v2.2/xsd_schemas/Grids.xsd", XSD)
    rows = list(dropped_files(str(tmp_path)))
    paths = {r["path"] for r in rows}
    assert "energistics/RESQML/grid.md" in paths
    assert "RESQML_v2.2.zip!/resqml/v2.2/xsd_schemas/Grids.xsd" in paths
    assert all(r["source"] == "energistics" for r in rows)   # from the folder, and from the zip's name
    assert any(r["title"] == "RESQML v2.2 (XSD) › ResqmlPropertyKind" for r in rows)


def test_the_source_label_follows_where_the_document_sits():
    from fespp_ia.corpus import source_of
    assert source_of("/repo/ia/corpus/glossaire-reservoir.md") == "docs"
    assert source_of("/repo/ia/corpus/energistics/RESQML/RESQML-500-217.md") == "energistics"
    assert source_of("/repo/ia/corpus/energistics/pdf/ETP_Specification_v1.2.pdf") == "etp"
    assert source_of("/repo/ia/corpus/etp_v1.2.zip") == "etp"
    assert source_of("/repo/ia/corpus/resqml_v2.2.zip") == "energistics"
    assert source_of("/repo/ia/corpus/geologie/aapg/Fluid_contacts.md") == "geologie"
    assert source_of("/repo/ia/corpus/notes-du-projet.zip") == "docs"
    assert source_of("/repo/ia/corpus/setpoints.md") == "docs"   # "etp" inside a word is not ETP


TOPIC = """<!DOCTYPE html><html><head><title>x</title><script>var a = 1;</script></head><body>
<div class="breadcrumb">14.7 Representations</div>
<h1 class="title topictitle1">14.7.3.38 IjkGridRepresentation</h1>
<div class="body refbody">
 <table class="table topicMeta"><tr><td>Topic Version 1</td><td>Published 09/11/2015</td></tr></table>
 <p class="shortdesc">Stereotypes: XSDcomplexType</p>
 <p class="p">Grid whose topology is characterized by structured column indices.</p>
 <ul class="ul"><li class="li">IJK radial grids</li><li class="li">K-Layer gaps</li></ul>
 <table class="table"><caption>Table 14.7.3.38-1 Attributes</caption>
  <tr><th>Name</th><th>Data Type</th><th>Notes</th></tr>
  <tr><td><p class="p">Ni</p></td><td>positiveInteger</td><td><p class="p">Count of cells.</p><p class="p">Must be positive.</p></td></tr>
 </table>
 <table class="table changehistory"><tr><td>first version</td></tr></table>
</div>
<div class="navfooter">Parent topic : 14.7.3 Grids</div>
</body></html>"""


def test_a_topic_keeps_its_title_text_and_table_rows_and_drops_the_chrome():
    title, md = topic_markdown(TOPIC, "RESQML v2.0.1", "https://docs.energistics.org/x.html")
    assert title == "RESQML v2.0.1 › 14.7.3.38 IjkGridRepresentation"
    assert md.startswith("# RESQML v2.0.1 › 14.7.3.38 IjkGridRepresentation\n\nSource : Energistics, https://")
    assert "Grid whose topology is characterized by structured column indices." in md
    assert "- IJK radial grids" in md
    assert "Ni | positiveInteger | Count of cells. Must be positive." in md
    for noise in ("Topic Version", "first version", "Parent topic", "Stereotypes", "14.7 Representations", "var a"):
        assert noise not in md


def test_a_page_without_a_topic_title_gives_nothing():
    assert topic_markdown("<html><body><p>hello</p></body></html>", "RESQML v2.0.1", "u") == (None, None)


def test_the_navigation_tree_gives_the_topics_of_the_chosen_families_once():
    root = ('<a href="RESQML/RESQML_TOPICS/RESQML-500-217-0-R-sv2010.html" data-id="r">14.7.3.38 IjkGridRepresentation</a>'
            '<a href="RESQML/RESQML_TOPICS/RESQML-500-217-0-R-sv2010.html">again</a>'
            '<a href="WITSML/WITSML_TOPICS/WITSML-1.html">witsml</a>'
            '<a href="EPC/EPC_TOPICS/EPC-000-000-titlepage.html">EPC</a>')
    topics = nav_topics(root, {"RESQML": "RESQML v2.0.1", "EPC": "EPC v1.0"})
    assert topics == [("RESQML", "RESQML/RESQML_TOPICS/RESQML-500-217-0-R-sv2010.html", "14.7.3.38 IjkGridRepresentation"),
                      ("EPC", "EPC/EPC_TOPICS/EPC-000-000-titlepage.html", "EPC")]


def test_a_pdf_is_titled_by_its_file_name_not_its_generic_metadata():
    from fespp_ia.corpus import pdf_title
    assert pdf_title("ETP_Specification_v1.2.pdf") == "ETP Specification v1.2"
    assert pdf_title("pdf/Energistics_Unit_of_Measure_Usage_Guide_v1.pdf") == "Energistics Unit of Measure Usage Guide v1"


# --- C++ owners and banners, duplicates, ParaView boilerplate, Markdown rules, glossary, catalogue ---

def test_the_owner_of_a_header_is_its_declared_class_not_a_forward_declaration_or_a_comment():
    """A Doxygen chunk is titled by its owning class, so the owner is the
    class the header declares, not a forward declaration above it nor the
    word "class" inside a comment; with no class, the file name."""
    from fespp_ia.corpus import cpp_owner
    forward = "class AbstractHdfProxy;\nnamespace COMMON_NS {\n\tclass DataObjectRepository final\n\t{\n"
    assert cpp_owner(forward, "DataObjectRepository.h") == "DataObjectRepository"
    comment = ("/** Proxy class for an abstract feature. */\n"
               "class DLL_IMPORT_OR_EXPORT Activity final : public EML2_NS::Activity {")
    assert cpp_owner(comment, "Activity.h") == "Activity"
    assert cpp_owner("/** nothing declared here */\n#define X 1\n", "MacroDefinitions.h") == "MacroDefinitions"
    assert cpp_owner("enum class Kind { A };\nclass vtkEPCCollector : public vtkAlgorithm {",
                     "vtkEPCCollector.h") == "vtkEPCCollector"
    assert cpp_owner("class ENERGISTICS_EXPORT  vtkOther : public X {", "vtkEPCReader.h") == "vtkOther"


LONG = "word " * 40    # 200 characters: over the 120-character minimum of a Doxygen block


def _cpp_tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_a_star_banner_in_a_cxx_is_not_a_doxygen_block_and_a_block_is_capped(tmp_path):
    """A `/****` banner is decoration: read as a Doxygen block it would
    attach the code below it to a chunk. A huge block is capped so that one
    comment cannot become an oversized chunk."""
    from fespp_ia.corpus import cpp_doxygen, _DOXY_CAP
    cxx = ("void f() {}\n/****\n *  change property parent\n ****/\nfor (x : y) { code(); }\n"
           + "int z;\n" * 300 + "\n/** " + LONG + "*/\nvoid documented();\n"
           + "/**\n" + ("* line of a very long comment\n" * 200) + "*/\nvoid huge();\n")
    root = _cpp_tree(tmp_path, {"Plugin/A.cxx": cxx})
    rows = list(cpp_doxygen(root, "fespp", ("Plugin",), (".h", ".cxx")))
    assert [r["title"] for r in rows] == ["A: void documented()", "A: void huge()"]
    assert all("int z;" not in r["text"] for r in rows)
    assert len(rows[1]["text"]) <= _DOXY_CAP + 40


def test_a_class_brief_above_the_includes_is_titled_by_the_class_alone(tmp_path):
    from fespp_ia.corpus import cpp_doxygen
    header = ("/** @brief transform a resqml ijkGrid representation to vtkExplicitStructuredGrid, " + LONG + "*/\n\n"
              "// include system\n#include <string>\n\nclass ResqmlIjkGridToVtkExplicitStructuredGrid : public Base\n{\n};\n")
    root = _cpp_tree(tmp_path, {"Plugin/Mapping/ResqmlIjkGridToVtkExplicitStructuredGrid.h": header})
    rows = list(cpp_doxygen(root, "fespp", ("Plugin",)))
    assert [r["title"] for r in rows] == ["ResqmlIjkGridToVtkExplicitStructuredGrid"]
    assert rows[0]["text"].startswith("ResqmlIjkGridToVtkExplicitStructuredGrid\n\ntransform a resqml ijkGrid")


def test_the_macro_file_and_the_gsoap_stubs_are_skipped(tmp_path):
    """Generated gSOAP proxies and the macro header document no RESQML
    concept: they are left out of the fesapi corpus."""
    from fespp_ia.corpus import cpp_doxygen
    block = "/** " + LONG + "*/\nvoid f();\n"
    root = _cpp_tree(tmp_path, {"src/MacroDefinitions.h": block, "src/proxies/gsoap_resqml2_0_1Stub.h": block,
                                "src/proxies/envStub.h": block, "src/resqml2/Grid.h": "class Grid {\n" + block})
    rows = list(cpp_doxygen(root, "fesapi", ("src",)))
    assert [r["path"] for r in rows] == ["src/resqml2/Grid.h"]
    assert rows[0]["title"] == "Grid: void f()"


def test_build_drops_the_exact_duplicates_of_a_source_and_counts_them(tmp_path):
    """fesapi documents many classes word for word in each RESQML version:
    one copy is kept, so the copies cannot crowd out the other extracts, the
    ids stay consecutive and the dropped copies are counted per source."""
    from fespp_ia.corpus import build
    block = "class Twin {\n/** " + LONG + "*/\nvoid f();\n"
    root = _cpp_tree(tmp_path, {"src/resqml2_0_1/Twin.h": block, "src/resqml2_2/Twin.h": block,
                                "src/eml2/Other.h": "class Other {\n/** " + LONG + "*/\nvoid f();\n"})
    dup = {}
    rows = list(build(fesapi=root, duplicates=dup))
    paths = sorted(r["path"] for r in rows)
    assert len(paths) == 2 and paths[0] == "src/eml2/Other.h" and paths[1].endswith("/Twin.h")
    assert [r["id"] for r in rows] == [1, 2]
    assert dup == {"fesapi": 1}


def test_paraview_rows_lose_the_generated_boilerplate_and_the_empty_ones_go(tmp_path):
    """The paragraph paraview.simple appends to every proxy function says
    nothing about the proxy: it is stripped, and a row left without text of
    its own is dropped."""
    import json
    from fespp_ia.corpus import jsonl_chunks
    tail = ("This function creates a new proxy. For pipeline objects that accept inputs, all non-keyword arguments "
            "are assumed to be inputs. All keyword arguments are assumed to be property-value pairs and are passed "
            "to the new proxy.  ")
    rows = [{"path": "paraview.simple.AMRContour", "title": "AMRContour", "text": "AMRContour (function)\n\n" + tail},
            {"path": "paraview.simple.Clip", "title": "Clip",
             "text": "Clip(*input) (function)\n\nThe Clip filter cuts away a portion of the input dataset. " + tail},
            {"path": "paraview.simple.Show", "title": "Show", "text": "Show(proxy) (function)\n\nShow it."}]
    p = tmp_path / "pv.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = list(jsonl_chunks(str(p), "paraview"))
    assert [r["path"] for r in out] == ["paraview.simple.Clip"]
    assert out[0]["text"] == "Clip(*input) (function)\n\nThe Clip filter cuts away a portion of the input dataset."
    assert out[0]["source"] == "paraview"


def test_markdown_rules_todo_skipped_small_file_one_chunk_one_level_down(tmp_path):
    """TODO and CHANGELOG files are working notes, left out; the immediate
    subfolders of a `one_level` folder are read; a small file is one chunk
    whatever its headings; a large one is cut on its headings, each piece
    titled by the document and its section."""
    from fespp_ia.corpus import markdown_chunks
    dev = tmp_path / "doc" / "dev"
    (dev / "widgets").mkdir(parents=True)
    (dev / "widgets" / "toolbar.md").write_text(
        "# Widget: Toolbar\n\nThe top app bar.\n\n## Scope\nGlobal.\n\n## Input\n- User clicks.\n\n## Reads\n- `x`.\n",
        encoding="utf-8")
    (dev / "widgets" / "TODO.md").write_text("# TODO\n\n- fix everything\n", encoding="utf-8")
    (dev / "CHANGELOG-2026.md").write_text("# Changes\n\n- v2\n", encoding="utf-8")
    (dev / "ARCHITECTURE.md").write_text("# Architecture\n\n## Engine\n\n" + "A sentence. " * 200
                                         + "\n\n## UI\n\n" + "Another. " * 100, encoding="utf-8")
    rows = list(markdown_chunks(str(tmp_path), "fespp_on_trame", ("doc/dev",), one_level=("doc/dev",)))
    paths = [r["path"] for r in rows]
    assert "doc/dev/widgets/TODO.md" not in paths and "doc/dev/CHANGELOG-2026.md" not in paths
    toolbar = [r for r in rows if r["path"] == "doc/dev/widgets/toolbar.md"]
    assert len(toolbar) == 1
    assert toolbar[0]["title"] == "Widget: Toolbar"
    assert toolbar[0]["text"].startswith("Widget: Toolbar\n\nThe top app bar.\n\n## Scope\nGlobal.")
    arch = [r["title"] for r in rows if r["path"] == "doc/dev/ARCHITECTURE.md"]
    assert arch[0].startswith("Architecture › Engine") and "Architecture › UI" in arch


def test_a_glossary_of_bullets_is_one_chunk_per_term(tmp_path):
    """A bullet glossary gives one chunk per term, titled by the term, so a
    question naming the term retrieves its definition alone; a wrapped
    bullet is joined into one line. Prose with a stray bullet is not a
    glossary."""
    from fespp_ia.corpus import glossary_entries, markdown_chunks
    text = ("# Glossary\n\nVocabulary used throughout the code.\n\n## Geoscience\n\n"
            "- **RESQML** — Energistics' XML/HDF5 standard for reservoir models.\n"
            "- **EPC** — *Energistics Packaging Conventions*: a `.epc` ZIP container\n"
            "  holding the RESQML XML parts.\n"
            "- **FESAPI** — F2I-Consulting's C++ library to read/write RESQML.\n\n## ParaView\n\n"
            "- **`vtkDataAssembly`** — the hierarchical tree FESPP emits.\n")
    entries = glossary_entries(text, "Glossary")
    assert [t for t, _ in entries] == ["Glossary › RESQML", "Glossary › EPC", "Glossary › FESAPI",
                                       "Glossary › `vtkDataAssembly`"]
    assert entries[1][1] == ("EPC — *Energistics Packaging Conventions*: a `.epc` ZIP container "
                             "holding the RESQML XML parts.")
    assert glossary_entries("# Notes\n\n- **one** — bullet\n\nlots\nof\nprose\nlines\nhere\n", "Notes") is None
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Glossary.md").write_text(text * 3, encoding="utf-8")   # over the small-file size: cut
    rows = list(markdown_chunks(str(tmp_path), "fespp_on_trame", ("wiki",)))
    assert [r["title"] for r in rows][:2] == ["Glossary › RESQML", "Glossary › EPC"]
    assert rows[0]["text"] == "Glossary › RESQML\n\nRESQML — Energistics' XML/HDF5 standard for reservoir models."


def test_the_catalogue_gives_one_chunk_per_command_with_the_slots_of_its_sibling(tmp_path):
    """Each assistant command becomes one bilingual chunk; its slots come
    from catalogue.json beside the hints file, and a missing hints file
    gives no chunk rather than an error."""
    import json
    from fespp_ia.corpus import catalogue_chunks
    hints = [{"name": "show", "fr": "afficher un objet — pas une zone", "en": "show an object"},
             {"name": "help", "fr": "ce que l'assistant sait faire", "en": "what the assistant can do"}]
    (tmp_path / "catalogue-hints.json").write_text(json.dumps(hints, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "catalogue.json").write_text(json.dumps([{"name": "show", "slots": ["object", "kind"]}]),
                                             encoding="utf-8")
    rows = list(catalogue_chunks(str(tmp_path / "catalogue-hints.json")))
    assert [r["title"] for r in rows] == ["Assistant › show", "Assistant › help"]
    assert rows[0]["source"] == "docs" and rows[0]["path"] == "catalogue#show"
    assert rows[0]["text"] == ("Assistant › show\n\nCommande de l'assistant / assistant command: show\n"
                               "FR : afficher un objet — pas une zone\nEN: show an object\n"
                               "Paramètres / slots: object, kind")
    assert "slots" not in rows[1]["text"]
    assert list(catalogue_chunks(str(tmp_path / "missing.json"))) == []


def test_the_source_label_knows_pwls_and_paraview_folders():
    from fespp_ia.corpus import source_of
    assert source_of("/repo/ia/corpus/pwls/quantities.md") == "pwls"
    assert source_of("/repo/ia/corpus/paraview/filters/Clip.md") == "paraview"
    assert source_of("/repo/ia/corpus/geologie/aapg/Fluid_contacts.md") == "geologie"
    assert source_of("/repo/ia/corpus/swig/swig-Python.md") == "swig"


SWIG_I = '''/*-----------------------------------------------------------------------
Licensed to the Apache Software Foundation (ASF) under one
-----------------------------------------------------------------------*/
%module fesapi

%{
#include "../src/common/DataObjectRepository.h"
%}

%include "std_string.i"

#if defined(SWIGJAVA) || defined(SWIGCSHARP)
	%nspace COMMON_NS::AbstractObject;
	%nspace COMMON_NS::EpcDocument;
	%nspace RESQML2_NS::IjkGridRepresentation;
#endif

#ifdef SWIGJAVA // functions, to avoid premature garbage collection
	%array_functions(double, DoubleArray);
#else
	%array_class(double, DoubleArray);
#endif

// Turn the C++ exceptions into errors of the target language
%exception {
    try {
        $action
    }
    catch (std::exception& e) {
        SWIG_exception(SWIG_RuntimeError, const_cast<char*>(e.what()));
    }
}

#ifdef SWIGCSHARP
%typemap(csin,
         post="      hdfProxyFactoryReference = $csinput;"
         ) COMMON_NS::HdfProxyFactory * factory "HdfProxyFactory.getCPtr($csinput)"
#endif

namespace COMMON_NS
{
	%template(StringVector) std::vector<std::string>;
	/** A repository. */
	class DataObjectRepository
	{
	public:
		enum class openingMode : std::int8_t { READ_ONLY = 0 };
		%rename(createPartialIjkGrid) createPartial;
		void clear();
	};
}
'''


def test_a_swig_interface_gives_its_directives_with_what_they_do_and_their_condition():
    """What an interface file adds to the headers is its directives: a
    directive that spans lines is one chunk, the one-line ones are gathered
    by kind and condition, and the class declarations -- the headers again
    -- the #includes and the licence are left out."""
    from fespp_ia.corpus import swig_file_chunks
    rows = swig_file_chunks(SWIG_I, "swigModule.i")
    titles = [t for t, _ in rows]
    assert titles[0] == "SWIG › swigModule.i › %exception"
    assert titles[1].startswith("SWIG › swigModule.i › %typemap(csin, post=")
    assert titles[2:] == ["SWIG › swigModule.i › %module", "SWIG › swigModule.i › %include",
                          "SWIG › swigModule.i › %nspace (SWIGJAVA || SWIGCSHARP)",
                          "SWIG › swigModule.i › %array_functions (SWIGJAVA)",
                          "SWIG › swigModule.i › %array_class (not (SWIGJAVA))",
                          "SWIG › swigModule.i › %template", "SWIG › swigModule.i › %rename"]
    text = dict(rows)
    handler = text["SWIG › swigModule.i › %exception"]
    assert handler.startswith("SWIG directive %exception: the code around every wrapped call")
    assert "Interface file swigModule.i, whatever the target language." in handler
    assert "// Turn the C++ exceptions into errors of the target language\n%exception {\n    try {" in handler
    assert handler.rstrip().endswith("}")
    assert "only when SWIGCSHARP." in rows[1][1] and rows[1][1].rstrip().endswith('"HdfProxyFactory.getCPtr($csinput)"')
    nspace = text["SWIG › swigModule.i › %nspace (SWIGJAVA || SWIGCSHARP)"]
    assert "3 classes, of the namespaces COMMON_NS, RESQML2_NS; for instance:" in nspace
    assert "%array_class(double, DoubleArray);" in text["SWIG › swigModule.i › %array_class (not (SWIGJAVA))"]
    assert "%rename(createPartialIjkGrid) createPartial;" in text["SWIG › swigModule.i › %rename"]
    everything = "\n".join(t for _, t in rows)
    assert "READ_ONLY" not in everything and "void clear" not in everything
    assert "Licensed" not in everything and "DataObjectRepository.h" not in everything


def test_nested_conditions_are_joined_and_a_define_runs_to_its_enddef():
    from fespp_ia.corpus import swig_directives
    text = ("#if defined(SWIGJAVA) || defined(SWIGCSHARP)\n#if SWIG_VERSION >= 0x040300\n%nspacemove(common) A;\n"
            "#else\n%feature(\"nspace\", \"common\") A;\n#endif\n#endif\n"
            "%define GETTER(type, name)\n\ttype* get ## name() const;\n%enddef\n%include \"x.i\"\n")
    got = [(name, cond, len(lines)) for name, cond, _comment, lines in swig_directives(text)]
    assert got == [("nspacemove", "(SWIGJAVA || SWIGCSHARP) and (SWIG_VERSION >= 0x040300)", 1),
                   ("feature", "(SWIGJAVA || SWIGCSHARP) and (not (SWIG_VERSION >= 0x040300))", 1),
                   ("define", "", 3), ("include", "", 1)]


def test_cmakes_template_of_an_interface_is_read_and_its_output_left_out(tmp_path):
    from fespp_ia.corpus import swig_chunks
    root = _cpp_tree(tmp_path, {"cmake/swigEtp1_2Include.i.in": "%module ${NAME}\n",
                                "swig/swigEtp1_2Include.i": "%module fetpapi\n",
                                "swig/other.i": "%include \"std_string.i\"\n"})
    rows = list(swig_chunks(root, ("swig", "cmake")))
    assert [(r["source"], r["path"], r["title"]) for r in rows] == [
        ("swig", "swig/other.i", "SWIG › other.i › %include"),
        ("swig", "cmake/swigEtp1_2Include.i.in", "SWIG › swigEtp1_2Include.i › %module")]


PY_EXAMPLE = '''import fesapi

def serialize_grid(repo):
    """Creates a one cell grid."""
    points = fesapi.DoubleArray(24)

def serialize(file_name):
    repo = fesapi.DataObjectRepository()
    serialize_grid(repo)
'''

CPP_EXAMPLE = '''/*-----------------------------------------------------------------------
Licensed to the Apache Software Foundation (ASF) under one
-----------------------------------------------------------------------*/
#include "common/EpcDocument.h"

using namespace std;

void serializeGrid(COMMON_NS::DataObjectRepository * repo, EML2_NS::AbstractHdfProxy* hdfProxy)
{
	if (repo == nullptr) return;
	repo->createIjkGridExplicitRepresentation(nullptr, "", "grid", 1, 1, 1);
}

RESQML2_NS::IjkGridExplicitRepresentation* Example::makeGrid(
	COMMON_NS::DataObjectRepository & repo)
{
	return nullptr;
}

int main()
{
	serializeGrid(nullptr, nullptr);
	return 0;
}
'''


def test_an_example_is_cut_function_by_function_and_titled_by_them(tmp_path):
    """The examples answer "how do I write a grid?": each function is a
    chunk (several when long) titled by the library, the file and the
    function; the licence banner is not a chunk, a notebook is read cell
    by cell without its outputs."""
    import json
    from fespp_ia.corpus import example_chunks
    notebook = json.dumps({"cells": [
        {"cell_type": "markdown", "source": ["# Read an EPC\n", "Open the file."]},
        {"cell_type": "code", "source": ["repo = fesapi.DataObjectRepository()"], "outputs": [{"text": "noise"}]}]})
    root = _cpp_tree(tmp_path, {"python/example/example.py": PY_EXAMPLE, "python/example/demo.ipynb": notebook,
                                "example/example.cpp": CPP_EXAMPLE, "example/CMakeLists.txt": "project(x)\n"})
    rows = list(example_chunks(root, "fesapi", ("example", "python/example")))
    assert all(r["source"] == "examples" for r in rows)
    assert [r["title"] for r in rows] == [
        "fesapi example › example/example.cpp",
        "fesapi example › example/example.cpp › serializeGrid",
        "fesapi example › example/example.cpp › Example::makeGrid",
        "fesapi example › example/example.cpp › main",
        "fesapi example › python/example/demo.ipynb",
        "fesapi example › python/example/example.py",
        "fesapi example › python/example/example.py › serialize_grid",
        "fesapi example › python/example/example.py › serialize"]
    text = {r["title"]: r["text"] for r in rows}
    assert "Licensed" not in text["fesapi example › example/example.cpp"]
    assert "    repo->createIjkGridExplicitRepresentation(" in text["fesapi example › example/example.cpp › serializeGrid"]
    assert "points = fesapi.DoubleArray(24)" in text["fesapi example › python/example/example.py › serialize_grid"]
    cells = text["fesapi example › python/example/demo.ipynb"]
    assert "Open the file." in cells and "repo = fesapi.DataObjectRepository()" in cells and "noise" not in cells


def test_a_long_function_is_cut_at_line_ends():
    from fespp_ia.corpus import lines_to_chunks
    lines = [f"    repo->create({k});" for k in range(100)]
    pieces = lines_to_chunks(lines, size=300)
    assert len(pieces) > 1 and all(len(p) <= 300 for p in pieces)
    assert "\n".join(pieces).split("\n") == lines      # nothing lost, no line cut in two


def test_the_developers_sources_enter_the_corpus_only_when_asked(tmp_path):
    """The application's index answers who looks at a reservoir: the SWIG
    interfaces, the examples, the READMEs of the libraries, fetpapi and
    SWIG's manual enter the corpus only with `developer` -- and the code of
    conduct of a library never."""
    from fespp_ia.corpus import build
    fesapi = _cpp_tree(tmp_path / "fesapi", {
        "src/resqml2/Grid.h": "class Grid {\n/** " + LONG + "*/\nvoid f();\n",
        "swig/swigModule.i": "%module fesapi\n", "python/example/example.py": PY_EXAMPLE,
        "README.md": "# fesapi\n\nBuild it with CMake.\n", "CODE_OF_CONDUCT.md": "# Code\n\nBe kind.\n"})
    fetpapi = _cpp_tree(tmp_path / "fetpapi", {
        "src/etp/ClientSession.h": "class ClientSession {\n/** " + LONG + "*/\nvoid run();\n",
        "cmake/swigEtp1_2Include.i.in": "%module fetpapi\n"})
    dropped = tmp_path / "corpus"
    (dropped / "swig").mkdir(parents=True)
    (dropped / "swig" / "swig-Python.md").write_text("# SWIG 4.4 manual — 33 SWIG and Python\n\nA typemap.\n",
                                                     encoding="utf-8")
    (dropped / "glossaire.md").write_text("# Glossaire\n\nUn pilier est une ligne.\n", encoding="utf-8")
    plain = list(build(fesapi=fesapi, dropped=str(dropped)))
    assert sorted({r["source"] for r in plain}) == ["docs", "fesapi"]
    assert [r["path"] for r in plain if r["source"] == "fesapi"] == ["src/resqml2/Grid.h"]
    dev = list(build(fesapi=fesapi, fetpapi=fetpapi, dropped=str(dropped), developer=True))
    assert sorted({r["source"] for r in dev}) == ["docs", "examples", "fesapi", "fetpapi", "swig"]
    assert sorted(r["path"] for r in dev if r["source"] == "swig") == [
        "cmake/swigEtp1_2Include.i.in", "swig/swig-Python.md", "swig/swigModule.i"]
    assert sorted(r["path"] for r in dev if r["source"] == "fesapi") == ["README.md", "src/resqml2/Grid.h"]
    assert [r["path"] for r in dev if r["source"] == "fetpapi"] == ["src/etp/ClientSession.h"]
    assert [r["id"] for r in dev] == list(range(1, len(dev) + 1))
