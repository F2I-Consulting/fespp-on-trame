from trame.app import get_server
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify3

_server = get_server()
_state = _server.state

# Node `kind` values that are pure groupings (no VTK object behind them, just
# organize children). Mirror of C++ `isGroupingType` in enum.h. When the user
# checks one of these, the UI auto-checks all descendants too — so the
# treeview reflects what FESPP will actually load (independent select_strategy
# means Vuetify itself won't propagate; we do it manually here).
_GROUPING_KINDS = (
    "Collection",
    "Wellbore",
    "Partial",
    # Inserted by the alternate tree-hierarchy modes
    # (ByInterpretation, ByFeatureAndInterpretation).
    "Feature",
    "Interpretation",
)

# Domain-level dependency: a WellboreChannel or WellboreMarker requires its
# Wellbore's Trajectory (the geometry that anchors the per-depth log values
# or marker positions). When the user checks one of these, we auto-check
# the parent Wellbore's Trajectory child too.
_WELLBORE_LEAF_KINDS_NEEDING_TRAJECTORY = ("WellboreChannel", "WellboreMarker")


def _expand_selection_with_deps(curr_ids, prev_ids, tree, tab):
    """Given the new selection from VTreeview (`curr_ids`) and the previous
    state (`prev_ids`), return the expanded selection that includes implicit
    dependencies for the newly added nodes:
      - Adding a grouping (Wellbore, Collection, Partial) → add all
        descendants so UI reflects the full subtree FESPP will load.
      - Adding a WellboreChannel / WellboreMarker → add the parent
        Wellbore's WellboreTrajectory (sibling, not ancestor).
    Returns the expanded id list."""
    if not curr_ids:
        return list(curr_ids or [])
    prev_set = set(prev_ids or [])
    added = [n for n in curr_ids if n not in prev_set]
    if not added:
        return list(curr_ids)

    expanded = set(curr_ids)
    for node_id in added:
        kind = tree.find_type(node_id) if tree else None
        if not kind:
            continue
        # Grouping → all descendants
        if kind in _GROUPING_KINDS:
            for desc in tree.find_all_descendant_ids(node_id):
                expanded.add(desc)
        # Channel / Marker → parent Wellbore's Trajectory
        if kind in _WELLBORE_LEAF_KINDS_NEEDING_TRAJECTORY:
            wb = tree.find_parent_node_id_with_type(node_id, "Wellbore")
            if wb is not None:
                traj = tree.find_first_child_of_type(wb, "WellboreTrajectory")
                if traj is not None:
                    expanded.add(traj)
    return list(expanded)


def _wire_select_to_active(select_var: str, active_var: str, prev_var: str):
    """When a new node is checked in `select_var`, set `active_var` to it.
    When the currently-active node is unchecked, fall back to any remaining
    selected node. Activating via label click does NOT alter selection (kept
    by Vuetify's separate update_activated callback)."""
    @_state.change(select_var)
    def _on_change(**_):
        curr = list(getattr(_state, select_var) or [])
        prev = list(getattr(_state, prev_var, []) or [])
        prev_set = set(prev)
        new_ones = [x for x in curr if x not in prev_set]
        if new_ones:
            setattr(_state, active_var, [new_ones[-1]])
        else:
            active = getattr(_state, active_var) or []
            if active and active[0] not in curr:
                setattr(_state, active_var, [curr[0]] if curr else [])
        setattr(_state, prev_var, curr)


def _wire_dependency_expansion(select_var: str, prev_var: str, tree):
    """When `select_var` changes, expand the selection to include implicit
    dependencies (groupings → descendants, Channel/Marker → Trajectory).
    The expanded list is written back to `select_var` so Vuetify checks the
    extra nodes too. `prev_var` is reused with the active-wiring (fine — both
    handlers read it then advance it in lockstep on the same flush)."""
    @_state.change(select_var)
    def _on_select(**_):
        curr = list(getattr(_state, select_var) or [])
        prev = list(getattr(_state, prev_var, []) or [])
        if not curr:
            return
        expanded = _expand_selection_with_deps(curr, prev, tree, select_var)
        if set(expanded) != set(curr):
            # Trigger a state mutation to mirror the deps in the UI.
            # Trame coalesces this with the original event; the next flush
            # carries the union and downstream handlers see the final value.
            setattr(_state, select_var, expanded)

