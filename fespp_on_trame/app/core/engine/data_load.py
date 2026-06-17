"""Driver of the load-time pipeline — extracted from
`boot.initialize_fespp_engine`.

`run(...)` is invoked whenever `state.fespp_data_selectors` changes
(from `Selector.select_node_*` in any of the three tabs). It:

  1. Pushes selectors to the active source (Collector or
     ETPConnector) and triggers a single UpdatePipeline so the
     resulting multiblock is materialised once.
  2. Hides the parent multiblock representation; rendering happens
     through per-rep extracts only.
  3. Reserves a distinct chip color for every newly-loaded rep,
     BEFORE the registry sync so newly-created sources tint from
     `state.solid_color_by_rep` immediately.
  4. Syncs `SourceRegistry` (creates / drops ExtractBlock + IjkGrid
     instances; refreshes BlockSelectors on each IjkGrid).
  5. Bumps every source's pipeline info so freshly-added properties
     become visible to ColorBy.
  6. Notifies the Activator of the new present-paths set so stale
     color bars get hidden.
  7. Maintains visibility tracking (`ui_loaded_rep_paths`,
     `ui_hidden_rep_paths`, per-view variants).
  8. Maintains data-array tracking (`ui_loaded_array_paths`,
     `ui_active_array_by_rep`, per-view variants) with the
     "newly-loaded array auto-becomes the rep's active one" rule.
  9. Refreshes the threshold UI for the active grid.
 10. Mirrors the active IjkGrid's stored slicer/range state into
     the trame UI vars.
 11. Single final Render.

Heavily commented because the order of operations matters — see the
per-step rationale below."""
import time as _time

from paraview import simple as pvsimple

from fespp_on_trame.app.utils.color_palette import color_for_index


