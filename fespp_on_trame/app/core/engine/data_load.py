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

The order of operations matters — see the per-step rationale below."""
from paraview import simple as pvsimple

from fespp_on_trame.app.utils.color_palette import color_for_index
from fespp_on_trame.app.core import element_type


def run(state, controller, server, view, tree, collector, etp_connector,
        source_registry, activator,
        refresh_threshold_ui, push_active_ijk_state):
    active_source = etp_connector if etp_connector.is_connected else collector
    if active_source is None:
        return

    # SetPropertyWithName triggers ClearSelectors + AddSelector × N
    # on the C++ side; both are Modified()-only (no per-call Update())
    # to avoid N full pipeline executions per add. We trigger the
    # actual RequestData ONCE here so downstream code (set_node_id,
    # source_registry.sync) sees the freshly-loaded multiblock output.
    active_source.get_source().SetPropertyWithName('Selectors', state.fespp_data_selectors)
    active_source.get_source().UpdatePipeline()
    active_source.show()

    # Hide the parent multiblock representation BEFORE any render.
    # Each loaded rep is rendered through its own ExtractBlock proxy
    # below; leaving the parent visible would make Render() process all
    # N blocks via the parent rep, scaling O(N) per add.
    representation = active_source.get_representation()
    representation.Assembly = 'Assembly'
    representation.BlockSelectors = ['/data']
    representation.Visibility = 0

    # Reserve a distinct chip color for every newly-loaded rep.
    # Cache (selector → rep_path) to avoid re-walking the tree each
    # call. Done BEFORE source_registry.sync so newly created
    # sources can read their assigned color from solid_color_by_rep
    # and tint their display straight away (both ExtractBlock and
    # IjkGrid read this state var during creation).
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

    # Unified sync: drives BOTH the IjkGrid side (rep_path resolved
    # from each reservoir node id) and the ExtractBlock side
    # (rep_path resolved from each selector). Tears down anything
    # no longer in the selection; creates anything new.
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

    # The C++ side modifies partition data in place (addDataArray
    # for new property selectors, array swap for realization/time
    # changes). Sources cache their data information at the proxy
    # level — without a Modified() bump, GetCellDataInformation
    # returns a stale array list and the active handler can't
    # find a freshly-added property like "SOIL".
    for src in source_registry.all_sources():
        try:
            src.GetClientSideObject().Modified()
            src.UpdatePipelineInformation()
        except Exception:
            pass
    # IjkGrid slicers + volume crops need the same bump (they aren't in
    # all_sources(); the canonical source is the rep_data extractor only).
    #
    # The rep_data extractor AND each slicer need a full
    # `UpdatePipeline()` (data pass) here, not just
    # `UpdatePipelineInformation()` (metadata pass). Without the data
    # pass the slicer keeps the output it cached at creation time — a
    # structurally valid `vtkExplicitStructuredGrid` with the right cell
    # count but no `CellData` arrays — so the activator's later
    # `_find_array_in_store` misses the property array even though it's
    # present upstream on `rep_data`.
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
            # Pipeline the rep_data extractor first so its output type
            # and CellData arrays settle before slicers pull from it.
            try:
                if ijk._src_extract_init is not None:
                    ijk._src_extract_init.GetClientSideObject().Modified()
                    ijk._src_extract_init.UpdatePipelineInformation()
                    ijk._src_extract_init.UpdatePipeline()
            except Exception:
                pass
            slicer_sources = list(ijk._all_slice_sources())
            if ijk._src_slicer_volume is not None:
                slicer_sources.append(ijk._src_slicer_volume)
            for slc in slicer_sources:
                try:
                    slc.GetClientSideObject().Modified()
                    slc.UpdatePipelineInformation()
                    slc.UpdatePipeline()
                except Exception:
                    pass
        except Exception:
            pass

    present_paths = set(p for p, _ in source_registry.items())

    # Captured BEFORE the tracking update mutates ui_loaded_rep_paths — used
    # below to spot blocked wellbores that appeared in THIS run.
    prev_rep_paths = set(state.ui_loaded_rep_paths or [])

    _update_visibility_tracking(state, present_paths)
    last_array_for_rep, prev_loaded_set = _update_data_array_tracking(
        state, tree, present_paths,
    )
    newly_markers = _update_marker_tracking(state, tree, present_paths)
    _update_active_array_maps(state, tree, present_paths, last_array_for_rep, prev_loaded_set)

    # Visibility and colouring are ORTHOGONAL: loading a property colours the
    # rep (array eye) but never re-opens its geometry eye. This used to force
    # freshly-arrayed reps visible ("select a property = load + eye"), which
    # made checking a NEW property resurrect a grid the user had just hidden —
    # the exact state "grid hidden, wells coloured by its property" relies on.
    # Colouring a hidden rep is legal: it shows when the geometry eye reopens.

    # --- SYNCHRONOUS teardown of DESELECTED reps' per-view pipelines ---
    # A just-deselected rep's per-view RepInScene (UG: `_extractor`,
    # IjkGrid: per-view slicers) is still Shown on the scene clone, but
    # the C++ `UpdatePipeline()` at the top of run() already rebuilt the
    # collector output WITHOUT that rep's partition. The normal teardown
    # (scene_registry.sync_loaded_reps via @state.change("ui_loaded_rep_paths"))
    # is deferred until after run() returns, i.e. after the activator
    # render below. Rendering a stale, still-visible source against a
    # clone whose upstream partition is gone crashes natively, so
    # hide+delete the deselected reps' per-view pipelines NOW, before any
    # render. The clone is already consistent (UpdatePipeline'd above).
    try:
        scene_reg = getattr(server.context, "scene_registry", None)
        if scene_reg is not None:
            for scene in scene_reg.all_scenes():
                for r_path in (set(scene._reps.keys()) - present_paths):
                    scene.remove_rep(r_path)
            # A deselected rep's display is gone, so its LUT is now
            # unreferenced — sweep each scene view to drop the orphaned
            # color bar. (Coloring + bar ownership live on the eye path;
            # the activator no longer tracks per-rep bars.)
            from fespp_on_trame.app.core.engine import source_resolver
            for scene in scene_reg.all_scenes():
                if scene.pv_view is not None:
                    source_resolver.hide_unused_scalar_bars(scene.pv_view)
    except Exception:
        pass

    # Build the ADD / eager-setup half SYNCHRONOUSLY too — not only via the
    # deferred @state.change("ui_loaded_rep_paths") handler. A newly-loaded
    # rep's per-view display + ColorBy must exist BEFORE the view push below;
    # otherwise the first push paints an empty client and the object only
    # appears once the user nudges the camera (which forces a client-side
    # re-render). Idempotent — the deferred handler then no-ops.
    try:
        scene_reg = getattr(server.context, "scene_registry", None)
        if scene_reg is not None:
            scene_reg.sync_loaded_reps(state.ui_loaded_rep_paths or [])
    except Exception:
        pass

    # Re-show the per-view pipeline of every rep we just un-hid in the active
    # scene. For an ALREADY-loaded rep the eager setup above is skipped (it
    # only fires for newly-added reps), so nothing else re-Shows it after the
    # eye was re-opened — without this the property loads + colors but the
    # rep stays dark.
    try:
        scene_reg = getattr(server.context, "scene_registry", None)
        if newly_arrayed and scene_reg is not None:
            active_pid = getattr(state, "fespp_active_panel_id", "") or ""
            scene = scene_reg.get_scene(active_pid) if active_pid else None
            if scene is not None:
                for r in newly_arrayed:
                    rep = scene.get_rep(r)
                    if rep is None:
                        continue
                    try:
                        rep.element_type.refresh_primary_visibility(rep)
                    except Exception:
                        pass
    except Exception:
        pass

    # Show markers freshly loaded this run in the active scene. Their per-view
    # extractor is built on demand by set_marker_visible, so a checked
    # MarkerFrame (all its markers) / a selected marker appears immediately
    # instead of needing a manual eye click.
    try:
        scene_reg = getattr(server.context, "scene_registry", None)
        active_pid = getattr(state, "fespp_active_panel_id", "") or ""
        scene = scene_reg.get_scene(active_pid) if (scene_reg and active_pid) else None
        if scene is not None and newly_markers:
            for marker_path in newly_markers:
                n_id = tree.find_node_id(marker_path)
                r_id = tree.find_representation_node(n_id) if n_id is not None else None
                r_path = tree.find_path(r_id) if r_id is not None else None
                rep = scene.get_rep(r_path) if r_path else None
                if rep is not None:
                    try:
                        rep.set_marker_visible(marker_path, True)
                    except Exception:
                        pass
    except Exception:
        pass

    # Set the FESPP source as active for ParaView dialogs that look
    # at it. We do NOT call active_source.show() here — that would
    # re-set the parent rep's Visibility to 1 and undo the early
    # hide above.
    pvsimple.SetActiveSource(active_source.get_source())
    server.controller.on_data_loaded()
    server.controller.on_active_proxy_change()

    if (not state.has_data_loaded_once) and (len(state.fespp_data_selectors) > 0):
        state.view_reset_camera = True
        state.has_data_loaded_once = True

    if activator is not None:
        activator.refresh_active()

    # A blocked wellbore checked while its grid ALREADY colours by a property
    # arrives uncoloured: the active-array map did not change, so nothing
    # re-applies ColorBy. Re-run the grid's colouring — its mirror hook then
    # paints the fresh wellbores (FESPP pushed them the arrays on load).
    try:
        from fespp_on_trame.app.core.engine import source_resolver
        new_bw = [
            p for p in (present_paths - prev_rep_paths)
            if (tree.find_type(tree.find_node_id(p)) or "") == "BlockedWellbore"
        ]
        if new_bw:
            active_map = dict(state.ui_active_array_by_rep or {})
            # The active panel's realization picks: an MR property only exists
            # as suffixed arrays ("<title>_real_<idx>"), so a resolve without
            # the index finds nothing and the fresh wellbores would stay
            # SolidColor — exactly, and only, when the active property is MR.
            panel_id = getattr(state, "fespp_active_panel_id", "") or ""
            panel_realizations = dict(
                (state.ui_active_realization_by_array_by_view or {})
                .get(panel_id, {}) or {}
            )
            grids_done = set()
            for bw_path in new_bw:
                bw_id = tree.find_node_id(bw_path)
                container = tree.find_parent_node_id_with_type(bw_id, "GridContainer")
                if container is None:
                    continue
                geom_id = tree.find_representation_node(container)
                geom_path = tree.find_path(geom_id) if geom_id is not None else None
                if not geom_path or geom_path in grids_done:
                    continue
                grids_done.add(geom_path)
                array_path = active_map.get(geom_path)
                if array_path:
                    source_resolver.apply_color_array(
                        source_registry, tree, geom_path, array_path, view=view,
                        realization_idx=panel_realizations.get(array_path),
                    )
    except Exception:
        pass

    try:
        refresh_threshold_ui()
    except Exception:
        pass
    try:
        push_active_ijk_state()
    except Exception:
        pass

    state.view_update = True
    # Reliable client refresh — render the (possibly empty) scene and push a
    # fresh frame to the client. Render UNCONDITIONALLY: an empty selection
    # must repaint the now-empty scene so an unload clears without a manual
    # view interaction. Push TWICE — a just-created representation's mapper is
    # realised on the first StillRender and only appears in the image grabbed
    # by the second.
    try:
        pvsimple.Render(view=view)
        push = getattr(server.controller, "view_update_all", None) or getattr(server.controller, "view_update", None)
        if push is not None:
            push()
            push()
    except Exception:
        pass


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
        if element_type.for_kind(tree.find_type(n_id)).tracking_bucket() != element_type.BUCKET_ARRAY:
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


def _update_marker_tracking(state, tree, present_paths):
    """Recompute `ui_loaded_marker_paths`: every WellboreMarker leaf
    (C++ runtime kind 'Marker') whose MarkerFrame rep is loaded.

    Markers display MULTIPLE at a time (unlike single-select log
    channels), so they get their own per-marker visibility eye rather
    than a data-array eye. This list only decides WHICH leaves render an
    eye; the per-view shown set lives in
    `ui_visible_marker_paths_by_view` and is mutated by
    `visibility.toggle_marker_visibility`. Also prune the per-view shown
    buckets of markers whose frame is no longer loaded so they don't
    ghost-show on a future reload."""
    loaded_markers = []
    loaded_set = set()
    for sel in state.fespp_data_selectors or []:
        n_id = tree.find_node_id(sel)
        if n_id is None:
            continue
        if element_type.for_kind(tree.find_type(n_id)).tracking_bucket() != element_type.BUCKET_MARKER:
            continue
        r_id = tree.find_representation_node(n_id)
        r_path = tree.find_path(r_id) if r_id is not None else None
        if not r_path or r_path not in present_paths:
            continue
        if sel not in loaded_set:
            loaded_markers.append(sel)
            loaded_set.add(sel)
    prev_loaded = set(state.ui_loaded_marker_paths or [])
    if loaded_markers != list(state.ui_loaded_marker_paths or []):
        state.ui_loaded_marker_paths = loaded_markers
    newly_loaded = [m for m in loaded_markers if m not in prev_loaded]
    # Prune shown-marker buckets (drop unloaded so they don't ghost) AND
    # auto-show markers freshly loaded this run in the ACTIVE panel: selecting
    # a marker / checking a MarkerFrame must display them without an extra eye
    # click (markers default to visible on load, like a property auto-colors).
    active_pid = getattr(state, "fespp_active_panel_id", "") or ""
    by_view = dict(state.ui_visible_marker_paths_by_view or {})
    updated = {}
    changed = False
    for pid, paths in by_view.items():
        kept = [p for p in (paths or []) if p in loaded_set]
        if pid == active_pid:
            for m in newly_loaded:
                if m not in kept:
                    kept.append(m)
        updated[pid] = kept
        if kept != list(paths or []):
            changed = True
    if active_pid and active_pid not in updated and newly_loaded:
        updated[active_pid] = list(newly_loaded)
        changed = True
    if changed:
        state.ui_visible_marker_paths_by_view = updated
    return newly_loaded


def _update_active_array_maps(state, tree, present_paths, last_array_for_rep, prev_loaded_set):
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
    solid_color_panel) keep reading a coherent value.

    MR properties carry an extra hook: when auto-activated, the
    panel's realization bucket
    (`ui_active_realization_by_array_by_view`) is seeded with the
    smallest available index — otherwise the resolver can't find any
    array name (only suffixed `<title>_real_<idx>` arrays exist) and
    the rep stays in SolidColor on first load."""
    from fespp_on_trame.app.core.engine import realization_dispatch

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

    by_view = state.ui_active_array_by_rep_by_view or {}
    new_by_view = {}
    by_view_changed = False
    # Track per-panel MR auto-activations so we can seed the realization
    # bucket in lockstep — without the idx, apply_color_array can't
    # resolve to a suffixed VTK array name.
    mr_seeds: dict = {}  # {panel_id: {array_path: default_idx}}
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
                if realization_dispatch.is_multirealization_property(tree, last_arr):
                    default_idx = realization_dispatch.default_realization_for(
                        state, tree, last_arr,
                    )
                    if default_idx is not None:
                        mr_seeds.setdefault(pid, {})[last_arr] = default_idx
            elif prev_arr_p in loaded_arrays_set:
                new_pmap[r_path] = prev_arr_p
            # else: SolidColor — omit entry.
        new_by_view[pid] = new_pmap
        if new_pmap != prev_pmap:
            by_view_changed = True

    # CRITICAL: the realization bucket MUST be written BEFORE the
    # active-array buckets (global + per-view) because their state.change
    # handlers (on_active_array_change, on_active_array_by_view_change)
    # read the realization bucket to resolve the suffixed VTK array name.
    # If the active-array writes fire first, the handlers see real_idx=None
    # for any new MR auto-activation and the rep stays in SolidColor.
    if mr_seeds:
        real_by_view = dict(state.ui_active_realization_by_array_by_view or {})
        real_changed = False
        for pid, seeds in mr_seeds.items():
            bucket = dict(real_by_view.get(pid, {}) or {})
            for array_path, idx in seeds.items():
                if bucket.get(array_path) is None:
                    bucket[array_path] = idx
                    real_changed = True
            real_by_view[pid] = bucket
        if real_changed:
            state.ui_active_realization_by_array_by_view = real_by_view

    if new_active != prev_active:
        state.ui_active_array_by_rep = new_active
    if by_view and by_view_changed:
        state.ui_active_array_by_rep_by_view = new_by_view