# Inline rainbow gradient for the "Property" chip — a single CSS string,
# rendered on the rare nodes whose rep is currently coloured by a data array.
_RAINBOW_STYLE = (
    "width:10px;height:10px;border-radius:50%;display:inline-block;"
    "margin-left:4px;vertical-align:middle;"
    "background:linear-gradient(90deg,"
    "#ff0000,#ff8000,#ffff00,#00ff00,#00ffff,#0000ff,#8000ff);"
)


def _chip_slot():
    """Color chip rendered next to the tree node label.

    - No chip if the rep_path has no entry in tree_chip_color_by_path
      (i.e. rep not loaded yet).
    - Rainbow gradient if mode is Property (sentinel "PROPERTY").
    - Solid mdi-circle in the assigned color otherwise.
    Lookup is O(1) per node — safe for large trees.
    """
    has_chip = "tree_chip_color_by_path && tree_chip_color_by_path[item.path]"
    is_property = (
        "tree_chip_color_by_path && tree_chip_color_by_path[item.path] === 'PROPERTY'"
    )
    is_solid = (
        "tree_chip_color_by_path && tree_chip_color_by_path[item.path]"
        " && tree_chip_color_by_path[item.path] !== 'PROPERTY'"
    )
    html.Div(v_if=is_property, style=_RAINBOW_STYLE)
    vuetify3.VIcon(
        "mdi-circle",
        v_else_if=is_solid,
        size="x-small",
        color=("tree_chip_color_by_path[item.path]",),
        classes="ml-1",
    )


def _eye_slot(controller):
    """Visibility eye on a tree node (rendered in the v_slot_append slot).

    Two flavours of eye:
    - Rep eye: shown next to a representation node when it's loaded.
      Open → display.Visibility=1; barred → Visibility=0 (data stays
      loaded). Click → controller.toggle_rep_visibility(item.path).
    - DataArray eye: shown next to Property/TimeSeries/MultiRealization
      nodes when their data is loaded. Open → ColorBy this array on the
      rep parent; barred → not the active array (rep falls back to its
      previous coloring or SolidColor if no other array is active).
      Click → controller.toggle_dataarray_color(item.path).

    The two are mutually exclusive: a path is either a rep or a data-
    array, never both.
    """
    is_loaded_rep = (
        "ui_loaded_rep_paths && ui_loaded_rep_paths.indexOf(item.path) !== -1"
    )
    is_hidden_rep = (
        "ui_hidden_rep_paths && ui_hidden_rep_paths.indexOf(item.path) !== -1"
    )
    is_loaded_array = (
        "ui_loaded_array_paths && ui_loaded_array_paths.indexOf(item.path) !== -1"
    )
    is_active_array = (
        "ui_active_array_by_rep"
        " && Object.values(ui_active_array_by_rep).indexOf(item.path) !== -1"
    )
    # Rep eye — `click=(callable, "[args]")` is trame's tuple form: trame
    # auto-registers a trigger for the callable, and the JS expression
    # is evaluated as the args list. mdi-eye-closed gives a clearer
    # "barred" look than mdi-eye-off (which renders too similarly to
    # mdi-eye).
    vuetify3.VIcon(
        v_if=is_loaded_rep,
        icon=(f"({is_hidden_rep}) ? 'mdi-eye-closed' : 'mdi-eye'",),
        size="small",
        color=(f"({is_hidden_rep}) ? 'grey' : 'blue-darken-1'",),
        classes="ml-1",
        style="cursor: pointer;",
        click=(controller.toggle_rep_visibility, "[item.path]"),
    )
    # DataArray eye
    vuetify3.VIcon(
        v_else_if=is_loaded_array,
        icon=(f"({is_active_array}) ? 'mdi-eye' : 'mdi-eye-closed'",),
        size="small",
        color=(f"({is_active_array}) ? 'purple-darken-1' : 'grey'",),
        classes="ml-1",
        style="cursor: pointer;",
        click=(controller.toggle_dataarray_color, "[item.path]"),
    )


