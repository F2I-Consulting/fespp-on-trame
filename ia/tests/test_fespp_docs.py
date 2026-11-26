"""The FESPP plugin's documentation as corpus chunks: the proxies of
Energistics.xml, the class summaries of the headers and the enums of
enum.h."""
from fespp_ia.fespp_docs import cut_lines, enum_summaries, header_summaries, header_summary, xml_chunks

XML = """<ServerManagerConfiguration>
  <ProxyGroup name="sources">
    <SourceProxy name="EPCReader" class="vtkEPCReader" label="Energistics Packaging Conventions (EPC) Reader">
      <Documentation short_help="A reader for an Energistics format.">A reader for an Energistics format.
        The underlying format uses OPC to store XML documents.</Documentation>
      <StringVectorProperty name="FileName" command="SetFileName" number_of_elements="1">
        <Documentation>This property specifies the file name for the epc reader.</Documentation>
      </StringVectorProperty>
      <StringVectorProperty name="FilesInfo" command="GetAllFiles" information_only="1">
        <StringArrayHelper />
      </StringVectorProperty>
      <IntVectorProperty name="TreeHierarchyMode" label="Tree Hierarchy" command="SetTreeHierarchyMode"
          number_of_elements="1" default_values="0">
        <EnumerationDomain name="enum">
          <Entry value="0" text="Flat" />
          <Entry value="1" text="By Interpretation" />
        </EnumerationDomain>
        <Documentation>
          Layout of the data assembly tree.
        </Documentation>
      </IntVectorProperty>
      <PropertyGroup label="Wellbore marker"><Property name="MarkerSize" /></PropertyGroup>
    </SourceProxy>
  </ProxyGroup>
  <ProxyGroup name="filters">
    <SourceProxy name="EnergisticsExtractor" class="vtkEnergisticsExtractor" label="Extract Energistics block">
      <Documentation long_help="Extract Energistics block">
      </Documentation>
      <InputProperty command="SetInputConnection" name="Input">
        <Documentation>The input from which the selection is extracted.</Documentation>
      </InputProperty>
    </SourceProxy>
  </ProxyGroup>
</ServerManagerConfiguration>"""


def test_a_proxy_is_one_chunk_with_its_help_and_its_documented_properties():
    chunks = {c["title"]: c for c in xml_chunks(XML)}
    c = chunks["FESPP plugin › Energistics Packaging Conventions (EPC) Reader"]
    assert c["source"] == "fespp" and c["path"].endswith("Energistics.xml#EPCReader")
    text = c["text"]
    assert text.startswith("FESPP plugin › Energistics Packaging Conventions (EPC) Reader\n\n"
                           "Energistics Packaging Conventions (EPC) Reader: ParaView source EPCReader (class vtkEPCReader)")
    assert text.count("A reader for an Energistics format.") == 1    # the short help opens the full text: once
    assert "The underlying format uses OPC to store XML documents." in text
    assert "- FileName: This property specifies the file name for the epc reader." in text
    assert "- Tree Hierarchy (TreeHierarchyMode) [default 0; values 0 = Flat, 1 = By Interpretation]: " \
           "Layout of the data assembly tree." in text
    assert "Other properties: FilesInfo" in text
    assert "MarkerSize" not in text                                   # a PropertyGroup is not a property


def test_a_filter_documented_by_its_long_help_only():
    chunks = {c["title"]: c for c in xml_chunks(XML)}
    text = chunks["FESPP plugin › Extract Energistics block"]["text"]
    assert "Extract Energistics block: ParaView filter EnergisticsExtractor" in text
    assert "- Input: The input from which the selection is extracted." in text


def test_a_long_proxy_is_cut_with_its_title_repeated():
    """A proxy too long for one chunk is cut into numbered pieces, each
    opening with the proxy's title, so that a piece retrieved alone still
    says what it documents."""
    props = "".join(f'<IntVectorProperty name="P{i}"><Documentation>{"word " * 40}</Documentation>'
                    f"</IntVectorProperty>" for i in range(12))
    xml = f'<S><ProxyGroup name="sources"><SourceProxy name="Big" label="Big">{props}</SourceProxy></ProxyGroup></S>'
    chunks = list(xml_chunks(xml))
    assert len(chunks) >= 3
    assert [c["title"] for c in chunks[:2]] == ["FESPP plugin › Big (1)", "FESPP plugin › Big (2)"]
    assert all(c["text"].startswith("FESPP plugin › Big\n\n") for c in chunks)
    assert all(len(c["text"]) < 1200 for c in chunks)
    assert sum(c["text"].count("- P") for c in chunks) == 12