def run(state, controller, server, view, tree, collector, etp_connector,
        source_registry, activator,
        refresh_threshold_ui, push_active_ijk_state):
    _t_total_start = _time.perf_counter()

    def _ms(t0):
        return int((_time.perf_counter() - t0) * 1000)

    print("FESPP data selectors changed:", state.fespp_data_selectors)
    active_source = etp_connector if etp_connector.is_connected else collector
    if active_source is None:
        return

    # SetPropertyWithName triggers ClearSelectors + AddSelector × N
    # on the C++ side; both are Modified()-only (no per-call Update())
    # to avoid N full pipeline executions per add. We trigger the
    # actual RequestData ONCE here so downstream code (set_node_id,
    # source_registry.sync) sees the freshly-loaded multiblock output.
    _t = _time.perf_counter()
    active_source.get_source().SetPropertyWithName('Selectors', state.fespp_data_selectors)
    active_source.get_source().UpdatePipeline()
    active_source.show()
    print(f"[PERF py] SetSelectors+UpdatePipeline+show: {_ms(_t)}ms")

    # Hide the parent multiblock representation BEFORE any render.
    # Each loaded rep is rendered through its own ExtractBlock proxy
    # below; leaving the parent visible would cause a Render() that
    # processes all N blocks via the parent rep, scaling O(N) per
    # add (~1100ms per extra grid in the original code).
    _t = _time.perf_counter()
    representation = active_source.get_representation()
    representation.Assembly = 'Assembly'
    representation.BlockSelectors = ['/data']
    representation.Visibility = 0
    print(f"[PERF py] representation.Assembly+BlockSelectors+Visibility=0: {_ms(_t)}ms")

    # Reserve a distinct chip color for every newly-loaded rep.
    # Cache (selector → rep_path) to avoid re-walking the tree each
    # call. Done BEFORE source_registry.sync so newly created
    # sources can read their assigned color from solid_color_by_rep
    # and tint their display straight away (both ExtractBlock and
    # IjkGrid read this state var during creation).
    _t = _time.perf_counter()
    sel_cache = dict(getattr(state, "_selector_rep_cache", {}) or {})
    colors = dict(state.solid_color_by_rep or {})
    next_idx = int(state.solid_color_next_idx or 0)
    for sel in state.fespp_data_selectors or []:
        cached = sel_cache.get(sel)
        if cached is None:
            n_id = tree.find_node_id(sel)
            if n_id is None:
                sel_cache[sel] = None
                continue
            r_id = tree.find_representation_node(n_id)
            if r_id is None:
                sel_cache[sel] = None
                continue
            r_path = tree.find_path(r_id)
            sel_cache[sel] = r_path
        else:
            r_path = cached
        if not r_path or r_path in colors:
            continue
        colors[r_path] = color_for_index(next_idx)
        next_idx += 1
    state._selector_rep_cache = sel_cache
    state.solid_color_by_rep = colors
    state.solid_color_next_idx = next_idx
    print(f"[PERF py] color assignment loop: {_ms(_t)}ms")

    # Unified sync: drives BOTH the IjkGrid side (rep_path resolved
    # from each reservoir node id) and the ExtractBlock side
    # (rep_path resolved from each selector). Tears down anything
    # no longer in the selection; creates anything new.
    _t = _time.perf_counter()
    source_registry.sync(
        state.fespp_data_selectors,
        state.ui_select_node_reservoir or [],
    )
    # Keep BlockSelectors in sync with each active IjkGrid's
    # property path — the parent multiblock rep no longer shows
    # the IJK property block itself (that's rendered via the
    # IjkGrid's slicers).
    for ijk in source_registry.ijk_grids():
        ijk.update_block_visibility()
    print(f"[PERF py] source_registry.sync: {_ms(_t)}ms")

    # The C++ side modifies partition data in place (addDataArray
    # for new property selectors, array swap for realization/time
    # changes). Sources cache their data information at the proxy
    # level — without a Modified() bump, GetCellDataInformation
    # returns a stale array list and the active handler can't
    # find a freshly-added property like "SOIL".
    _t = _time.perf_counter()
    for src in source_registry.all_sources():
        try:
            src.GetClientSideObject().Modified()
            src.UpdatePipelineInformation()
        except Exception:
            pass
    # IjkGrid slicers + volume crops need the same bump (they
    # aren't in all_sources(); the canonical source is the
    # rep_data extractor only).
    _t_ijk = _time.perf_counter()
    ijk_paths_in_selection = []
    for ijk in source_registry.ijk_grids():
        ijk_path = ijk.rep_path
        ijk_in_selection = bool(
            ijk_path
            and any(s == ijk_path or s.startswith(ijk_path + '/') for s in (state.fespp_data_selectors or []))
        )
        if ijk_in_selection and ijk_path:
            ijk_paths_in_selection.append(ijk_path)
        if not ijk_in_selection:
            continue
        try:
            slicer_sources = list(ijk._all_slice_sources())
            if ijk._src_slicer_volume is not None:
                slicer_sources.append(ijk._src_slicer_volume)
            for slc in slicer_sources:
                try:
                    slc.GetClientSideObject().Modified()
                    slc.UpdatePipelineInformation()
                except Exception:
                    pass
        except Exception:
            pass
    print(f"[PERF py] ijk slicer bumps: {_ms(_t_ijk)}ms (grids_in_selection={len(ijk_paths_in_selection)})")
    print(f"[PERF py] source bumps: {_ms(_t)}ms")

    # Tell the activator which reps are still actively displayed so
    # it hides stale color bars (e.g. switching between two IJK
    # grids — without this, the previous grid's color bar stays
    # alongside the new grid's bar).
    present_paths = set(p for p, _ in source_registry.items())
    if activator is not None:
        try:
            activator.notify_active_reps(present_paths)
        except Exception as _e:
            print(f"[WARNING] notify_active_reps failed: {_e}")

    _update_visibility_tracking(state, present_paths)
    last_array_for_rep, prev_loaded_set = _update_data_array_tracking(
        state, tree, present_paths,
    )
    _update_active_array_maps(state, present_paths, last_array_for_rep, prev_loaded_set)

    controller.view_replace
    state.view_update = True

    # Set the FESPP source as active for ParaView dialogs that look
    # at it. We do NOT call active_source.show() here — that would
    # re-set the parent rep's Visibility to 1 and undo the early
    # hide above.
    _t = _time.perf_counter()
    pvsimple.SetActiveSource(active_source.get_source())
    server.controller.on_data_loaded()
    server.controller.on_active_proxy_change()
    print(f"[PERF py] setActive+notify: {_ms(_t)}ms")

    if (not state.has_data_loaded_once) and (len(state.fespp_data_selectors) > 0):
        state.view_reset_camera = True
        state.has_data_loaded_once = True

    # Re-run the active handlers AFTER the load+sync so newly-loaded
    # reps get their ColorBy / TimeControl wiring even when their
    # @state.change active handler fired before this load handler
    # (handler ordering between ui_select_node_* and ui_active_node_*
    # is not guaranteed). Idempotent: a no-op if the active handler
    # already ran successfully.
    if activator is not None:
        activator.refresh_active()

    # Refresh the threshold UI: newly-loaded properties on the
    # active grid now appear in CellData/PointData and should show
    # up in the array picker.
    try:
        refresh_threshold_ui()
    except Exception as _e:
        print(f"[WARNING] threshold UI refresh after load failed: {_e}")

    # Mirror the active grid's stored slicer/range state into the
    # UI vars. Idempotent — when the active grid hasn't changed
    # since the last push, this just re-asserts the same values.
    try:
        push_active_ijk_state()
    except Exception as _e:
        print(f"[WARNING] push active ijk state failed: {_e}")

    # Single Render at the very end. The parent multiblock was
    # hidden earlier, so this only paints the new ExtractBlock reps
    # + IJK slicers.
    _t = _time.perf_counter()
    state.view_update = True
    pvsimple.Render(view=view)
    print(f"[PERF py] final Render: {_ms(_t)}ms")
    print(f"[PERF py] >>> TOTAL on_change_fespp_data_selectors: {_ms(_t_total_start)}ms <<<")


