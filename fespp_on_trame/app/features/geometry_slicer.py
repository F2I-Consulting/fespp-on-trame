"""The Geometry slicer — the Slicers card as the shared slicer card on the I,
J and K of the view's grid, on the I, J, X, Y and Z of a surface on a 2D
grid, or on the X, Y and Z of any other object (a surface, a polyline or
point set, an unstructured grid); the same card as the Property slicer
(app/features/slicer_card_host does the gestures).

The card compiles into boxes (`engine/slicer_card.boxes`): whole indices on
an I/J/K grid, drawn by the isolate's volume crops; the scene's coordinates
otherwise, drawn by its X/Y/Z crops (engine/sources/xyz_crop: the scene
cut's filters on the object, a cell kept when it meets the box — a cut at
one value keeps the cells the plane crosses). Their union shows. A
card keeping the whole object builds no isolate — it copies the object's
cells out of the composite, seconds on a big grid, for a picture that does
not change. A live step (a drag, the player) moves the crops on screen and
nothing else.

Z is the scene's, as the axes of the view say: the file's own value on an
elevation CRS, its opposite on a depth CRS ("Z increasing downward", made
negative by the plugin); a time on a time CRS. The axes are named as the
view's CRS names them, with its units (the manager, 29/10): "Easting (m)",
"Northing (m)", "Elevation (m)" or "Time (ms)".

A slicing made elsewhere — a session read back, the assistant, the copy
from another view — reaches the card through the isolate's snapshot: when
what the isolate draws is not what the card drew, the card is read back
from it (`slicer_card.from_boxes`).

State: `ui_geometry_card__<vid>`, `ui_geometry_player__<vid>`.
"""
from fespp_on_trame.app.features.slicer_card_host import CardHost
from fespp_on_trame.engine import crs_reference
from fespp_on_trame.engine import geo
from fespp_on_trame.engine import slicer_card as sc
from fespp_on_trame.engine.blockscope.scene_crop import SCENE

IJK = ("i", "j", "k")
XYZ = ("x", "y", "z")
IJXYZ = ("i", "j") + XYZ


