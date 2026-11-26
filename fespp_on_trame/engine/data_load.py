"""Driver of the load-time pipeline.

`run(...)` is invoked whenever `state.fespp_data_selectors` changes
(from `Selector.select_node_*` in any of the three tabs). It:

  1. Pushes selectors to the active source (Collector or
     ETPConnector) and triggers a single UpdatePipeline so the
     resulting multiblock is materialised once.
  2. Without BlockScope, hides the parent multiblock representation;
     rendering happens through per-rep extracts only.
  3. Reserves a distinct chip color for every newly-loaded rep,
     BEFORE the registry sync so newly-created sources tint from
     `state.solid_color_by_rep` immediately.
  4. Syncs `SourceRegistry` (creates / drops ExtractBlock + IjkGrid
     instances; refreshes BlockSelectors on each IjkGrid).
  5. Bumps every source's pipeline info so freshly-added properties
     become visible to ColorBy.
  6. Maintains visibility tracking (`ui_loaded_rep_paths`,
     `ui_hidden_rep_paths`, per-view variants), marker tracking and
     data-array tracking (`ui_loaded_array_paths`,
     `ui_active_array_by_rep`, per-view variants) with the
     "newly-loaded array auto-becomes the rep's active one" rule.
  7. Tears down the per-view pipelines of deselected reps, hides the
     colour bars they leave orphaned, and builds the displays of the
     newly-loaded ones, all before any render.
  8. Re-runs the Activator, colours freshly loaded blocked wellbores
     from their grid and gives them the grid's threshold chain.
  9. Refreshes the threshold UI for the active grid.
 10. Mirrors the active IjkGrid's stored slicer/range state into
     the trame UI vars.
 11. Final Render and frame push.

The order of operations matters; see the per-step rationale below."""
import time

from paraview import simple as pvsimple

from fespp_on_trame.engine.utils.color_palette import color_for_index
from fespp_on_trame.engine import element_type
from fespp_on_trame.engine import view_routing


#: How long the reader's own pass took in the last `run`: the objects
#: read from the file or downloaded from the server, apart from the
#: redraw that follows. A stepped read (engine/progressive_load) sizes
#: its steps from the difference.
LAST_READ_SECONDS = 0.0
# the phases of the last run, [(breadcrumb, seconds since the one before)]
LAST_PHASES = []
# set by the stepped loader (app.boot) around a step that is not the last:
# the run then pushes one image, not two
INTERMEDIATE_STEP = False


