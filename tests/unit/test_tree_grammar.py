"""One grammar for the four trees — the pure half of it.

A CHECKBOX reads the object and puts it in the panel whose tree was ticked;
unticking leaves that panel and never unloads. An EYE is "shown in a 3D
view", everywhere and only that. What each panel keeps of a tick is
`engine/tree_grammar`; the routing around it is `app.boot`.
"""
from fespp_on_trame.engine import tree_grammar


# A tiny tree: /f is a folder over two properties, /g a grid with none.
_LEAVES = {"/f/a", "/f/b", "/w/log"}
_UNDER = {"/f": ["/f/a", "/f/b"], "/g": [], "/w": ["/w/log"]}


def _is_leaf(path):
    return path in _LEAVES


def _under(path):
    return list(_UNDER.get(path) or [])


class TestWhatATickStandsFor:
    def test_a_leaf_stands_for_itself(self):
        assert tree_grammar.expand(["/f/a"], _is_leaf, _under) == ["/f/a"]

    def test_a_folder_stands_for_every_leaf_under_it(self):
        assert tree_grammar.expand(["/f"], _is_leaf, _under) == ["/f/a", "/f/b"]

    def test_a_folder_with_no_leaf_stands_for_nothing(self):
        # a grid, a feature: the panel cannot compute on it and must not
        # pretend the tick did something
        assert tree_grammar.expand(["/g"], _is_leaf, _under) == []

    def test_the_same_leaf_twice_is_one(self):
        assert tree_grammar.expand(["/f", "/f/a"], _is_leaf, _under) == [
            "/f/a", "/f/b"]


class TestTheLogPanel:
    # the resolver answers with the well a node belongs to, or with every
    # well under it when the tick is a folder above them
    WELLS = {"/w": ["/w"], "/w/frame": ["/w"], "/w/log": ["/w"],
             "/field": ["/w", "/w2"], "/grid": []}

    def _of(self, path):
        return self.WELLS.get(path, [])

    def test_a_ticked_wellbore_is_the_well(self):
        assert tree_grammar.panel_wells(["/w"], self._of) == ["/w"]

    def test_anything_under_a_wellbore_resolves_up_to_it(self):
        # the log correlates wellbores: ticking a marker frame means
        # "this well", not "this array"
        assert tree_grammar.panel_wells(["/w/frame", "/w/log"],
                                        self._of) == ["/w"]

    def test_a_folder_above_the_wells_stands_for_all_of_them(self):
        assert tree_grammar.panel_wells(["/field"], self._of) == ["/w", "/w2"]

    def test_a_node_with_no_wellbore_at_all_adds_nothing(self):
        # the caller says so on screen: a tick that comes off again without
        # a word is the one thing the panel may not do
        assert tree_grammar.panel_wells(["/grid"], self._of) == []


# Two wells: /w1 with a frame of three logs, /w2 with one; a trajectory under /w1.
_CURVES = {"/w1": ["/w1/f/ai", "/w1/f/si", "/w1/f/gr"], "/w2": ["/w2/f/ai"]}


def _well_of(path):
    return "/" + path.strip("/").split("/")[0]


def _is_curve(path):
    return any(path in c for c in _CURVES.values())


def test_a_well_brought_in_by_some_of_its_curves_brings_those():
    # an eye on a kind's folder: the impedances of both wells
    left = tree_grammar.curves_alone(["/w1/f/ai", "/w1/f/si", "/w2/f/ai"], ["/w1", "/w2"],
                                     _well_of, _is_curve, _CURVES.get)
    assert left == ["/w1/f/gr"]


def test_a_well_named_as_a_whole_brings_everything():
    assert tree_grammar.curves_alone(["/w1"], ["/w1"], _well_of, _is_curve, _CURVES.get) == []
    assert tree_grammar.curves_alone(["/w1/traj", "/w1/f/ai"], ["/w1"], _well_of, _is_curve, _CURVES.get) == []


def test_a_well_already_in_the_log_keeps_what_it_draws():
    # /w1 was in the log before: not brought in by this gesture, nothing left out of it
    assert tree_grammar.curves_alone(["/w1/f/ai", "/w2/f/ai"], ["/w2"], _well_of, _is_curve, _CURVES.get) == []
    assert tree_grammar.curves_alone([], ["/w1"], _well_of, _is_curve, _CURVES.get) == []
