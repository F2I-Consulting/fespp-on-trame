"""The right-click menus of the three panel trees.

The six actions of the data tree are not replayed: half of them have no
meaning in a statistics table or a log. Each tree declares the actions that
mean something in it, the "in / out of this panel" pair is split by `when`
so only the one that would do something is drawn, and a node no action
applies to opens the menu on one disabled line saying why. A right-click
that offers four entries on one row and nothing at all on the next, without
a word, is the silent menu that rule R16 of the UI rules forbids
(doc/wiki/UI-Drawer-Toolbar-Shared.md).

The wrappers are also checked for the corollary of that rule: a panel's
tree leaves none of its outputs on the session-wide names, or a click in it
would reach the data tree's own dispatchers.
"""
import inspect

from fespp_on_trame.app.views.widgets import compare_tree, reconcile_tree, welllog_tree

_TREES = (welllog_tree, compare_tree, reconcile_tree)


def _offered_on(actions, node_type, held, ticked=True):
    """Replay the widget's own menu filter (DataExplorerTree.ctxItemsFor).

    `types` matches the node kind, `when` the side of the checkbox
    ("selected" / "unselected") or of the eye ("shown" / "hidden") the action
    belongs to. In a panel's tree the eye is "in this panel" (the one
    grammar, the PO 18/10): `held` is that."""
    side = {"selected": ticked, "unselected": not ticked,
            "shown": held, "hidden": not held}
    return [a["key"] for a in actions
            if (not a.get("types") or node_type in a["types"])
            and (not a.get("when") or side.get(a["when"]) is True)]


class TestEveryMenuIsAnswerable:
    def test_every_action_says_what_it_applies_to(self):
        for mod in _TREES:
            for action in mod._CONTEXT_ACTIONS:
                assert action.get("types"), (mod.__name__, action["key"])

    def test_every_label_is_a_short_imperative_in_title_case(self):
        for mod in _TREES:
            for action in mod._CONTEXT_ACTIONS:
                label = action["label"]
                assert label == label[0].upper() + label[1:]
                assert len(label) < 30


class TestTheLogMenu:
    def test_it_offers_in_out_and_the_one_act_that_leaves_the_panel(self):
        keys = {a["key"] for a in welllog_tree._CONTEXT_ACTIONS}
        assert keys == {"welllog-add", "welllog-remove"}

    def test_membership_is_offered_on_the_wellbore_only(self):
        # The log's unit is the wellbore, so "Add to this view" on a
        # trajectory would name a membership that is not the node's.
        assert "welllog-add" in _offered_on(welllog_tree._CONTEXT_ACTIONS,
                                            "Wellbore", held=False)
        assert "welllog-add" not in _offered_on(welllog_tree._CONTEXT_ACTIONS,
                                                "Trajectory", held=False)

    def test_a_well_already_in_the_log_is_offered_remove(self):
        offered = _offered_on(welllog_tree._CONTEXT_ACTIONS, "Wellbore",
                              held=True)
        assert "welllog-remove" in offered and "welllog-add" not in offered


class TestTheStatisticsMenu:
    def test_it_offers_what_the_eye_and_the_charts_do_not_give(self):
        keys = [a["key"] for a in compare_tree._CONTEXT_ACTIONS]
        assert keys == ["compare-baseline", "compare-health"]

    def test_the_baseline_is_offered_on_what_the_panel_holds(self):
        acts = compare_tree._CONTEXT_ACTIONS
        assert _offered_on(acts, "CompareItem", False) == ["compare-health"]
        assert _offered_on(acts, "CompareItem", True) == ["compare-baseline", "compare-health"]

    def test_a_part_has_no_baseline(self):
        acts = compare_tree._CONTEXT_ACTIONS
        assert _offered_on(acts, "ComparePart", True) == ["compare-health"]

    def test_a_kind_or_a_representation_folder_opens_the_disabled_line(self):
        for node_type in ("KindFolder", "RepFolder"):
            assert not _offered_on(compare_tree._CONTEXT_ACTIONS, node_type,
                                   held=False)
        src = inspect.getsource(compare_tree)
        assert "context_empty_label=" in src
        assert "a statistic is" in src and "property" in src

    def test_it_lists_the_extracts_of_the_3d_views_as_rows_of_the_session(self):
        src = inspect.getsource(compare_tree)
        assert 'session_rows=("ui_compare_session_rows || []",)' in src
        assert "server.controller.compare_session_eye" in src


class TestNoPanelTreeWritesTheSessionNames:
    """The corollary of rule R16: no panel tree writes the data tree's channels.

    `visible_paths`, `active_path`, `colour_request` and `context_action` are
    the data tree's channels. A panel's tree that left one of its outputs on
    a default name would send its clicks to the 3D views' dispatchers. The
    checkbox is the one shared thing (the one grammar, the PO 18/10: it is
    the session's load, common to every view) — read from `selected_paths`,
    but written through a tick event that says which view it came from."""

    def test_each_wrapper_names_its_outputs_per_view(self):
        for mod in _TREES:
            src = inspect.getsource(mod)
            for default in ('visible_paths="visible_paths"',
                            'active_path="active_path"',
                            'colour_request="colour_request"',
                            'context_action="context_action"'):
                assert default not in src, (mod.__name__, default)
            # Every output carries the view id.
            assert "__{vid}" in src
            # the checkbox's change is an event naming its view, never a
            # write of the session's selection
            assert "selected_changed=" in src and "vid: '{vid}'" in src, mod.__name__

    def test_each_panel_eye_is_what_the_panel_holds(self):
        # The eye is "in this panel" (its per-view holding), offered on what
        # the session holds — the tree's default gate, the checkbox. The
        # Statistics tree says it itself: a formula has no box.
        for mod in _TREES:
            src = inspect.getsource(mod)
            if not mod.__name__.endswith(".compare_tree"):
                assert "eye_paths=" not in src, mod.__name__
            assert ("visible_paths=sel_var" in src
                    or "visible_paths=selected_var" in src), mod.__name__

    def test_no_panel_tree_offers_the_bulk_select_menu(self):
        for mod in _TREES:
            assert "bulk_select=False" in inspect.getsource(mod)

    def test_every_tree_says_why_a_node_has_no_action(self):
        # R16: a right-click is never silent. The data tree is included: a
        # folder, a feature or an interpretation has none of its six actions.
        from fespp_on_trame.app.views.widgets import data_tree
        for mod in _TREES + (data_tree,):
            src = inspect.getsource(mod)
            assert "context_empty_label=" in src, mod.__name__
            # A reason, not a label: the sentence names what the actions
            # apply to.
            assert " — " in src.split("context_empty_label=")[1][:200], \
                mod.__name__


class TestTheReconcileMenu:
    """The Log-to-Grid panel's tree menu.

    "In / out of the table" is offered on what the table holds (a channel, a
    grid property, a wellbore), never on a trajectory."""

    def test_it_offers_the_acts_of_this_table(self):
        keys = {a["key"] for a in reconcile_tree._CONTEXT_ACTIONS}
        assert {"reconcile-add", "reconcile-remove"} <= keys

    def test_add_and_remove_sit_on_either_side_of_the_checkbox(self):
        acts = reconcile_tree._CONTEXT_ACTIONS
        assert "reconcile-add" in _offered_on(acts, "Wellbore", False)
        assert "reconcile-remove" in _offered_on(acts, "Wellbore", True)
        assert "reconcile-add" in _offered_on(acts, "ContinuousProperty", False)
        assert "reconcile-add" not in _offered_on(acts, "Trajectory", False)