def _update_visibility_tracking(state, present_paths):
    """Maintain `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, and the
    per-view `ui_hidden_rep_paths_by_view` map.

    Visibility tracking: newly-loaded reps default to visible (eye
    open); reps that were hidden but stayed loaded keep their hidden
    state; reps no longer present are dropped from the hidden set so
    they don't ghost-hide on a future re-load."""
    # Capture the previous loaded set *before* mutating the state
    # var so we can detect which reps are brand-new in this run.
    prev_loaded = set(state.ui_loaded_rep_paths or [])
    loaded_sorted = sorted(present_paths)
    if list(state.ui_loaded_rep_paths or []) != loaded_sorted:
        state.ui_loaded_rep_paths = loaded_sorted
    prev_hidden = list(state.ui_hidden_rep_paths or [])
    kept_hidden = [p for p in prev_hidden if p in present_paths]
    if kept_hidden != prev_hidden:
        state.ui_hidden_rep_paths = kept_hidden
    # Same prune for every per-view bucket — unloaded reps must not
    # ghost-hide on a future reload, in any panel. Also extend the
    # buckets of *non-active* panels with any rep that's newly
    # loaded in this run, since ParaView only adds the new display
    # to the active view — other panels haven't had Show() called
    # on the new source so the chips for those panels should appear
    # closed (rep present but not yet shown there).
    new_reps = [p for p in present_paths if p not in prev_loaded]
    by_view = state.ui_hidden_rep_paths_by_view or {}
    if not by_view:
        return
    updated = {}
    changed = False
    present = set(present_paths)
    active_panel_id = state.fespp_active_panel_id or ""
    for pid, paths in by_view.items():
        old = list(paths or [])
        # 1. Drop unloaded reps.
        new = [p for p in old if p in present]
        # 2. For non-active panels, append newly-loaded reps that
        #    aren't already in the bucket. The active panel keeps
        #    the new rep as "visible" (chip open).
        if pid != active_panel_id and new_reps:
            bucket_set = set(new)
            for r in new_reps:
                if r not in bucket_set:
                    new.append(r)
                    bucket_set.add(r)
        updated[pid] = new
        if new != old:
            changed = True
    if changed:
        state.ui_hidden_rep_paths_by_view = updated


