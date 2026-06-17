"""Tree-hierarchy mode dispatch — extracted from
`boot.initialize_fespp_engine`.

The FESPP collector supports three hierarchy modes on the C++ side:
flat, by_interpretation, by_feature_and_interpretation. Each mode
restructures the data assembly used by the treeview. Switching modes
invalidates every node id / path the engine is currently tracking,
so we clear the selection / visibility / coloring state at the same
time and re-parse the freshly-rebuilt assembly into the Python
`Tree`."""
from paraview.servermanager import vtkSMPropertyHelper


_MODE_NAME_TO_INT = {
    "flat": 0,
    "by_interpretation": 1,
    "by_feature_and_interpretation": 2,
}


def push_tree_hierarchy_mode(collector, mode_name) -> bool:
    """Push the chosen hierarchy mode to the C++ side. The
    collector's `SetTreeHierarchyMode` triggers a live rebuild of
    the assembly via `repository.rebuildAssembly()`."""
    try:
        proxy = collector.get_source().SMProxy
        if proxy is None or proxy.GetProperty("TreeHierarchyMode") is None:
            return False
        mode_int = _MODE_NAME_TO_INT.get(mode_name, 0)
        vtkSMPropertyHelper(proxy, "TreeHierarchyMode").Set(mode_int)
        proxy.UpdateVTKObjects()
        return True
    except Exception as _e:
        print(f"[WARNING] Could not set TreeHierarchyMode on FESPP collector: {_e}")
        return False


def on_tree_hierarchy_mode_change(state, controller, collector, tree_hierarchy_mode):
    """Push the new mode to the FESPP collector (which triggers the
    live C++ rebuild via `SetTreeHierarchyMode` → `rebuildAssembly()`),
    clear every selection / visibility / coloring state var (their
    node ids and paths belong to the old layout), then re-parse the
    assembly into the Python tree."""
    if not push_tree_hierarchy_mode(collector, tree_hierarchy_mode):
        return
    had_selection = bool(
        (state.ui_select_node_reservoir or [])
        or (state.ui_select_node_surface or [])
        or (state.ui_select_node_well or [])
        or (state.fespp_data_selectors or [])
    )
    state.ui_select_node_reservoir = []
    state.ui_select_node_surface = []
    state.ui_select_node_well = []
    state.ui_active_node_reservoir = []
    state.ui_active_node_surface = []
    state.ui_active_node_well = []
    state.fespp_data_selectors = []
    state.ui_loaded_rep_paths = []
    state.ui_hidden_rep_paths = []
    state.ui_hidden_rep_paths_by_view = {}
    state.ui_loaded_array_paths = []
    state.ui_active_array_by_rep = {}
    state.ui_active_array_by_rep_by_view = {}
    if had_selection:
        state.tree_hierarchy_snackbar_visible = True
    if state.file_loaded:
        # ParaView is not in auto-apply mode; the proxy's output
        # keeps the deep copy of the previous assembly until
        # RequestData runs again. UpdatePipeline triggers RequestData
        # which re-deep-copies the freshly-rebuilt repository
        # assembly into the output, so the Python tree parser reads
        # the new layout.
        try:
            collector.get_source().UpdatePipeline()
        except Exception as _e:
            print(f"[WARNING] UpdatePipeline after mode change failed: {_e}")
        try:
            controller.update_data_information()
        except Exception as _e:
            print(f"[WARNING] tree refresh after mode change failed: {_e}")
    print(f"[INFO] Tree hierarchy mode set to {tree_hierarchy_mode!r}.")