class TreeViews:
    """Encapsulate tree rendering and opened-node initialization.

    Instantiate with the Trame `controller` and `state` so the class
    registers the `init_opened_nodes` controller action and sets
    `state.ui_opened_*` variables and per-grid selection states.
    """

    def __init__(self, controller, state, tree=None):
        self.controller = controller
        self.state = state
        # `tree` is the Tree instance backing the assembly — needed by the
        # dependency-expansion handler to walk the assembly and find
        # descendants / siblings.
        self._tree = tree

        @controller.set("init_opened_nodes")
        def init_opened_nodes(tree_data):
            """Returns only the IDs of the first level nodes"""
            return [node["id"] for node in tree_data if node.get("parent_id") == 0 or "parent_id" not in node]

        # Initialize opened nodes using the controller helper
        # (keeps same behaviour as previous top-level code)
        try:
            state.ui_opened_reservoir = controller.init_opened_nodes(state.ui_subtree_reservoir)
        except Exception:
            state.ui_opened_reservoir = []
        try:
            state.ui_opened_surface = controller.init_opened_nodes(state.ui_subtree_surface)
        except Exception:
            state.ui_opened_surface = []
        try:
            state.ui_opened_well = controller.init_opened_nodes(state.ui_subtree_well)
        except Exception:
            state.ui_opened_well = []

        # Initialize per-grid selection states for reservoir (each grid has independent selection)
        self._init_grid_selections()

        # All three trees use `select_strategy="independent"` (each checkbox
        # is toggled independently — no Vuetify-side parent/children
        # propagation). Implicit dependencies (groupings → descendants,
        # Channel/Marker → Trajectory) are added by
        # `_wire_dependency_expansion`. The result mirrors the behaviour
        # FESPP applies under the hood, so the UI checkboxes always reflect
        # what's actually loaded.
        _wire_dependency_expansion(
            "ui_select_node_reservoir", "_prev_select_reservoir", self._tree,
        )
        _wire_dependency_expansion(
            "ui_select_node_surface", "_prev_select_surface", self._tree,
        )
        _wire_dependency_expansion(
            "ui_select_node_well", "_prev_select_well", self._tree,
        )

        # update_selected from Vuetify gives the FULL selected array, so
        # setting active = $event picks array[0] (the first ever selected),
        # not the last clicked. Wire a Python handler that sets active to
        # the newly-added node instead, with sensible fallback on removal.
        _wire_select_to_active(
            "ui_select_node_reservoir", "ui_active_node_reservoir",
            "_prev_select_reservoir",
        )
        _wire_select_to_active(
            "ui_select_node_surface", "ui_active_node_surface",
            "_prev_select_surface",
        )
        _wire_select_to_active(
            "ui_select_node_well", "ui_active_node_well",
            "_prev_select_well",
        )

    def _init_grid_selections(self):
        """Initialize per-grid selection states for reservoir grids.
        
        For each grid (root node with type IjkGrid/UnstructuredGrid),
        create a separate state variable ui_selected_grid_<id> to allow
        independent "single-leaf" selection per grid.
        """
        if not hasattr(self.state, "ui_subtree_reservoir"):
            return
        
        for grid in self.state.ui_subtree_reservoir:
            grid_id = grid.get("id")
            if grid_id is not None:
                state_key = f"ui_selected_grid_{grid_id}"
                # Initialize if not already set
                if not hasattr(self.state, state_key):
                    setattr(self.state, state_key, [])


    def reservoir_tree(self):
        """Render reservoir grids with independent selection per grid.
        
        Each grid (IjkGrid/UnstructuredGrid) gets its own VTreeview with
        "single-leaf" selection strategy, allowing simultaneous selection
        of children from different grids.
        """
        # Use a single items binding but update_selected captures per-grid state via JavaScript
        with vuetify3.VTreeview(
            slim=True,
            density="comfortable",
            opened=("ui_opened_reservoir", []),
            line="connected",
            item_value="id",
            items=("ui_subtree_reservoir", []),  # All grids at once
            activated=("ui_active_node_reservoir", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_reservoir = $event",
            color="primary",
            open_on_click=False,
            selected=("ui_select_node_reservoir", []),
            selectable=True,
            select_strategy="independent",
            item_props=True,
            update_selected="ui_select_node_reservoir = $event",
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
                # Secondary badges for synthetic nodes (TimeSeries collapses
                # multiple time-stamped properties under one leaf,
                # MultiRealization the same for realizations,
                # MultiRealizationTimeSeries combines both — up to 3 icons
                # total: primary property kind + TS + MR).
                vuetify3.VIcon(
                    "mdi-timeline-clock",
                    v_if="item.is_ts",
                    size="x-small",
                    color="purple",
                    classes="ml-1",
                )
                vuetify3.VChip(
                    "MR",
                    v_if="item.is_mr",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="ml-1",
                )
                _chip_slot()
            with vuetify3.Template(v_slot_append="{ item }"):
                _eye_slot(self.controller)

    def surface_tree(self):
        with vuetify3.VTreeview(
            slim=True,
            density="compact",
            opened=("ui_opened_surface", []),
            line="connected",
            item_value="id",
            items=("ui_subtree_surface", []),
            activated=("ui_active_node_surface", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_surface = $event",
            color="primary",
            open_on_click=False,
            selected=("ui_select_node_surface", []),
            selectable=True,
            select_strategy="independent",
            update_selected="ui_select_node_surface = $event",
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
                # Secondary badges for synthetic nodes (TimeSeries collapses
                # multiple time-stamped properties under one leaf,
                # MultiRealization the same for realizations,
                # MultiRealizationTimeSeries combines both — up to 3 icons
                # total: primary property kind + TS + MR).
                vuetify3.VIcon(
                    "mdi-timeline-clock",
                    v_if="item.is_ts",
                    size="x-small",
                    color="purple",
                    classes="ml-1",
                )
                vuetify3.VChip(
                    "MR",
                    v_if="item.is_mr",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="ml-1",
                )
                _chip_slot()
            with vuetify3.Template(v_slot_append="{ item }"):
                _eye_slot(self.controller)

    def well_tree(self):
        with vuetify3.VTreeview(
            slim=True,
            density="compact",
            opened=("ui_opened_well", []),
            line="connected",
            item_value="id",
            items=("ui_subtree_well", []),
            activated=("ui_active_node_well", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_well = $event",
            color="primary",
            open_on_click=False,
            selected=("ui_select_node_well", []),
            selectable=True,
            select_strategy="independent",
            indent_lines="default",
            separate_roots=True,
            update_selected="ui_select_node_well = $event",
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
                # Secondary badges for synthetic nodes (TimeSeries collapses
                # multiple time-stamped properties under one leaf,
                # MultiRealization the same for realizations,
                # MultiRealizationTimeSeries combines both — up to 3 icons
                # total: primary property kind + TS + MR).
                vuetify3.VIcon(
                    "mdi-timeline-clock",
                    v_if="item.is_ts",
                    size="x-small",
                    color="purple",
                    classes="ml-1",
                )
                vuetify3.VChip(
                    "MR",
                    v_if="item.is_mr",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="ml-1",
                )
                _chip_slot()
            with vuetify3.Template(v_slot_append="{ item }"):
                _eye_slot(self.controller)
