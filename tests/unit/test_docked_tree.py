"""The one rule for the docked tree of a panel that chooses its own content.

Closed by default — except while the panel is empty, where the tree is the
only door in. It opens once, on that first opening, and never by itself
again: a reader who closed it keeps it closed even after emptying the panel.
"""
from fespp_on_trame.app.views.widgets import docked_tree


class FakeState:
    """A trame state as these panels use it: `state[name] = value` to write,
    `getattr(state, name, None)` to read."""

    def __setitem__(self, name, value):
        setattr(self, name, value)


class TestTheFirstOpening:
    def setup_method(self):
        docked_tree.forget("view_1")

    def test_an_empty_panel_opens_its_tree(self):
        state = FakeState()
        docked_tree.seed_open(state, "compare_tree_open__view_1", "view_1",
                              empty=True)
        assert state.compare_tree_open__view_1 is True

    def test_a_panel_with_something_in_it_does_not(self):
        state = FakeState()
        docked_tree.seed_open(state, "compare_tree_open__view_1", "view_1",
                              empty=False)
        assert state.compare_tree_open__view_1 is False


class TestAfterwards:
    def setup_method(self):
        docked_tree.forget("view_2")

    def test_a_closed_tree_stays_closed_when_the_panel_empties(self):
        state = FakeState()
        docked_tree.seed_open(state, "welllog_tree_open__view_2", "view_2",
                              empty=False)
        state["welllog_tree_open__view_2"] = False   # the reader's own answer
        docked_tree.seed_open(state, "welllog_tree_open__view_2", "view_2",
                              empty=True)
        assert state.welllog_tree_open__view_2 is False

    def test_an_open_tree_stays_open_when_the_panel_fills(self):
        state = FakeState()
        docked_tree.seed_open(state, "welllog_tree_open__view_2", "view_2",
                              empty=True)
        docked_tree.seed_open(state, "welllog_tree_open__view_2", "view_2",
                              empty=False)
        assert state.welllog_tree_open__view_2 is True

    def test_a_torn_down_var_comes_back_closed_not_None(self):
        # per_view_state.teardown nulls the per-view vars; a rebuilt panel
        # of the SAME id must not mount its tree on `undefined`
        state = FakeState()
        docked_tree.seed_open(state, "compare_tree_open__view_2", "view_2",
                              empty=True)
        state["compare_tree_open__view_2"] = None
        docked_tree.seed_open(state, "compare_tree_open__view_2", "view_2",
                              empty=True)
        assert state.compare_tree_open__view_2 is False


class TestTheMemoryDiesWithTheView:
    def test_a_closed_view_leaves_nothing_behind(self):
        state = FakeState()
        docked_tree.seed_open(state, "compare_tree_open__view_3", "view_3",
                              empty=False)
        docked_tree.forget("view_3")
        docked_tree.seed_open(state, "compare_tree_open__view_3", "view_3",
                              empty=True)
        assert state.compare_tree_open__view_3 is True
