from trame.app import get_server
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify3

_server = get_server()
_state = _server.state


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


class TreeViews:
    """Encapsulate tree rendering and opened-node initialization.

    Instantiate with the Trame `controller` and `state` so the class
    registers the `init_opened_nodes` controller action and sets
    `state.ui_opened_*` variables and per-grid selection states.
    """

    def __init__(self, controller, state):
        self.controller = controller
        self.state = state

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

        # Surface and well trees use the "classic" multi-select strategy.
        # update_selected from Vuetify gives the FULL selected array, so
        # setting active = $event picks array[0] (the first ever selected),
        # not the last clicked. Wire a Python handler that sets active to
        # the newly-added node instead, with sensible fallback on removal.
        # Reservoir uses single-leaf (one selection at a time) and works
        # correctly via update_selected directly.
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
            selected=("ui_select_node_reservoir", []),  # Restored: single global selection for now
            selectable=True,
            select_strategy="single-leaf",
            item_props=True,
            update_selected="ui_select_node_reservoir = $event; ui_active_node_reservoir = $event",
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
            select_strategy="classic",
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
            select_strategy="classic",
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
