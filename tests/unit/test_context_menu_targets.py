"""What a right-click may offer, and on which node.

Statistics, a distribution, a cross-plot axis and a formula input all read
values, and only a property leaf has any. The tree menu says so through
each action's `types` (the widget hides an action whose types do not list
the node's type), and the controllers also refuse a path that carries no
values, since the 3D view builds its menu from a pick, not from a tree
node.
"""
from fespp_on_trame.app.views.widgets import data_tree
from fespp_on_trame.engine import element_type, node_facts, node_kinds


ACTIONS = {a["key"]: a for a in data_tree._CONTEXT_ACTIONS}
VALUE_ACTIONS = ("add-to-stats", "calculator")
# node types a right-click can land on that carry no values of their own
NOT_PROPERTIES = ("GridContainer", "PropertiesFolder", "IjkGrid",
                  "UnstructuredGrid", "Sub", "Wellbore", "Trajectory",
                  "Feature", "Interpretation", "Collection", "MarkerFrame",
                  "Marker", "BlockedWellboreFolder",
                  "SubRepresentationFolder")


class _FakeState(dict):
    """trame state as the tree mount uses it: attribute reads, item
    writes."""

    def __getattr__(self, name):
        return self.get(name)


class _FakeController:
    """The controllers the mount binds (tree_layout_set): any name answers."""

    def __getattr__(self, name):
        return lambda *a, **k: None


class _FakeServer:
    def __init__(self):
        self.state = _FakeState()
        self.controller = _FakeController()


def _offered_on(node_type):
    """Mirror the widget's own filter (DataExplorerTree.ctxItems): an action
    with no `types` is offered everywhere, one with `types` only on those."""
    return [a["key"] for a in data_tree._CONTEXT_ACTIONS
            if not a.get("types") or node_type in a["types"]]


class TestTreeMenuTypes:
    def test_every_action_says_what_it_applies_to(self):
        """Every action that reads values or a representation names its
        node types; the one exception is the XML explorer, offered on
        every row on purpose: a RESQML object always has XML, and a row
        without one opens the explorer on a note saying so."""
        for key, action in ACTIONS.items():
            if key == "xml":
                assert "types" not in action
                continue
            assert action.get("types"), f"{key} would be offered on every node"

    def test_the_value_actions_are_offered_on_a_property(self):
        for node_type in ("ContinuousProperty", "DiscreteProperty",
                          "CategoricalProperty", "TimeSeries",
                          "MultiRealization", "MultiRealizationTimeSeries"):
            assert set(VALUE_ACTIONS) <= set(_offered_on(node_type))

    def test_a_folder_a_grid_or_a_well_gets_none_of_them(self):
        for node_type in NOT_PROPERTIES:
            offered = _offered_on(node_type)
            assert not (set(VALUE_ACTIONS) & set(offered)), node_type

    def test_highlight_is_offered_on_what_resolves_to_a_representation(self):
        # a rep, a sub-representation, a leaf riding on one, and the grid's
        # container the click resolves through
        for node_type in ("IjkGrid", "Sub", "TriangulatedSet", "Trajectory",
                          "ContinuousProperty", "Marker", "GridContainer"):
            assert "center-3d" in _offered_on(node_type), node_type
        # pure grouping folders: nothing to turn to; a layout folder is not
        # in the file, its row has no menu (28/10)
        for node_type in ("Feature", "Collection", "Interpretation", "PropertiesFolder"):
            assert "center-3d" not in _offered_on(node_type), node_type

    def test_every_representation_kind_can_be_highlighted(self):
        # the type hierarchy is the authority on what renders
        for kind in element_type.registered_kinds():
            if isinstance(element_type.for_kind(kind),
                          element_type.Representation):
                assert "center-3d" in _offered_on(kind), kind

    def test_well_log_is_offered_on_a_wellbore_and_what_sits_under_it(self):
        # the controller climbs to the Wellbore folder from any of these
        for node_type in ("Wellbore", "Trajectory", "WellboreTrajectory",
                          "Frame", "MarkerFrame", "Marker", "Completion"):
            assert "add-to-welllog" in _offered_on(node_type), node_type
        # a grid, its folders and its properties have no well to send — and
        # a log channel shares its type with a grid property, so it is left
        # to its Frame
        for node_type in ("IjkGrid", "GridContainer", "PropertiesFolder",
                          "ContinuousProperty", "TimeSeries", "Feature",
                          "Collection", "Interpretation"):
            assert "add-to-welllog" not in _offered_on(node_type), node_type

    def test_a_log_frame_also_offers_its_logs_read_alone(self):
        # "Add to Well Log view" brings every log of a frame, "Add selected…" those read
        for node_type in ("Frame", "SeismicWellboreFrame"):
            assert "add-selected-to-welllog" in _offered_on(node_type), node_type
        for node_type in ("Wellbore", "WellboreTrajectory", "MarkerFrame", "ContinuousProperty", "IjkGrid"):
            assert "add-selected-to-welllog" not in _offered_on(node_type), node_type

    def test_a_log_frame_offers_its_logs_with_nothing_read(self):
        # "Add to Well Log view" reads every log of a frame: offered on it loaded or not;
        # "Add selected…" only once some are read
        for node_type in ("Frame", "SeismicWellboreFrame"):
            entries = [a for a in data_tree.context_actions([], None, [], [])
                       if node_type in (a.get("types") or ())]
            assert [a.get("when") for a in entries if a["key"] == "add-to-welllog"] == [None], node_type
            assert [a.get("when") for a in entries if a["key"] == "add-selected-to-welllog"] == ["loaded"], node_type
        # a wellbore and what else sits under it still ask for something read
        for node_type in ("Wellbore", "MarkerFrame", "Marker"):
            entries = [a for a in data_tree.context_actions([], None, [], [])
                       if a["key"] == "add-to-welllog" and node_type in (a.get("types") or ())]
            assert [a.get("when") for a in entries] == ["loaded"], node_type

    def test_an_unknown_type_gets_only_the_xml_explorer(self):
        assert _offered_on("Whatever") == ["xml"]

    def test_the_menu_reaches_the_widget_through_the_state_channel(self):
        """trame writes a literal prop value straight into a double-quoted
        HTML attribute: a serialized list closes that attribute with its
        own first quote and the tree's template stops compiling, leaving
        the Data Explorer blank. So the widget is handed the name of a
        state variable, and the list travels over the state channel."""
        server = _FakeServer()
        data_tree.DataExplorerTree.reset_mock()
        data_tree.DataTree(server, "view1")
        passed = data_tree.DataExplorerTree.call_args.kwargs["context_actions"]
        assert passed == (data_tree._CONTEXT_ACTIONS_VAR,)
        assert '"' not in data_tree._CONTEXT_ACTIONS_VAR
        assert (server.state[data_tree._CONTEXT_ACTIONS_VAR]
                == data_tree.context_actions(None, None, None, None))

    def test_a_log_is_sent_to_the_well_log_by_the_rows_of_the_log_frames(self):
        # a log's type is a grid property's: the entry on properties goes by the frames' rows, and under them alone
        entries = [a for a in data_tree.context_actions([], None, [], ["/w/logs/frame"])
                   if a["key"] == "add-to-welllog"]
        on_logs = [a for a in entries if "ContinuousProperty" in (a.get("types") or ())]
        assert len(on_logs) == 1 and on_logs[0]["rows"] == ["/w/logs/frame"]
        assert all("ContinuousProperty" not in (a.get("types") or ()) for a in entries if a is not on_logs[0])


