"""app/scene/activation: one writer for the active nodes of the 3D views,
and one rule for the representation a grid-scoped card acts on."""
from fespp_on_trame.app.scene.activation import Activation, SLICERS, THRESHOLDS


class _State(dict):
    def __getattr__(self, k):
        return self.get(k)


KINDS = {"/ijk": "IjkGrid", "/ugrid": "UnstructuredGrid", "/well": "Trajectory"}


def _act(loaded=("/ijk", "/ugrid", "/well")):
    state = _State()

    def rep_of(path):
        return path.split("#")[0] if path else ""

    def qualifies(tool, rep):
        kind = KINDS.get(rep, "")
        return kind == "IjkGrid" if tool == SLICERS else kind in ("IjkGrid", "UnstructuredGrid")

    return Activation(state, rep_of, qualifies, lambda: list(loaded),
                      views=lambda: ["v1", "v2"]), state


def test_activate_writes_the_node_and_its_tab_together():
    act, state = _act()
    act.activate("v1", "/ugrid#poro", tab="reservoir")
    assert state["active_path__v1"] == "/ugrid#poro"
    assert state["active_by_tab__v1"] == {"reservoir": "/ugrid#poro"}
    act.activate("v1", "/well")             # no tab: the tab's node stays
    assert state["active_by_tab__v1"] == {"reservoir": "/ugrid#poro"}


def test_the_thresholds_follow_an_unstructured_grid_the_slicers_do_not():
    # D14: the card's title and its controllers name the same grid
    act, _state = _act()
    act.activate("v1", "/ugrid#poro", tab="reservoir")
    assert act.target_of("v1", THRESHOLDS) == "/ugrid"
    assert act.target_of("v1", SLICERS) == "/ijk"      # the first IJK loaded


def test_the_view_s_active_node_comes_first_a_surface_included():
    # 27/10: a surface property clicked in the Surface tab is what the
    # Thresholds act on, the Reservoir tab's grid staying the Slicers'
    KINDS["/surf"] = "TriangulatedSet"
    try:
        act, _state = _act(loaded=("/ijk", "/surf"))
        act.activate("v1", "/ijk#poro", tab="reservoir")
        act.activate("v1", "/surf#depth", tab="surface")

        def qualifies(tool, rep):
            kind = KINDS.get(rep, "")
            return kind == "IjkGrid" if tool == SLICERS else kind in ("IjkGrid", "TriangulatedSet")
        act._qualifies = qualifies
        assert act.target_of("v1", THRESHOLDS) == "/surf"
        assert act.target_of("v1", SLICERS) == "/ijk"
    finally:
        KINDS.pop("/surf", None)


def test_a_container_is_filed_by_the_geometry_it_wraps():
    # 27/10: a surface laid out like a grid goes to the Surface tab
    from fespp_on_trame.engine import node_kinds
    from fespp_on_trame.engine.tree import Tree
    from tests.unit.fake_assembly import FakeDataAssembly
    asm = FakeDataAssembly()
    for uuid, kind in (("g1", "IjkGrid"), ("s1", "TriangulatedSet")):
        cont = asm.add_node_with_attrs(f"_gridfolder_{uuid}", 0, type="GridContainer", title=uuid)
        props = asm.add_node_with_attrs(f"_propsfolder_{uuid}", cont, type="PropertiesFolder")
        asm.add_node_with_attrs(f"_{uuid}", props, type=kind, title="SolidColor")
    tree = Tree(asm)
    grid = asm.FindFirstNodeWithName("_gridfolder_g1")
    surf = asm.FindFirstNodeWithName("_gridfolder_s1")
    assert tree.container_geometry_type(surf) == "TriangulatedSet"
    assert node_kinds.family_of_type(tree.family_type(surf)) == "Surface"
    assert node_kinds.family_of_type(tree.family_type(grid)) == "Reservoir"


