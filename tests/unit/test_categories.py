"""Tests for engine/utils/categories: the names behind the codes of a
categorical property, over a fake assembly, with the ParaView lookup table
and the reader's query channel patched."""
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import repo_query
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine.utils import categories as cat

PROP_UUID = "11111111-2222-3333-4444-555555555555"
LOOKUP_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

_PROP_XML = f"""<CategoricalProperty xmlns="http://www.energistics.org/energyml/data/resqmlv2">
  <Title>Facies</Title>
  <Lookup><ContentType>x</ContentType><Title>facies lookup</Title>
    <UUID>{LOOKUP_UUID}</UUID></Lookup>
</CategoricalProperty>"""
_LOOKUP_XML = """<StringTableLookup xmlns="http://www.energistics.org/energyml/data/resqmlv2">
  <Value><Value>Sand</Value><Key>1</Key></Value>
  <Value><Value>Shale</Value><Key>2</Key></Value>
  <Value><Value>Coal, thin</Value><Key>3</Key></Value>
</StringTableLookup>"""


def _tree():
    """A grid in the SolidColor layout (GridContainer > PropertiesFolder >
    geometry + properties) with a categorical FACIES and a discrete ZONE,
    plus a plain grid with a categorical property under it."""
    asm = FakeDataAssembly()
    cont = asm.add_node_with_attrs("_cont", 0, label="Grid", title="Grid",
                                   type="GridContainer", typeCode="2")
    folder = asm.add_node_with_attrs("_propsfolder", cont, label="Properties",
                                     title="Properties", type="PropertiesFolder",
                                     typeCode="2")
    geom = asm.add_node_with_attrs("_geom", folder, label="SolidColor",
                                   title="SolidColor", type="IjkGrid", typeCode="2")
    facies = asm.add_node_with_attrs(f"_{PROP_UUID}", folder, label="Properties_FACIES",
                                     title="FACIES", type="CategoricalProperty",
                                     typeCode="4")
    zone = asm.add_node_with_attrs("_zone", folder, label="Properties_ZONE",
                                   title="ZONE", type="DiscreteProperty", typeCode="4")
    grid_b = asm.add_node_with_attrs("_gridB", 0, label="IjkGrid_B", title="B",
                                     type="IjkGrid", typeCode="2")
    fb = asm.add_node_with_attrs(f"_{PROP_UUID}", grid_b, label="Properties_FB",
                                 title="FB", type="CategoricalProperty", typeCode="4")
    # a realization set: the FESPP reader names the node after the title, no uuid
    mr = asm.add_node_with_attrs("_multireal_Facies", grid_b, label="MR_Facies",
                                 title="Facies", propTitle="Facies",
                                 type="MultiRealization", propType="CategoricalProperty",
                                 typeCode="4", realization_indices="0,1")
    tree = Tree(asm)
    return tree, {k: asm.GetNodePath(n) for k, n in (
        ("geom", geom), ("facies", facies), ("zone", zone), ("grid_b", grid_b),
        ("fb", fb), ("mr", mr))}


@pytest.fixture
def channel(monkeypatch):
    """The query channel answers the property's XML and its lookup's; the
    file lists one categorical property."""
    xml = {PROP_UUID: _PROP_XML, LOOKUP_UUID: _LOOKUP_XML}
    monkeypatch.setattr(repo_query, "has_channel", lambda src: True)
    monkeypatch.setattr(repo_query, "object_xml",
                        lambda src, uuids, cache_tag=None: (
                            xml.get(uuids, "") if isinstance(uuids, str)
                            else [xml.get(u, "") for u in uuids]))
    monkeypatch.setattr(repo_query, "object_uuids",
                        lambda src, type_name, cache_tag=None: [PROP_UUID])
    return object()


def test_the_file_lookup_wins_over_the_lut_annotations(monkeypatch, channel):
    # the ParaView table is shared by every array of that name in the
    # session: the file's own lookup is the authority
    tree, p = _tree()
    monkeypatch.setattr(cat, "lut_labels", lambda name: {1: "One", 2: "Two"})
    assert cat.labels_for(tree, p["facies"], "FACIES", channel) == {
        1: "Sand", 2: "Shale", 3: "Coal, thin"}
    # the plain-grid variant resolves the same way
    assert cat.labels_for(tree, p["fb"], "FB", channel)[2] == "Shale"


