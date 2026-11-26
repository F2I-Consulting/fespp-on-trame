"""Per-view thresholds — the chain lives on the view's GridIsolate
(rep_data -> Threshold proxies, threshold_chain reused verbatim); the
composite swaps the grid block out while active.

(Moved out of app/boot, overhaul slice 10.)"""
import time
from paraview import simple as pvsimple
from fespp_on_trame.engine.state_defaults import z_scale_of


def register(core, *, _axes_grid_scale, _display_title, _ensure_isolate,
             _nav_blocked, _push_grid_targets, _pv_view_of, _rep_path_of,
             _settle_isolate, _threshold_isolate, _threshold_target,
             occupancy):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_push_threshold_note, _push_threshold_state, _say_took)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    selector = core.selector
    scheduler = core.scheduler
    batcher = core.batcher
    displays = core.displays
    _mv = core.mv
    # Per-view thresholds — the chain lives on the view's GridIsolate
    # (rep_data -> Threshold proxies, threshold_chain reused verbatim); the
    # composite swaps the grid block out while active.
    def _vtk_backend():
        """Which SMP backend the filters ran on, for the timing lines below.

        A duration alone means nothing: the same threshold runs several times
        faster on twelve threads than on one. So every timing line carries
        the backend it was taken on, and two logs cannot be compared by
        mistake.

        Read every time, never cached: a scenario may flip the backend
        mid-run to time the same gesture both ways, and a cached tag would
        label the second timing with the first one's backend."""
        try:
            from vtkmodules.vtkCommonCore import vtkSMPTools
            return (f"{vtkSMPTools.GetBackend()}"
                    f"/{vtkSMPTools.GetEstimatedNumberOfThreads()}")
        except Exception as exc:
            print("[fespp] VTK backend unreadable:", exc, flush=True)
            return "?"

    def _say_took(what, t0, detail=""):
        print(f"[fespp] {what}: {(time.perf_counter() - t0) * 1000:.0f} ms"
              f"{' ' + detail if detail else ''} — VTK {_vtk_backend()}",
              flush=True)

    def _push_threshold_state(view_id, iso):
        state[f"ui_thresholds__{view_id}"] = (
            list(iso.get_chain() or []) if iso is not None else [])
        # the Property slicer's card shows the chain (app/features/property_slicer)
        publish = getattr(ctx, "property_card_publish", None)
        if publish is not None:
            publish(view_id)
        core.lifecycle.emit("view_cuts", vid=view_id)

    def _push_threshold_note(view_id, path=None, rep_path=None):
        """Why the Thresholds card of this view cannot add an entry right
        now, or "" when it can. The chain acts on the view's thresholdable
        representation (`_threshold_target` — an IJK grid, an unstructured
        grid or a sub-representation), while the arrays the card lists are
        the ACTIVE node's: on another object they would name arrays that one
        does not have, and the add would do nothing."""
        if path is None:
            path = getattr(state, f"active_path__{view_id}", None) or ""
            rep_path = _rep_path_of(path) if path else ""
        grid_path = _threshold_target(view_id)[0]
        if not grid_path:
            note = ("Thresholds act on a grid, a surface, a polyline or a"
                    " point set — none is loaded in this view.")
        elif rep_path == grid_path:
            note = ""
        else:
            grid = _display_title(grid_path, "the grid")
            if path:
                note = (f"Thresholds act on {grid} — "
                        f"{_display_title(path, 'the active object')} is not"
                        " it. Click the grid, or one of its properties, in"
                        " the tree.")
            else:
                note = (f"Thresholds act on {grid}: click it, or one of its"
                        " properties, in the tree to list its arrays.")
        state[f"ui_thresholds_note__{view_id}"] = note
        _push_grid_targets(view_id)

    @controller.set("threshold_add")
    def threshold_add(payload, view_id):
        """`[array, parent]`: parent None = a new ROOT (its cells join the
        other roots', a union), an entry name = chained under it (its cells
        must also pass that one, an intersection). A bare array name chains
        under the last entry."""
        try:
            iso, _sel, _scene = _ensure_isolate(view_id, _threshold_target(view_id))
            if iso is None:
                return
            chain = iso.get_chain() or []
            if isinstance(payload, (list, tuple)):
                array_name = payload[0] if payload else None
                parent = payload[1] if len(payload) > 1 else None
                if parent is not None and not any(e.get("name") == parent for e in chain):
                    parent = None
            else:
                array_name = payload
                parent = chain[-1]["name"] if chain else None
            if not array_name:
                return
            t0 = time.perf_counter()
            iso.add_threshold(parent, array_name)
            occupancy.settle(view_id, iso.rep_path)
            _push_threshold_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
            # AFTER the flush, never before: VTK pipelines are lazy, so a
            # timer closed on `set_range` alone reads 0 ms and says the work
            # was free when it has simply not happened yet. What is timed
            # here is what the reader waits for — the filter AND the frame.
            _say_took("threshold add", t0, f"({array_name})")
        except Exception as exc:
            print(f"[fespp] threshold_add error ({view_id}):", exc, flush=True)

    @controller.set("threshold_remove")
    def threshold_remove(name, view_id):
        try:
            iso, sel, scene = _threshold_isolate(view_id)
            if iso is None:
                return
            iso.delete_threshold(name)
            occupancy.settle(view_id, iso.rep_path)
            _push_threshold_state(view_id, iso)
            # nothing left for the isolate to show (no chain, full mode, no
            # NaN mask): the composite paints the block again; the slicer
            # state stays for a Slice on
            _settle_isolate(view_id, iso.rep_path, sel, scene)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] threshold_remove error ({view_id}):", exc, flush=True)

    @controller.set("threshold_range")
    def threshold_range(payload, view_id):
        try:
            iso, _sel, _scene = _threshold_isolate(view_id)
            if iso is None:
                return
            name, rng = payload
            # Not timed here: `set_range` only writes the property and
            # `scheduler.flush()` schedules a frame rather than drawing one,
            # so a timer around this would read 0 ms whatever the grid and
            # suggest the work is free. The cost of a range change lands in
            # the next frame, and that is where it would have to be measured.
            iso.set_range(name, float(rng[0]), float(rng[1]))
            _push_threshold_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] threshold_range error ({view_id}):", exc, flush=True)

    @controller.set("threshold_visible")
    def threshold_visible(payload, view_id):
        try:
            iso, _sel, _scene = _threshold_isolate(view_id)
            if iso is None:
                return
            name, vis = payload
            iso.set_visible(name, bool(vis))
            occupancy.settle(view_id, iso.rep_path)
            _push_threshold_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] threshold_visible error ({view_id}):", exc, flush=True)

    def _apply_zscale(z, vid):
        """The vertical exaggeration of 3D view `vid`, at once: its composite
        (main_rep.Scale), its wellheads, its camera and axes grid, and
        everything it draws outside the composite (app/scene/displays)."""
        before = z_scale_of(state, vid)
        state[f"ui_scale_z__{vid}"] = z
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is not None:
            try:
                scene.set_zscale(z)
            except Exception as exc:
                print(f"[fespp] zscale error ({vid}):", exc, flush=True)
        # Wellheads are Text reps with absolute anchors — they can't ride
        # the rep Scale, re-anchor them explicitly.
        selector.apply_z_scale(z, vid)
        from fespp_on_trame.app.views import camera as _camera
        # the camera and the pivot follow the data they were on, or the scene
        # slides out of the frame; a Globe view has its own (radial)
        # exaggeration and an Earth-centred camera
        if z > 0 and not _nav_blocked(vid):
            try:
                _camera.follow_z_scale(_pv_view_of(vid), z / before)
            except Exception as exc:
                print(f"[fespp] zscale camera ({vid}):", exc, flush=True)
        # the axes grid keeps reading true depths
        if getattr(state, f"ui_nav_axes_grid__{vid}", False):
            pvv = _pv_view_of(vid)
            if pvv is not None:
                _axes_grid_scale(pvv, vid)
        # everything drawn outside the composite: isolates (their threshold
        # tips included), extracts and their copies, formulas, overlays,
        # contact planes, wellheads (app/scene/displays)
        displays.set_zscale(z, vid)
        scheduler.mark_dirty(vid)

    def _zscale_views(view_id):
        """The view named and those its camera is linked with (one camera,
        one exaggeration), or every 3D view (a document's session-wide value,
        a script)."""
        if not view_id:
            mv = _mv()
            return [str(v) for v in (mv.view_ids() if mv is not None else [])]
        links = getattr(state, "view_links", None) or {}
        group, todo = [], [str(view_id)]
        while todo:
            vid = todo.pop()
            if vid not in group:
                group.append(vid)
                todo.extend(str(o) for o in links.get(vid) or ())
        return group

    @controller.set("set_zscale_now")
    def set_zscale_now(value, view_id=None):
        """The exaggeration applied NOW, not after the slider's debounce: a
        session restore needs it before a view draws anything again, or a
        reused view keeps the old one on its grid while the slider shows the
        new (04-verification D25). Rounded as the view's field shows it, no
        image between two views: linked, they share a camera."""
        try:
            z = round(float(value), 2)
        except (TypeError, ValueError) as exc:
            print(f"[fespp] exaggeration refused: {value!r} ({exc})", flush=True)
            return
        if not 0.01 <= z <= 100:
            print(f"[fespp] exaggeration refused: {z} is not between 0.01 and 100", flush=True)
            return
        views = _zscale_views(view_id)
        if not views:
            ctx.zscale_no_view = z
            return
        for vid in views:
            _apply_zscale(z, vid)
        pins = getattr(ctx, "time_depth_pins_refresh", None)
        for vid in views:
            if pins is not None:
                pins(vid)
        scheduler.flush()

    @controller.set("set_zscale")
    def set_zscale(value, view_id=None):
        # the view's slider: one commit per burst (debounced)
        batcher.schedule(f"zscale:{view_id or ''}", lambda: set_zscale_now(value, view_id))

    # camera reset for ptc.ResetCameraButtons — resets the ACTIVE view (click a
    # view to make it active) + pushes a frame to every view.
    @controller.set("view_reset_camera")
    def view_reset_camera(*_a, **_k):
        av = pvsimple.GetActiveView()
        if av is not None:
            try:
                from fespp_on_trame.app.views.camera import reset_camera_centered
                reset_camera_centered(av)
                pvsimple.Render(view=av)
            except Exception:
                pass
        controller.view_update_all()
    return (_push_threshold_note, _push_threshold_state, _say_took)