def run(state, controller, server, view, tree, collector, etp_connector,
        source_registry,
        refresh_threshold_ui, push_active_ijk_state, frame=None):
    active_source = source_registry.provider
    if active_source is None:
        return

    # Breadcrumbs on the ETP path only: a native crash in the ETP selection
    # path kills the process before any Python traceback, so the last line
    # in etp_debug.log names the faulting step.
    if etp_connector.is_connected:
        from fespp_on_trame.engine.etp_debug import etp_debug as _trace
    else:
        _trace = lambda _m: None
    # the same breadcrumbs clock the run's phases (LAST_PHASES: what each
    # step of a stepped read costs beyond its own read — the stepped
    # loader's "[fespp] load: step of …" line names the costliest ones)
    phases, t_last = [], [time.monotonic()]

    def _dbg(message):
        now = time.monotonic()
        phases.append((message.replace("data_load: ", ""), now - t_last[0]))
        t_last[0] = now
        _trace(message)

    # SetPropertyWithName triggers ClearSelectors + AddSelector × N
    # on the C++ side; both are Modified()-only (no per-call Update())
    # to avoid N full pipeline executions per add. We trigger the
    # actual RequestData ONCE here so downstream code (set_node_id,
    # source_registry.sync) sees the freshly-loaded multiblock output.
    _dbg(f"data_load: selectors={list(state.fespp_data_selectors or [])}")
    active_source.push_selectors(state.fespp_data_selectors)
    _dbg("data_load: selectors pushed")
    t_read = time.monotonic()
    active_source.get_source().UpdatePipeline()
    global LAST_READ_SECONDS
    LAST_READ_SECONDS = time.monotonic() - t_read
    _dbg("data_load: pipeline updated")
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
        # FAMILY colour: a grid geometry and every BlockedWellbore of the
        # same GridContainer share ONE solid colour, anchored on the
        # GEOMETRY's rep_path. Whichever member loads first fixes it (a
        # blocked wellbore loading first also writes the anchor, so the
        # geometry arriving later reuses the family colour instead of
        # drawing a fresh one).
        family_anchor = None
        try:
            n_id2 = tree.find_node_id(r_path)
            kind2 = tree.find_type(n_id2) or ""
            if kind2 == "BlockedWellbore":
                cont = tree.find_parent_node_id_with_type(n_id2, "GridContainer")
                g_id = tree.find_representation_node(cont) if cont is not None else None
                family_anchor = tree.find_path(g_id) if g_id is not None else None
            elif kind2 in ("IjkGrid", "UnstructuredGrid"):
                family_anchor = r_path
        except Exception:
            family_anchor = None
        if family_anchor:
            fam_color = colors.get(family_anchor)
            if fam_color is None:
                fam_color = color_for_index(next_idx)
                next_idx += 1
                colors[family_anchor] = fam_color
            colors[r_path] = fam_color
        else:
            colors[r_path] = color_for_index(next_idx)
            next_idx += 1
    state._selector_rep_cache = sel_cache
    state.solid_color_by_rep = colors
    state.solid_color_next_idx = next_idx

    # Unified sync: drives BOTH the IjkGrid side (rep_path resolved
    # from each reservoir node id) and the ExtractBlock side
    # (rep_path resolved from each selector). Tears down anything
    # that left the selection; creates anything new.
    _dbg("data_load: colors assigned, syncing source registry")
    source_registry.sync(
        state.fespp_data_selectors,
        state.ui_select_node_reservoir or [],
    )
    _dbg("data_load: source registry synced")
    # The C++ side modifies partition data in place (addDataArray
    # for new property selectors, array swap for realization/time
    # changes). Sources cache their data information at the proxy
    # level: without a Modified() bump, GetCellDataInformation
    # returns a stale array list and the active handler cannot
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
    # pass the slicer keeps the output it cached at creation time (a
    # structurally valid `vtkExplicitStructuredGrid` with the right cell
    # count but no `CellData` arrays), so the activator's later
    # `_find_array_in_store` misses the property array even though it is
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
            slicer_sources.extend(ijk._src_volumes)
            for slc in slicer_sources:
                try:
                    slc.GetClientSideObject().Modified()
                    slc.UpdatePipelineInformation()
                    slc.UpdatePipeline()
                except Exception:
                    pass
        except Exception:
            pass

    _dbg("data_load: sources bumped, computing tracking")
    present_paths = set(p for p, _ in source_registry.items())

    _update_visibility_tracking(state, present_paths)
    last_array_for_rep, prev_loaded_set = _update_data_array_tracking(
        state, tree, present_paths,
    )
    _update_marker_tracking(state, tree, present_paths)
    _update_active_array_maps(state, tree, present_paths, last_array_for_rep, prev_loaded_set)

    # Set the FESPP source as active for ParaView dialogs that look
    # at it. No active_source.show() here: that would re-set the
    # parent rep's Visibility to 1 and undo the early hide above.
    pvsimple.SetActiveSource(active_source.get_source())
    server.controller.on_data_loaded()
    server.controller.on_active_proxy_change()

    if (not state.has_data_loaded_once) and (len(state.fespp_data_selectors) > 0):
        # Re-centre on the first load that actually MATERIALISES
        # geometry ("0 cells → ≥1 cell"). A selection whose data cannot
        # load (EPC imported without its H5: tree fine, geometry empty
        # + error message) must NOT consume the one-shot flag, else the
        # retry after the H5 upload renders off-centre with no reset.
        n_cells = 0
        try:
            info = active_source.get_source().GetDataInformation()
            n_cells = int(info.GetNumberOfCells() or 0)
        except Exception:
            n_cells = 0
        _dbg(f"data_load: first-load camera check n_cells={n_cells}")
        if n_cells > 0:
            # Reset the camera SYNCHRONOUSLY (pure server-side) so the
            # final render+push at the end of this run already carries
            # the framed camera. The sentinel path below resolves in a
            # LATER state flush (after this run's frame push) through
            # an async html-widget reset, so on its own the client would
            # keep the empty-scene default camera (pos z≈6.7 at origin)
            # until the next manual interaction.
            # The sentinel is still set: on_view_reset_camera also
            # refreshes per-block visibility and re-syncs the client.
            # `frame(view)` is the app's framing: it leaves the camera where
            # it stands when nothing is visible yet (app/views/camera)
            try:
                if frame is not None:
                    frame(view)
                else:
                    pvsimple.ResetCamera(view)
                    view.CenterOfRotation = list(view.CameraFocalPoint)
            except Exception:
                pass
            state.view_reset_camera = True
            state.has_data_loaded_once = True

    _dbg("data_load: colors re-applied")
    try:
        refresh_threshold_ui()
    except Exception:
        pass
    try:
        push_active_ijk_state()
    except Exception:
        pass

    state.view_update = True
    # Reliable client refresh: render the (possibly empty) scene and push a
    # fresh frame to the client. Render UNCONDITIONALLY: an empty selection
    # must repaint the empty scene so an unload clears without a manual view
    # interaction. Push TWICE: a just-created representation's mapper is
    # realised on the first StillRender and only appears in the image grabbed
    # by the second.
    _dbg("data_load: rendering")
    try:
        pvsimple.Render(view=view)
        push = getattr(server.controller, "view_update_all", None) or getattr(server.controller, "view_update", None)
        if push is not None:
            push()
            # … unless this is a step of a stepped read with another step
            # to come, which draws again anyway: the second push there only
            # cost (measured 12/10: a third of the step's final render)
            if not INTERMEDIATE_STEP:
                push()
    except Exception:
        pass
    _dbg("data_load: done")
    global LAST_PHASES
    LAST_PHASES = phases