def test_a_point_set_s_property_resolves_to_its_geometry():
    # 27/10 evening, the PO: a property of a point set ticked no geometry
    # and coloured nothing — the up-walk knew the grids only
    from fespp_on_trame.engine.tree import Tree
    from tests.unit.fake_assembly import FakeDataAssembly
    asm = FakeDataAssembly()
    cont = asm.add_node_with_attrs("_gridfolder_p1", 0, type="GridContainer", title="events")
    props = asm.add_node_with_attrs("_propsfolder_p1", cont, type="PropertiesFolder")
    geom = asm.add_node_with_attrs("_p1", props, type="PointSet", title="SolidColor")
    mag = asm.add_node_with_attrs("_m1", props, type="ContinuousProperty", title="Magnitude")
    tree = Tree(asm)
    assert tree.find_representation_node(mag) == geom
    assert tree.find_representation_node(cont) == geom


def test_nothing_qualifying_targets_nothing():
    act, _state = _act(loaded=("/well",))
    assert act.target_of("v1", THRESHOLDS) == ""


def test_clear_drops_an_unread_node_everywhere():
    # SA: a node that failed to read leaves no view with it active
    act, state = _act()
    act.activate("v1", "/ugrid#poro", tab="reservoir")
    act.activate("v2", "/ijk", tab="reservoir")
    assert act.clear(["/ugrid#poro"]) == ["v1"]
    assert state["active_path__v1"] == "" and state["active_by_tab__v1"] == {}
    assert state["active_path__v2"] == "/ijk"


def test_restore_puts_both_back():
    act, state = _act()
    act.restore("v1", "/ijk", {"reservoir": "/ijk"})
    assert act.path("v1") == "/ijk" and act.by_tab("v1") == {"reservoir": "/ijk"}


def test_the_values_view_reads_the_node_made_active_last_in_whichever_tree():
    # the log view's tree used last: every 3D view's Values reads its node; a 3D view's tree used again: back
    act, state = _act()
    act._kind_of = lambda p: "ContinuousProperty" if p else ""
    act.activate("v1", "/ugrid#poro")
    act.values_update("v1")
    assert act.values_path("v1") == "/ugrid#poro"
    act.focused("welllog", "/well#GR")
    assert act.values_path("v1") == "/well#GR" and act.values_path("v2") == "/well#GR"
    act.unfocused()
    assert act.values_path("v1") == "/ugrid#poro" and not state.get("ui_values_focus")


def test_a_node_unloaded_leaves_the_cards():
    act, state = _act()
    act.activate("v1", "/ugrid#efac", tab="well")
    act.clear(["/ugrid#efac"])
    assert state["active_path__v1"] == "" and state["active_by_tab__v1"] == {}


def test_a_panel_s_active_node_unticked_stays_in_the_values_view():
    # the log view's tree: its active log unticked stays its active row, the Values view offers to read it again
    act, state = _act()
    act._kind_of = lambda p: "ContinuousProperty" if p else ""
    act.activate("v1", "/ugrid#poro")
    act.focused("welllog", "/well#GR")
    act.unloaded(["/well#GR"])
    assert act.focus() == "/well#GR"
    assert act.values_path("v1") == "/well#GR" and act.values_path("v2") == "/well#GR"
    # ticked again: still the node read, nothing to make active again
    assert act.values_path("v1") == "/well#GR"


def test_a_3d_view_s_active_node_unticked_stays_its_active_row():
    # the PO, 23/11: the box clicked lights its row like any click, an untick too;
    # the cards act on what is read
    act, state = _act(loaded=("/ijk", "/well"))
    act._kind_of = lambda p: "ContinuousProperty" if p else ""
    act.activate("v1", "/ugrid#poro", tab="reservoir")
    act.values_update("v1")
    act.unloaded(["/ugrid#poro"])
    assert act.path("v1") == "/ugrid#poro" and act.by_tab("v1") == {"reservoir": "/ugrid#poro"}
    assert act.values_path("v1") == "/ugrid#poro"
    assert act.target_of("v1", THRESHOLDS) == "/ijk"      # the grid unticked is acted on no more