_DATA_ARRAY_KINDS = frozenset({
    "ContinuousProperty", "DiscreteProperty", "CategoricalProperty",
    "TimeSeries", "MultiRealization", "MultiRealizationTimeSeries",
})


def _update_data_array_tracking(state, tree, present_paths):
    """Recompute `ui_loaded_array_paths` and return
    `(last_array_for_rep, prev_loaded_array_set)` for downstream
    active-map maintenance.

    The "last added per rep" entry becomes the active eye by default
    later (mirroring the C++ side which colors by the last array
    added to the rep)."""
    prev_loaded_arrays = list(state.ui_loaded_array_paths or [])
    prev_loaded_set = set(prev_loaded_arrays)
    loaded_arrays = []
    loaded_arrays_set = set()
    last_array_for_rep = {}
    for sel in state.fespp_data_selectors or []:
        n_id = tree.find_node_id(sel)
        if n_id is None:
            continue
        kind = tree.find_type(n_id) or ""
        if kind not in _DATA_ARRAY_KINDS:
            continue
        r_id = tree.find_representation_node(n_id)
        r_path = tree.find_path(r_id) if r_id is not None else None
        if not r_path or r_path not in present_paths:
            continue
        if sel not in loaded_arrays_set:
            loaded_arrays.append(sel)
            loaded_arrays_set.add(sel)
        last_array_for_rep[r_path] = sel
    if loaded_arrays != prev_loaded_arrays:
        state.ui_loaded_array_paths = loaded_arrays
    return last_array_for_rep, prev_loaded_set


def _update_active_array_maps(state, present_paths, last_array_for_rep, prev_loaded_set):
    """Recompute `ui_active_array_by_rep` (global) and
    `ui_active_array_by_rep_by_view` (per-panel).

    Rules for the per-panel map:
      - Newly-loaded array (= last_arr ∉ prev_loaded_set) auto-becomes
        the rep's active one in **only the currently-active panel**.
        Other panels keep their previous eye state untouched — the
        user expects the load to affect just the panel they're
        focused on, not every replicated view at once.
      - Otherwise keep the panel's prior choice if its array is still
        loaded.
      - Otherwise leave the rep in SolidColor (no entry). Respects
        explicit deactivation by the user.

    The global `ui_active_array_by_rep` mirrors the active panel's
    bucket via the same rule, so legacy consumers (Activator,
    solid_color_panel) keep reading a coherent value."""
    active_panel_id = getattr(state, "fespp_active_panel_id", "") or None
    loaded_arrays_set = set(state.ui_loaded_array_paths or [])
    prev_active = dict(state.ui_active_array_by_rep or {})
    new_active = {}
    for r_path in present_paths:
        prev_arr = prev_active.get(r_path)
        last_arr = last_array_for_rep.get(r_path)
        newly_added = last_arr is not None and last_arr not in prev_loaded_set
        if newly_added:
            new_active[r_path] = last_arr
        elif prev_arr in loaded_arrays_set:
            new_active[r_path] = prev_arr
        # else: SolidColor (omit entry).
    if new_active != prev_active:
        state.ui_active_array_by_rep = new_active

    by_view = state.ui_active_array_by_rep_by_view or {}
    if not by_view:
        return
    new_by_view = {}
    changed = False
    for pid, pmap in by_view.items():
        prev_pmap = dict(pmap or {})
        new_pmap = {}
        is_active_panel = (active_panel_id is not None and pid == active_panel_id)
        for r_path in present_paths:
            prev_arr_p = prev_pmap.get(r_path)
            last_arr = last_array_for_rep.get(r_path)
            newly_added = last_arr is not None and last_arr not in prev_loaded_set
            if newly_added and is_active_panel:
                new_pmap[r_path] = last_arr
            elif prev_arr_p in loaded_arrays_set:
                new_pmap[r_path] = prev_arr_p
            # else: SolidColor — omit entry.
        new_by_view[pid] = new_pmap
        if new_pmap != prev_pmap:
            changed = True
    if changed:
        state.ui_active_array_by_rep_by_view = new_by_view