def _update_visibility_tracking(state, present_paths):
    """Maintain `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, and the
    per-view `ui_hidden_rep_paths_by_view` map.

    Visibility tracking: newly-loaded reps default to visible (eye
    open); reps that were hidden but stayed loaded keep their hidden
    state; reps no longer present are dropped from the hidden set so
    they don't ghost-hide on a future re-load.

    (A grid GEOMETRY loading while one of its blocked wellbores is
    already present is hidden right after this tracking pass; see the
    born-hidden block in run().)"""
    # Capture the previous loaded set *before* mutating the state
    # var, to detect which reps are brand-new in this run.
    prev_loaded = set(state.ui_loaded_rep_paths or [])
    loaded_sorted = sorted(present_paths)
    if list(state.ui_loaded_rep_paths or []) != loaded_sorted:
        state.ui_loaded_rep_paths = loaded_sorted
    new_reps = [p for p in present_paths if p not in prev_loaded]

    prev_hidden = list(state.ui_hidden_rep_paths or [])
    kept_hidden = [p for p in prev_hidden if p in present_paths]
    if kept_hidden != prev_hidden:
        state.ui_hidden_rep_paths = kept_hidden
    # Same prune for every per-view bucket: unloaded reps must not
    # ghost-hide on a future reload, in any panel. Also extend the
    # buckets of *non-active* panels with any rep newly loaded in this
    # run, since ParaView only adds the new display to the active view:
    # other panels have not had Show() called on the new source, so
    # their chips appear closed (rep present but not yet shown there).
    by_view = state.ui_hidden_rep_paths_by_view or {}
    if not by_view:
        return
    updated = {}
    changed = False
    present = set(present_paths)
    # The "visible by default" panel must be a RENDER panel: with the
    # Statistics tab focused, fespp_active_panel_id points at
    # a non-render panel, no bucket matches it, and a bulk load would
    # arrive hidden in EVERY view.
    active_panel_id = view_routing.resolve_active_render_panel(state)
    for pid, paths in by_view.items():
        old = list(paths or [])
        # 1. Drop unloaded reps.
        new = [p for p in old if p in present]
        # 2. For non-active panels, append newly-loaded reps that
        #    are not already in the bucket. The active panel keeps
        #    the new rep as "visible" (chip open), EXCEPT born-hidden
        #    geometries, hidden in the active panel too.
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
    active_pid = view_routing.resolve_active_render_panel(state)
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
    # Also report the markers that LEFT the loaded set this run: the
    # caller must set_marker_visible(False) on their extractors. The
    # state prune above does not touch the proxies, so otherwise a
    # deselected marker's glyph keeps rendering until its whole frame
    # unloads.
    removed = [m for m in prev_loaded if m not in loaded_set]
    return newly_loaded, removed


def _update_active_array_maps(state, tree, present_paths, last_array_for_rep, prev_loaded_set):
    """Recompute `ui_active_array_by_rep` (global) and
    `ui_active_array_by_rep_by_view` (per-panel).

    Rules for the per-panel map:
      - Newly-loaded array (= last_arr ∉ prev_loaded_set) auto-becomes
        the rep's active one in **only the currently-active panel**.
        Other panels keep their previous eye state untouched: a load
        affects just the focused panel, not every replicated view at
        once.
      - Otherwise keep the panel's prior choice if its array is still
        loaded.
      - Otherwise leave the rep in SolidColor (no entry). Respects
        explicit deactivation by the user.

    The global `ui_active_array_by_rep` mirrors the active panel's
    bucket via the same rule, so the consumers of the global map
    (Activator, solid_color_panel) read a coherent value.

    MR properties carry an extra hook: when auto-activated, the
    panel's realization bucket
    (`ui_active_realization_by_array_by_view`) is seeded with the
    smallest available index; otherwise the resolver cannot find any
    array name (only suffixed `<title>_real_<idx>` arrays exist) and
    the rep stays in SolidColor on first load."""
    from fespp_on_trame.engine import realization_dispatch

    active_panel_id = view_routing.resolve_active_render_panel(state) or None
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
    # Track per-panel MR auto-activations to seed the realization bucket
    # in lockstep: without the idx, apply_color_array cannot resolve to a
    # suffixed VTK array name.
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
