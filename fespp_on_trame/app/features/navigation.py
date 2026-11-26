"""3D navigation
A frustum pick can carry hundreds of thousands of cells; walking each
one through GetCell() to build a box is pointless past a few thousand
(the extra cells cannot widen the box much, and each GetCell allocates).

(Moved out of app/boot, overhaul slice 10.)"""
import asyncio
import os
import time
from fespp_on_trame.engine import stats_dispatch
from fespp_on_trame.engine.state_defaults import z_scale_of


def register(core, *, _blocks_for_rep, _cmap_array_path, _derived_fanout,
             _display_title, _globe_scene, _hl_state,
             _ids_to_source, _is_property_path, _leaf_dataset,
             _nothing_under, _path_for_flat_index,
             _pick_region, _refresh_calculator,
             _rep_path_of, _row_of_rep,
             _selection_ids, _surface_fallback,
             _xml_open_from_path):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_axes_grid_scale, _axes_grid_titles, _nav_blocked, _nav_note, _pv_view_of, _rep_bounds)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    scheduler = core.scheduler
    lifecycle = core.lifecycle
    notifier = core.notifier
    _mv = core.mv
    _last_pick = core.selection.last_pick
    selection = core.selection
    # --- 3D navigation -------------------------------------------------
    # A frustum pick can carry hundreds of thousands of cells; walking each
    # one through GetCell() to build a box is pointless past a few thousand
    # (the extra cells cannot widen the box much, and each GetCell allocates).
    _BOUNDS_CELL_CAP = 4000

    def _cells_bounds(flat_cells, points=()):
        """World bounds of a {flat_index: [cell ids]} map, or None; the
        ids of the flats in `points` are a point set's points."""
        import math
        b = [math.inf, -math.inf, math.inf, -math.inf, math.inf, -math.inf]
        got = False
        budget = _BOUNDS_CELL_CAP
        for flat, cells in (flat_cells or {}).items():
            ds = _leaf_dataset(flat)
            if ds is None:
                continue
            as_points = flat in points
            n = ds.GetNumberOfPoints() if as_points else ds.GetNumberOfCells()
            if len(cells) > budget:
                # sample ACROSS the set, not its head: a prefix would box the
                # first corner only
                step = max(1, len(cells) // budget)
                cells = cells[::step]
            budget = max(0, budget - len(cells))
            for c in cells:
                if not (0 <= c < n):
                    continue
                if as_points:
                    x, y, z = ds.GetPoint(c)
                    cb = (x, x, y, y, z, z)
                else:
                    cb = ds.GetCell(c).GetBounds()
                b[0] = min(b[0], cb[0]); b[1] = max(b[1], cb[1])
                b[2] = min(b[2], cb[2]); b[3] = max(b[3], cb[3])
                b[4] = min(b[4], cb[4]); b[5] = max(b[5], cb[5])
                got = True
        return b if got else None

    def _rep_bounds(rep_path):
        """World bounds of every block of `rep_path`, or None. Resolves
        blocks through `_blocks_for_rep` — the SAME walk the Attributes
        highlight and the cross-plot lasso use, so "frame this object" can
        never disagree with "highlight this object" about what it is."""
        import math
        try:
            blocks = _blocks_for_rep(rep_path)
        except Exception:
            return None
        b = [math.inf, -math.inf, math.inf, -math.inf, math.inf, -math.inf]
        got = False
        for ds, _flat in blocks or ():
            if ds is None or ds.GetNumberOfPoints() == 0:
                continue
            db = ds.GetBounds()
            b[0] = min(b[0], db[0]); b[1] = max(b[1], db[1])
            b[2] = min(b[2], db[2]); b[3] = max(b[3], db[3])
            b[4] = min(b[4], db[4]); b[5] = max(b[5], db[5])
            got = True
        return b if got else None

    def _scaled_z(bounds, vid):
        """Bounds carry RAW Z; the view draws Z exaggerated, so the camera
        must aim at the SCALED height or it frames empty space."""
        zs = z_scale_of(state, vid)
        b = list(bounds)
        b[4] *= zs
        b[5] *= zs
        return b

    def _pv_view_of(vid):
        mv = _mv()
        return mv.get_pv_view(vid) if mv is not None else None

    def _nav_blocked(vid):
        """The Globe view draws in ECEF; every bound below is local-CRS, so
        aiming at one would throw the camera to the other side of the
        planet. The card is not built there; the title bar's gestures reach
        these controllers all the same."""
        return bool(getattr(state, f"ui_globe_mode__{vid}", False))

    # A "Centre view here" / "Zoom here" / framing of the active object
    # TRAVELS, like a camera move in a film, instead of jumping: the reader
    # keeps sight of where the view goes (the PO, 15/10). CAMERA_FLIGHT_FPS
    # frames a second for FESPP_CAMERA_FLIGHT_S seconds (0.6 by default, 0 to
    # jump as before), eased in and out, each frame rendered and pushed. A
    # click or a wheel notch in a view STOPS it where it is (the PO, 15/10);
    # a newer flight in the same view takes over from where this one is.
    CAMERA_FLIGHT_FPS = 25
    _flights = {}

    @lifecycle.on("view_closed")
    def _forget_flight_of(vid):
        """A closed view's camera flight stops: it checks its generation."""
        _flights.pop(vid, None)

    def _flight_seconds():
        raw = os.environ.get("FESPP_CAMERA_FLIGHT_S", "0.6")
        try:
            return max(0.0, min(3.0, float(raw)))
        except ValueError:
            print(f"[fespp] FESPP_CAMERA_FLIGHT_S={raw!r} is not a number: 0.6 s", flush=True)
            return 0.6

    def _camera_of(pvv):
        """Where the camera IS: the VTK camera, not the proxy's properties,
        which a mouse drag or a wheel notch in the browser leaves stale (a
        flight from them started from an old, farther view: "Zoom here"
        zoomed out, the PO 15/10; see camera.follow_z_scale)."""
        cam = pvv.GetActiveCamera()
        if cam is not None:
            return {"foc": [float(v) for v in cam.GetFocalPoint()],
                    "pos": [float(v) for v in cam.GetPosition()],
                    "ps": float(cam.GetParallelScale())}
        return {"foc": [float(v) for v in pvv.CameraFocalPoint],
                "pos": [float(v) for v in pvv.CameraPosition],
                "ps": float(pvv.CameraParallelScale)}

    def _parallel(pvv):
        """The camera's own projection: in 2D ParaView makes it parallel
        without telling the view's property."""
        try:
            return bool(pvv.GetActiveCamera().GetParallelProjection())
        except Exception as exc:
            print("[fespp] camera projection, read on the view instead:", exc, flush=True)
            return bool(int(getattr(pvv, "CameraParallelProjection", 0) or 0))

    def _put_camera(pvv, cam):
        pvv.CameraFocalPoint = list(cam["foc"])
        pvv.CameraPosition = list(cam["pos"])
        pvv.CameraParallelScale = cam["ps"]

    def _settled(vid, pvv, centre):
        """The camera is where it stays: the pivot on `centre` (None leaves
        it where it is), the linked views following, one frame."""
        if centre is not None:
            pvv.CenterOfRotation = list(centre)
        # a nav move is a camera move: linked views must follow it exactly
        # as they follow a mouse drag (EndAnimation only fires on the mouse)
        try:
            controller.camera_link_sync(vid)
        except Exception as exc:
            print(f"[fespp] nav link sync ({vid}):", exc, flush=True)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    async def _fly(vid, pvv, start, end, centre, seconds):
        from fespp_on_trame.app.views.camera import ACTIVITY, FLIGHTS, flight_frame
        gen = _flights.get(vid, 0) + 1
        _flights[vid] = gen
        frames = max(2, int(round(seconds * CAMERA_FLIGHT_FPS)))
        t0 = time.monotonic()
        # its frames are a move's: the log graphs keep their lay until it lands
        FLIGHTS.take_off(vid)
        k = 0
        try:
            while k < frames:
                if _flights.get(vid) != gen:
                    return      # a newer flight took the camera
                if ACTIVITY.touched_since(t0):
                    # a click or a wheel notch: stop HERE, and turn around
                    # what the view looks at now
                    _flights.pop(vid, None)
                    FLIGHTS.land(vid)
                    _settled(vid, pvv, _camera_of(pvv)["foc"]
                             if centre is not None else None)
                    _nav_note(vid, "Camera move stopped")
                    return
                # paced on the clock: a slow frame skips the ones it overran,
                # the flight lands on time
                k = flight_frame(k, frames, time.monotonic() - t0, seconds)
                t = k / frames
                e = t * t * (3.0 - 2.0 * t)         # smoothstep: eased in and out
                _put_camera(pvv, {
                    "foc": [a + (b - a) * e for a, b in zip(start["foc"], end["foc"])],
                    "pos": [a + (b - a) * e for a, b in zip(start["pos"], end["pos"])],
                    "ps": start["ps"] + (end["ps"] - start["ps"]) * e})
                if k == frames:
                    FLIGHTS.land(vid)
                    _settled(vid, pvv, centre)
                    return
                scheduler.mark_dirty(vid)
                scheduler.flush()
                await asyncio.sleep(max(0.0, t0 + seconds * (k + 1) / frames - time.monotonic()))
        except Exception as exc:
            print(f"[fespp] camera flight ({vid}):", exc, flush=True)
            try:
                FLIGHTS.land(vid)
                _put_camera(pvv, end)
                _settled(vid, pvv, centre)
            except Exception as exc2:
                print(f"[fespp] camera landing ({vid}):", exc2, flush=True)
        finally:
            if _flights.get(vid) == gen:
                _flights.pop(vid, None)
                FLIGHTS.land(vid)

    def _aim_at(vid, bounds, zoom):
        """Point THIS view at `bounds`, travelling there (see _fly).
        `zoom=False` turns the camera, from where it stands, to put the
        target in the middle, and leaves the rotation centre where it is:
        centring is not choosing what to turn around, "Set rotation centre
        here" does that (the manager, 16/10, as in ParaView); `zoom=True`
        also brings the camera CLOSER to it — framed when that is closer than
        the camera already is, else half way in, a zoom never goes back out
        (the PO, 15/10) — and turns around it from then on."""
        pvv = _pv_view_of(vid)
        if pvv is None or not bounds or _nav_blocked(vid):
            return False
        b = _scaled_z(bounds, vid)
        centre = [(b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0, (b[4] + b[5]) / 2.0]
        pivot = centre if zoom else None
        try:
            start = _camera_of(pvv)
        except Exception as exc:
            print(f"[fespp] nav aim ({vid}):", exc, flush=True)
            return False
        foc, pos = start["foc"], start["pos"]
        # The camera as a cameraman holds it (the manager, 15/10: the pan
        # slid the eye sideways, through whatever stood beside it, and could
        # end with the target hidden behind something). The eye never walks
        # anywhere but straight at the target: "Centre" leaves it where it is
        # and TURNS it to the target, "Zoom" moves it along the line it
        # already sees the target on. A picked cell is on a surface the eye
        # sees, so the eye still sees it, and the move crosses nothing.
        d = [pos[i] - centre[i] for i in range(3)]
        current = sum(v * v for v in d) ** 0.5
        if current < 1e-9:
            d = [pos[i] - foc[i] for i in range(3)]
            current = sum(v * v for v in d) ** 0.5 or 1.0
        d = [v / current for v in d]
        try:
            up = [float(v) for v in pvv.GetActiveCamera().GetViewUp()]
        except Exception:
            up = [float(v) for v in pvv.CameraViewUp]
        # a target straight above or below the eye would leave no "up" to
        # roll the image by: that one case keeps the former pan, and a zoom
        # the former viewing direction. In 2D the direction never changes:
        # the view slides and zooms, it does not turn.
        flat = str(getattr(state, f"ui_interaction_mode__{vid}", "") or "").upper() == "2D"
        turnable = not flat and abs(sum(a * b for a, b in zip(d, up))) < 0.995
        if not turnable:
            d = [pos[i] - foc[i] for i in range(3)]
            n = sum(v * v for v in d) ** 0.5 or 1.0
            d = [v / n for v in d]
        if zoom:
            # straight at the target, from where the eye is
            import math
            diag = max(((b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2
                        + (b[5] - b[4]) ** 2) ** 0.5, 1e-6)
            try:
                ang = float(pvv.CameraViewAngle) or 30.0
            except (TypeError, ValueError):
                ang = 30.0
            framed = (diag / 2.0) / max(math.tan(math.radians(ang / 2.0)), 1e-6) * 1.4
            dist = framed if framed < current else current * 0.5
            if _parallel(pvv):
                # the scale zooms; an eye brought closer would only end
                # inside the data, cutting away what is behind it
                dist = current
            framed_ps = diag / 2.0 * 1.2
            ps = framed_ps if framed_ps < start["ps"] else start["ps"] * 0.5
            end = {"foc": list(centre),
                   "pos": [centre[i] + d[i] * dist for i in range(3)],
                   "ps": ps}
        elif turnable:
            # the eye stays, the camera turns: the target in the middle
            end = {"foc": list(centre), "pos": list(pos), "ps": start["ps"]}
        else:
            shift = [centre[i] - foc[i] for i in range(3)]
            end = {"foc": list(centre),
                   "pos": [pos[i] + shift[i] for i in range(3)],
                   "ps": start["ps"]}
        seconds = _flight_seconds()
        moved = any(abs(p - q) > 1e-9 for p, q in zip(
            start["foc"] + start["pos"] + [start["ps"]], end["foc"] + end["pos"] + [end["ps"]]))
        try:
            if seconds <= 0.0 or not moved:
                _put_camera(pvv, end)
                _settled(vid, pvv, pivot)
                return True
            # the flight starts where the camera IS: the proxy is put in step
            # with it first, nothing being drawn in between
            _put_camera(pvv, start)
        except Exception as exc:
            print(f"[fespp] nav aim ({vid}):", exc, flush=True)
            return False
        asyncio.ensure_future(_fly(vid, pvv, start, end, pivot, seconds))
        return True

    def _nav_note(vid, text):
        notifier.note(vid, text)

    @controller.set("nav_set_pivot")
    def nav_set_pivot(view_id, at=None):
        """Drop the rotation centre WITHOUT moving the camera: on `at`, the
        point of the data the reader clicked (data space: the right-click
        menu's "Set rotation center here"), else on the last picked cells —
        the middle of a long cell (a log's tube runs the length of the
        hole) can be far off what was clicked. Rotation then turns around
        that point, and ParaView's own centre-of-rotation axes (the little
        cross) mark it — shown here so the choice is visible. A second pick
        moves the cross."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        picked = _last_pick.get(vid)
        if pvv is None or _nav_blocked(vid) or not (picked or at):
            if pvv is not None and not picked:
                _nav_note(vid, "Pick a cell first (hand or frustum tool)")
            return
        if at is not None:
            c = [float(at[0]), float(at[1]), float(at[2]) * z_scale_of(state, vid)]
        else:
            b = _cells_bounds(picked, selection.points_of(vid, pick=True))
            if b is None:
                _nav_note(vid, "The picked cells are no longer loaded")
                return
            b = _scaled_z(b, vid)
            c = [(b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0, (b[4] + b[5]) / 2.0]
        try:
            pvv.CenterOfRotation = c
            pvv.CenterAxesVisibility = 1     # the cross marking the pivot
        except Exception as exc:
            print(f"[fespp] nav pivot ({vid}):", exc, flush=True)
            return
        # the cross says it: no note
        state[f"ui_nav_pivot_shown__{vid}"] = True
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("nav_pivot_toggle")
    def nav_pivot_toggle(on, view_id):
        """The navigation card's "Show rotation centre" checkbox. Turning it
        ON puts the cross at the CURRENT centre of rotation (wherever the
        last pivot / reset left it); OFF hides it."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        if pvv is None:
            return
        try:
            pvv.CenterAxesVisibility = 1 if on else 0
        except Exception:
            pass
        state[f"ui_nav_pivot_shown__{vid}"] = bool(on)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    def _axes_grid_scale(pvv, vid):
        """The grid's labels read the file's depths whatever the vertical
        exaggeration: ParaView's DataScale divides the graduations by the
        scale the reps are drawn with."""
        try:
            pvv.AxesGrid.DataScale = [1.0, 1.0, z_scale_of(state, vid)]
        except Exception as exc:
            print("[fespp] axes grid scale error:", exc, flush=True)

    def _axes_grid_titles(vid, pvv):
        """The axes grid's three titles after the data's CRS — "Easting (m)",
        "Northing (m)", "Elevation (m)" (`geo.axes_grid_titles`) — instead of
        ParaView's "X Axis" (the manager, 16/10); X Y Z on the Globe, whose
        axes are the Earth's."""
        from fespp_on_trame.engine import geo
        globe = bool(getattr(state, f"ui_globe_mode__{vid}", False))
        titles = ("X", "Y", "Z") if globe else geo.axes_grid_titles(ctx.view_crs(vid))
        try:
            grid = pvv.AxesGrid
            for prop, text in zip(("XTitle", "YTitle", "ZTitle"), titles):
                if getattr(grid, prop) != text:
                    setattr(grid, prop, text)
        except Exception as exc:
            print(f"[fespp] axes grid titles ({vid}):", exc, flush=True)

    @controller.set("nav_axes_grid")
    def nav_axes_grid(on, view_id):
        """The navigation card's "Axes grid" checkbox: ParaView's data axes
        grid around everything shown in THIS view, graduated in the units
        of the file — the scale and the orientation of the scene."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        if pvv is None:
            return
        try:
            pvv.AxesGrid.Visibility = 1 if on else 0
            if on:
                _axes_grid_scale(pvv, vid)
                _axes_grid_titles(vid, pvv)
        except Exception as exc:
            print(f"[fespp] axes grid error ({vid}):", exc, flush=True)
            _nav_note(vid, f"Axes grid not available: {exc}")
            return
        state[f"ui_nav_axes_grid__{vid}"] = bool(on)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("nav_center_on_pick")
    def nav_center_on_pick(view_id, zoom=False, at=None):
        """Put the pivot (and optionally the framing) on the LAST picked
        cells of this view. Needs one pick first — the hand / frustum tool.
        `at`: the point of the data clicked (data space; the right-click
        menu, the double-click) — the view aims there, the picked cells only
        giving how much to take in: a cell of a well runs the length of the
        hole, and its middle can be far off what was clicked."""
        vid = str(view_id or "")
        picked = _last_pick.get(vid)
        if not picked:
            _nav_note(vid, "Pick a cell first (hand or frustum tool)")
            return
        b = _cells_bounds(picked, selection.points_of(vid, pick=True))
        if b is None:
            _nav_note(vid, "The picked cells are no longer loaded")
            return
        if at is not None:
            half = [(b[1] - b[0]) / 2.0, (b[3] - b[2]) / 2.0, (b[5] - b[4]) / 2.0]
            b = [float(at[k // 2]) + (half[k // 2] if k % 2 else -half[k // 2]) for k in range(6)]
        # the camera's move says it: no note
        _aim_at(vid, b, bool(zoom))

    @controller.set("nav_zoom_active")
    def nav_zoom_active(view_id):
        """Frame the object activated in THIS view's tree."""
        vid = str(view_id or "")
        path = getattr(state, f"active_path__{vid}", None)
        rep_path = (_rep_path_of(path) or path) if path else None
        if not rep_path:
            _nav_note(vid, "Activate an object in the tree first")
            return
        b = _rep_bounds(rep_path)
        if b is None:
            _nav_note(vid, "That object has no loaded geometry")
            return
        _aim_at(vid, b, True)

    @controller.set("nav_frame_node")
    def nav_frame_node(path, view_id=None, zoom=False):
        """The tree's right-click "Centre / Zoom the 3D view on <object>":
        the active 3D view (or `view_id`) turns to the object — `zoom`
        brings it closer too — whatever is active (the PO, 20/10: a surface
        shown among many others could not be found). A folder takes in what
        it holds (a wellbore, its trajectory, logs and markers)."""
        from fespp_on_trame.engine import view_routing
        vid = str(view_id or view_routing.resolve_active_render_panel(state) or "")
        rep_path = (_rep_path_of(path) or path) if path else ""
        if not vid or not rep_path:
            return
        b = _rep_bounds(rep_path)
        if b is None:
            _nav_note(vid, "That object is not loaded: tick it in the tree first")
            return
        # the camera's move says it: no note
        _aim_at(vid, b, bool(zoom))

    @controller.set("nav_axis")
    def nav_axis(view_id, axis):
        """Axis preset, NEGATIVE ones included (ParaView only ships +X/+Y/+Z
        buttons). Keeps the current focal point as the pivot."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        if pvv is None or _nav_blocked(vid):
            return
        vecs = {"+x": ((1, 0, 0), (0, 0, 1)), "-x": ((-1, 0, 0), (0, 0, 1)),
                "+y": ((0, 1, 0), (0, 0, 1)), "-y": ((0, -1, 0), (0, 0, 1)),
                "+z": ((0, 0, 1), (0, 1, 0)), "-z": ((0, 0, -1), (0, 1, 0))}
        v = vecs.get(str(axis or "").lower())
        if v is None:
            return
        try:
            # where the camera IS (a drag in the browser leaves the proxy stale)
            cam = _camera_of(pvv)
            foc, pos = cam["foc"], cam["pos"]
            dist = sum((pos[i] - foc[i]) ** 2 for i in range(3)) ** 0.5 or 1.0
            pvv.CameraFocalPoint = list(foc)
            pvv.CameraPosition = [foc[i] + v[0][i] * dist for i in range(3)]
            pvv.CameraViewUp = list(v[1])
        except Exception as exc:
            print(f"[fespp] nav axis ({view_id}):", exc, flush=True)
            return
        try:
            controller.camera_link_sync(vid)
        except Exception:
            pass
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("view_activate")
    def view_activate(view_id):
        """Make THIS view the active one. The title-bar chrome stops the
        click that dockview would have used for it (or the tab would start
        dragging), so a control up there says it itself before acting — ptc's
        camera group drives the ACTIVE view, not the one it sits on."""
        vid = str(view_id or "")
        mv = _mv()
        if mv is None or not vid:
            return
        try:
            mv._set_active(vid)
        except Exception as exc:
            print(f"[fespp] view activate ({vid}):", exc, flush=True)

    @controller.set("nav_reset")
    def nav_reset(view_id):
        """Fit everything, pivot re-centred (camera.reset_camera_centered)."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        if pvv is None or _nav_blocked(vid):
            return
        from fespp_on_trame.app.views.camera import reset_camera_centered
        try:
            reset_camera_centered(pvv)
        except Exception as exc:
            print(f"[fespp] nav reset ({vid}):", exc, flush=True)
        try:
            controller.camera_link_sync(vid)
        except Exception:
            pass
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("nav_zoom_step")
    def nav_zoom_step(view_id, factor):
        """Zoom in / out by a fixed step (the title-bar buttons). Dollies
        along the view direction in perspective; in PARALLEL projection the
        camera distance changes nothing on screen, so the parallel scale is
        what has to move.

        Offered on the Earth too, unlike its neighbours: `_nav_blocked`
        guards the framings, which aim at LOCAL-CRS bounds and in ECEF would
        point at the other side of the planet — this one reads no bounds at
        all, it slides the eye along the direction it already looks, which is
        exactly what the wheel does there."""
        from fespp_on_trame.app.views.camera import (
            WALL_NOTE, eye_is_inside, point_is_inside, visible_box)
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        if pvv is None:
            return
        try:
            f = float(factor)
        except (TypeError, ValueError):
            return
        if f <= 0:
            return
        try:
            # where the camera IS (a drag in the browser leaves the proxy stale)
            cam = _camera_of(pvv)
            if _parallel(pvv):
                pvv.CameraParallelScale = max(cam["ps"] * f, 1e-9)
            else:
                foc, pos = cam["foc"], cam["pos"]
                pvv.CameraFocalPoint = list(foc)
                d = [pos[i] - foc[i] for i in range(3)]
                # never let the eye reach the focal point: the direction
                # would be lost and the camera could not be pulled back out
                n = sum(v * v for v in d) ** 0.5
                if n < 1e-12:
                    return
                eye = [foc[i] + d[i] * f for i in range(3)]
                # the SAME wall the wheel stops at (camera.WheelWall): two
                # controls for one gesture must not disagree about where the
                # data begins. Only a step INWARDS is judged, and only from
                # outside — a camera already inside is left its way out.
                if f < 1.0 and _nav_blocked(vid):
                    # Globe views only: a plain 3D view may enter the data.
                    # The DATA's box, as the wheel's wall reads it: the
                    # Earth's cube always holds the camera
                    box = visible_box(pvv, data_only=True)
                    if (point_is_inside(box, eye)
                            and not eye_is_inside(pvv, box)):
                        state[f"ui_zoom_note__{vid}"] = WALL_NOTE
                        return
                state[f"ui_zoom_note__{vid}"] = ""
                pvv.CameraPosition = eye
        except Exception as exc:
            print(f"[fespp] nav zoom ({vid}):", exc, flush=True)
            return
        try:
            controller.camera_link_sync(vid)
        except Exception:
            pass
        scheduler.mark_dirty(vid)
        scheduler.flush()

    # Right-click menu on the 3D view: the SAME actions as the tree's (app/features/view_context_menu)
    from fespp_on_trame.app.features import view_context_menu as _feature_view_context_menu
    _feature_view_context_menu.register(
        core,
        _cmap_array_path=_cmap_array_path,
        _display_title=_display_title,
        _globe_scene=_globe_scene,
        _hl_state=_hl_state,
        _ids_to_source=_ids_to_source,
        _is_property_path=_is_property_path,
        _nav_note=_nav_note,
        _nothing_under=_nothing_under,
        _path_for_flat_index=_path_for_flat_index,
        _pick_region=_pick_region,
        _pv_view_of=_pv_view_of,
        _rep_path_of=_rep_path_of,
        _row_of_rep=_row_of_rep,
        _selection_ids=_selection_ids,
        _surface_fallback=_surface_fallback,
        _xml_open_from_path=_xml_open_from_path)

    # the calculator panel's controls (app/features/calculator_panel)
    from fespp_on_trame.app.features import calculator_panel as _feature_calculator_panel
    _feature_calculator_panel.register(
        core,
        _derived_fanout=_derived_fanout,
        _refresh_calculator=_refresh_calculator)

    return (_axes_grid_scale, _axes_grid_titles, _nav_blocked, _nav_note, _pv_view_of, _rep_bounds)