def test_a_node_made_active_takes_over_from_an_object_picked_in_a_card():
    # the PO, 23/11: Geogrid picked in the slicer's list, then a node clicked: the card follows the node
    act, state = _act()
    act.activate("v1", "/ugrid#poro", tab="reservoir")
    act.pin("v1", SLICERS, "/ijk")
    act.pin("v1", THRESHOLDS, "/ijk")
    assert act.target_of("v1", THRESHOLDS) == "/ijk"
    act.unpinned("v1")
    assert act.pinned("v1", SLICERS) == "" and act.pinned("v1", THRESHOLDS) == ""
    assert act.target_of("v1", THRESHOLDS) == "/ugrid"


def test_a_node_made_active_takes_over_from_the_whole_scene_too():
    # the PO, 23/11: Whole scene picked by hand, then anything highlighted: the card goes to it
    from fespp_on_trame.engine.blockscope.scene_crop import SCENE
    act, state = _act()
    act.pin("v1", SLICERS, SCENE)
    act.pin("v1", THRESHOLDS, "/ijk")
    act.unpinned("v1")
    assert act.pinned("v1", SLICERS) == "" and act.pinned("v1", THRESHOLDS) == ""


def test_the_geometry_slicer_takes_no_grid_the_view_does_not_name():
    # the PO, 23/11: a surface active (no grid the card cuts), nothing active: the whole scene,
    # not the Reservoir tree's last grid
    act, _state = _act()
    act.activate("v1", "/ijk#poro", tab="reservoir")
    act.activate("v1", "/well", tab="well")
    assert act.target_of("v1", SLICERS, fallback=False) == "/ijk"
    assert act.target_of("v1", SLICERS, fallback=False, remembered=False) == ""
    act.activate("v1", "/ijk#poro", tab="reservoir")
    assert act.target_of("v1", SLICERS, fallback=False, remembered=False) == "/ijk"


def test_a_wellbore_made_active_in_a_panel_s_tree_reads_as_in_a_3d_view():
    # a folder: the Values view reads its trajectory, not "no representation for this node"
    act, state = _act()
    kinds = {"/wb": "Wellbore", "/wb/traj": "WellboreTrajectory", "/wb/f/gr": "ContinuousProperty"}
    act._kind_of = lambda p: kinds.get(p, "")
    act._rep_path_of = lambda p: {"/wb/traj": "/wb/traj", "/wb/f/gr": "/wb/f"}.get(p, "")
    state["selected_paths"] = ["/wb/traj", "/wb/f/gr"]
    act.focused("welllog", "/wb")
    assert act.values_path("v1") == "/wb/traj"


def _views_state(last="v2", **by_tab):
    state = _State(fespp_render_panels=[{"id": "v1"}, {"id": "v2"}, {"id": "g", "globe": True}],
                   fespp_last_render_panel_id=last)
    for vid, tabs in by_tab.items():
        state[f"active_by_tab__{vid}"] = tabs
    return state


def test_a_log_tree_opens_on_the_well_node_of_the_3d_view_used_last():
    from fespp_on_trame.app.scene.activation import well_node_to_open
    state = _views_state(v1={"well": "/w1/log"}, v2={"well": "/w2/log", "reservoir": "/ijk"})
    assert well_node_to_open(state) == "/w2/log"
    state["fespp_last_render_panel_id"] = "v1"
    assert well_node_to_open(state) == "/w1/log"


def test_a_log_tree_opens_on_another_3d_view_s_well_node_when_the_last_has_none():
    from fespp_on_trame.app.scene.activation import well_node_to_open
    assert well_node_to_open(_views_state(v1={"well": "/w1"}, v2={"reservoir": "/ijk"})) == "/w1"
    # the Globe has no Well card of the data, a view closed is no longer read
    assert well_node_to_open(_views_state(last="g", g={"well": "/wg"})) == ""
    assert well_node_to_open(_views_state(last="gone")) == ""
