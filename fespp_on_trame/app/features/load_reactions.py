"""What a load sets off: the ticked paths (`fespp_data_selectors`) read
GLOBALLY and synced to every view's scene, the first frame of each
view, the cards and the Globe refreshed; the loaded arrays and reps
followed by the weights and the views where a rep is born visible.

(Moved out of app/boot, overhaul slice 10.)"""
import time
from paraview import simple as pvsimple
from fespp_on_trame.engine import data_load
from fespp_on_trame.engine import memory
from fespp_on_trame.engine import view_routing
from fespp_on_trame.engine.vtk_log import capture_vtk_messages
from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.app.views.camera import reset_camera_centered


def register(core, *, _detect_crs, _frame_first, _globe_refresh_marks,
             _globe_scene, _panel_reads, _progressive, _push_globe_state,
             _push_slicer_state, _push_threshold_state,
             _rep_path_of, view):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    server = core.server
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    collector = core.collector
    etp_connector = core.etp_connector
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    selector = core.selector
    scheduler = core.scheduler
    eyes = core.eyes
    _mv = core.mv
    selection = core.selection
    def _give_memory_back():
        """An unload ended: what it freed goes back to the system, now and
        once the views have let go of what they drew (engine/memory)."""
        import asyncio
        import sys

        def _now(when):
            before, after = memory.give_back()
            if before is not None and after is not None and before - after >= 16:
                print(f"[fespp] memory: {before:.0f} -> {after:.0f} MiB given back {when}",
                      file=sys.stderr, flush=True)

        _now("after the unload")
        try:
            asyncio.get_event_loop().call_later(3.0, _now, "once the views followed")
        except RuntimeError as exc:
            print(f"[fespp] memory: no second pass ({exc})", file=sys.stderr, flush=True)

    @state.change("fespp_data_selectors")
    def _on_selectors(**_):
        # selected_paths (session-global) -> fespp_data_selectors -> load the reps
        # GLOBALLY (data_load.run + scene_registry.sync builds one RepInScene per
        # view), then ONE render + frame-push per view via the scheduler. First
        # data frames each view's camera once (per_view_state.FRAMED — don't
        # fight later toggles); the push avoids the remote "needs one click"
        # quirk.
        import sys
        try:
            server.context.load_generation += 1  # invalidates stale debounces
            # the weights the statistics use are built from the porosity and
            # net-to-gross loaded at this moment: drop them, the loaded set is
            # about to change. The cell geometry underneath stays — a grid's
            # cells do not change when a property is ticked beside them, and
            # reading them takes seconds on a large grid.
            from fespp_on_trame.engine import cell_weights as _cw
            _cw.clear()
            # A pick is a set of (block, cell index) pairs into the PDC that
            # is about to be rebuilt: the same indices would then point at
            # DIFFERENT cells. Drop them rather than aim the camera at a
            # ghost. The gate is cleared for EVERY view, not just the ones
            # in _last_pick, so the button can never outlive its target
            # however the two got out of step.
            _mv0 = _mv()
            selection.forget_picks()
            for _vid in (_mv0.view_ids() if _mv0 is not None else []):
                state[f"ui_nav_has_pick__{_vid}"] = False
            mv = _mv()
            active = pvsimple.GetActiveView() or view
            # The active source may have flipped since the scenes were built
            # (ETP connect after panel creation): re-point their clones first,
            # or every per-view extractor pulls from the stale (empty) source.
            core.view_resources.rebind_clone_inputs()
            print("[fespp] load: start", file=sys.stderr, flush=True)
            # loading overlay: pushed to the client BEFORE the (synchronous)
            # load so it actually shows while the server is busy. The veil
            # counts what CHANGES against the previous selection: unticking
            # one item of twelve is not "loading 11 items"
            n_sel = len(state.fespp_data_selectors or [])
            delta = n_sel - _sel_count["n"]
            _sel_count["n"] = n_sel
            if delta > 0:
                state.view_loading_message = (
                    f"Loading {delta} checked item{'s' if delta != 1 else ''}…")
            elif delta < 0:
                state.view_loading_message = (
                    f"Unloading {-delta} item{'s' if delta != -1 else ''}…")
            else:
                state.view_loading_message = "Updating the selection…"
            # a step of a stepped read goes without the veil: the pill at
            # the bottom says how far the read is, and the view shows what
            # arrives (a veil on and off at every step would flicker)
            if not _progressive["stepping"]:
                state.ui_loading = True
            state.flush()
            load_error_before = state.load_error
            t_sel = time.monotonic()
            try:
                with capture_vtk_messages(state) as load_msgs:
                    data_load.run(
                        state, controller, server, active,
                        tree, collector, etp_connector,
                        source_registry,
                        refresh_threshold_ui=lambda: None,
                        push_active_ijk_state=lambda: None,
                        frame=reset_camera_centered,
                    )
            finally:
                state.ui_loading = False
                # the end of the load and its length: a selection that
                # never ends is told apart from one that ends slowly
                print(f"[fespp] load: {n_sel} selected ({delta:+d}), "
                      f"{time.monotonic() - t_sel:.1f} s (reader "
                      f"{data_load.LAST_READ_SECONDS:.1f} s)", file=sys.stderr, flush=True)
                if delta < 0:
                    _give_memory_back()
            # A property ticked without its .h5 (or whose dataset fesapi
            # cannot open) LOGS its failure and stays ticked with an empty
            # view: the reader's line names the uuid, the snackbar names
            # the property, the missing file and the next step. An
            # unreadable RENDER is reported by vtk_log._flag_invalid_nodes
            # already (it wrote load_error inside the capture): not twice.
            from fespp_on_trame.engine.io import read_report
            from fespp_on_trame.engine.io.temp_dir import temp_dir

            def _title_for_uuid(uuid):
                try:
                    nid = tree._data_assembly.FindFirstNodeWithName("_" + uuid)
                except Exception:
                    nid = -1
                return (tree.find_title(nid) or "") if nid is not None \
                    and nid >= 0 else ""

            unreadable = read_report.property_note(
                read_report.unreadable_properties(
                    load_msgs, _title_for_uuid, temp_dir))
            if unreadable and state.load_error == load_error_before:
                state.load_error = unreadable
                state.dirty("load_error")   # the same text again re-opens
            # An object whose points all sit at one place (a store that
            # served zero coordinates: Volve_SGrid from ADME, 13/10) loads
            # and draws nothing: said once per object, with why the camera
            # did not move (camera.py refuses to frame on no extent)
            try:
                from fespp_on_trame.engine import extent as _extent
                flat = _extent.no_extent_paths(
                    active_data_source.get_source().GetClientSideObject().GetOutputDataObject(0),
                    list(state.fespp_data_selectors or []))
                # said once per SELECTION of the object: unticking it forgets it,
                # so ticking it again says it again (the health table, cumulative,
                # keeps one line per object)
                _flat_said.intersection_update(set(state.fespp_data_selectors or []))
                fresh = [(p, t) for p, t in flat if p not in _flat_said]
                if fresh:
                    _flat_said.update(p for p, _t in fresh)
                    # a data-health finding, counted on the Health button
                    empty = dict(getattr(state, "ui_empty_geometry", None) or {})
                    empty.update({p: t for p, t in fresh})
                    state.ui_empty_geometry = empty
                    print("[fespp] load: no extent:", ", ".join(t for _p, t in fresh),
                          file=sys.stderr, flush=True)
                    if state.load_error == load_error_before:
                        state.load_error = _extent.note([t for _p, t in fresh])
                        state.dirty("load_error")
            except Exception as exc:
                print("[fespp] load: extent check error:", exc, file=sys.stderr, flush=True)
            loaded = state.ui_loaded_rep_paths or []
            from fespp_on_trame.engine.etp_debug import etp_debug as _edbg, enabled as _edbg_enabled
            _edbg_on = _edbg_enabled()
            _edbg(f"post-load: loaded={list(loaded)} views={mv.view_ids() if mv else []} "
                  f"FRAMED={sorted(per_view_state.FRAMED)}")
            # The eyes born OPEN at a tick are server-authored: the widget never
            # writes an eye at check time, because its full-list
            # snapshot would race the born-visible append and clobber it (a
            # late client write would wipe the geometry from the eye var).
            # The server opens the eye of each NEWLY ticked row here,
            # post load, then dispatches the eye reconcile directly — the
            # ui_loaded_rep_paths watcher does NOT fire when a property
            # loads onto an already-loaded rep, nor when a rep is ticked
            # again under a container that kept it read (unchanged list).
            try:
                sel_set = set(state.selected_paths or [])
                # Unchecked paths lose their eye (the widget writes no
                # eye at all — the server owns the set).
                for vid in (mv.view_ids() if mv is not None else []):
                    ev = f"visible_paths__{vid}"
                    cur = list(getattr(state, ev, None) or [])
                    kept = [p for p in cur if p in sel_set]
                    if len(kept) != len(cur):
                        state[ev] = kept
                # every ticked row of an object: a property, and its
                # representation too. Never a row that only holds others (a
                # wellbore, one of its folders): shown, it would draw
                # everything under it, whatever the eyes of those rows say
                ticked = [p for p in (state.selected_paths or []) if _rep_path_of(p)]
                # ...except what a PANEL's tree asked to read: born
                # hidden, its eye is the door (`_panel_reads`)
                new_ticked = [p for p in ticked
                              if p not in _seen_ticked["set"]
                              and p not in _panel_reads]
                _seen_ticked["set"] = set(ticked)
                active_vid = _born_visible_vid()
                # Wellhead companions (flagpole 'A' + billboard well
                # name at the MD datum) for every checked Trajectory —
                # this path never runs the per-tab selector, so
                # nothing else adds the heads and labels. Incremental
                # sync; their visibility follows the trajectory's eye in
                # on_eye_changed.
                traj_ids = []
                for p in (state.selected_paths or []):
                    nid = tree.find_node_id(p)
                    if nid is not None and tree.find_type(nid) == "Trajectory":
                        traj_ids.append(nid)
                # heads are Text reps at projected coordinates: never
                # in a Globe view (ECEF) — the first plain view instead.
                # Only the heads: the load's eyes are born in the view it
                # was asked from, a Globe included (04-verification D28)
                heads_vid = active_vid
                if mv is not None and mv.kind_of(heads_vid) == "globe":
                    heads_vid = next(
                        (v for v in mv.view_ids() if mv.kind_of(v) != "globe"), "")
                pvv0 = (mv.get_pv_view(heads_vid)
                        if (mv is not None and heads_vid) else None)
                selector.sync_wellheads(traj_ids, view=pvv0 or active,
                                        view_id=heads_vid)
                if new_ticked and active_vid:
                    ev = f"visible_paths__{active_vid}"
                    cur = list(getattr(state, ev, None) or [])
                    fresh = [p for p in new_ticked if p not in cur]
                    if fresh:
                        state[ev] = cur + fresh
                for vid in (mv.view_ids() if mv is not None else []):
                    try:
                        controller.on_eye_changed(vid, list(
                            getattr(state, f"visible_paths__{vid}",
                                    None) or []))
                    except Exception as exc2:
                        print(f"[fespp] eye dispatch error ({vid}):",
                              exc2, flush=True)
                # a read changed the world under the eyes: the watcher's
                # pass at the end of this flush still runs (app/scene/eyes)
                eyes.invalidate()
            except Exception as exc2:
                print("[fespp] born-open arrays error:", exc2, flush=True)
            for vid in (mv.view_ids() if mv is not None else []):
                pvv = mv.get_pv_view(vid)
                if pvv is None:
                    continue
                # the trace below costs a GetDataInformation() per visible
                # representation (a round trip each, on the load path): built
                # only when the ETP trace is on, which is where it is read
                if _edbg_on:
                    try:
                        n_reps = len(pvv.Representations)
                        n_vis = sum(1 for r in pvv.Representations
                                    if getattr(r, "Visibility", 0))
                        _edbg(f"post-load: view {vid} reps={n_reps} visible={n_vis} "
                              f"cam={[round(c, 1) for c in pvv.CameraPosition]}")
                        for r in pvv.Representations:
                            if not getattr(r, "Visibility", 0):
                                continue
                            # scalar-bar widgets sit in the same list, without Input
                            inp = getattr(r, "Input", None)
                            if inp is None:
                                continue
                            try:
                                di = inp.GetDataInformation()
                                _edbg(f"    visible in {vid}: input="
                                      f"{inp.SMProxy.GetLogNameOrDefault()} "
                                      f"cells={di.GetNumberOfCells()} "
                                      f"bounds={[round(b, 1) for b in di.GetBounds()]}")
                            except Exception as exc:
                                _edbg(f"    visible in {vid}: introspect failed {exc}")
                    except Exception as exc:
                        _edbg(f"post-load: view {vid} introspect failed {exc}")
                scheduler.mark_dirty(vid)
            try:
                bv = sum(1 for r in view.Representations
                         if getattr(r, "Visibility", 0))
                _edbg(f"post-load: BOOT view reps={len(view.Representations)} "
                      f"visible={bv}")
            except Exception:
                pass
            scheduler.flush()
        except Exception as exc:
            print("[fespp] data_load error:", exc, file=sys.stderr, flush=True)

    # Baseline for the born-visible reps (new-since-last-load delta).
    _prev_loaded_reps = {"set": set()}
    # Baseline for the eyes born open at a tick (the rows ticked at the last load).
    _seen_ticked = {"set": set()}
    # How many selectors the previous load had: the veil names the delta.
    _sel_count = {"n": 0}
    # The ticked paths already said to have no extent (every point at one
    # place): the note names each object once.
    _flat_said = set()

    def _born_visible_vid():
        """The 3D view a data-tree load is born visible in: the active
        panel when it is a 3D view, otherwise the 3D view the user last
        worked in, else the first one — never a panel of another kind
        (Statistics, the well-log), whose id names an eye set no
        3D view reads: written there, a load would show nothing anywhere
        and its eye would stay closed under a note saying otherwise. Empty
        when no 3D view is open."""
        mv0 = _mv()
        vids = list(mv0.view_ids()) if mv0 is not None else []
        vid = view_routing.resolve_active_render_panel(state)
        return vid if vid in vids else ""

    @state.change("ui_loaded_array_paths")
    def _on_loaded_arrays_weights(**_):
        # The pore-volume weight is built from a porosity and a net-to-gross
        # PROPERTY, so an array arriving or leaving changes what a cell is
        # worth. The selector watcher above clears before the load runs, and
        # a weight read in between would cache a grid as having no porosity
        # for the rest of the session; this is the signal that says what is
        # actually loaded.
        from fespp_on_trame.engine import cell_weights as _cw
        _cw.clear()

    @state.change("ui_loaded_rep_paths")
    def _on_loaded_reps(ui_loaded_rep_paths=None, **_):
        loaded = list(ui_loaded_rep_paths or [])
        # a rep loaded or unloaded changes which cells exist: the cached
        # weights of engine/cell_weights go with them
        from fespp_on_trame.engine import cell_weights as _cw
        _cw.clear()
        # BlockScope: a rep is a selector string — refresh the index once
        # per Selectors commit, prune each view's desired-state table to
        # the loaded set and re-project. The per-rep eager extraction
        # (scene_registry.sync_loaded_reps -> _eager_setup_rep_in_scene)
        # is skipped entirely on this path. data_load.run does run
        # source_registry.sync (one ExtractBlock per rep, O(N) at load),
        # because _on_col's colour path resolves through it.
        try:
            ctx.assembly_index.refresh()
        except Exception as exc:
            print("[fespp] assembly index refresh error:", exc, flush=True)
        selectors = {rp
                     for rp in loaded}
        # NEW reps only (the delta since the last load): what is born
        # visible below. No rule closes a grid's geometry eye when a
        # BlockedWellbore or a wellbore arrives with it: the view would
        # hide the grid while the tree shows its eye open, and the
        # crosshair ray would meet the wells' tubes and nothing else. A
        # user who wants the grid out of the way closes its eye.
        new_reps = [rp for rp in loaded
                    if rp not in _prev_loaded_reps["set"]]
        _prev_loaded_reps["set"] = set(loaded)

        # Born visible in the active 3D view: append newly loaded rep
        # paths to that view's eye var — the tree widget AND the eye
        # handler both read it (single source of truth), so the eyes
        # drive set_visible and the chips can't diverge from the render.
        active_vid = _born_visible_vid()
        if active_vid and loaded:
            eye_var = f"visible_paths__{active_vid}"
            cur = list(getattr(state, eye_var, None) or [])
            # NEW reps only — appending the full loaded list would
            # re-open, on each later load, every eye the user closed. And
            # not a rep a PANEL's read pulled in: born hidden
            # (`_panel_reads`).
            fresh = [rp for rp in new_reps
                     if rp not in cur and rp not in _panel_reads]
            if fresh:
                state[eye_var] = cur + fresh
        mv0 = _mv()
        all_vids = list(mv0.view_ids()) if mv0 is not None else []
        # The eye vars just changed SERVER-side: the @state.change
        # cascade back into on_eye_changed is not reliable mid-flush (a
        # first load could leave the geometry hidden while its chip shows
        # open) — dispatch the eye reconcile directly. Idempotent if the
        # cascade fires too.
        for vid in all_vids:
            try:
                controller.on_eye_changed(vid, list(
                    getattr(state, f"visible_paths__{vid}", None)
                    or []))
            except Exception as exc:
                print(f"[fespp] eye dispatch error ({vid}):", exc,
                      flush=True)
        # a read changed the world under the eyes: the watcher's pass at
        # the end of this flush still runs (app/scene/eyes)
        eyes.invalidate()
        # Family solid colours (geometry + its BWs share one colour,
        # anchored on the geometry) — projected as BlockColors. data_load
        # assigns them into solid_color_by_rep (#RRGGBBAA hex).
        def _solid_rgb_for(rp):
            hexv = (state.solid_color_by_rep or {}).get(rp) or ""
            hexv = hexv.lstrip("#")
            if len(hexv) >= 6:
                try:
                    return tuple(int(hexv[i:i + 2], 16) / 255.0
                                 for i in (0, 2, 4))
                except ValueError:
                    return None
            return None

        for vid, scene in (getattr(ctx, "blockscope_scenes", None) or {}).items():
            try:
                scene.prune(selectors)
                # its per-view isolate goes with it: crops kept alive
                # against an absent block are what the composite would
                # otherwise keep subtracting — and render
                gone = [k for k in list(getattr(ctx, "grid_isolates", {}) or {})
                        if k[0] == vid and k[1] not in selectors]
                for k in gone:
                    iso = ctx.grid_isolates.pop(k)
                    ctx.grid_hide_nan.pop(k, None)
                    try:
                        iso.set_node_id(None)
                    except Exception:
                        pass
                if gone:
                    _push_slicer_state(vid)
                    _push_threshold_state(vid, None)
                for sel in selectors:
                    entry = scene.ensure_entry(sel)  # visible stays eye-driven
                    rgb = _solid_rgb_for(sel)
                    if rgb is not None:
                        entry.solid_rgb = rgb
                if _globe_scene(vid) is not None and not scene.epsg:
                    # a Globe opened before any data: read the CRS now
                    crs = _detect_crs()
                    if crs:
                        scene.set_epsg(crs["epsg"])
                scene.reconcile()
                _globe_refresh_marks(vid)
                _push_globe_state(vid)
                scheduler.mark_dirty(vid)
                # First-load framing, AFTER the reconcile that actually
                # makes blocks visible (the _on_selectors loop is skipped
                # under blockscope for exactly this ordering reason).
                if (scene.shown_selectors()
                        and vid not in per_view_state.FRAMED):
                    try:
                        if _frame_first(vid):
                            per_view_state.FRAMED.add(vid)
                    except Exception:
                        pass
            except Exception as exc:
                print(f"[fespp] blockscope reconcile error ({vid}):", exc,
                      flush=True)
        scheduler.flush()
        return

    # Headless visual-test hook — inert unless FESPP_SCENARIO is set (see
    # tests/visual/runner/scenario.py and tests/visual/).
