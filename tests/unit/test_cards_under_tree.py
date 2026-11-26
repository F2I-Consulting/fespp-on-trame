"""The Time & Realizations card and the two slicer cards open docked under
the tree card of the view's active node, split below its panel; with no tree
card open, where the dock places any card."""
from fespp_on_trame.app.views.widgets.card_dock import (
    UNDER_TREE, anchored_specs, card_spec, tree_anchor)


def test_the_three_cards_acting_on_a_node_open_under_a_tree():
    assert set(UNDER_TREE) == {"timereal", "slicers", "thresholds"}


def test_under_the_tree_card_of_the_active_node():
    opened = ["tree", "tree_well", "colormap"]
    for key in UNDER_TREE:
        assert tree_anchor(key, opened + [key], "tree_well") == "tree_well"


def test_the_active_node_tree_closed_the_first_tree_card_open():
    assert tree_anchor("slicers", ["colormap", "tree_surface", "tree"], "tree_well") == "tree_surface"
    assert tree_anchor("timereal", ["tree_seismic", "tree"], "") == "tree_seismic"


def test_no_tree_card_open_the_dock_places_it():
    assert tree_anchor("thresholds", ["colormap", "navigation"], "tree") == ""
    assert tree_anchor("slicers", [], "") == ""


def test_another_card_is_never_anchored():
    assert tree_anchor("colormap", ["tree"], "tree") == ""
    assert tree_anchor("tree_well", ["tree"], "tree") == ""


def test_the_spec_names_the_panel_it_opens_under():
    specs = {"slicers": card_spec("v1", "slicers", "Geometry slicer", 300, 380),
             "tree": card_spec("v1", "tree", "Reservoir", 340, 520)}
    out = anchored_specs(specs, "slicers", "tree_well")
    assert out["slicers"]["below"] == "tree_well"
    assert out["slicers"]["title"] == "Geometry slicer" and out["tree"] == specs["tree"]
    assert "below" not in specs["slicers"]


def test_no_anchor_takes_the_previous_one_off():
    specs = {"timereal": dict(card_spec("v1", "timereal", "Steps"), below="tree")}
    assert "below" not in anchored_specs(specs, "timereal", "")["timereal"]
    plain = {"timereal": card_spec("v1", "timereal", "Steps")}
    assert anchored_specs(plain, "timereal", "") == plain


def test_a_card_without_a_spec_is_left_alone():
    assert anchored_specs(None, "slicers", "tree") == {}
    assert anchored_specs({"tree": {"title": "Reservoir"}}, "slicers", "tree") == {"tree": {"title": "Reservoir"}}


def test_the_two_slicers_open_as_tabs_of_one_another():
    from fespp_on_trame.app.views.widgets.card_dock import tab_mate
    assert tab_mate("thresholds", ["tree", "slicers", "thresholds"]) == "slicers"
    assert tab_mate("slicers", ["tree", "thresholds", "slicers"]) == "thresholds"
    # the first one open opens under the tree, as before
    assert tab_mate("slicers", ["tree", "slicers"]) == ""
    assert tab_mate("timereal", ["tree", "slicers", "thresholds", "timereal"]) == ""


def test_a_tab_mate_goes_with_the_spec_and_is_dropped_when_gone():
    specs = {"thresholds": card_spec("v1", "thresholds", "Property slicer")}
    beside = anchored_specs(specs, "thresholds", "tree", "slicers")["thresholds"]
    assert beside["with"] == "slicers" and beside["below"] == "tree"
    alone = anchored_specs({"thresholds": beside}, "thresholds", "tree")["thresholds"]
    assert "with" not in alone and alone["below"] == "tree"
