"""Per-view IJK slicers — a GridIsolate: a per-view IjkGrid (crops
chained on the view's clone, leaf displays in THAT view only) while
the composite swaps the grid's block out (scene.isolated).
Mode 'full' releases everything and the composite takes back over.

(Moved out of app/boot, overhaul slice 10.)"""
import time


def register(core, *, ISOLATABLE, _globe_scene, _push_grid_targets,
             _slicer_armed, occupancy):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_codes_mask_sync, _ensure_isolate, _hide_nan_grids, _hide_nan_set, _push_slicer_state, _settle_isolate, _slicer_grid, _sync_isolate_colour, _threshold_isolate, _threshold_target)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    scheduler = core.scheduler
    activation = core.activation
    displays = core.displays
    _mv = core.mv
    # Per-view IJK slicers — a GridIsolate: a per-view IjkGrid (crops
    # chained on the view's clone, leaf displays in THAT view only) while
    # the composite swaps the grid's block out (scene.isolated).
    # Mode 'full' releases everything and the composite takes back over.
    ctx.grid_isolates = {}  # (view_id, rep_path) -> GridIsolate
    # "Hide NaN cells" (Colormap card, engine/nan_mask.py):
    # (view_id, rep_path) -> {"on": True, "auto": bool}; absent = off.
    # "auto": the NaN opacity going to 0 checked it, so the opacity going back
    # above 0 unchecks it; a hand on the box clears it (a choice wins).
    ctx.grid_hide_nan = {}
    # A grid painted by a cell property holding NaN hides those cells by
    # default (`_hide_nan_defaults`); (view_id, rep_path) unticked by hand
    # afterwards keep them shown — saved with the session's grids
    ctx.grid_nan_shown = set()
    # (view_id, rep_path, array) the default was weighed for, once; and
    # (dataset, its mtime, array) -> whether the array holds a NaN
    _nan_weighed, _nan_held = set(), {}

    def _slicer_var(view_id):
        return f"ui_slicers__{view_id}"

    # (view, grid) whose Slicers card shows Volume mode with no isolate built
    # yet: opening the card is wanting to cut (the manager, 15/10), but the
    # isolate — the grid's cells copied out of the composite, seconds on a big
    # grid for a picture that does not change (the manager, 16/10) — waits
    # for a bound that moves, a cut or a slice mode (`_slicer_armed`, made
    # by boot: the per-view wiring arms it too)

    def _push_slicer_state(view_id, iso=None):
        """Project the isolate's (or the idle full-extent) state into the
        per-view var the SlicersPanel binds."""
        rep_path, _sel, _scene = _slicer_grid(view_id)
        ext = None
        snap = iso.snapshot() if iso is not None else None
        if snap is not None and snap["extent"]:
            ext = list(snap["extent"])
        elif rep_path:
            shared = source_registry.get_ijk_grid(rep_path)
            shared_ext = shared.snapshot()["extent"] if shared is not None else None
            if shared_ext:
                ext = list(shared_ext)
        if ext is None:
            ext = [0, 0, 0, 0, 0, 0]
        armed = (view_id, rep_path) in _slicer_armed
        d = {
            # no isolate = slicing OFF, unless the card was just opened
            # (`_slicer_armed`): the panel's switch must read that
            "mode": (snap["mode"] if snap is not None
                     else ("range" if armed else "full")),
            "has_grid": bool(rep_path),
            "range_i": ext[0:2], "range_j": ext[2:4], "range_k": ext[4:6],
        }
        if snap is not None:
            d.update({
                "slice_range_i": snap["range"]["i"] or ext[0:2],
                "slice_range_j": snap["range"]["j"] or ext[2:4],
                "slice_range_k": snap["range"]["k"] or ext[4:6],
                "positions_i": snap["positions"]["i"],
                "positions_j": snap["positions"]["j"],
                "positions_k": snap["positions"]["k"],
                "vis_i": snap["visible"]["i"],
                "vis_j": snap["visible"]["j"],
                "vis_k": snap["visible"]["k"],
                "volume_visible": bool((snap["volumes_visible"] or [True])[0]),
                # [] = every volume deleted (nothing renders), not "idle"
                "volumes": snap["volumes"],
                "volumes_visible": snap["volumes_visible"],
            })
        else:
            d.update({
                "slice_range_i": ext[0:2], "slice_range_j": ext[2:4],
                "slice_range_k": ext[4:6],
                "positions_i": [], "positions_j": [], "positions_k": [],
                "vis_i": [], "vis_j": [], "vis_k": [],
                "volume_visible": True,
                "volumes": [[ext[0:2], ext[2:4], ext[4:6]]],
                "volumes_visible": [True],
            })
        state[_slicer_var(view_id)] = d
        _push_grid_targets(view_id)
        # the Geometry slicer's card shows what the isolate draws
        # (app/features/geometry_slicer, 28/10)
        publish = getattr(ctx, "geometry_card_publish", None)
        if publish is not None:
            publish(view_id)
        core.lifecycle.emit("view_cuts", vid=view_id)

    def _slicer_grid(view_id):
        """(rep_path, selector, scene) of the grid the slicers act on: the
        Reservoir tab's ACTIVE node, or — when a grid was merely checked and
        shown, never clicked — the first loaded one. Without the fallback the
        panel would sit empty on a perfectly sliceable grid, and the toolbar
        button (which keys on what is loaded) would promise something it
        could not do."""
        rep_path = activation.target_of(view_id, "slicers")
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        return rep_path, rep_path, scene

    def _sync_isolate_colour(iso, sel, scene):
        """The isolate paints what the composite paints: the array the eye
        colours the grid with, as the composite resolved it (sanitized VTK
        name, realization suffix), else the grid's solid colour."""
        entry = (scene.block_state.get(sel)
                 if scene is not None and sel else None)
        if entry is not None and entry.color_array:
            iso.set_color(entry.assoc or "CELLS", entry.color_array)
        else:
            iso.clear_colors()
        # the cell mask follows the colour: it hides where THE ARRAY PAINTING
        # THE GRID is NaN ("Hide NaN cells") or holds a code its table puts
        # at opacity 0 (a node property cannot hide cells). Whether the mask
        # changed is returned: the caller settles the grid then
        flag = ctx.grid_hide_nan.get((getattr(iso, "_view_id", None), iso.rep_path)) or {}
        painting = (entry.color_array
                    if entry is not None and entry.color_array
                    and (entry.assoc or "CELLS") == "CELLS" else None)
        return iso.set_cell_mask(painting, nan=bool(flag.get("on")),
                                 codes=_hidden_codes(scene, painting))

    def _hidden_codes(scene, array):
        """The codes `array`'s table puts at opacity 0 in this view (a
        property painted by code), () when none."""
        if scene is None or not array:
            return ()
        try:
            from fespp_on_trame.engine import categorical_palette
            return categorical_palette.hidden_codes(scene.scoped_lut(array))
        except Exception as exc:
            print(f"[fespp] codes at opacity 0 ({array!r}): {exc!r}", flush=True)
            return ()

    def _codes_mask_sync(view_id, array=None):
        """A code at opacity 0 takes its cells OUT of the grid, so their
        neighbours' faces show (engine/nan_mask), not a see-through hole:
        every visible grid of the view painted by a CELL array (`array`
        alone when given) whose table hides codes gets its isolate — the
        mask lives there — and a live isolate follows its table, released
        by `_settle_isolate` when nothing else needs it."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        if scene is None:
            return
        for rp, sel, entry in _hide_nan_grids(view_id, array):
            iso = ctx.grid_isolates.get((view_id, rp))
            if iso is None:
                if not _hidden_codes(scene, entry.color_array):
                    continue
                iso, _s, _sc = _ensure_isolate(view_id, (rp, sel, scene))
                if iso is None:
                    continue
                _settle_isolate(view_id, rp, sel, scene)
            elif _sync_isolate_colour(iso, sel, scene):
                _settle_isolate(view_id, rp, sel, scene)

    def _settle_isolate(view_id, rep_path, sel, scene):
        """THE release rule: the grid stays isolated (drawn by its own
        displays) while its isolate needs it — a threshold chain, a slicer
        mode, the NaN mask — else the composite paints the block again. Its
        displays follow the grid's eye: closed, nothing of it is drawn."""
        if rep_path:
            occupancy.settle(view_id, rep_path, sel)

    def _hide_nan_grids(view_id, array=None):
        """The grids of this view the NaN mask can act on — isolatable,
        visible, painted by a CELL array — as (rep_path, sel, entry); only
        those painted by `array` (realization suffix aside) when given."""
        from fespp_on_trame.engine.utils.naming import strip_realization_suffix
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        if scene is None or type(scene).__name__ == "GlobeScene":
            # the Globe view hosts no isolate: the card greys the box
            # there, and the NaN opacity checks nothing
            return []
        want = strip_realization_suffix(array) if array else None
        shown = scene.shown_selectors()
        out = []
        for rp in (state.ui_loaded_rep_paths or []):
            nid = tree.find_node_id(rp)
            if nid is None or (tree.find_type(nid) or "") not in ISOLATABLE:
                continue
            sel = rp
            entry = scene.block_state.get(sel)
            if (sel not in shown or entry is None or not entry.color_array
                    or (entry.assoc or "CELLS") != "CELLS"):
                continue
            if want is not None and strip_realization_suffix(entry.color_array) != want:
                continue
            out.append((rp, sel, entry))
        return out

    def _holds_nan(rep_path, array):
        """Whether the cell array `array` of the grid `rep_path` as read holds
        a NaN."""
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        index = getattr(ctx, "assembly_index", None)
        for ds, _flat in (index.datasets(rep_path) if index is not None else ()):
            arr = ds.GetCellData().GetArray(array) if ds.GetCellData() is not None else None
            if arr is None:
                continue
            key = (ds.GetAddressAsString("vtkDataObject"), ds.GetMTime(), array)
            if key not in _nan_held:
                values = vtk_to_numpy(arr)
                _nan_held[key] = bool(values.dtype.kind == "f" and np.isnan(values).any())
            if _nan_held[key]:
                return True
        return False

    def _hide_nan_defaults(vids):
        """Before a render: a grid a view paints with a cell property holding
        NaN hides those cells (the Colormap card's "Hide NaN cells" ticked),
        once per view, grid and property — unticked by hand, they stay shown."""
        for vid in vids:
            for rp, _sel, entry in _hide_nan_grids(vid):
                key = (vid, rp, entry.color_array)
                if key in _nan_weighed:
                    continue
                _nan_weighed.add(key)
                if (vid, rp) in ctx.grid_nan_shown or (ctx.grid_hide_nan.get((vid, rp)) or {}).get("on"):
                    continue
                try:
                    if not _holds_nan(rp, entry.color_array):
                        continue
                    started = time.monotonic()
                    if _hide_nan_set(vid, rp, True):
                        iso = ctx.grid_isolates.get((vid, rp))
                        hidden = iso.hide_nan_hidden if iso is not None else None
                        nid = tree.find_node_id(rp)
                        title = (tree.find_rep_title(nid) if nid is not None else "") or rp
                        print(f"[fespp] journal hide NaN cells ({vid}): {title} painted by"
                              f" {entry.color_array}, its NaN cells hidden by default"
                              f" ({'?' if hidden is None else hidden} cell(s), {time.monotonic() - started:.2f} s)",
                              flush=True)
                except Exception as exc:
                    print(f"[fespp] hide NaN cells by default ({vid}): {exc!r}", flush=True)

    scheduler.add_flush_listener(_hide_nan_defaults)

    @state.change("ui_loaded_rep_paths")
    def _nan_defaults_forgotten(ui_loaded_rep_paths=None, **_):
        """A grid unloaded: read again, it hides its NaN cells by default again."""
        loaded = set(ui_loaded_rep_paths or ())
        for key in [k for k in _nan_weighed if k[1] not in loaded]:
            _nan_weighed.discard(key)
        for key in [k for k in ctx.grid_nan_shown if k[1] not in loaded]:
            ctx.grid_nan_shown.discard(key)
        if not loaded:
            _nan_held.clear()

    @core.lifecycle.on("view_closed")
    def _nan_defaults_closed(vid):
        for key in [k for k in _nan_weighed if k[0] == str(vid)]:
            _nan_weighed.discard(key)
        for key in [k for k in ctx.grid_nan_shown if k[0] == str(vid)]:
            ctx.grid_nan_shown.discard(key)

    def _hide_nan_set(view_id, rep_path, on, auto=False):
        """Turn the NaN mask on/off for one grid of one view: the flag, the
        isolate (built when on, released by `_settle_isolate` when nothing
        else needs it), the mask on the painting array."""
        key = (view_id, rep_path)
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        sel = rep_path
        if on:
            ctx.grid_hide_nan[key] = {"on": True, "auto": bool(auto)}
            iso, _s, _sc = _ensure_isolate(view_id, (rep_path, sel, scene))
            if iso is None:
                ctx.grid_hide_nan.pop(key, None)
                print(f"[fespp] hide NaN cells: {rep_path[-40:]!r} cannot be isolated"
                      f" in {view_id} — cells left as they are", flush=True)
                return False
        else:
            ctx.grid_hide_nan.pop(key, None)
            iso = ctx.grid_isolates.get(key)
        if iso is not None:
            _sync_isolate_colour(iso, sel, scene)
            _settle_isolate(view_id, rep_path, sel, scene)
        return True


    def _threshold_target(view_id):
        """(rep_path, selector, scene) the Thresholds card acts on.

        The SLICERS need an IJK grid and keep `_slicer_grid`. A threshold
        does not, so this one takes the view's ACTIVE representation when it
        is isolatable, and otherwise falls back the same way `_slicer_grid`
        does — to the first loaded one — so a card opened on a grid that
        was merely checked is not empty."""
        rep_path = activation.target_of(view_id, "thresholds")
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        return rep_path, rep_path, scene

    def _threshold_isolate(view_id):
        """(isolate, selector, scene) the Thresholds card edits — looked up,
        never built: an edit sent for a grid that is no longer the target
        must not create an empty isolate on the new one (D15)."""
        rep_path, sel, scene = _threshold_target(view_id)
        iso = ctx.grid_isolates.get((view_id, rep_path)) if rep_path else None
        return iso, sel, scene

    def _ensure_isolate(view_id, target=None):
        if _globe_scene(view_id) is not None:
            # an isolate is built from the local-CRS source: on the Earth
            # it would be drawn thousands of km off (D13)
            return None, None, None
        rep_path, sel, scene = (target if target is not None
                                else _slicer_grid(view_id))
        n_id = tree.find_node_id(rep_path) if rep_path else None
        if n_id is None or (tree.find_type(n_id) or "") not in ISOLATABLE:
            return None, None, None
        key = (view_id, rep_path)
        iso = ctx.grid_isolates.get(key)
        if iso is None:
            from fespp_on_trame.engine.sources.grid_isolate import GridIsolate
            # the view's clone and colour tables (engine/view_resources)
            vres = core.view_resources.get(view_id)
            mv = _mv()
            iso = GridIsolate(
                active_data_source, tree, view_id=view_id,
                clone=vres.clone if vres is not None else None,
                pv_view=mv.get_pv_view(view_id) if mv is not None else None,
                lut_for=(vres.get_or_create_lut if vres is not None else None),
                shown_by=lambda i, v=view_id, r=rep_path: occupancy.settle(v, r),
            )
            iso.set_node_id(n_id)
            if iso.source is None:
                return None, None, None
            # drawn as the view's Represent By, crops and threshold tips alike
            iso.rep_style = getattr(state, f"ui_rep_style__{view_id}", None) or "Surface"
            ctx.grid_isolates[key] = iso
            # a scene already cut cuts the new isolate too
            # (app/features/geometry_slicer)
            hook = getattr(ctx, "scene_cut_for_isolate", None)
            if hook is not None:
                try:
                    hook(view_id, iso)
                except Exception as exc:
                    print(f"[fespp] scene cut on a new isolate ({view_id}):", exc, flush=True)

            def _iso_style(style, i=iso, v=view_id, r=rep_path):
                i.rep_style = style
                occupancy.settle(v, r)
            displays.add(view_id, f"isolate:{rep_path}", "isolate", None,
                         follows_style=True,
                         # Scale, threshold tips included — and only when
                         # the isolate draws (N8: Slice off, then Z)
                         zscale=lambda _z, v=view_id, r=rep_path: occupancy.settle(v, r),
                         style=_iso_style,
                         close=lambda v=view_id, r=rep_path: _drop_isolate(v, r))
            if scene is not None:
                iso.after_show = scene.resync_bars
            _sync_isolate_colour(iso, sel, scene)
        # whether the composite gives the block up is the occupancy's to
        # decide, once the caller has changed what the isolate needs
        return iso, sel, scene

    def _drop_isolate(view_id, rep_path):
        """One isolate of a view forgotten, with its crops, its chain and its
        "Hide NaN cells" flag; the composite takes the block back."""
        key = (view_id, rep_path)
        displays.remove(view_id, f"isolate:{rep_path}")
        iso = ctx.grid_isolates.pop(key, None)
        ctx.grid_hide_nan.pop(key, None)
        if iso is None:
            return
        try:
            iso.set_node_id(None)
        except Exception:
            pass

    @controller.set("slicer_mode")
    def slicer_mode(mode, view_id):
        try:
            if mode == "full":
                # Slice off keeps the isolate and its state (volumes, cuts,
                # eyes, thresholds) for the next Slice on; with no
                # threshold the composite paints the block again
                rep_path, sel, scene = _slicer_grid(view_id)
                _slicer_armed.discard((view_id, rep_path))
                iso = ctx.grid_isolates.get((view_id, rep_path)) if rep_path else None
                if iso is not None:
                    iso.apply_mode("full")
                    # kept isolated while a threshold or the NaN mask needs it
                    _settle_isolate(view_id, rep_path, sel, scene)
                _push_slicer_state(view_id, iso)
                scheduler.mark_dirty(view_id)
                scheduler.flush()
                return
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            iso.apply_mode("slice" if mode == "slice" else "range")
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_mode error ({view_id}):", exc, flush=True)

    @controller.set("slicer_range")
    def slicer_range(payload, view_id):
        try:
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            axis, rng = payload
            iso.set_volume_range(axis, rng)
            snap = iso.snapshot()
            vols = [[snap["range"]["i"], snap["range"]["j"], snap["range"]["k"]]]
            iso.apply_mode("range")
            iso.apply_volumes(vols, snap["volumes_visible"] or [True])
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_range error ({view_id}):", exc, flush=True)

    @controller.set("slicer_positions")
    def slicer_positions(payload, view_id):
        try:
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            axis, positions = payload
            cur = iso.snapshot()["positions"]
            cur[axis] = [int(p) for p in (positions or [])]
            iso.apply_mode("slice")
            iso.apply_slice_positions(cur["i"], cur["j"], cur["k"])
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_positions error ({view_id}):", exc, flush=True)

    @controller.set("slicer_visibility")
    def slicer_visibility(payload, view_id):
        try:
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            axis, vis = payload
            cur = iso.snapshot()["visible"]
            cur[axis] = [bool(v) for v in (vis or [])]
            iso.apply_slice_visibility(cur["i"], cur["j"], cur["k"])
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_visibility error ({view_id}):", exc, flush=True)

    @controller.set("slicer_volumes")
    def slicer_volumes(volumes, view_id):
        """The range-mode boxes, all of them: their UNION renders. Each is
        [[i0,i1],[j0,j1],[k0,k1]]."""
        try:
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            vols = []
            for v in volumes or []:
                try:
                    vols.append([[int(v[0][0]), int(v[0][1])],
                                 [int(v[1][0]), int(v[1][1])],
                                 [int(v[2][0]), int(v[2][1])]])
                except (TypeError, ValueError, IndexError):
                    continue
            # an empty list is a state too: every volume deleted, nothing renders
            snap = iso.snapshot()
            if snap["mode"] == "range" and vols == snap["volumes"]:
                return
            vis = list(snap["volumes_visible"])
            vis = (vis + [True] * len(vols))[:len(vols)]
            iso.apply_mode("range")
            iso.apply_volumes(vols, vis)
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_volumes error ({view_id}):", exc, flush=True)

    @controller.set("slicer_copy_from")
    def slicer_copy_from(src_view, view_id):
        """Another view's slicer state (mode, volumes, cuts, eyes) onto this
        view's isolate of the same grid — the card's copy-from-view menu."""
        try:
            if not src_view or src_view == view_id:
                return
            rep_path, _sel, _scene = _slicer_grid(view_id)
            src = ctx.grid_isolates.get((src_view, rep_path)) if rep_path else None
            src_snap = src.snapshot() if src is not None else None
            if src_snap is None or src_snap["mode"] == "full":
                slicer_mode("full", view_id)
                return
            iso, _s, _sc = _ensure_isolate(view_id)
            if iso is None:
                return
            iso.apply_volumes(src_snap["volumes"], src_snap["volumes_visible"])
            iso.apply_slice_positions(*(src_snap["positions"][a] for a in "ijk"))
            iso.apply_slice_visibility(*(src_snap["visible"][a] for a in "ijk"))
            iso.apply_mode(src_snap["mode"])
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_copy_from error ({view_id}):", exc, flush=True)

    @controller.set("slicer_volumes_visible")
    def slicer_volumes_visible(flags, view_id):
        try:
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            vols = iso.snapshot()["volumes"]
            vis = [bool(f) for f in (flags or [])]
            vis = (vis + [True] * len(vols))[:len(vols)]
            iso.apply_volumes(vols, vis)
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_volumes_visible error ({view_id}):", exc, flush=True)

    @controller.set("slicer_volume_visible")
    def slicer_volume_visible(visible, view_id):
        try:
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            snap = iso.snapshot()
            vols = snap["volumes"] or [[snap["range"][a] or [0, 0] for a in "ijk"]]
            iso.apply_volumes(vols, [bool(visible)])
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_volume error ({view_id}):", exc, flush=True)

    def _locate(items, idx, value):
        """The index the card named, or where `value` now sits when the list
        moved under the card (None when it is gone)."""
        if isinstance(idx, int) and 0 <= idx < len(items) and (value is None or items[idx] == value):
            return idx
        if value is not None and value in items:
            return items.index(value)
        return None

    def _edit_cuts(iso, edit):
        """A cut added, removed, shown / hidden or moved on one axis of the
        CURRENT cuts; False when there is nothing to do."""
        axis = edit.get("axis")
        if axis not in ("i", "j", "k"):
            return False
        snap = iso.snapshot()
        pos = {a: [int(p) for p in snap["positions"][a]] for a in "ijk"}
        vis = {a: [bool(v) for v in snap["visible"][a]] for a in "ijk"}
        for a in "ijk":   # one flag per cut, a missing one shown
            vis[a] = (vis[a] + [True] * len(pos[a]))[:len(pos[a])]
        p, v, op = pos[axis], vis[axis], edit.get("op")
        if op == "add_cut":
            p.append(int(edit.get("at", 0)))
            v.append(True)
        else:
            # a moved cut is named by its index alone: a drag sends its
            # position again and again, and the first send moves it
            value = None if op == "set_cut" or edit.get("value") is None else int(edit["value"])
            i = _locate(p, edit.get("idx"), value)
            if i is None:
                return False
            if op == "del_cut":
                del p[i]
                del v[i]
            elif op == "toggle_cut":
                v[i] = not v[i]
            elif op == "set_cut":
                # clamped to the extent by the card, as the whole-list path
                new = int(edit.get("value", p[i]))
                if new == p[i]:
                    return False
                p[i] = new
            else:
                return False
        iso.apply_mode("slice")
        iso.apply_slice_positions(pos["i"], pos["j"], pos["k"])
        iso.apply_slice_visibility(vis["i"], vis["j"], vis["k"])
        return True

    def _edit_volumes(iso, edit):
        """A box added, removed, shown / hidden or reshaped among the CURRENT
        boxes; False when there is nothing to do."""
        def box_of(b):
            return [[int(b[0][0]), int(b[0][1])], [int(b[1][0]), int(b[1][1])],
                    [int(b[2][0]), int(b[2][1])]]
        snap = iso.snapshot()
        vols = [box_of(b) for b in snap["volumes"]]
        vis = [bool(f) for f in snap["volumes_visible"]]
        vis = (vis + [True] * len(vols))[:len(vols)]
        op = edit.get("op")
        try:
            box = box_of(edit["box"]) if edit.get("box") is not None else None
        except (TypeError, ValueError, IndexError, KeyError) as exc:
            print(f"[fespp] slicer_edit: not a box {edit.get('box')!r} ({exc})", flush=True)
            return False
        if op == "add_volume":
            if box is None:
                return False
            vols.append(box)
            vis.append(True)
        else:
            # a reshaped box is named by its index alone, as a moved cut
            i = _locate(vols, edit.get("idx"), None if op == "set_volume" else box)
            if i is None:
                return False
            if op == "del_volume":
                del vols[i]
                del vis[i]
            elif op == "toggle_volume":
                vis[i] = not vis[i]
            elif op == "set_volume":
                if box is None or (snap["mode"] == "range" and vols[i] == box):
                    return False
                vols[i] = box
            else:
                return False
        iso.apply_mode("range")
        iso.apply_volumes(vols, vis)
        return True

    @controller.set("slicer_edit")
    def slicer_edit(edit, view_id):
        """One gesture of the card, applied to the isolate's CURRENT state.
        The card sends what the gesture means — add, remove, show / hide or
        move ONE cut or box ({op, axis?, idx?, value? | box?}) — never a
        whole list rebuilt from what it last received: of two quick clicks,
        the second would undo the first (the tree's rule for its eyes). The
        whole-state controllers above stay for the session and the
        assistant, which do hold the whole state."""
        try:
            edit = dict(edit or {})
            op = edit.get("op") or ""
            iso, _sel, _scene = _ensure_isolate(view_id)
            if iso is None:
                return
            if op.endswith("_cut"):
                changed = _edit_cuts(iso, edit)
            elif op.endswith("_volume"):
                changed = _edit_volumes(iso, edit)
            else:
                print(f"[fespp] slicer_edit ({view_id}): unknown gesture {op!r}", flush=True)
                return
            if not changed:
                return
            occupancy.settle(view_id, iso.rep_path)
            _push_slicer_state(view_id, iso)
            scheduler.mark_dirty(view_id)
            scheduler.flush()
        except Exception as exc:
            print(f"[fespp] slicer_edit error ({view_id}):", exc, flush=True)

    # ------------------------------------------------------------------
    return (_codes_mask_sync, _ensure_isolate, _hide_nan_grids, _hide_nan_set, _push_slicer_state, _settle_isolate, _slicer_grid, _sync_isolate_colour, _threshold_isolate, _threshold_target)
