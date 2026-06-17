import time
from pathlib import Path

from paraview import simple as pvsimple
from trame_server import Server

from fespp_on_trame.app.core.tree import Tree
from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.sources.etp_connector import ETPConnector
from fespp_on_trame.app.core.sources.source_registry import SourceRegistry
from fespp_on_trame.app.core.sources.scene_registry import SceneRegistry
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
    slice_dispatch,
    clip_dispatch,
    time_realization,
    realization_dispatch,
    data_load,
    etp,
    visibility,
    active_array,
    diff,
    hierarchy,
    selection_dispatch,
    view_ops,
    stats_dispatch,
    distribution_dispatch,
)
from fespp_on_trame.app.core.engine.state_defaults import init_state_defaults


def initialize_fespp_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    state = server.state
    # Pre-register the trame_plotly JS module at boot so the
    # client receives its bundle on first connect, BEFORE the
    # Distribution panel template is rendered. trame-plotly's
    # Figure widget normally calls server.enable_module(...) on
    # its own __init__, but our Figure widget is created lazily
    # (only when the user opens the floating Distribution panel)
    # — by that point the client is already connected, and trame's
    # late module registration may not push the bundle to the
    # already-connected client. Importing + enabling eagerly here
    # forces the JS to be loaded as part of the initial client
    # bundle.
    try:
        from trame_plotly import module as _plotly_module
        server.enable_module(_plotly_module)
    except Exception as _exc:
        print(f"[WARNING] trame_plotly module enable failed: {_exc}")
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

    # Per-view scene registry (Phase 1 of the view-scenes refactor —
    # see doc/REFACTOR_VIEW_SCENES.md). Coexists with the legacy
    # SourceRegistry above: lifecycle and per-(view, rep) tracking
    # land here while data load / threshold / slice-clip continue
    # through SourceRegistry until later phases migrate them.
    _scene_registry = SceneRegistry(_collector, _tree)

    # Expose both registries on server.context so other modules
    # (RepInScene's legacy-source fallback, the multi_view lifecycle
    # hooks, …) can reach them without circular imports.
    server.context.source_registry = _source_registry
    server.context.scene_registry = _scene_registry

    def _ijkgrid_by_rep_path(rep_path):
        """Resolve the IjkGrid for `rep_path` PREFERRING the drawer
        target view's per-view instance, falling back to the legacy
        shared one.

        This is the activator's `ijk_lookup`. It MUST return the
        per-view IjkGrid (the one actually rendering in the panel),
        not the legacy shared instance: the per-view rendering fix
        Hides every legacy IjkGrid source in the panel's view, so the
        activator's `_resolve_color_target_source` — which walks this
        grid's sources looking for a VISIBLE one — would always get
        None from the legacy grid and bail before calling
        `update_color_editor`. That left `active_color_array_name`
        stale and the Colors & Opacity panel stuck on the SolidColor
        picker whenever the user activated a property node whose eye
        was not the currently-colored one (active node = PRESSURE,
        eye = PVTregion → COE showed SolidColor)."""
        if not rep_path:
            return None
        target_panel = (
            getattr(state, "drawer_target_view_id", "") or ""
            or getattr(state, "fespp_active_panel_id", "") or ""
        )
        if target_panel:
            rep = _scene_registry.get_rep(target_panel, rep_path)
            if rep is not None:
                ijk = getattr(rep, "_per_view_ijk", None)
                if ijk is None and hasattr(rep, "_ensure_per_view_ijk"):
                    try:
                        ijk = rep._ensure_per_view_ijk()
                    except Exception:
                        ijk = None
                if ijk is not None:
                    return ijk
        return _source_registry.get_ijk_grid(rep_path)

    def _active_ijkgrid():
        """Resolve the IjkGrid driving the slicer panel UI for the
        currently-active representation. Thin wrapper over
        `_ijkgrid_by_rep_path` (which already prefers the drawer
        target view's per-view instance) keyed on
        `state.active_representation_path`."""
        rep_path = state.active_representation_path
        if not rep_path:
            return None
        return _ijkgrid_by_rep_path(rep_path)

    def _push_active_ijk_state_to_ui():
        """Mirror the currently-active IjkGrid's slicer/range state into
        the trame UI vars. Called on active-grid change, after grid
        creation in the load handler, AND on panel switch — Phase 3b:
        each view owns its own slicer state, so flipping the active
        panel republishes that panel's per-view IjkGrid snapshot into
        the flat `ui_slices_*` / `ui_range_*` state vars the panel
        reads from."""
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

    @controller.set("view_update_for")
    def view_update_for(panel_id):
        """Push a fresh vtk.js frame to the panel's HTML view.

        `controller.view_update()` only refreshes the currently-active
        panel — fine for the legacy single-view era, broken once
        edits target a non-active view (pinned mode in the Attributes
        drawer). Dispatchers call this method with the target panel
        id so the pinned view's browser tile gets the new frame even
        when the focus stays elsewhere."""
        if not panel_id:
            return
        mv = getattr(server.context, "multi_view", None)
        if mv is None:
            return
        html_view = mv.get_html_view(panel_id) if hasattr(mv, "get_html_view") else None
        if html_view is None:
            return
        try:
            html_view.update()
        except Exception:
            pass

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
        slicer_dispatch.apply_z_scale(state, controller, _source_registry, _view, ui_scale_z)

    @controller.set("get_rep_source")
    def get_rep_source(rep_path):
        """Resolve a rep path to its extracted ParaView source. Used by
        UI panels (SolidColorPanel, ColorEditor)."""
        return _source_registry.get(rep_path)

    @state.change("ui_loaded_array_paths")
    def _refresh_diff_choices(ui_loaded_array_paths, **_):
        diff.refresh_diff_choices(state, _tree, ui_loaded_array_paths)

    @state.change("ui_loaded_rep_paths")
    def _sync_scene_registry_reps(ui_loaded_rep_paths, **_):
        """Phase 1 view-scene wiring: keep each ViewScene's rep set in
        sync with the global loaded set. The legacy source_registry
        still owns the data filters; the scene_registry only tracks
        the per-(view, rep) bookkeeping until later phases migrate
        behavior."""
        try:
            _scene_registry.sync_loaded_reps(ui_loaded_rep_paths or [])
        except Exception as exc:
            print(f"[boot] scene_registry.sync_loaded_reps failed: {exc}")


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
            server=server,
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

    @controller.set("toggle_marker_visibility")
    def toggle_marker_visibility(marker_path, panel_id=None):
        visibility.toggle_marker_visibility(
            state, controller, server, _source_registry, _tree,
            marker_path, panel_id=panel_id,
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

    # Phase 3b (full): slicer_dispatch now writes slicer state DIRECTLY
    # onto the active view's per-view IjkGrid (via
    # `slicer_dispatch._active_ijk_grid` → scene_registry lookup).
    # `_on_active_panel_change` republishes the new active view's
    # snapshot into the flat `ui_slices_*` / `ui_range_*` state vars on
    # panel switch. That means each view owns its own slicer state and
    # the legacy lockstep mirror this used to install (legacy →
    # per-views fan-out on every slider edit) is now actively HARMFUL:
    # legacy stays stale (no one writes to it from the panel anymore)
    # and re-publishing its stale state onto every per-view would
    # clobber per-view divergence the user just made. The mirror hook
    # is therefore removed. `SceneRegistry.mirror_legacy_ijk_state`
    # stays defined for one-shot snapshot/apply use (snapshot is the
    # source view's per-view IjkGrid in the new model — see
    # `RepInScene.snapshot_ijk_slicers`).

    # --- Threshold chain wiring -------------------------------------------
    # The data layer (SourceRegistry / IjkGrid) owns the chain. The engine's
    # job is to:
    #   1. Publish the chain to `ui_threshold_chain` so the UI can render it.
    #   2. Forward UI events (add / delete / set_range / set_visible) into
    #      the data layer via controller methods.
    # No per-rep persistence dicts on the state side — chains live with
    # their rep in the data layer until the rep is unloaded.

    def _refresh_threshold_ui_for_active_grid():
        # Phase 3a: threshold chain is per-view for non-IjkGrid reps.
        # Publish the chain belonging to the currently-active panel.
        threshold_dispatch.refresh_threshold_ui_for_active_grid(
            state, _scene_registry, _source_registry,
        )

    def _refresh_descriptive_stats():
        """Recompute `ui_stats_tables` for every property pinned in
        `ui_stats_pinned_paths`. Triggered by the union of state
        changes below (pinned set, per-property panel state, view
        list, threshold chain, realization picks, …) — the stats are
        computed cheaply (transient Threshold + DescriptiveStatistics
        per row, deleted afterwards) so re-running on every relevant
        signal is acceptable."""
        try:
            stats_dispatch.publish_descriptive_stats(
                state, _scene_registry, _source_registry, _tree,
            )
        except Exception as _e:
            print(f"[WARNING] publish descriptive stats failed: {_e}")
        # Re-derive every open Compare-stats panel's resolved items
        # from the fresh tables — stale rows drop out automatically.
        # publish_compare_items is now per-property (new signature
        # takes array_path); iterate the singleton-panel registry to
        # know which properties have a live panel that needs a push.
        compare_panels = getattr(state, "ui_stats_compare_panel", {}) or {}
        for _ap in list(compare_panels.keys()):
            try:
                _refresh_compare_stats(_ap)
            except Exception as _e:
                print(f"[WARNING] _refresh_compare_stats({_ap}) failed: {_e}")

    def _open_stats_if_closed() -> None:
        """Open the Stats floating overlay only when it's not
        already open. Used by the tree's chart-icon on first pin
        so we don't steal focus or move an already-open Stats
        window when the user is just adding more pinned
        properties."""
        mv = getattr(server.context, "multi_view", None)
        if mv is None:
            return
        existing = getattr(state, "fespp_stats_panel_id", "") or ""
        if existing:
            return
        try:
            mv.add_view(kind="stats")
        except Exception as exc:
            print(f"[WARNING] open stats panel failed: {exc}")

    @controller.set("toggle_stats_display")
    def toggle_stats_display(array_path):
        """Tree button entry-point: add / remove `array_path` from
        the stats-pinned set. The `ui_stats_pinned_paths` change
        handler republishes the tables. On first pin, opens the
        singleton stats dockview tab at the bottom (no focus
        steal)."""
        pinned_before = list(getattr(state, "ui_stats_pinned_paths", []) or [])
        stats_dispatch.toggle_stats_pinned(state, array_path)
        pinned_after = list(getattr(state, "ui_stats_pinned_paths", []) or [])
        was_added = array_path in pinned_after and array_path not in pinned_before
        if was_added:
            _open_stats_if_closed()

    @controller.set("open_stats_panel")
    def open_stats_panel():
        """Toolbar 'View Statistics' button entry-point — pure
        OPEN/CLOSE toggle. If the Stats floating overlay is
        closed, opens it via `add_view(kind="stats")`; if it's
        open, closes it via `remove_panel`. Doesn't touch
        `ui_stats_pinned_paths` or `ui_stats_panel_state`, so the
        user's pinned properties + per-Original snapshots survive
        the cycle and reappear on next open. To raise an obscured
        floating window, click twice (close, reopen) — dockview's
        z-index singleton lifts the freshly-added group to the
        top."""
        mv = getattr(server.context, "multi_view", None)
        if mv is None:
            return
        existing = getattr(state, "fespp_stats_panel_id", "") or ""
        if existing:
            try:
                mv.remove_panel(existing)
            except Exception as exc:
                print(f"[WARNING] close stats panel failed: {exc}")
            return
        try:
            mv.add_view(kind="stats")
        except Exception as exc:
            print(f"[WARNING] open stats panel failed: {exc}")

    # Stats hooks invoked from Vue templates via `trigger('name', […])`
    # — `@server.trigger(name)` is the registration path that the
    # Vue runtime resolves (controller-set methods are reachable as
    # `controller.name(...)` from Python only, not from the
    # template). Each delegates to a thin `stats_dispatch` helper.

    @server.trigger("stats_set_original_real_idx")
    def _stats_set_original_real_idx(array_path, original_id, real_idx):
        stats_dispatch.set_original_real_idx(
            state, array_path, original_id, real_idx,
        )

    @server.trigger("stats_set_original_ts_idx")
    def _stats_set_original_ts_idx(array_path, original_id, ts_idx):
        stats_dispatch.set_original_ts_idx(
            state, array_path, original_id, ts_idx,
        )

    @server.trigger("stats_pin_original")
    def _stats_pin_original(array_path, original_id):
        stats_dispatch.pin_original(state, array_path, original_id)

    @server.trigger("stats_unpin_original")
    def _stats_unpin_original(array_path, original_id):
        stats_dispatch.unpin_original(state, array_path, original_id)

    @server.trigger("stats_compare_toggle")
    def _stats_compare_toggle(array_path, item_key):
        stats_dispatch.toggle_compare(state, array_path, item_key)
        # Live-update both singleton panels (stats + dist) if open.
        stats_panels = getattr(state, "ui_stats_compare_panel", {}) or {}
        dist_panels = getattr(state, "ui_stats_compare_dist_panel", {}) or {}
        if array_path in stats_panels:
            _refresh_compare_stats(array_path)
        if array_path in dist_panels:
            _refresh_compare_dist(array_path)

    @server.trigger("stats_compare_clear")
    def _stats_compare_clear(array_path):
        stats_dispatch.clear_compare(state, array_path)
        stats_panels = getattr(state, "ui_stats_compare_panel", {}) or {}
        dist_panels = getattr(state, "ui_stats_compare_dist_panel", {}) or {}
        if array_path in stats_panels:
            _refresh_compare_stats(array_path)
        if array_path in dist_panels:
            _refresh_compare_dist(array_path)

    @server.trigger("open_compare_stats")
    def _open_compare_stats(array_path):
        """Open or focus the singleton Compare-stats floating panel
        for array_path. If a panel is already registered, just
        re-push the items; otherwise spawn a new floating dockview
        panel via mv.add_view(kind=stats_compare)."""
        if not array_path:
            return
        panels = dict(getattr(state, "ui_stats_compare_panel", {}) or {})
        if array_path in panels:
            _refresh_compare_stats(array_path)
            return
        mv = getattr(server.context, "multi_view", None)
        if mv is None:
            return
        try:
            panel_id = mv.add_view(kind="stats_compare")
        except Exception as exc:
            print("[WARNING] add_view(stats_compare) failed: " + str(exc))
            return
        panels[array_path] = panel_id
        state.ui_stats_compare_panel = panels
        # Stash the property the panel binds to so the panel UI can
        # read it from a single state var without threading
        # panel_id<->array_path lookups in Vue expressions.
        state["ui_stats_compare_array_path_" + str(panel_id)] = array_path
        # Lazy import: the seeds dict below needs the canonical
        # metric-key list to default visible_metrics to "all". The
        # later _refresh_compare_stats import is independent.
        from fespp_on_trame.app.core.engine import compare_matrix
        # Seed per-panel option defaults so the toolbar v_models
        # bind cleanly on first render.
        seeds = {
            # Visible-metrics list seeded with every canonical metric
            # key — the user prunes individual columns via the
            # Columns menu in the panel toolbar. Inverted semantics
            # vs the old hidden_metrics state var (which seeded to
            # [] = "hide nothing"); the new flag is "show what is in
            # the list", so the default has to be every key.
            ("ui_stats_compare_visible_metrics_" + str(panel_id)): list(compare_matrix._METRIC_KEYS),
            ("ui_stats_compare_baseline_" + str(panel_id)): "",
            ("ui_stats_compare_order_" + str(panel_id)): [],
            ("ui_stats_compare_transposed_" + str(panel_id)): False,
            ("ui_stats_compare_sort_key_" + str(panel_id)): "",
            ("ui_stats_compare_sort_asc_" + str(panel_id)): True,
            ("ui_stats_compare_items_" + str(panel_id)): [],
            ("ui_stats_compare_csv_" + str(panel_id)): "",
        }
        for k, v in seeds.items():
            try:
                state[k] = v
            except Exception:
                pass

        def _on_compare_stats_options_changed(**_kw):
            _refresh_compare_stats(array_path)
        watched = (
            "ui_stats_compare_baseline_" + str(panel_id),
            "ui_stats_compare_sort_key_" + str(panel_id),
            "ui_stats_compare_sort_asc_" + str(panel_id),
            "ui_stats_compare_order_" + str(panel_id),
        )
        try:
            state.change(*watched)(_on_compare_stats_options_changed)
        except Exception as exc:
            print("[WARNING] compare-stats watcher for " + str(panel_id) + ": " + str(exc))
        _refresh_compare_stats(array_path)

    # --- Distribution panel: option-driven re-compute -----------------------
    # The Distribution panel exposes per-panel option vars (mode, bins,
    # log Y, stats overlay, cumulative, normalisation). Pinning a row
    # spawns a panel via `_spawn_distribution_panel(...)` which stores
    # the row context in `state.ui_distribution_context_<panel_id>` AND
    # registers a `state.change` watcher on every option var. The
    # watcher reads the context + the current option values, re-runs
    # the compute, and pushes a fresh figure + meta + CSV through the
    # panel's update controller method.
    # ------------------------------------------------------------------------

    def _distribution_option_vars(panel_id):
        """Names of every state var the watcher should react to for
        `panel_id`. Mirrors `DistributionPanel.*_var` properties."""
        return (
            f"ui_distribution_mode_{panel_id}",
            f"ui_distribution_nbins_{panel_id}",
            f"ui_distribution_log_y_{panel_id}",
            f"ui_distribution_show_stats_{panel_id}",
            f"ui_distribution_cumulative_{panel_id}",
            f"ui_distribution_norm_{panel_id}",
        )

    def _csv_data_url(csv_text):
        """Encode a CSV string as a base64 data URL so the toolbar's
        `<a :href download>` resolves to a browser download without
        needing a dedicated HTTP route. Cheap for histogram-size
        payloads (a few KB) — switch to a route if compare ever
        produces 100k+ row CSVs."""
        import base64
        b = csv_text.encode("utf-8")
        return "data:text/csv;base64," + base64.b64encode(b).decode("ascii")

    def _refresh_distribution(panel_id):
        """Re-run the compute for `panel_id` using its current option
        state vars + its stored context, then push the fresh figure +
        meta + CSV. Defensive: any failure prints a warning and
        leaves the prior figure in place."""
        ctx = (getattr(state, "ui_distribution_contexts", {}) or {}).get(panel_id)
        if not ctx:
            return
        opts = {
            "display_mode": getattr(state, f"ui_distribution_mode_{panel_id}", None),
            "nbins": getattr(state, f"ui_distribution_nbins_{panel_id}", None),
            "log_y": getattr(state, f"ui_distribution_log_y_{panel_id}", None),
            "show_stats": getattr(state, f"ui_distribution_show_stats_{panel_id}", None),
            "cumulative": getattr(state, f"ui_distribution_cumulative_{panel_id}", None),
            "norm": getattr(state, f"ui_distribution_norm_{panel_id}", None),
        }
        try:
            if ctx.get("kind") == "compare":
                array_path = ctx.get("array_path")
                carts = getattr(state, "ui_stats_compare", {}) or {}
                selection = list(carts.get(array_path) or [])
                result = distribution_dispatch.compute_compare_figure(
                    state, _tree, _scene_registry, _source_registry,
                    selection,
                    return_meta=True, **opts,
                )
                if isinstance(result, tuple):
                    fig, meta = result
                else:
                    fig, meta = result, None
            else:
                fig, meta = distribution_dispatch.compute_histogram_figure(
                    state, _tree, _scene_registry, _source_registry,
                    ctx.get("array_path"), ctx.get("row_kind"), ctx.get("row_id"),
                    return_meta=True, **opts,
                )
        except Exception as exc:
            print(f"[WARNING] _refresh_distribution({panel_id}) failed: {exc}")
            return
        if fig is None:
            return
        ctrl_name = f"update_distribution_figure_{panel_id}"
        upd = getattr(controller, ctrl_name, None)
        if upd is not None:
            try:
                upd(fig)
            except Exception as exc:
                print(f"[WARNING] {ctrl_name} failed: {exc}")
                try:
                    state[f"ui_distribution_figure_{panel_id}"] = fig.to_plotly_json()
                except Exception:
                    pass
        else:
            try:
                state[f"ui_distribution_figure_{panel_id}"] = fig.to_plotly_json()
            except Exception:
                pass
        # Push meta + CSV alongside the figure so the toolbar's badge
        # + download button update in lockstep with the new figure.
        try:
            state[f"ui_distribution_meta_{panel_id}"] = {
                "kept": meta.get("kept", 0),
                "total": meta.get("total", 0),
                "nan": meta.get("nan", 0),
            }
        except Exception:
            pass
        try:
            csv_text = distribution_dispatch.build_csv_from_meta(meta)
            state[f"ui_distribution_csv_{panel_id}"] = _csv_data_url(csv_text)
        except Exception:
            pass

    def _refresh_compare_dist(array_path):
        """Push a fresh compare figure into the singleton compare-
        dist panel for array_path. Cart < 2 → placeholder figure
        with 'add rows to compare' annotation so the panel stays
        mounted (user feedback round 2026-06)."""
        panels = getattr(state, "ui_stats_compare_dist_panel", {}) or {}
        panel_id = panels.get(array_path)
        if not panel_id:
            return
        carts = getattr(state, "ui_stats_compare", {}) or {}
        selection = list(carts.get(array_path) or [])
        opts = {
            "display_mode": getattr(state, "ui_distribution_mode_" + str(panel_id), None),
            "nbins": getattr(state, "ui_distribution_nbins_" + str(panel_id), None),
            "log_y": getattr(state, "ui_distribution_log_y_" + str(panel_id), None),
            "show_stats": getattr(state, "ui_distribution_show_stats_" + str(panel_id), None),
            "cumulative": getattr(state, "ui_distribution_cumulative_" + str(panel_id), None),
            "norm": getattr(state, "ui_distribution_norm_" + str(panel_id), None),
        }
        fig = None
        meta = {"kept": 0, "total": 0, "nan": 0}
        try:
            result = distribution_dispatch.compute_compare_figure(
                state, _tree, _scene_registry, _source_registry,
                selection, return_meta=True, **opts,
            )
            if isinstance(result, tuple):
                fig, meta = result
            else:
                fig = result
        except Exception as exc:
            print("[WARNING] _refresh_compare_dist(" + str(array_path) + "): " + str(exc))
        if fig is None:
            try:
                import plotly.graph_objects as go
                fig = go.Figure(
                    data=[],
                    layout=go.Layout(
                        annotations=[dict(
                            text=("Add 2 or more rows to the Cmp dist"
                                  " column to populate this overlay."),
                            xref="paper", yref="paper",
                            x=0.5, y=0.5, showarrow=False,
                            font=dict(size=14, color="#9e9e9e"),
                        )],
                        margin=dict(l=20, r=20, t=20, b=20),
                    ),
                )
                meta = {"kept": 0, "total": 0, "nan": 0}
            except Exception:
                return
        ctrl_name = "update_distribution_figure_" + str(panel_id)
        upd = getattr(controller, ctrl_name, None)
        if upd is not None:
            try:
                upd(fig)
            except Exception:
                try:
                    state["ui_distribution_figure_" + str(panel_id)] = fig.to_plotly_json()
                except Exception:
                    pass
        try:
            state["ui_distribution_meta_" + str(panel_id)] = {
                "kept": int((meta or {}).get("kept", 0) or 0),
                "total": int((meta or {}).get("total", 0) or 0),
                "nan": int((meta or {}).get("nan", 0) or 0),
            }
        except Exception:
            pass

    def _refresh_compare_stats(array_path):
        """Push fresh item list + CSV into the singleton Compare-
        stats panel for array_path. Item list = stats_dispatch.
        publish_compare_items(...). CSV = compare_matrix_csv(...).
        Reads the per-panel options to apply transpose / hidden
        metrics / sort BEFORE pushing (server-side filtering)."""
        panels = getattr(state, "ui_stats_compare_panel", {}) or {}
        panel_id = panels.get(array_path)
        if not panel_id:
            return
        try:
            items = stats_dispatch.publish_compare_items(
                state, _tree, _scene_registry, _source_registry,
                array_path,
            )
        except Exception as exc:
            print("[WARNING] _refresh_compare_stats(" + str(array_path) + "): " + str(exc))
            items = []
        # Server-side sort (so the cell-class annotations indices line
        # up with the displayed row order — the template iterates the
        # items list in order).
        from fespp_on_trame.app.core.engine import compare_matrix
        sort_key = getattr(state, "ui_stats_compare_sort_key_" + str(panel_id), "") or ""
        sort_asc = bool(getattr(state, "ui_stats_compare_sort_asc_" + str(panel_id), True))
        if sort_key:
            rows = [(it or {}).get("row") or {} for it in items]
            order = sorted(
                range(len(items)),
                key=lambda i: (
                    1 if rows[i].get(sort_key) is None else 0,
                    (1 if sort_asc else -1) * (
                        float(rows[i].get(sort_key)) if rows[i].get(sort_key) is not None else 0.0
                    ),
                ),
            )
            items = [items[i] for i in order]
        baseline_key = getattr(state, "ui_stats_compare_baseline_" + str(panel_id), "") or ""
        # User-defined manual order (drag-to-reorder). When non-empty,
        # rebuilds the items list in that key order; keys not present
        # in the order list trail at the end (newly-added rows).
        user_order = list(getattr(state, "ui_stats_compare_order_" + str(panel_id), []) or [])
        if user_order:
            by_key = {it.get("key"): it for it in items}
            ordered = [by_key[k] for k in user_order if k in by_key]
            # Append anything not in the order (new cart additions).
            seen = set(user_order)
            for it in items:
                if it.get("key") not in seen:
                    ordered.append(it)
            items = ordered

        # Pin baseline first so it stays anchored on the left of the
        # scroll area; the panel template applies position: sticky on
        # this column / row.
        if baseline_key:
            baseline_item = next(
                (it for it in items if it.get("key") == baseline_key),
                None,
            )
            if baseline_item is not None:
                items = [it for it in items if it.get("key") != baseline_key]
                items.insert(0, baseline_item)
        # Annotate items with their distribution profile tag, computed
        # from each row's Skewness + Kurtosis. Empty string when the
        # numbers are missing — the panel chip is conditional on this.
        for it in items:
            row = (it or {}).get("row") or {}
            it["profile"] = compare_matrix.profile_tag(
                row.get("Skewness"), row.get("Kurtosis"),
            )
        # Highlight mode is now implicit from baseline_key: when the
        # user picked a baseline row, render Δ comparisons; when the
        # picker is "(no baseline)" (empty string), fall back to
        # extrema (min/max) so the user still sees a useful visual cue.
        mode = "baseline" if baseline_key else "extrema"
        annotations = compare_matrix.highlight_annotations_for_items(
            items, mode,
            baseline_key=baseline_key,
        )
        # Push the per-panel state vars: items first (template's v-for
        # source), then the annotations dict (template's cell-class
        # lookup), then the CSV.
        state["ui_stats_compare_items_" + str(panel_id)] = items
        state["ui_stats_compare_annotations_" + str(panel_id)] = annotations
        # Build the CSV from the items list. Light pass; the panel
        # toolbar's Download button binds to the data URL state var.
        try:
            from fespp_on_trame.app.core.engine import compare_matrix
            # The new visible_metrics state var inverts the old
            # hidden_metrics; items_to_csv still takes the legacy
            # hidden_metrics argument so we invert here.
            visible = getattr(
                state, "ui_stats_compare_visible_metrics_" + str(panel_id),
                list(compare_matrix._METRIC_KEYS),
            ) or list(compare_matrix._METRIC_KEYS)
            hidden = [k for k in compare_matrix._METRIC_KEYS if k not in visible]
            csv_text = compare_matrix.items_to_csv(
                items,
                hidden_metrics=hidden,
            )
            import base64
            data_url = "data:text/csv;base64," + base64.b64encode(
                csv_text.encode("utf-8")
            ).decode("ascii")
            state["ui_stats_compare_csv_" + str(panel_id)] = data_url
        except Exception:
            pass

    def _spawn_distribution_panel(*, kind, context):
        """Create a fresh Distribution panel + register its per-panel
        watcher + push the initial figure.

        `kind`: "single" | "compare". `context`: dict carrying the
        row info (single) or the selection list (compare). The
        context is stored under
        `state.ui_distribution_contexts[panel_id]` so the watcher
        can re-run the same compute when options change.

        Order of operations matters: `mv.add_view(kind="distribution")`
        runs the template build synchronously Python-side, which is
        when `setattr(controller, "update_distribution_figure_<id>",
        widget.update)` happens — so the controller method exists by
        the time this helper returns."""
        mv = getattr(server.context, "multi_view", None)
        if mv is None:
            return None
        try:
            panel_id = mv.add_view(kind="distribution")
        except Exception as exc:
            print(f"[WARNING] add_view(distribution) failed: {exc}")
            return None
        # Store the context so the watcher can re-compute on demand.
        contexts = dict(getattr(state, "ui_distribution_contexts", {}) or {})
        contexts[panel_id] = dict(context, kind=kind)
        state.ui_distribution_contexts = contexts
        # Seed per-panel option vars with their defaults so the
        # toolbar initial render binds to known values (avoids
        # "v_model undefined" lifecycle warnings).
        defaults = {
            f"ui_distribution_mode_{panel_id}": "bars",
            f"ui_distribution_nbins_{panel_id}": 50,
            f"ui_distribution_log_y_{panel_id}": False,
            f"ui_distribution_show_stats_{panel_id}": False,
            f"ui_distribution_cumulative_{panel_id}": False,
            f"ui_distribution_norm_{panel_id}": "count",
            f"ui_distribution_is_compare_{panel_id}": kind == "compare",
            f"ui_distribution_meta_{panel_id}": {"kept": 0, "total": 0, "nan": 0},
            f"ui_distribution_csv_{panel_id}": "",
        }
        for k, v in defaults.items():
            try:
                state[k] = v
            except Exception:
                pass
        # Register the per-panel watcher on every option var. Trame
        # supports `state.change(*names)(callback)` as the runtime
        # form of the decorator — the callback is fired whenever any
        # of the listed vars mutates.
        def _on_options_changed(**_kwargs):
            _refresh_distribution(panel_id)
        try:
            state.change(*_distribution_option_vars(panel_id))(_on_options_changed)
        except Exception as exc:
            print(f"[WARNING] state.change registration for {panel_id} failed: {exc}")
        # Initial compute pushes figure + meta + CSV.
        _refresh_distribution(panel_id)
        return panel_id

    @server.trigger("open_row_histogram")
    def _open_row_histogram(array_path, row_kind, row_id):
        """Per-Stats-row chart icon — opens a NEW floating
        Distribution panel for that row's histogram. Multi-instance:
        every click spawns its own panel so users can compare
        multiple distributions side-by-side without losing earlier
        ones. The user closes via the dockview `×`."""
        _spawn_distribution_panel(
            kind="single",
            context={
                "array_path": array_path,
                "row_kind": row_kind,
                "row_id": row_id,
            },
        )

    @server.trigger("open_compare_distributions")
    def _open_compare_distributions(array_path):
        """Open or focus the singleton Compare-distribution floating
        panel for array_path. If a panel is already registered for
        this property, no new one is spawned — we re-push the figure
        (user clicks the existing tab to focus; dockview lacks a
        Python hook for programmatic focus)."""
        if not array_path:
            return
        panels = dict(getattr(state, "ui_stats_compare_dist_panel", {}) or {})
        if array_path in panels:
            _refresh_compare_dist(array_path)
            return
        panel_id = _spawn_distribution_panel(
            kind="compare",
            context={"array_path": array_path, "kind": "compare"},
        )
        if panel_id is None:
            return
        panels[array_path] = panel_id
        state.ui_stats_compare_dist_panel = panels
        _refresh_compare_dist(array_path)

    @server.trigger("toggle_stats_display")
    def _toggle_stats_display_trigger(array_path):
        # Same body as `controller.toggle_stats_display` so the
        # tree's chart icon (which goes through the controller call
        # pattern) and the panel's × buttons (which go through
        # `trigger('toggle_stats_display', …)`) share the
        # auto-open-stats-tab side effect. Kept as a separate
        # callable rather than `server.trigger` re-decorating the
        # existing controller method to avoid the silent override
        # gotchas of the latter pattern.
        controller.toggle_stats_display(array_path)

    @controller.set("threshold_add")
    def threshold_add(parent_name=None, array=None):
        threshold_dispatch.threshold_add(
            state, controller, _scene_registry, _source_registry,
            _activator, _view,
            parent_name=parent_name, array=array, tree=_tree,
        )

    @controller.set("threshold_delete")
    def threshold_delete(name):
        threshold_dispatch.threshold_delete(
            state, controller, _scene_registry, _source_registry,
            _view, name,
        )

    @controller.set("threshold_set_range")
    def threshold_set_range(name, low, high):
        threshold_dispatch.threshold_set_range(
            state, controller, _scene_registry, _source_registry,
            _view, name, low, high,
        )

    @controller.set("threshold_set_visible")
    def threshold_set_visible(name, visible):
        threshold_dispatch.threshold_set_visible(
            state, controller, _scene_registry, _source_registry,
            _activator, _view, name, visible,
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
        # Refresh the slice-plane panel from the newly-active rep's
        # SlicePlane state. Per-rep instance, so switching reps must
        # repaint the panel.
        try:
            slice_dispatch.publish_slice_state(state, _scene_registry)
        except Exception as _e:
            print(f"[WARNING] publish slice state failed: {_e}")
        # Same for the clip-plane panel.
        try:
            clip_dispatch.publish_clip_state(state, _scene_registry)
        except Exception as _e:
            print(f"[WARNING] publish clip state failed: {_e}")
        _refresh_descriptive_stats()

    @state.change(
        "ui_stats_pinned_paths",
        "ui_stats_panel_state",
        "fespp_render_panels",
        "ui_active_realization_by_array_by_view",
        "ui_threshold_chain",
        "time_index",
        "ui_per_view_time_pulse",
        "ui_slice_enabled",
        "ui_slice_axis",
        "ui_slice_offset",
        "ui_clip_enabled",
        "ui_clip_axis",
        "ui_clip_offset",
        "ui_clip_inside_out",
        "ui_slices_i_list",
        "ui_slices_j_list",
        "ui_slices_k_list",
        "ui_slices_i_visible_list",
        "ui_slices_j_visible_list",
        "ui_slices_k_visible_list",
        "ui_slices_range_i",
        "ui_slices_range_j",
        "ui_slices_range_k",
        "ui_slices_range_mode",
        "ui_slices_volume_visible",
    )
    def _on_stats_inputs_change(**_):
        """Recompute the multi-property stats tables whenever an input
        that affects any of the rows changes:

          - `ui_stats_pinned_paths` / `ui_stats_panel_state` — user
            pinned a property or edited an Original row's selectors.
          - `fespp_render_panels` — a view was created / removed →
            the per-view rows appear / disappear.
          - `ui_active_realization_by_array_by_view` — a view picked
            a different realization → that view's row recomputes.
          - `ui_threshold_chain` — a threshold was added / removed /
            edited → the affected view's row recomputes (post-
            threshold output).
          - `ui_slice_*` / `ui_clip_*` / `ui_slices_*` — slice / clip /
            IJK slicer edits go through `publish_slice_state` /
            `publish_clip_state` / `_push_active_ijk_state_to_ui`
            which rewrite these flat vars from the drawer target
            view's per-view state. Listening to them catches the
            per-view edits without needing a "stats might be stale"
            signal from each dispatcher."""
        _refresh_descriptive_stats()

    def _follow_mode_target_from_active():
        """Resolve the drawer target in follow mode. Picks the
        currently active panel when it's a render view; otherwise
        falls back to the first render panel (the Stats / Diff tabs
        are non-render and can't be edited, so they shouldn't
        leave the Attributes panel orphaned)."""
        active = getattr(state, "fespp_active_panel_id", "") or ""
        render_panels = getattr(state, "fespp_render_panels", []) or []
        render_ids = [p.get("id") for p in render_panels if isinstance(p, dict)]
        if active in render_ids:
            return active
        if render_ids:
            return render_ids[0]
        return ""

    @state.change("fespp_active_panel_id")
    def _on_active_panel_change(**_):
        """Per-view scenes: when the user clicks a different panel tab,
        the slice / clip / threshold / IJK-slicer state they edit now
        belongs to the new panel's scene. Re-publish the descriptors
        so the panel sliders + chain reflect THAT panel's actual
        state instead of the previously-active panel's.

        `active_representation_path` may not change on a tab switch
        (same rep activated in both panels), so the existing
        `on_active_grid_change` handler doesn't fire. This handler
        closes the loop for slice + clip (Phase 1.b.2) + threshold
        chain (Phase 3a) + IjkGrid slicers (Phase 3b).

        Also: when the Attributes drawer is in follow-active mode
        (drawer_target_view_pinned=False), mirror the active panel id
        onto `drawer_target_view_id` so the edit panels stay locked
        on the focused view — but only when that panel is actually
        a render view. The Stats / Diff tabs aren't editable, so
        when one of them is focused we keep targeting the first
        render panel instead. Pinned mode is left alone — the user
        has explicitly chosen a target."""
        if not state.drawer_target_view_pinned:
            new_target = _follow_mode_target_from_active()
            if state.drawer_target_view_id != new_target:
                state.drawer_target_view_id = new_target
        try:
            slice_dispatch.publish_slice_state(state, _scene_registry)
        except Exception as _e:
            print(f"[WARNING] publish slice state on panel change: {_e}")
        try:
            clip_dispatch.publish_clip_state(state, _scene_registry)
        except Exception as _e:
            print(f"[WARNING] publish clip state on panel change: {_e}")
        try:
            _refresh_threshold_ui_for_active_grid()
        except Exception as _e:
            print(f"[WARNING] refresh threshold ui on panel change: {_e}")
        try:
            _push_active_ijk_state_to_ui()
        except Exception as _e:
            print(f"[WARNING] push active ijk state on panel change: {_e}")
        _refresh_descriptive_stats()
        # Pinned mode: the multi_view's `_on_view_activated` has just
        # called `pvsimple.SetActiveView(active_panel.pv_view)` via
        # ptc's base class. That clobbers the active view the drawer
        # target picked. Restore it so SolidColorPanel / RepresentBy
        # keep editing the pinned target.
        if state.drawer_target_view_pinned:
            _sync_pvsimple_active_to_target()

    @state.change("drawer_target_view_pinned")
    def _on_drawer_target_pinned_change(drawer_target_view_pinned=False, **_):
        """When the user UNPINS the drawer, resync the target id onto
        a render panel (active when it's render, first render
        otherwise — same fallback as `_on_active_panel_change`). When
        they pin, leave the target alone (the picker's VSelect drives
        subsequent changes)."""
        if not drawer_target_view_pinned:
            new_target = _follow_mode_target_from_active()
            if state.drawer_target_view_id != new_target:
                state.drawer_target_view_id = new_target

    def _sync_pvsimple_active_to_target():
        """Force `pvsimple.GetActiveView()` to return the drawer
        target's pv_view. The legacy panels (`SolidColorPanel`,
        `RepresentationTypePanel` via `ptc.RepresentBy`) read this
        global — in pinned mode the drawer target differs from
        `fespp_active_panel_id` and the multi_view's
        `_on_view_activated` would otherwise set pvsimple's active
        view back to the focused panel, making those panels edit
        the wrong view.

        No-op when the drawer target is empty or the scene isn't
        resolved yet (boot window)."""
        target = getattr(state, "drawer_target_view_id", "") or ""
        if not target:
            return
        scene = _scene_registry.get_scene(target)
        if scene is None or scene.pv_view is None:
            return
        try:
            pvsimple.SetActiveView(scene.pv_view)
        except Exception:
            pass

    @state.change("drawer_target_view_id")
    def _on_drawer_target_view_change(**_):
        """When the Attributes drawer's target view changes (either via
        the picker's pinned VSelect or an auto-sync triggered by an
        active-panel event), republish every UI flat var the edit
        panels read from so the sliders / chains / IJK state reflect
        the new target's actual configuration. Mirrors the publishers
        called from `_on_active_panel_change` — we deliberately don't
        share the body because the two events fire on slightly
        different conditions (the active-panel handler also tweaks
        `drawer_target_view_id` itself in follow mode, which is a
        no-op once we land here on the next state.change tick).

        Also re-points pvsimple's global active view at the target so
        the legacy panels (SolidColor, RepresentBy) edit the right
        view in pinned mode."""
        _sync_pvsimple_active_to_target()
        try:
            slice_dispatch.publish_slice_state(state, _scene_registry)
        except Exception as _e:
            print(f"[WARNING] publish slice state on target view change: {_e}")
        try:
            clip_dispatch.publish_clip_state(state, _scene_registry)
        except Exception as _e:
            print(f"[WARNING] publish clip state on target view change: {_e}")
        try:
            _refresh_threshold_ui_for_active_grid()
        except Exception as _e:
            print(f"[WARNING] refresh threshold ui on target view change: {_e}")
        try:
            _push_active_ijk_state_to_ui()
        except Exception as _e:
            print(f"[WARNING] push active ijk state on target view change: {_e}")

    @state.change("fespp_render_panels")
    def _on_render_panels_change(fespp_render_panels=None, **_):
        """Auto-depin when the pinned view is closed, and re-anchor
        the follow-mode target when the active panel isn't a render
        view (e.g. the user has the Stats / Diff tab focused). We
        watch the `fespp_render_panels` publisher (MultiView emits
        it on every add/close), so this also re-evaluates the target
        whenever a new render view appears."""
        panels = fespp_render_panels or []
        ids = {p.get("id") for p in panels}
        if state.drawer_target_view_pinned:
            if state.drawer_target_view_id and state.drawer_target_view_id not in ids:
                state.drawer_target_view_pinned = False
                state.drawer_target_view_id = _follow_mode_target_from_active()
            return
        # Follow mode: keep the target aligned with a real render
        # panel — falls back to the first available when the active
        # panel is non-render (Stats / Diff tab focused).
        new_target = _follow_mode_target_from_active()
        if state.drawer_target_view_id != new_target:
            state.drawer_target_view_id = new_target

    @controller.set("slice_set")
    def slice_set(enabled=None, axis=None, offset=None, panel_id=None):
        slice_dispatch.slice_set(
            state, controller, _scene_registry, _view,
            enabled=enabled, axis=axis, offset=offset, panel_id=panel_id,
        )

    @controller.set("clip_set")
    def clip_set(enabled=None, axis=None, offset=None, inside_out=None,
                 panel_id=None):
        clip_dispatch.clip_set(
            state, controller, _scene_registry, _view,
            enabled=enabled, axis=axis, offset=offset, inside_out=inside_out,
            panel_id=panel_id,
        )

    @controller.set("plane_edit_mode_set")
    def plane_edit_mode_set(mode):
        clip_dispatch.set_edit_mode(
            state, controller, _scene_registry, _view, mode,
        )

    # Phase 3c — "Copy from View X" controllers. Each one snapshots a
    # source view's state for a single concern and applies it to the
    # destination (defaults to the currently-active panel). The
    # underlying primitives live on RepInScene; SceneRegistry.replicate_view
    # is the multi-rep variant (used by view split). These are the
    # single-concern variants the UI panel headers will bind to.

    def _copy_concern(src_view, dst_view, concern, rep_path=None):
        """Internal: dispatch a single-concern copy. dst_view defaults
        to the Attributes drawer's target view (which itself follows
        the active panel unless pinned), rep_path to every rep present
        in the source scene."""
        dst_view = dst_view or (
            getattr(state, "drawer_target_view_id", "") or ""
            or getattr(state, "fespp_active_panel_id", "") or ""
        )
        if not src_view or not dst_view or src_view == dst_view:
            return
        if rep_path:
            # Single rep — bypass replicate_view's iteration so the
            # user can target one rep at a time via the panel.
            src_scene = _scene_registry.get_scene(str(src_view))
            dst_scene = _scene_registry.get_scene(str(dst_view))
            if src_scene is None or dst_scene is None:
                return
            src_rep = src_scene.get_rep(rep_path)
            dst_rep = dst_scene.get_rep(rep_path) or dst_scene.add_rep(rep_path)
            if src_rep is None or dst_rep is None:
                return
            try:
                if concern == "threshold":
                    dst_rep.apply_threshold_chain(src_rep.snapshot_threshold_chain())
                elif concern == "slice":
                    dst_rep.apply_slice(src_rep.snapshot_slice())
                elif concern == "clip":
                    dst_rep.apply_clip(src_rep.snapshot_clip())
                elif concern == "ijk_slicers":
                    dst_rep.apply_ijk_slicers(src_rep.snapshot_ijk_slicers())
            except Exception as exc:
                print(f"[copy {concern}] {src_view}→{dst_view}/{rep_path}: {exc}")
        else:
            # All reps in src — same machinery as view-split inheritance.
            _scene_registry.replicate_view(
                src_view, dst_view, concerns=(concern,),
            )
        # Re-render the dst view + republish UI panels so the copy is
        # visible immediately.
        dst_scene = _scene_registry.get_scene(str(dst_view))
        if dst_scene is not None and dst_scene.pv_view is not None:
            try:
                pvsimple.Render(view=dst_scene.pv_view)
            except Exception:
                pass
        # Republish flat UI state vars when the destination matches the
        # Attributes drawer's current target view — without this the
        # picker would silently refresh the rendered output but the
        # sliders in the panels would keep showing pre-copy values.
        drawer_target = (
            getattr(state, "drawer_target_view_id", "") or ""
            or getattr(state, "fespp_active_panel_id", "") or ""
        )
        if dst_view == drawer_target:
            try:
                if concern == "slice":
                    slice_dispatch.publish_slice_state(state, _scene_registry)
                elif concern == "clip":
                    clip_dispatch.publish_clip_state(state, _scene_registry)
                elif concern == "threshold":
                    _refresh_threshold_ui_for_active_grid()
                elif concern == "ijk_slicers":
                    _push_active_ijk_state_to_ui()
            except Exception as exc:
                print(f"[copy {concern}] republish failed: {exc}")
        try:
            controller.view_update()
        except Exception:
            pass

    @controller.set("copy_threshold_chain_from")
    def copy_threshold_chain_from(src_view, dst_view=None, rep_path=None):
        _copy_concern(src_view, dst_view, "threshold", rep_path=rep_path)

    @controller.set("copy_slice_from")
    def copy_slice_from(src_view, dst_view=None, rep_path=None):
        _copy_concern(src_view, dst_view, "slice", rep_path=rep_path)

    @controller.set("copy_clip_from")
    def copy_clip_from(src_view, dst_view=None, rep_path=None):
        _copy_concern(src_view, dst_view, "clip", rep_path=rep_path)

    @controller.set("copy_ijk_slicers_from")
    def copy_ijk_slicers_from(src_view, dst_view=None, rep_path=None):
        _copy_concern(src_view, dst_view, "ijk_slicers", rep_path=rep_path)

    # ------------------------------------------------------------------
    # Per-view multi-realization wiring.
    # Loading is driven by the assembly tree: each MR / MR+TS parent is
    # a grouping; checking it loads every realization child as a
    # distinct suffixed VTK array `<title>_real_<idx>`. This block only
    # tracks which realization each panel's ColorBy binds to.

    def _refresh_panel_mr_specs(**_):
        """Recompute the per-panel MR specs map that drives the
        RealizationPicker widget. Hooked on every state change that
        could affect the result — eye click (active_array_by_view),
        realization picker (active_realization_by_view), and tree
        rebuild (loaded reps changed). Idempotent — only writes when
        the new value differs from the current."""
        new_specs = realization_dispatch.recompute_panel_mr_specs(state, _tree)
        if new_specs != (state.ui_panel_active_mr_specs_by_id or {}):
            state.ui_panel_active_mr_specs_by_id = new_specs

    def _refresh_mr_derived(**_):
        """Recompute the panel_has_mr_by_id and ui_global_mr_specs
        aggregates from `ui_panel_active_mr_specs_by_id`. Hooked on the
        per-panel specs map so the derivations stay coherent without
        each consumer doing its own aggregation."""
        new_has = realization_dispatch.recompute_panel_has_mr(state)
        if new_has != (state.panel_has_mr_by_id or {}):
            state.panel_has_mr_by_id = new_has
        new_global = realization_dispatch.recompute_global_mr_specs(state)
        if new_global != (state.ui_global_mr_specs or []):
            state.ui_global_mr_specs = new_global
        _refresh_global_selected()

    def _refresh_global_selected(**_):
        """Clamp `ui_global_mr_selected_path` to a valid value and
        publish the matching spec. Hooked on changes to either the
        user pick or the underlying specs list so the widget always
        reads a coherent (path, spec) pair."""
        path, spec = realization_dispatch.resolve_global_selected(state)
        if path != (state.ui_global_mr_selected_path or ""):
            state.ui_global_mr_selected_path = path
        if spec != (state.ui_global_mr_selected_spec or None):
            state.ui_global_mr_selected_spec = spec

    state.change("ui_active_array_by_rep_by_view")(_refresh_panel_mr_specs)
    state.change("ui_active_realization_by_array_by_view")(_refresh_panel_mr_specs)
    state.change("ui_loaded_rep_paths")(_refresh_panel_mr_specs)
    state.change("ui_panel_active_mr_specs_by_id")(_refresh_mr_derived)
    state.change("ui_global_mr_selected_path")(_refresh_global_selected)

    @server.trigger("set_view_realization")
    def set_view_realization(panel_id, array_path, idx):
        """Trigger handler for the per-view RealizationPicker widget.
        Updates `ui_active_realization_by_array_by_view` and re-applies
        ColorBy on the target view so the new realization renders
        immediately. Loading is already handled at tree-selection time
        (MR parent is a grouping → all realization children are loaded
        as suffixed VTK arrays), so no plugin reconcile is needed."""
        try:
            panel_id_str = str(panel_id)
            array_path_str = str(array_path)
            idx_int = int(idx)
        except (TypeError, ValueError) as exc:
            print(f"[WARNING] set_view_realization invalid args: {exc}")
            return
        prev = realization_dispatch.get_active_realization_for_view(
            state, panel_id_str, array_path_str,
        )
        if prev == idx_int:
            # No-op — slider clicked on the already-active value.
            return
        realization_dispatch.set_active_realization_for_view(
            state, panel_id_str, array_path_str, idx_int,
        )

        # Re-apply ColorBy on the target view so the new suffixed
        # array gets bound. Look up the rep this array belongs to
        # via the tree.
        node_id = _tree.find_node_id(array_path_str)
        if node_id is None:
            return
        r_id = _tree.find_representation_node(node_id)
        r_path = _tree.find_path(r_id) if r_id is not None else None
        if not r_path:
            return
        from fespp_on_trame.app.core.engine import panel_resolver
        target_view, html_view = panel_resolver.resolve_view_and_html_view(
            server, panel_id_str,
        )
        from fespp_on_trame.app.core.engine import source_resolver
        source_resolver.apply_color_array(
            _source_registry, _tree, r_path, array_path_str,
            view=target_view, realization_idx=idx_int,
        )
        if target_view is not None:
            try:
                pvsimple.Render(view=target_view)
            except Exception:
                pass
        if html_view is not None:
            try:
                html_view.update()
            except Exception:
                pass
        else:
            try:
                controller.view_update()
            except Exception:
                pass

    @server.trigger("set_global_realization")
    def set_global_realization(array_path, idx):
        """Trigger handler for the global RealizationPicker in the tools
        band. Dispatches `set_view_realization` to every panel that has
        `array_path` active in its ColorBy — effectively a 'set this
        realization everywhere' shortcut, equivalent to clicking each
        per-view picker in turn."""
        try:
            array_path_str = str(array_path)
            idx_int = int(idx)
        except (TypeError, ValueError) as exc:
            print(f"[WARNING] set_global_realization invalid args: {exc}")
            return
        specs_by_panel = state.ui_panel_active_mr_specs_by_id or {}
        for panel_id, specs in specs_by_panel.items():
            for spec in specs or []:
                if spec.get("array_path") == array_path_str:
                    set_view_realization(panel_id, array_path_str, idx_int)
                    break

    @state.change("ui_threshold_pending_action")
    def _on_threshold_pending_action(ui_threshold_pending_action=None, **_):
        threshold_dispatch.on_threshold_pending_action(
            state, ui_threshold_pending_action,
            threshold_add, threshold_delete,
            threshold_set_range, threshold_set_visible,
        )

    @state.change("representation_active")
    def _propagate_representation(representation_active, **kwargs):
        slicer_dispatch.propagate_representation(
            _source_registry, _scene_registry, controller, representation_active,
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

    @state.change("time_index")
    def changeTimeLabel(**kwargs):
        time_realization.change_time_label(state, _tree)
        # Global TC moved → time step changed for every view at
        # global time → stats reflecting the active view need to
        # recompute on the new ViewTime.
        _refresh_descriptive_stats()

    @controller.set("register_per_view_time_label")
    def register_per_view_time_label(time_value_var, label_var):
        time_realization.register_per_view_time_label(
            state, _tree, time_value_var, label_var,
        )
        # Per-view TC: hook the panel's time-value var so a per-view
        # scrub also refreshes stats when the panel is the active one.
        # The handler is unconditional (cheap when not active — the
        # stats compute itself short-circuits when active_color_array_name
        # is empty or the rep / view don't match).
        @state.change(time_value_var)
        def _on_view_time_change(**_):
            _refresh_descriptive_stats()

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