def test_unreadable_xml_gives_nothing():
    assert list(xml_chunks("<not closed")) == []


MAPPING_H = """/*---- Licensed to the Apache Software Foundation ----*/
#ifndef __ResqmlIjkGridToVtkExplicitStructuredGrid__h__
#define __ResqmlIjkGridToVtkExplicitStructuredGrid__h__

/** @brief\ttransform a resqml ijkGrid representation to vtkExplicitStructuredGrid
 */

// include system
#include <string>
#include "ResqmlAbstractRepresentationToVtkPartitionedDataSet.h"

namespace RESQML2_NS
{
\tclass AbstractIjkGridRepresentation;
}

class ResqmlIjkGridToVtkExplicitStructuredGrid : public ResqmlAbstractRepresentationToVtkPartitionedDataSet
{
public:
\t/**
\t * Constructor
\t */
\texplicit ResqmlIjkGridToVtkExplicitStructuredGrid(const RESQML2_NS::AbstractIjkGridRepresentation *ijkGrid);

\t/**
\t * load vtkDataSet with resqml data
\t */
\tvoid loadVtkObject() override;

\t/**
\t * Create the VTK points from the RESQML points of the RESQML IJK grid representation. Each point is
\t * read once.
\t */
\tvoid createPoints();
protected:
\t/**
\t * method : checkHyperslabingCapacity
\t * check if an ijkgrid is Hyperslabed
\t */
\tvoid checkHyperslabingCapacity(const RESQML2_NS::AbstractIjkGridRepresentation *ijkGrid);
};
#endif
"""

VTK_H = """#include <vtkPartitionedDataSetCollectionAlgorithm.h>
class vtkDataAssembly;

/**
 * A VTK reader for EPC document.
 */
class ENERGISTICS_EXPORT  vtkEPCReader : public vtkPartitionedDataSetCollectionAlgorithm
{
public:
\tstatic vtkEPCReader *New();
\t///@{
\t/**
\t* API to set the filenames.
\t*/
\tvoid AddFileNameToFiles(const char* fname);
\tvoid ClearFileName();
\t///@}
protected:
\tvtkEPCReader();
\t~vtkEPCReader() final;
};
"""

ENUM_H = """#include <string>

enum class MapperType
{
\tFolder,
\tData
};

// Tree node kinds set as the "typeCode" attribute on each vtkDataAssembly
// node.
enum class TreeViewNodeType
{
\tUnknown,
\tCollection,
\t// Synthetic types created by searchRealization() to fold per-
\t// realization property nodes into a single tree leaf.
\tMultiRealization,
\t// Appended on purpose (keeps existing serialized int values stable).
\t// A BlockedWellbore is a WellboreFrame subclass, but FESPP attaches it
\t// UNDER its supporting grid.
\tBlockedWellbore,
\t// KEEP LAST, never serialized: how many entries there are.
\t_Count
};

enum class TreeHierarchyMode
{
\tFlat = 0,
\tByInterpretation = 1
};
"""


def test_a_mapping_header_gives_its_brief_from_above_the_includes_and_its_method_one_liners():
    lines = header_summary(MAPPING_H, "ResqmlIjkGridToVtkExplicitStructuredGrid.h")
    assert lines[0] == "ResqmlIjkGridToVtkExplicitStructuredGrid: transform a resqml ijkGrid representation " \
                       "to vtkExplicitStructuredGrid"
    assert lines[1] == "Derives from ResqmlAbstractRepresentationToVtkPartitionedDataSet."
    assert "- void loadVtkObject() override: load vtkDataSet with resqml data" in lines
    assert "- void createPoints(): Create the VTK points from the RESQML points of the RESQML IJK grid " \
           "representation." in lines
    assert any(ln.startswith("- void checkHyperslabingCapacity(") and "Hyperslabed" in ln for ln in lines)
    assert not any("Constructor" in ln for ln in lines)


