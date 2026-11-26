"""engine/node_facts: one answer to "is it a property?", "which
representation?" and "what is it called?" — over a fake assembly laid out as
the reader lays a grid out (a grid folder, its properties folder holding the
geometry leaf "SolidColor"), a multi-realization node, a well, and a derived
recipe of the calculator."""
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import node_facts as nf
from fespp_on_trame.engine.tree import Tree


class _State:
    def __init__(self, loaded):
        self.ui_loaded_array_paths = list(loaded)
        self.ui_vector_component = {}


class _Context:
    load_generation = 0


class _Server:
    context = _Context()


@pytest.fixture
def world():
    asm = FakeDataAssembly()
    folder = asm.add_node_with_attrs("_gridfolder_g1", 0, label="GridContainer_G",
                                     title="Geogrid", type="GridContainer")
    props = asm.add_node_with_attrs("_propsfolder_g1", folder, label="Properties",
                                    title="properties", type="PropertiesFolder")
    geom = asm.add_node_with_attrs("_g1", props, label="IjkGrid_G", title="SolidColor",
                                   type="IjkGrid", typeCode="2")
    poro = asm.add_node_with_attrs("_poro", geom, label="Properties_PORO",
                                   title="PORO", type="ContinuousProperty",
                                   typeCode="4", uom="m3/m3")
    tp = asm.add_node_with_attrs("_tp", geom, label="Properties_TP",
                                 title="Total Porosity", type="ContinuousProperty",
                                 typeCode="4")
    mr = asm.add_node_with_attrs("_mr", geom, label="Properties_MR",
                                 title="NettoGross", propTitle="Net to Gross",
                                 type="MultiRealization", typeCode="4")
    well = asm.add_node_with_attrs("_well", 0, label="Wellbore_W", title="W-1", type="Wellbore")
    tree = Tree(asm)
    p = {k: asm.GetNodePath(v) for k, v in
         (("folder", folder), ("props", props), ("geom", geom), ("poro", poro),
          ("tp", tp), ("mr", mr), ("well", well))}
    store = derived_props.DerivedStore(_Server())
    err, _d = store.create(_State([p["poro"]]), tree, p["geom"], "phi2", "PORO * 2")
    assert not err, err
    previous = derived_props.get_store()
    derived_props.set_store(store)
    p["derived"] = derived_props.path_for(p["geom"], "phi2")
    yield tree, p
    derived_props.set_store(previous)


def test_a_property_is_a_property_leaf_a_series_node_or_a_recipe(world):
    tree, p = world
    for k in ("poro", "mr", "derived"):
        assert nf.is_property(tree, p[k]), k
    for k in ("folder", "props", "geom", "well"):
        assert not nf.is_property(tree, p[k]), k
    assert not nf.is_property(tree, "") and not nf.is_property(tree, "/nowhere")
    assert nf.is_derived(p["derived"]) and not nf.is_derived(p["poro"])
    assert nf.is_property_kind("TimeSeries") and nf.is_property_kind(nf.DERIVED_KIND)
    # a type merely CONTAINING "Property" is not one
    assert not nf.is_property_kind("PropertiesFolder")
    assert not nf.is_property_kind("PropertyKind")


def test_the_representation_of_a_path_a_derived_one_included(world):
    tree, p = world
    assert nf.rep_path_for(tree, p["poro"]) == p["geom"]
    assert nf.rep_path_for(tree, p["geom"]) == p["geom"]
    # a recipe carries the grid it is written on (the app layer had None)
    assert nf.rep_path_for(tree, p["derived"]) == p["geom"]
    assert nf.rep_path_for(tree, p["well"]) == ""        # no representation of its own
    assert nf.rep_path_for(tree, "/nowhere") == "" and nf.rep_path_for(None, p["poro"]) == ""