def register(core, *, _blocks_for_rep, _ensure_isolate, _push_slicer_state, _rep_bounds,
             _settle_isolate, _slicer_grid):
    """Wire the `geometry_slicer` controller."""
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    scheduler = core.scheduler
    _cards = {}    # (vid, rep_path) -> (card, the boxes it drew)

    _ij_memo = {}    # rep_path -> a surface's I/J point extent

    def _ij_extent(rep):
        """The point extent of a surface on a 2D grid, None when it is not
        drawn as one (yet)."""
        held = _ij_memo.get(rep)
        if held is not None:
            return held
        try:
            blocks = _blocks_for_rep(rep) or ()
        except Exception as exc:
            print(f"[fespp] geometry slicer: the surface's grid not read ({rep}):", exc, flush=True)
            return None
        for ds, _flat in blocks:
            if ds is not None and ds.IsA("vtkStructuredGrid") and ds.GetNumberOfPoints():
                ext = [int(v) for v in ds.GetExtent()]
                if ext[0] <= ext[1] and ext[2] <= ext[3]:
                    _ij_memo[rep] = ext
                    return ext
        return None

    def _axes(rep):
        """I, J, K on an I/J/K grid; I, J, X, Y, Z on a surface drawn on its
        2D grid; X, Y, Z on anything else."""
        nid = tree.find_node_id(rep) if rep else None
        kind = (tree.find_type(nid) or "") if nid is not None else ""
        if kind == "IjkGrid":
            return IJK
        if kind == "Grid2d" and _ij_extent(rep):
            return IJXYZ
        return XYZ

    def _snapshot(vid, rep):
        iso = ctx.grid_isolates.get((vid, rep))
        return iso, (iso.snapshot() if iso is not None else None)

    def _drawn(snap):
        """The boxes an isolate draws ([] when it draws the whole object)."""
        if snap is None or snap.get("mode") == "full":
            return []
        if snap.get("mode") == "range":
            return [v for v, on in zip(snap.get("volumes") or [], snap.get("volumes_visible") or []) if on]
        return None   # cuts: another slicing than the card's

    def _scene_of(vid):
        return (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)

    def _target(vid):
        """What the card cuts in `vid`: the object picked in its list or the
        active node's, else the whole SCENE (the PO, 29/10: "by default, with
        no active node, the card is on the scene"; 23/11: an active node it
        cannot cut, a surface, is no reason to go back to a grid)."""
        scene = _scene_of(vid)
        if scene is None or not scene.shown_selectors():
            return ""       # nothing drawn: nothing to cut, whatever was picked
        activation = core.activation
        if activation.pinned(vid, "slicers") == SCENE:
            return SCENE
        return activation.target_of(vid, "slicers", fallback=False, remembered=False) or SCENE

    _bounds_memo = {}    # vid -> (the objects drawn, their bounds)
    _card_exts = {}      # (vid, rep_path) -> the extents its card was last read with

    def _scene_bounds(vid):
        """The bounds of everything the view draws (its domain's objects),
        or None."""
        scene = _scene_of(vid)
        if scene is None:
            return None
        shown = frozenset(scene.shown_selectors())
        held = _bounds_memo.get(vid)
        if held is not None and held[0] == shown:
            return held[1]
        b, got = [float("inf"), float("-inf")] * 3, False
        for sel in shown:
            rb = _rep_bounds(sel)
            if not rb:
                continue
            for n in range(3):
                b[2 * n] = min(b[2 * n], float(rb[2 * n]))
                b[2 * n + 1] = max(b[2 * n + 1], float(rb[2 * n + 1]))
            got = True
        _bounds_memo[vid] = (shown, b if got else None)
        return b if got else None

    def targets_of(vid):
        """The card's list: the whole scene, then the objects it can cut."""
        scene = _scene_of(vid)
        if scene is None or not scene.shown_selectors():
            return []
        return [{"value": SCENE, "label": "Whole scene"}]

    def context(vid, _extra=()):
        rep = _target(vid)
        if not rep:
            return "", {}, ("The Geometry slicer cuts what this view draws — nothing is"
                            " drawn in it yet."), []
        if rep == SCENE:
            b = _scene_bounds(vid)
            if not b:
                return rep, {}, "What this view draws is being read.", []
            infos = {a: {"label": label, "kind": "Continuous",
                         "extent": [float(b[2 * n]), float(b[2 * n + 1])]}
                     for n, (a, label) in enumerate(zip(XYZ, _xyz_labels(vid, rep)))}
            return rep, infos, "", []
        _iso, snap = _snapshot(vid, rep)
        if _axes(rep) == IJK:
            ext = (snap or {}).get("extent")
            if not ext:
                shared = core.source_registry.get_ijk_grid(rep)
                ext = shared.snapshot()["extent"] if shared is not None else None
            if not ext:
                # no card on an extent not known yet: its ranges would stay
                # at 0-0 once the grid is read
                return rep, {}, "This grid is being read.", []
            ext = list(ext)
            infos = {a: {"label": a.upper(), "kind": "Index", "extent": [int(ext[2 * n]), int(ext[2 * n + 1])]}
                     for n, a in enumerate(IJK)}
            return rep, infos, "", []
        b = (snap or {}).get("bounds") or _rep_bounds(rep)
        if not b:
            return rep, {}, "This object has no point to cut yet: it is being read.", []
        infos = {}
        if _axes(rep) == IJXYZ:
            ij = (snap or {}).get("ij_extent") or _ij_extent(rep)
            infos = {a: {"label": a.upper(), "kind": "Index", "extent": [int(ij[2 * n]), int(ij[2 * n + 1])]}
                     for n, a in enumerate(("i", "j"))}
        infos.update({a: {"label": label, "kind": "Continuous", "extent": [float(b[2 * n]), float(b[2 * n + 1])]}
                      for n, (a, label) in enumerate(zip(XYZ, _xyz_labels(vid, rep)))})
        return rep, infos, "", []

    def _xyz_labels(vid, rep):
        """The axes as the CRS names them, with its units (the manager,
        29/10): "Easting (m)", "Northing (m)" in the file's order, then
        "Elevation (m)" (the scene's Z) or "Time (ms)"; X, Y and Elevation
        or Time when no CRS names them (geo.axes_grid_titles)."""
        view_crs = getattr(ctx, "view_crs", None)
        try:
            labels = geo.axes_grid_titles(view_crs(vid) if view_crs is not None else None)
        except Exception as exc:
            print(f"[fespp] geometry slicer: axis names ({vid}):", exc, flush=True)
            nid = tree.find_node_id(rep) if rep != SCENE else None
            time = nid is not None and crs_reference.domain_of(tree, nid) == "time"
            return ("X", "Y", "Time" if time else "Elevation")
        # RESQML writes its axis order in lower case ("easting northing")
        return tuple(t[:1].upper() + t[1:] for t in labels)

    def card_of(vid, rep, infos):
        key = (vid, rep)
        axes = _axes(rep)
        if not infos:
            return sc.empty(axes)
        exts = {s: info["extent"] for s, info in infos.items()}
        held = _cards.get(key)
        if held is not None and _card_exts.get(key) not in (None, exts):
            # the extent changed under the card (the scene's objects read or
            # put away, a grid read after its card): the ranges that held it
            # whole hold it still
            sc.follow_extents(held[0], _card_exts[key], exts)
        _card_exts[key] = {s: list(e) for s, e in exts.items()}
        if rep == SCENE:
            # the scene's cut is the card's own: nothing else draws one
            if held is None:
                card = sc.empty(axes)
                sc.defaults(card, exts)
                held = _cards[key] = (card, [])
            return held[0]
        _iso, snap = _snapshot(vid, rep)
        if held is not None and (key in host.off or _drawn(snap) == held[1]):
            return held[0]
        drawn = _drawn(snap)
        if drawn:
            card = sc.from_boxes(snap["volumes"], snap["volumes_visible"], exts, subjects=axes)
        elif drawn is None:
            # cuts made elsewhere (an I/J/K grid in slice mode): one Slice box
            card = sc.from_cuts(snap.get("positions"), snap.get("visible"), exts)
            drawn = sc.boxes(card, exts)
        else:
            card = sc.empty(axes)
            sc.defaults(card, exts)
        _cards[key] = (card, drawn)
        return card

    def draw(vid, rep, card, infos, live):
        key = (vid, rep)
        axes = _axes(rep)
        exts = {s: info["extent"] for s, info in infos.items()}
        if not exts:
            return
        try:
            boxes = sc.boxes(card, exts, axes, whole=True if axes == IJK else ("i", "j"))
        except ValueError as exc:
            core.notifier.note(vid, f"Geometry slicer: {exc}")
            return
        whole = [[exts[a][0], exts[a][1]] for a in axes]
        cut = sc.cutting(card) and key not in host.off and boxes != [whole]
        if rep == SCENE:
            # the whole scene of the view: its composite cut by planes
            # (engine/blockscope/scene_crop), live steps moving the planes
            scene = _scene_of(vid)
            if scene is None:
                return
            bounds = [v for a in axes for v in exts[a]]
            scene.set_crop(boxes if cut else None, bounds, live=live)
            # the isolates of the view too: a grid a card isolated is drawn
            # by its own displays, not by the composite (the PO, 29/10)
            for (v, _rp), iso in list((getattr(ctx, "grid_isolates", None) or {}).items()):
                if v == vid:
                    try:
                        iso.set_scene_cut(boxes if cut else None, bounds, live=live)
                    except Exception as exc:
                        print(f"[fespp] scene cut on an isolate ({vid}):", exc, flush=True)
            _cards[key] = (card, boxes if cut else [])
            scheduler.mark_dirty(vid)
            scheduler.flush()
            return
        iso, snap = _snapshot(vid, rep)
        if cut and live and iso is not None and (snap or {}).get("mode") == "range":
            # a step: the crops on screen move, nothing else
            iso.apply_volumes(boxes, [True] * len(boxes))
            _cards[key] = (card, boxes)
            scheduler.mark_dirty(vid)
            scheduler.flush()
            return
        if cut:
            iso, _sel, _scene = _ensure_isolate(vid)
            if iso is None:
                return
            iso.apply_mode("range")
            iso.apply_volumes(boxes, [True] * len(boxes))
            _cards[key] = (card, boxes)
        else:
            _cards[key] = (card, [])
            if iso is None:
                return
            iso.apply_mode("full")
        # isolated while it cuts, a threshold or the NaN mask needs it; else
        # the composite paints the object again
        _settle_isolate(vid, rep, rep, (getattr(ctx, "blockscope_scenes", None) or {}).get(vid))
        _push_slicer_state(vid, iso)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    def _scene_cut_for_isolate(vid, iso):
        """A new isolate of a cut scene, cut as the scene is
        (app/features/slicers calls it when it makes one)."""
        held = _cards.get((vid, SCENE))
        if not held or not held[1]:
            return
        b = _scene_bounds(vid)
        if b:
            iso.set_scene_cut(held[1], b)

    ctx.scene_cut_for_isolate = _scene_cut_for_isolate

    host = CardHost(core, tool="slicers", card_key="ui_geometry_card__",
                    player_key="ui_geometry_player__", context=context, card_of=card_of,
                    draw=draw, fixed_subjects=True, extra_targets=targets_of)

    @core.lifecycle.on("view_closed")
    def _forget_view(vid):
        """A closed view's cards and scene bounds go."""
        _bounds_memo.pop(vid, None)
        _ij_memo.clear()
        for key in [k for k in _cards if k[0] == vid]:
            _cards.pop(key, None)
            _card_exts.pop(key, None)

    @controller.set("geometry_slicer")
    def geometry_slicer(edit, view_id):
        """One gesture of the Geometry slicer card (slicer_card_host)."""
        try:
            vid = str(view_id)
            if ((edit or {}).get("op") != "target" and _target(vid) == SCENE
                    and core.activation.pinned(vid, "slicers") != SCENE):
                # the scene once cut stays the card's object: an active node
                # clicked afterwards would show its own card over a scene
                # still cut, the card no longer saying what the view shows
                core.activation.pin(vid, "slicers", SCENE)
            host.gesture(edit, view_id)
        except Exception as exc:
            print(f"[fespp] geometry slicer error ({view_id}):", exc, flush=True)

    # what the isolate draws changed (a session, the assistant, a copy): the
    # card shows it (app/features/slicers._push_slicer_state calls this)
    ctx.geometry_card_publish = host.publish
    # the card's object, the whole scene included (node_helpers names it in
    # the card's title); an object ticked or unticked changes the scene's
    # extent: the card reads it again
    ctx.geometry_target = _target
    ctx.slicer_listeners = list(getattr(ctx, "slicer_listeners", None) or []) + [host.publish]
    return host
