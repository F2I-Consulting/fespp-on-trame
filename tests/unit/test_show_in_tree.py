"""The 3D view's right-click "Show in tree": the object's node made the
view's active one and its family's tree card opened, as a click on its row
does — the same gesture as a row of the Data health table."""
from fespp_on_trame.app.scene.activation import Activation
from fespp_on_trame.app.scene.cards import Cards
from fespp_on_trame.app.scene.tree_reveal import show_in_tree
from fespp_on_trame.app.ui import action_icons

XML = ('<root type="Root">'
       '<Geogrid type="GridContainer"><geo type="IjkGrid"/></Geogrid>'
       '<Velocity type="GridContainer"><lat type="IjkGrid"/></Velocity>'
       '<Top type="TriangulatedSet"/>'
       '<W1 type="Wellbore"><traj type="Trajectory"/></W1>'
       '</root>')


class _State(dict):
    def __getattr__(self, k):
        return self.get(k)


def _services(**state):
    st = _State(assembly_xml=XML, **state)
    act = Activation(st, lambda p: p, lambda _tool, _rep: True, lambda: [])
    return act, Cards(st), st


def test_the_node_becomes_active_and_its_family_card_opens():
    act, cards, st = _services()
    cards.set("v1", ["tree"])
    assert show_in_tree(act, cards, st, "v1", "/root/W1/traj") == "tree_well"
    assert act.path("v1") == "/root/W1/traj"
    assert cards.keys("v1") == ["tree", "tree_well"]


def test_a_card_already_open_stays_where_it_is():
    act, cards, st = _services()
    cards.set("v1", ["tree_surface", "tree"])
    assert show_in_tree(act, cards, st, "v1", "/root/Geogrid/geo") == "tree"
    assert cards.keys("v1") == ["tree_surface", "tree"]
    assert act.path("v1") == "/root/Geogrid/geo"


def test_the_values_card_leaves_a_folder_ticked_as_on_a_click_on_the_active_row():
    act, cards, st = _services()
    act.activate("v1", "/root/Geogrid/geo")
    act.ticked("v1", ["/root/Geogrid"])
    show_in_tree(act, cards, st, "v1", "/root/Geogrid/geo")
    assert st["values_folder__v1"] == [] and act.path("v1") == "/root/Geogrid/geo"


def test_a_card_open_behind_another_tab_comes_in_front():
    act, cards, st = _services()
    cards.set("v1", ["tree", "colormap"])
    cards.seen("v1", "colormap", True)
    cards.seen("v1", "tree", False)
    show_in_tree(act, cards, st, "v1", "/root/Geogrid/geo")
    assert st["ui_card_reveal__v1"]["id"] == "tree"


def test_a_lattice_grid_is_shown_in_the_seismic_tree():
    act, cards, st = _services(ui_cube_grid_rows=["/root/Velocity"])
    assert show_in_tree(act, cards, st, "v1", "/root/Velocity/lat") == "tree_seismic"
    assert cards.keys("v1") == ["tree_seismic"]


def test_nothing_under_the_pointer_shows_nothing():
    act, cards, st = _services()
    assert show_in_tree(act, cards, st, "v1", "") == ""
    assert show_in_tree(act, cards, st, "", "/root/Top") == ""
    assert act.path("v1") == "" and cards.keys("v1") == []


def test_the_entry_has_the_tree_icon_and_follows_the_camera_moves():
    entry = action_icons.entry("show-in-tree", "Show in tree")
    assert entry["icon"] == "fespp-data-tree"
    menu = [action_icons.entry(k, k) for k in
            ("xml", "geometry-slicer", "add-to-welllog", "show-in-tree", "pivot", "zoom", "center")]
    assert [e["key"] for e in action_icons.ordered(menu)] == [
        "center", "zoom", "pivot", "show-in-tree", "add-to-welllog", "geometry-slicer", "xml"]