def test_lut_used_when_the_lookup_has_nothing(monkeypatch, channel):
    tree, p = _tree()
    monkeypatch.setattr(repo_query, "object_xml",
                        lambda src, uuids, cache_tag=None: "" if isinstance(uuids, str) else [])
    monkeypatch.setattr(cat, "lut_labels", lambda name: {1: "One", 2: "Two"})
    assert cat.labels_for(tree, p["facies"], "FACIES", channel) == {1: "One", 2: "Two"}


def test_no_reader_means_no_lookup(monkeypatch):
    tree, p = _tree()
    monkeypatch.setattr(cat, "lut_labels", lambda name: {})
    assert cat.labels_for(tree, p["facies"], "FACIES", None) == {}


def test_a_realization_set_resolves_by_title_and_reads_the_loaded_lut(monkeypatch, channel):
    tree, p = _tree()
    # no uuid in the node name: the file's categorical of that title
    monkeypatch.setattr(cat, "lut_labels", lambda name: {})
    assert cat.labels_for(tree, p["mr"], "Facies", channel)[1] == "Sand"
    # nothing in the file: the table of the realization array actually loaded
    monkeypatch.setattr(repo_query, "object_uuids",
                        lambda src, type_name, cache_tag=None: [])
    seen = []
    monkeypatch.setattr(cat, "lut_labels",
                        lambda name: seen.append(name) or ({1: "Sand"} if name == "Facies_real_1" else {}))
    assert cat.labels_for(tree, p["mr"], "Facies", channel) == {1: "Sand"}
    assert seen == ["Facies", "Facies_real_0", "Facies_real_1"]


def test_labels_note_speaks_only_for_a_categorical_without_names():
    tree, p = _tree()
    assert cat.labels_note(tree, p["facies"], {}) == cat.NO_NAMES_NOTE
    assert cat.labels_note(tree, p["mr"], {}) == cat.NO_NAMES_NOTE
    assert cat.labels_note(tree, p["facies"], {1: "Sand"}) == ""
    assert cat.labels_note(tree, p["zone"], {}) == ""
    assert cat.labels_note(tree, "derived:///data/_cont#x", {}) == ""


def test_a_discrete_property_never_has_names(monkeypatch, channel):
    tree, p = _tree()
    monkeypatch.setattr(cat, "lut_labels", lambda name: {1: "One"})
    assert cat.labels_for(tree, p["zone"], "ZONE", channel) == {}
    assert cat.labels_for(tree, "/data/_nope", "X", channel) == {}
    assert cat.labels_for(tree, "derived:///data/_cont#x", "x", channel) == {}


def test_lookup_labels_survive_a_channel_that_is_missing(monkeypatch):
    tree, p = _tree()
    monkeypatch.setattr(repo_query, "has_channel", lambda src: True)

    def _raise(*a, **k):
        raise repo_query.ChannelMissing("old plugin")
    monkeypatch.setattr(repo_query, "object_xml", _raise)
    assert cat.lookup_labels(tree, p["facies"], object()) == {}


def test_label_of_falls_back_to_the_code():
    labels = {1: "Sand", 2: "Shale"}
    assert cat.label_of(labels, 1) == "Sand"
    assert cat.label_of(labels, 2.0) == "Shale"
    assert cat.label_of(labels, 3) == "3"
    assert cat.label_of({}, 12345.0) == "12345"       # an identifier, never grouped
    assert cat.label_of(None, 3) == "3"
    assert cat.label_of({}, 2.5) == "2.5"
    assert cat.label_of({}, float("nan")) == "–"


def test_array_path_for_vtk_name_widens_to_the_grid_container():
    tree, p = _tree()
    assert cat.array_path_for_vtk_name(tree, p["geom"], "FACIES") == p["facies"]
    assert cat.array_path_for_vtk_name(tree, p["geom"], "ZONE") == p["zone"]
    assert cat.array_path_for_vtk_name(tree, p["grid_b"], "FB") == p["fb"]
    assert cat.array_path_for_vtk_name(tree, p["grid_b"], "FB_real_3") == p["fb"]
    assert cat.array_path_for_vtk_name(tree, p["geom"], "NOPE") is None
    assert cat.array_path_for_vtk_name(tree, "", "FACIES") is None