class TestServerSideGuard:
    """The controllers' guard (`node_facts.is_property`) reads the node's type
    against `node_kinds.PROPERTY_KINDS`: the same rule, for the entry points that
    do not go through the tree menu (the 3D view's right-click, a harness call)."""

    def test_the_menu_and_the_guard_read_one_list(self):
        for action in VALUE_ACTIONS:
            assert ACTIONS[action]["types"] == list(node_kinds.PROPERTY_KINDS)
        for kind in node_kinds.PROPERTY_KINDS:
            assert node_facts.is_property_kind(kind), kind

    def test_a_pinnable_kind_is_a_property_leaf(self):
        for kind in node_kinds.PROPERTY_KINDS:
            if kind == "Property":
                continue   # the generic kind, unregistered on purpose
            assert isinstance(element_type.for_kind(kind),
                              element_type.PropertyLeaf), kind

    def test_no_folder_grid_or_well_is_pinnable(self):
        for node_type in NOT_PROPERTIES:
            assert not node_facts.is_property_kind(node_type), node_type


class TestOneOrderForBothMenus:
    def test_the_tree_ends_on_stats_then_info(self):
        keys = [a["key"] for a in data_tree._CONTEXT_ACTIONS]
        assert keys[-2:] == ["add-to-stats", "xml"]
        assert ACTIONS["add-to-stats"]["label"] == "Stats"
        assert "distribute" not in keys and "crossplot" not in keys

    def test_the_view_menu_reads_the_same_order(self):
        from fespp_on_trame.app.ui import action_icons
        view = [action_icons.entry(k, k) for k in
                ("xml", "property-slicer", "add-to-stats", "calculator", "pivot", "zoom", "center")]
        assert [e["key"] for e in action_icons.ordered(view)] == [
            "center", "zoom", "pivot", "calculator", "property-slicer", "add-to-stats", "xml"]
