"""engine/tree_families.node_brought_back: a family's tree card made the card
in use brings back its own active node — the one it had last, else its first
object read, else its first row, in the order the card draws them — so the
cards of the view (slicers, thresholds, Values) follow a node of the tree in
use, never another family's (the PO, 23/11: the Surface tree clicked, the
Geometry slicer stayed on the Reservoir's Geogrid), and a card opened with
nothing active has its first row active."""
from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import tree_families
from fespp_on_trame.engine.tree import Tree


def _world():
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_geogrid", 0, label="IjkGrid_G", title="Geogrid", type="IjkGrid")
    poro = asm.add_node_with_attrs("_poro", grid, label="P", title="PORO", type="ContinuousProperty")
    pts = asm.add_node_with_attrs("_pts", 0, label="PointSet_D", title="Depth Points", type="PointSet")
    horizon = asm.add_node_with_attrs("_hz", 0, label="Tri_H", title="Horizon", type="TriangulatedSet")
    depth = asm.add_node_with_attrs("_hzd", horizon, label="Z", title="Depth", type="ContinuousProperty")
    well = asm.add_node_with_attrs("_w", 0, label="Wellbore_W", title="W-1", type="Wellbore")
    tree = Tree(asm)
    p = {k: asm.GetNodePath(v) for k, v in (("grid", grid), ("poro", poro), ("pts", pts), ("horizon", horizon),
                                            ("depth", depth), ("well", well))}
    return tree, p


def test_the_family_of_a_card():
    assert tree_families.title_of_key("tree_surface") == "Surface"
    assert tree_families.title_of_key("tree") == "Reservoir"
    assert tree_families.title_of_key("slicers") == ""


def test_a_card_never_clicked_in_brings_its_first_object_read():
    tree, p = _world()
    got = tree_families.node_brought_back(tree, "Surface", p["poro"], None, [p["poro"], p["horizon"], p["pts"]])
    assert got == p["pts"], "the first in the tree's order, not in the order ticked"


def test_a_card_brings_back_the_node_it_had_last():
    tree, p = _world()
    got = tree_families.node_brought_back(tree, "Surface", p["poro"], p["depth"], [p["pts"], p["horizon"], p["depth"]])
    assert got == p["depth"]


def test_nothing_changes_when_the_active_node_is_already_of_its_tree():
    # a pick in the 3D view reveals the card: the node picked stays
    tree, p = _world()
    assert tree_families.node_brought_back(tree, "Surface", p["horizon"], p["pts"], [p["pts"], p["horizon"]]) == ""


def test_a_card_with_nothing_read_brings_its_first_row():
    tree, p = _world()
    assert tree_families.node_brought_back(tree, "Surface", p["poro"], None, [p["poro"]]) == p["pts"]
    assert tree_families.node_brought_back(tree, "Surface", "", None, None) == p["pts"]
    assert tree_families.node_brought_back(tree, "Well", p["poro"], None, None) == p["well"]


def test_a_card_of_a_family_the_file_has_not_brings_nothing():
    tree, p = _world()
    assert tree_families.node_brought_back(tree, "Seismic", p["poro"], None, None) == ""


def _surfaces():
    """Surfaces written in an order that is not the tree's, a grid and a
    lattice grid among them, two under interpretations."""
    asm = FakeDataAssembly()
    s10 = asm.add_node_with_attrs("_s10", 0, title="Surf 10", type="TriangulatedSet",
                                  interpretation="i-a", interpretationTitle="Top")
    grid = asm.add_node_with_attrs("_gridfolder_g", 0, title="Grid", type="GridContainer")
    asm.add_node_with_attrs("_g", grid, title="SolidColor", type="IjkGrid")
    cube = asm.add_node_with_attrs("_gridfolder_c", 0, title="Cube", type="GridContainer")
    asm.add_node_with_attrs("_c", cube, title="SolidColor", type="IjkGrid")
    s2 = asm.add_node_with_attrs("_s2", 0, title="Surf 2", type="PointSet")
    wrapped = asm.add_node_with_attrs("_gridfolder_t", 0, title="horizon B", type="GridContainer",
                                      interpretation="i-b", interpretationTitle="Base",
                                      feature="f-b", featureTitle="Zone")
    asm.add_node_with_attrs("_t", wrapped, title="SolidColor", type="Grid2d")
    tree = Tree(asm)
    tree.lattice_rows = frozenset({asm.GetNodePath(cube)})
    return tree, {k: asm.GetNodePath(v) for k, v in (("s10", s10), ("s2", s2), ("wrapped", wrapped),
                                                     ("grid", grid), ("cube", cube))}


def test_the_rows_of_a_card_in_the_order_it_draws_them():
    tree, p = _surfaces()
    # by title, case aside, numbers as numbers; a container is the geometry it wraps
    assert tree_families.family_rows(tree, "Surface") == [p["wrapped"], p["s2"], p["s10"]]
    # the lattice grid is the Seismic card's, the other grid the Reservoir's
    assert tree_families.family_rows(tree, "Reservoir") == [p["grid"]]
    assert tree_families.family_rows(tree, "Seismic") == [p["cube"]]
    assert tree_families.node_brought_back(tree, "Surface", "", None, None) == p["wrapped"]


def test_the_first_row_follows_the_layout():
    tree, p = _surfaces()
    # under their interpretations, by its title (Base before Top); an object with none after them
    assert tree_families.family_rows(tree, "Surface", "by_interpretation") == [p["wrapped"], p["s10"], p["s2"]]
    # a feature's row by its title (Zone), after the interpretation Top that has none
    assert tree_families.family_rows(tree, "Surface", "by_feature_and_interpretation") == [
        p["s10"], p["wrapped"], p["s2"]]
    assert tree_families.node_brought_back(tree, "Surface", "", None, None,
                                           "by_feature_and_interpretation") == p["s10"]


def test_the_first_object_read_in_the_order_the_card_draws_them():
    tree, p = _surfaces()
    # Surf 10 written first in the file, Surf 2 first in the card
    assert tree_families.node_brought_back(tree, "Surface", "", None, [p["s10"], p["s2"]]) == p["s2"]


def test_a_remembered_node_gone_from_the_file_or_of_another_family_is_not_brought_back():
    tree, p = _world()
    assert tree_families.node_brought_back(tree, "Surface", "", "/data/_gone", [p["pts"]]) == p["pts"]
    assert tree_families.node_brought_back(tree, "Surface", "", p["poro"], [p["pts"]]) == p["pts"]


def test_back_to_the_reservoir():
    tree, p = _world()
    assert tree_families.node_brought_back(tree, "Reservoir", p["pts"], p["poro"], [p["poro"], p["pts"]]) == p["poro"]
