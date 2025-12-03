from trame.widgets import vuetify3 as vuetify3
from trame.widgets import vuetify3 as vuetify3


class TreeViews:
    """Encapsulate tree rendering and opened-node initialization.

    Instantiate with the Trame `controller` and `state` so the class
    registers the `init_opened_nodes` controller action and sets
    `state.ui_opened_*` variables.
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

    def reservoir_tree(self):
        with vuetify3.VTreeview(
            slim=True,
            density="comfortable",
            opened=("ui_opened_reservoir", []),
            line="connected",
            item_value="id",
            items=("ui_subtree_reservoir", []),
            activated=("ui_active_node_reservoir", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_reservoir = $event",
            color="primary",
            open_on_click=False,
            selected=("ui_select_node_reservoir", []),
            selectable=True,
            select_strategy="single-leaf",
            item_props=True,
            update_selected="ui_select_node_reservoir = $event",
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")

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
