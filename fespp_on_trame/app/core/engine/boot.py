import time
from pathlib import Path

from paraview import simple as pvsimple
from trame_server import Server

from fespp_on_trame.app.core.tree import Tree
from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.sources.etp_connector import ETPConnector
from fespp_on_trame.app.core.sources.source_registry import SourceRegistry
from fespp_on_trame.app.core.selector import Selector
import fespp_on_trame.app.core.activator as activator
from fespp_on_trame.app.io.session_hooks import on_client_connected, on_client_exited
from fespp_on_trame.app.io.upload_endpoint import (
    register_upload_route,
    resolve_upload_session_id,
)

from fespp_on_trame.app.core.engine.vtk_log import (
    setup_stderr_tee,
    capture_vtk_messages,
)
from fespp_on_trame.app.core.engine import (
    threshold_dispatch,
    slicer_dispatch,
    time_realization,
    data_load,
    etp,
    visibility,
    active_array,
    diff,
    hierarchy,
    selection_dispatch,
    view_ops,
)
from fespp_on_trame.app.core.engine.state_defaults import init_state_defaults


def initialize_fespp_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    state = server.state
    controller = server.controller

    # User-facing busy spinner timing — Trame bumps `trame__busy` on every
    # state mutation that triggers a flush, so this logs how long the UI
    # is "blocked" between an interaction and the next idle.
    _busy_start = [None]

    @state.change("trame__busy")
    def _on_trame_busy(trame__busy=None, **_):
        if trame__busy:
            if _busy_start[0] is None:
                _busy_start[0] = time.perf_counter()
        else:
            if _busy_start[0] is not None:
                ms = int((time.perf_counter() - _busy_start[0]) * 1000)
                print(f"[BUSY] {ms}ms")
                _busy_start[0] = None

    pvsimple.LoadPlugin(str(fespp_plugin_path))
    # ExplicitStructuredGrid is needed for IJK volume crop / slicing.
    pvsimple.LoadPlugin('/opt/paraview/lib/paraview-6.0/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.so')

    _view = pvsimple.GetActiveViewOrCreate("RenderView")
    _view.Visible = 1
    _view.Location = 'Bottom Left'
    _view.OrientationAxesVisibility = 0

    # Run the tee after ParaView init — startup noise would otherwise
    # flood the queue.
    setup_stderr_tee()

    _tree = Tree(None)
    # Mirror onto the `engine` package so `app/ui/app_layout.py`
    # (which uses `engine._tree` to share the assembly with TreeViews)
    # keeps working. Done inside the function so we don't trip the
    # circular import between `engine.boot` and `engine` at module
    # load time.
    import fespp_on_trame.app.core.engine as _engine_pkg
    _engine_pkg._tree = _tree

    _collector = Collector()
    _etp_connector = ETPConnector()
    # Unified per-rep registry — one entry per loaded representation,
    # whether it's an IjkGrid (slicer / volume pipeline) or an
    # ExtractBlockRepresentation. The engine talks to the registry
    # only; it never tracks per-type instances directly.
    _source_registry = SourceRegistry(_collector, _tree)

    def _ijkgrid_by_rep_path(rep_path):
        return _source_registry.get_ijk_grid(rep_path)

    def _active_ijkgrid():
        return _source_registry.get_ijk_grid(state.active_representation_path)

    def _push_active_ijk_state_to_ui():
        """Mirror the currently-active IjkGrid's slicer/range state into
        the trame UI vars. Called on active-grid change and after grid
        creation in the load handler."""
        active = _active_ijkgrid()
        if active is None:
            return
        snap = active.to_ui_state()
        if snap:
            state.update(snap)

    # Switch the FESPP collector to "explicit selection" mode: a selector
    # path is taken literally for non-grouping nodes (selecting a grid
    # does NOT auto-load its properties). Pairs with `select_strategy=
    # "independent"` in the VTreeview.
    try:
        from paraview.servermanager import vtkSMPropertyHelper
        _coll_proxy = _collector.get_source().SMProxy
        if _coll_proxy is not None and _coll_proxy.GetProperty("ExplicitSelection") is not None:
            vtkSMPropertyHelper(_coll_proxy, "ExplicitSelection").Set(1)
            _coll_proxy.UpdateVTKObjects()
    except Exception as _e:
        print(f"[WARNING] Could not set ExplicitSelection on FESPP collector: {_e}")

    hierarchy.push_tree_hierarchy_mode(_collector, state.tree_hierarchy_mode)

    _selector = Selector(_tree)
    _activator = activator.Activator(
        _tree, _source_registry, ijk_lookup=_ijkgrid_by_rep_path,
    )

    # Seed every trame state var the engine + UI assume to exist.
    # Grouped declaratively in `state_defaults.init_state_defaults`
    # so adding a new flag doesn't require scrolling through this
    # boot function.
    init_state_defaults(state)

    @controller.add("on_server_ready")
    def _set_upload_session_id(**kwargs):
        resolve_upload_session_id(server)

    state.flush()

    # Register the /upload HTTP route. First try eagerly; if the aiohttp
    # server hasn't been created yet, defer to on_server_ready.
    if not register_upload_route(server):
        @controller.add("on_server_ready")
        def _register_upload_on_ready(**kwargs):
            register_upload_route(server)

    @controller.add("on_data_change")
    def update():
        view_ops.broadcast_view_update(server)

    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str):
        with capture_vtk_messages(state):
            state.file_loaded = _collector.add_file(epc_file_path)

    @controller.set("connect_to_etp")
    def connect_to_etp(etp_url: str, data_partition: str, token: str, token_type: str = "Bearer",
                       proxy_url: str = None, proxy_token: str = None, proxy_token_type: str = "Bearer"):
        with capture_vtk_messages(state):
            etp.connect_to_etp(
                state, _etp_connector,
                etp_url, data_partition, token,
                token_type=token_type,
                proxy_url=proxy_url, proxy_token=proxy_token,
                proxy_token_type=proxy_token_type,
            )

    @controller.set("select_etp_dataspace")
    def select_etp_dataspace(dataspace: str):
        etp.select_etp_dataspace(_etp_connector, dataspace)

    @controller.set("force_etp_refresh")
    def force_etp_refresh():
        with capture_vtk_messages(state):
            etp.force_etp_refresh(state, _etp_connector, _collector, _tree)

    @controller.set("update_data_information")
    def update_data_information():
        with capture_vtk_messages(state):
            etp.update_data_information(_etp_connector, _collector, _tree)

    @controller.set("set_slider_value")
    def set_slider_value(index, value):
        slicer_dispatch.set_slider_value(state, index, value)

    @state.change("fespp_data_selectors")
    def on_change_fespp_data_selectors(**kwargs):
        with capture_vtk_messages(state):
            data_load.run(
                state, controller, server, _view,
                _tree, _collector, _etp_connector,
                _source_registry, _activator,
                refresh_threshold_ui=_refresh_threshold_ui_for_active_grid,
                push_active_ijk_state=_push_active_ijk_state_to_ui,
            )

    state.setdefault("ui_scale_z", 1.0)

    @state.change("ui_scale_z")
    def ui_scale_z_update(ui_scale_z, **kwargs):
        slicer_dispatch.apply_z_scale(controller, _source_registry, _view, ui_scale_z)

    @controller.set("get_rep_source")
    def get_rep_source(rep_path):
        """Resolve a rep path to its extracted ParaView source. Used by
        UI panels (SolidColorPanel, ColorEditor)."""
        return _source_registry.get(rep_path)

    @state.change("ui_loaded_array_paths")
    def _refresh_diff_choices(ui_loaded_array_paths, **_):
        diff.refresh_diff_choices(state, _tree, ui_loaded_array_paths)

    @state.change("diff_array_a_path", "diff_array_choices")
    def _refresh_diff_b_choices(diff_array_a_path, diff_array_choices, **_):
        diff.refresh_diff_b_choices(state, diff_array_a_path, diff_array_choices)

    @controller.set("compute_diff")
    def compute_diff():
        diff.compute_diff(state, controller, server, _source_registry)

    @controller.set("get_rep_chain_proxies")
    def get_rep_chain_proxies(rep_path):
        """Every chain Threshold proxy attached to a non-IjkGrid rep —
        used by panels (SolidColorPanel) that need to fan-out display
        edits across the rep + every chain node."""
        try:
            return _source_registry.all_chain_proxies(rep_path)
        except AttributeError:
            return []

    @controller.set("toggle_rep_visibility")
    def toggle_rep_visibility(rep_path, panel_id=None):
        visibility.toggle_rep_visibility(
            state, controller, server, _source_registry, rep_path,
            panel_id=panel_id, tree=_tree,
        )

    @state.change("ui_active_array_by_rep")
    def _on_active_array_change(ui_active_array_by_rep, **_):
        active_array.on_active_array_change(
            state, controller, _source_registry, _tree, ui_active_array_by_rep,
        )

    @state.change("ui_active_array_by_rep_by_view")
    def _on_active_array_by_view_change(ui_active_array_by_rep_by_view, **_):
        active_array.on_active_array_by_view_change(
            state, _tree, ui_active_array_by_rep_by_view,
        )

    @controller.set("toggle_dataarray_color")
    def toggle_dataarray_color(array_path, panel_id=None):
        active_array.toggle_dataarray_color(
            state, controller, server, _source_registry, _tree,
            array_path, panel_id=panel_id,
        )

    @controller.set("apply_panel_coloring")
    def apply_panel_coloring(panel_id):
        """Re-apply ColorBy on every rep coloured in the given panel.
        Used by MultiView.add_view right after replicating a scene —
        the per-view active-array bucket alone doesn't trigger a
        ColorBy on the new view's displays."""
        mv = server.context.multi_view
        if mv is None:
            return
        view = mv._pv_internal.get(panel_id) if panel_id else None
        if view is None:
            return
        active_array.apply_panel_coloring(
            state, _source_registry, _tree, panel_id, view,
        )
        html_view = mv._html_views.get(panel_id) if panel_id else None
        if html_view is not None:
            try:
                html_view.update()
            except Exception:
                pass

    @state.change("ui_slices_i_list", "ui_slices_j_list", "ui_slices_k_list")
    def update_slice(ui_slices_i_list, ui_slices_j_list, ui_slices_k_list, **kwargs):
        slicer_dispatch.update_slice_positions(
            state, controller, _source_registry, _view,
            ui_slices_i_list, ui_slices_j_list, ui_slices_k_list,
        )

    @state.change("ui_slices_range_i", "ui_slices_range_j", "ui_slices_range_k")
    def update_range_slicer(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k, **kwargs):
        slicer_dispatch.update_slice_range(
            state, controller, _source_registry, _view,
            ui_slices_range_i, ui_slices_range_j, ui_slices_range_k,
        )

    @state.change("ui_slices_range_mode")
    def update_mode_slicer(ui_slices_range_mode=None, **kwargs):
        slicer_dispatch.update_slice_mode(
            state, controller, _source_registry, _view, ui_slices_range_mode,
        )

    @state.change("ui_slices_volume_visible")
    def update_volume_visible(ui_slices_volume_visible=None, **kwargs):
        slicer_dispatch.update_volume_visible(
            state, controller, _source_registry, _view, ui_slices_volume_visible,
        )

    # --- Threshold chain wiring -------------------------------------------
    # The data layer (SourceRegistry / IjkGrid) owns the chain. The engine's
    # job is to:
    #   1. Publish the chain to `ui_threshold_chain` so the UI can render it.
    #   2. Forward UI events (add / delete / set_range / set_visible) into
    #      the data layer via controller methods.
    # No per-rep persistence dicts on the state side — chains live with
    # their rep in the data layer until the rep is unloaded.

    def _refresh_threshold_ui_for_active_grid():
        threshold_dispatch.refresh_threshold_ui_for_active_grid(
            state, _source_registry,
        )

    @controller.set("threshold_add")
    def threshold_add(parent_name=None, array=None):
        threshold_dispatch.threshold_add(
            state, controller, _source_registry, _activator, _view,
            parent_name=parent_name, array=array,
        )

    @controller.set("threshold_delete")
    def threshold_delete(name):
        threshold_dispatch.threshold_delete(
            state, controller, _source_registry, _view, name,
        )

    @controller.set("threshold_set_range")
    def threshold_set_range(name, low, high):
        threshold_dispatch.threshold_set_range(
            state, controller, _source_registry, _view, name, low, high,
        )

    @controller.set("threshold_set_visible")
    def threshold_set_visible(name, visible):
        threshold_dispatch.threshold_set_visible(
            state, controller, _source_registry, _activator, _view,
            name, visible,
        )

    @state.change("active_representation_path", "ui_active_node_reservoir_type_rep")
    def on_active_grid_change(**kwargs):
        _refresh_threshold_ui_for_active_grid()
        # Mirror the new active grid's stored slicer/range state into
        # the UI vars so the panels re-attach to it. Idempotent.
        try:
            _push_active_ijk_state_to_ui()
        except Exception as _e:
            print(f"[WARNING] push active ijk state failed: {_e}")

    @state.change("ui_threshold_pending_action")
    def _on_threshold_pending_action(ui_threshold_pending_action=None, **_):
        threshold_dispatch.on_threshold_pending_action(
            state, ui_threshold_pending_action,
            threshold_add, threshold_delete,
            threshold_set_range, threshold_set_visible,
        )

    @state.change("representation_active")
    def _propagate_representation(representation_active, **kwargs):
        slicer_dispatch.propagate_representation(_source_registry, representation_active)

    @state.change("ui_slices_real")
    def update_realization_slider(ui_slices_real, **kwargs):
        time_realization.update_realization_slider(
            state, controller, _collector, _view, ui_slices_real,
        )

    @state.change("ui_slices_i_visible_list", "ui_slices_j_visible_list", "ui_slices_k_visible_list")
    def update_slices_visibility(
        ui_slices_i_visible_list=None,
        ui_slices_j_visible_list=None,
        ui_slices_k_visible_list=None,
        **kwargs,
    ):
        slicer_dispatch.update_slice_visibility(
            state, controller, _source_registry, _view,
            ui_slices_i_visible_list, ui_slices_j_visible_list, ui_slices_k_visible_list,
        )

    @state.change("ui_slices_real_locked")
    def update_real_lock(ui_slices_real_locked, **kwargs):
        time_realization.update_real_lock(state, ui_slices_real_locked)

    @state.change("time_index")
    def changeTimeLabel(**kwargs):
        time_realization.change_time_label(state, _tree)

    @controller.set("register_per_view_time_label")
    def register_per_view_time_label(time_value_var, label_var):
        time_realization.register_per_view_time_label(
            state, _tree, time_value_var, label_var,
        )

    # load_mode "auto" → every checkbox toggle pushes immediately to
    # ParaView (legacy behaviour). "manual" → toggles only update the
    # per-tab selection state; the toolbar Load button pushes the
    # aggregated selection in one shot. Independent from visibility,
    # which is driven by the per-node eye icons.

    @state.change("ui_select_node_surface")
    def on_change_ui_select_node_surface(**kwargs):
        selection_dispatch.on_change_ui_select_node_surface(state, _selector)

    @state.change("ui_select_node_well")
    def on_change_ui_select_node_well(**kwargs):
        selection_dispatch.on_change_ui_select_node_well(state, _selector)

    @state.change("ui_select_node_reservoir")
    def on_change_ui_select_node_reservoir(**kwargs):
        selection_dispatch.on_change_ui_select_node_reservoir(state, _selector)

    @controller.set("apply_pending_selection")
    def apply_pending_selection():
        selection_dispatch.apply_pending_selection(_selector, _activator)

    @state.change("load_mode")
    def on_load_mode_change(load_mode, **kwargs):
        selection_dispatch.on_load_mode_change(_selector, _activator, load_mode)

    @state.change("tree_hierarchy_mode")
    def on_tree_hierarchy_mode_change(tree_hierarchy_mode, **kwargs):
        hierarchy.on_tree_hierarchy_mode_change(
            state, controller, _collector, tree_hierarchy_mode,
        )

    @state.change("view_reset_camera")
    def view_reset_camera(view_reset_camera, **kwargs):
        view_ops.on_view_reset_camera(
            state, controller, _source_registry, view_reset_camera,
        )

    @state.change("view_update")
    def view_update(view_update, **kwargs):
        view_ops.on_view_update(state, controller, view_update)

    # Drop the shared temp directory when the last client disconnects.
    # Falls back to atexit-only cleanup on trame_server versions that
    # don't expose these hooks.
    try:
        server.controller.on_client_connected.add(on_client_connected)
        server.controller.on_client_exited.add(on_client_exited)
        print("[Session] Client lifecycle hooks registered.", flush=True)
    except AttributeError:
        print("[Session] Client hooks unavailable in this trame version - cleanup via atexit only.", flush=True)