def test_titles_names_and_units(world):
    tree, p = world
    assert nf.title_of(tree, p["poro"]) == "PORO"
    assert nf.title_of(tree, p["derived"]) == "ƒ phi2"       # as the screen names it
    # a series node: its name in the file, and the VTK name the reader made
    assert nf.title_of(tree, p["mr"]) == "NettoGross"
    assert nf.property_title(tree, p["mr"]) == "Net to Gross"
    assert nf.vtk_base_name(tree, p["mr"]) == "NettoGross"
    assert nf.vtk_base_name(tree, p["tp"]) == "TotalPorosity"   # the C++ strips, never replaces
    assert nf.vtk_base_name(tree, p["derived"]) == "phi2"
    # a grid's geometry leaf is named by its grid folder
    assert nf.display_title(tree, p["geom"]) == "Geogrid"
    assert nf.display_title(tree, p["well"]) == "W-1"
    assert nf.display_title(tree, "/nowhere", "fallback") == "fallback"
    assert nf.unit_of(tree, p["poro"]) == "m3/m3" and nf.unit_of(tree, p["mr"]) == ""
    assert nf.kind_of(tree, p["derived"]) == nf.DERIVED_KIND
    assert nf.kind_of(tree, p["geom"]) == "IjkGrid" and nf.kind_of(tree, "") == ""


def test_the_name_of_the_representation_of_a_path(world):
    tree, p = world
    # a property, a recipe and the geometry leaf all name their grid
    for k in ("poro", "mr", "derived", "geom"):
        assert nf.rep_title(tree, p[k]) == "Geogrid", k
    assert nf.rep_title(tree, p["well"]) == "" and nf.rep_title(tree, "/nowhere") == ""


def test_the_type_registry_agrees_on_what_a_property_is():
    """The polymorphic types (element_type) and node_facts name the same
    kinds: the generic "Property" is the reader's propType fallback on a
    series node, never a node type."""
    from fespp_on_trame.engine import node_kinds
    from fespp_on_trame.engine.element_type import registry
    typed = {k for k, t in registry._REGISTRY.items() if t.is_property()}
    assert typed == set(node_kinds.PROPERTY_KINDS) - {"Property"}
    assert all(nf.is_property_kind(k) for k in typed)


def _well_world():
    asm = FakeDataAssembly()
    well = asm.add_node_with_attrs("_wb", 0, title="55/33-A-4", label="Wellbore", type="Wellbore", typeCode="1")
    frame = asm.add_node_with_attrs("_frame", well, title="Well Log Frame", label="Frame", type="Frame", typeCode="1")
    logs = [asm.add_node_with_attrs(f"_log{i}", frame, title=t, label=t, type="ContinuousProperty", typeCode="4")
            for i, t in enumerate(("GR", "RHOB"))]
    traj = asm.add_node_with_attrs("_traj", well, title="Drilled trajectory", label="Trajectory",
                                   type="WellboreTrajectory", typeCode="1")
    tree = Tree(None)
    tree.set_tree(asm)
    return tree, tree.find_path(frame), sorted(tree.find_path(n) for n in logs), tree.find_path(traj)


def test_the_logs_of_a_frame():
    tree, frame, logs, traj = _well_world()
    assert nf.frame_logs(tree, frame) == logs
    assert nf.frame_logs(tree, traj) == [] and nf.frame_logs(tree, "") == []


def test_a_values_row_is_a_sample_of_a_log_or_of_every_log_of_a_frame_read_by_samples():
    tree, frame, logs, traj = _well_world()
    assert nf.sampled_logs(tree, logs[0], False) == [logs[0]]
    assert nf.sampled_logs(tree, frame, True) == logs        # "Samples": a row is a sample of each log
    assert nf.sampled_logs(tree, frame, False) == []         # "Logs": a row is a log
    assert nf.sampled_logs(tree, traj, True) == [] and nf.sampled_logs(tree, "", True) == []


def test_the_log_view_brings_the_active_node_s_graph_to_its_middle():
    tree, frame, logs, traj = _well_world()
    # a log: its own track; any other node of a wellbore: the wellbore
    assert nf.log_view_focus(tree, logs[0]) == {"well": "55/33-A-4", "curve": "GR"}
    assert nf.log_view_focus(tree, frame) == {"well": "55/33-A-4", "curve": ""}
    assert nf.log_view_focus(tree, traj) == {"well": "55/33-A-4", "curve": ""}
    assert nf.log_view_focus(tree, tree.find_path(tree.find_parent_node_id_with_type(
        tree.find_node_id(frame), "Wellbore"))) == {"well": "55/33-A-4", "curve": ""}
    assert nf.log_view_focus(tree, "") is None and nf.log_view_focus(tree, "/nowhere") is None