def test_a_vtk_header_gives_its_brief_from_right_above_the_class_and_the_grouped_method():
    lines = header_summary(VTK_H, "vtkEPCReader.h")
    assert lines[0] == "vtkEPCReader: A VTK reader for EPC document."
    assert lines[1] == "Derives from vtkPartitionedDataSetCollectionAlgorithm."
    assert lines[2:] == ["Methods:", "- void AddFileNameToFiles(const char* fname): API to set the filenames."]


def test_an_undocumented_class_still_gives_its_name_and_base_and_no_class_gives_nothing():
    assert header_summary("class ResqmlWellboreFrameToVtkPartitionedDataSet : public CommonAbstractObjectSet"
                          "ToVtkPartitionedDataSetSet\n{\npublic:\n  void bar();\n};\n",
                          "ResqmlWellboreFrameToVtkPartitionedDataSet.h") == [
        "ResqmlWellboreFrameToVtkPartitionedDataSet (a class of the FESPP plugin)",
        "Derives from CommonAbstractObjectSetToVtkPartitionedDataSetSet."]
    assert header_summary("#define X 1\nclass Other {\n};\n", "Foo.h") is None


def test_the_enums_give_every_value_with_its_integer_and_its_comment():
    """Each value carries its implicit integer and its comment; the trailing
    count sentinel and the maintenance notes stay out."""
    summaries = dict(enum_summaries(ENUM_H))
    assert set(summaries) == {"MapperType", "TreeViewNodeType", "TreeHierarchyMode"}
    assert summaries["MapperType"][:2] == ["MapperType (enum of the FESPP plugin)", "Values:"]
    assert summaries["MapperType"][2:] == ["- Folder = 0", "- Data = 1"]
    t = summaries["TreeViewNodeType"]
    assert t[0] == 'TreeViewNodeType: Tree node kinds set as the "typeCode" attribute on each vtkDataAssembly node.'
    assert "- Collection = 1" in t
    assert "- MultiRealization = 2: Synthetic types created by searchRealization() to fold per- realization " \
           "property nodes into a single tree leaf." in t
    assert "- BlockedWellbore = 3: A BlockedWellbore is a WellboreFrame subclass, but FESPP attaches it UNDER " \
           "its supporting grid." in t
    assert not any("_Count" in ln or "KEEP LAST" in ln or "Appended on purpose" in ln for ln in t)
    assert summaries["TreeHierarchyMode"][2:] == ["- Flat = 0", "- ByInterpretation = 1"]


def test_header_summaries_walk_the_plugin_folder(tmp_path):
    plugin = tmp_path / "Plugin" / "Energistics"
    (plugin / "Mapping").mkdir(parents=True)
    (plugin / "Tools").mkdir()
    (plugin / "Mapping" / "ResqmlIjkGridToVtkExplicitStructuredGrid.h").write_text(MAPPING_H, encoding="utf-8")
    (plugin / "vtkEPCReader.h").write_text(VTK_H, encoding="utf-8")
    (plugin / "vtkEPCReader.cxx").write_text("/** not a header */ int x;", encoding="utf-8")
    (plugin / "Tools" / "enum.h").write_text(ENUM_H, encoding="utf-8")
    rows = list(header_summaries(str(tmp_path)))
    titles = [r["title"] for r in rows]
    assert titles == ["FESPP › ResqmlIjkGridToVtkExplicitStructuredGrid", "FESPP › MapperType",
                      "FESPP › TreeViewNodeType", "FESPP › TreeHierarchyMode", "FESPP › vtkEPCReader"]
    assert all(r["source"] == "fespp" for r in rows)
    assert rows[0]["path"] == "Plugin/Energistics/Mapping/ResqmlIjkGridToVtkExplicitStructuredGrid.h"
    assert rows[2]["path"] == "Plugin/Energistics/Tools/enum.h#TreeViewNodeType"


def test_cut_lines_never_splits_a_line():
    lines = ["a" * 500, "b" * 500, "c" * 100]
    assert cut_lines(lines, 900) == ["a" * 500, "b" * 500 + "\n" + "c" * 100]
    assert cut_lines(["a" * 500, "b" * 500, "c" * 100, "d" * 600, "e" * 50], 900) == \
        ["a" * 500, "b" * 500 + "\n" + "c" * 100, "d" * 600 + "\n" + "e" * 50]     # the short tail joins the last piece
    assert cut_lines([], 900) == []
