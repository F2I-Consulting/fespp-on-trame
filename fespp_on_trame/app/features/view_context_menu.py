"""Right-click menu on the 3D view: the SAME actions as the tree's
context menu, but on what the pointer is over — plus the two camera
moves that only make sense against a picked point.

(Split out of app/features/navigation, overhaul slice 10.)"""
from fespp_on_trame.app.scene.tree_reveal import show_in_tree
from fespp_on_trame.app.ui import action_icons


def register(core, *, _cmap_array_path, _display_title, _globe_scene,
             _hl_state, _ids_to_source, _is_property_path, _nav_note,
             _nothing_under, _path_for_flat_index, _pick_region, _pv_view_of,
             _rep_path_of, _row_of_rep, _selection_ids, _surface_fallback,
             _xml_open_from_path):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    scheduler = core.scheduler
    displays = core.displays
    _mv = core.mv
    selection = core.selection
    # Right-click menu on the 3D view: the SAME actions as the tree's
    # context menu, but on what the pointer is over — plus the two camera
    # moves that only make sense against a picked point.
    _CTX_ALWAYS = (("pivot", "Set rotation center here"),
                   ("center", "Center view here"),
                   ("zoom", "Zoom here"))
    # "Show in tree": the object's row made active in its tree card, as a
    # click on it (app/scene/tree_reveal)
    _CTX_ON_REP = (("show-in-tree", "Show in tree"),
                   ("xml", "Info"),
                   # this object's slicer cards, in this view (28/10)
                   ("geometry-slicer", "Geometry slicer"),
                   ("property-slicer", "Property slicer"))
    # Offered on the property the view COLOURS the picked object by — a
    # representation carries no values of its own, and these read values.
    # Nothing colouring it, nothing to offer.
    _CTX_ON_PROP = (("add-to-stats", "Stats"),
                    ("calculator", "Derived property"))
    _CTX_WELL = (("add-to-welllog", "Add to Well Log view"),)
    # the globe menu is one entry per object it can fly to, and the menu is
    # rendered inside the panel — it scrolls past this, but a wall of wells is
    # not a menu
    _CTX_GLOBE_MAX = 12

    # the extract a right-click landed on, per view: the menu says its name
    _pixel_extract = {}
    # the point of the data under the right-click, per view (data space):
    # "Set rotation center here" turns around it
    _clicked = {}

    def _pick_pixel(vid, pvv, ev):
        """{flat index: [cell ids]} of what is under ONE pixel of the render
        (`ev` = [ox, oy, clientW, clientH] in element coordinates), or {}.
        The camera actions then act on THIS pick: it becomes the view's last
        pick."""
        from vtkmodules.vtkCommonCore import vtkCollection
        # press == release: a one-pixel region
        region = _pick_region([ev[0], ev[1], ev[0], ev[1], ev[2], ev[3]], pvv)
        by_flat = {}
        # the selection's own chain (view_pick), so the right-click and the
        # double-click name what the hand would select: the hardware pick,
        # else the fallback through what an isolate draws (a crop, a
        # threshold), each hit's ids mapped back to the source's cells (an
        # extract's are the grid's) — 04-verification D11
        if not _nothing_under(vid, pvv, region):
            hits = []
            reps, srcs = vtkCollection(), vtkCollection()
            if pvv.SMProxy.SelectSurfaceCells(region, reps, srcs, False, 0, False):
                for i in range(min(reps.GetNumberOfItems(), srcs.GetNumberOfItems())):
                    s_i = srcs.GetItemAsObject(i)
                    hits.append((reps.GetItemAsObject(i), _selection_ids(s_i)))
            if not hits:
                r_f, s_f, ids_f = _surface_fallback(pvv, region, vid)
                if s_f is not None:
                    hits = [(r_f, ids_f)]
            _pixel_extract.pop(vid, None)
            for rep_i, ids_i in hits:
                ids_i, _origin = _ids_to_source(vid, rep_i, ids_i)
                if _origin is not None:
                    _pixel_extract[vid] = _origin.get("title")
                for k in range(0, len(ids_i) - 2, 3):
                    by_flat.setdefault(ids_i[k], []).append(ids_i[k + 2])
        if by_flat:
            selection.set_pick(vid, by_flat)
        else:
            # nothing there: "Centre view here" must not fly to an old pick
            selection.drop_pick(vid)
        state[f"ui_nav_has_pick__{vid}"] = bool(by_flat)
        return by_flat

    @controller.set("view_center_here")
    def view_center_here(ev, view_id):
        """Double-click on the render: centre the view on what is under the
        pointer (the manager, 15/10), the camera turning from where it
        stands as "Centre view here" does. Nothing under the pointer,
        nothing moves; the Globe has its own fly-to menu."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        if pvv is None or not ev or len(ev) < 4 or _globe_scene(vid) is not None:
            return
        try:
            by_flat = _pick_pixel(vid, pvv, ev)
        except Exception as exc:
            print(f"[fespp] double-click pick ({vid}):", exc, flush=True)
            return
        if not by_flat:
            _nav_note(vid, "Nothing under the pointer to center on")
            return
        controller.nav_center_on_pick(vid, False, at=_point_under(vid, pvv, ev))

    def _point_under(vid, pvv, ev):
        """The point of the data under the pointer (`ev`, element
        coordinates), data space; None over nothing."""
        region = _pick_region([ev[0], ev[1], ev[0], ev[1], ev[2], ev[3]], pvv)
        point, _what = controller.cursor_hit(vid, region[0], region[1])
        return list(point) if point is not None else None

    @controller.set("view_context_menu")
    def view_context_menu(ev, view_id):
        """Right-click on the render: pick what is under the pointer, then
        publish the menu for THAT object. `ev` is
        [ox, oy, clientW, clientH] in element coordinates."""
        vid = str(view_id or "")
        mv = _mv()
        pvv = mv.get_pv_view(vid) if mv is not None else None
        if pvv is None or not ev or len(ev) < 4:
            return
        path = ""
        title = ""
        picked = ""   # the block the pointer is on, before it is resolved
        by_flat = {}  # what the pixel holds (a failed pick holds nothing)
        # the Globe first: a hardware surface pick does not come back on its
        # scene, and its menu does not need one (below)
        scene = _globe_scene(vid)
        try:
            by_flat = _pick_pixel(vid, pvv, ev) if scene is None else {}
            if by_flat:
                flat = max(by_flat, key=lambda f: len(by_flat[f]))
                p = _path_for_flat_index(flat)
                if p:
                    picked = p
                    path = _rep_path_of(p) or p
                    title = _pixel_extract.get(vid) or _display_title(path)
        except Exception as exc:
            print(f"[fespp] context pick ({vid}):", exc, flush=True)
        _clicked.pop(vid, None)
        if by_flat:
            point = _point_under(vid, pvv, ev)
            if point is not None:
                _clicked[vid] = point
        if scene is not None:
            # On the Earth the camera actions of _CTX_ALWAYS are meaningless
            # (they aim with local-CRS bounds, guarded by _nav_blocked) and a
            # surface pick cannot resolve a field that is a third of a pixel
            # wide. Offer what the view CAN do instead: fly to a named object.
            items = [action_icons.entry("globe:earth", "Whole Earth")]
            spec = scene._mark_spec.get("labels") or {}
            shown = scene._mark_spec.get("shown")
            targets = [(s, lab) for s, (lab, is_grid) in spec.items()
                       if (shown is None or s in shown) and lab]
            # grids first — they are what the user means by "the zone"
            targets.sort(key=lambda kv: (not spec[kv[0]][1], kv[1].lower()))
            items += [action_icons.entry(f"globe:{s}", f"Zoom on {lab}")
                      for s, lab in targets[:_CTX_GLOBE_MAX]]
            state[f"ui_ctx_menu__{vid}"] = {
                "open": True, "x": float(ev[0]), "y": float(ev[1]),
                "w": float(ev[2]), "h": float(ev[3]),
                "title": title or "Globe", "path": path, "items": items,
            }
            return
        # the camera actions act on the pick: offered only on something (D11)
        items = [action_icons.entry(k, lab) for k, lab in _CTX_ALWAYS] if by_flat else []
        prop = ""
        if path:
            items += [action_icons.entry(k, lab) for k, lab in _CTX_ON_REP]
            # A pick may land ON a property — a well-log channel is its own
            # block. Otherwise the values under the pointer are those of the
            # property the view colours the object by.
            ap = _cmap_array_path(vid, path)
            if _is_property_path(picked):
                prop = picked
            elif ap != path and _is_property_path(ap):
                prop = ap
            if prop:
                items += [action_icons.entry(k, lab) for k, lab in _CTX_ON_PROP]
            # a well-log track only means something on a wellbore
            nid = tree.find_node_id(path)
            wid = (tree.find_parent_node_id_with_type(nid, "Wellbore")
                   if nid is not None else None)
            if wid is not None:
                items += [action_icons.entry(k, lab) for k, lab in _CTX_WELL]
            # what features add on the picked property, else on the block
            # under the pointer (`ctx.view_menu_extras`: [(view, path) ->
            # [(key, label)]], run by `ctx.context_actions_extra`)
            for extra in getattr(ctx, "view_menu_extras", None) or ():
                items += [action_icons.entry(k, lab) for k, lab in extra(vid, prop or picked)]
        state[f"ui_ctx_menu__{vid}"] = {
            "open": True, "x": float(ev[0]), "y": float(ev[1]),
            "w": float(ev[2]), "h": float(ev[3]),
            "title": title or ("nothing under the pointer" if not path
                               else "object"),
            "path": path, "prop": prop, "items": action_icons.ordered(items),
        }

    @controller.set("view_context_action")
    def view_context_action(action, view_id):
        """Run one entry of the render's right-click menu, then close it."""
        vid = str(view_id or "")
        menu = dict(getattr(state, f"ui_ctx_menu__{vid}", None) or {})
        path = menu.get("path") or ""
        # the four value actions were offered on what the view colours the
        # picked object by, not on the object
        prop = menu.get("prop") or ""
        state[f"ui_ctx_menu__{vid}"] = {"open": False, "items": []}
        if action.startswith("globe:"):
            target = action[len("globe:"):]
            controller.globe_frame("earth" if target == "earth" else "block",
                                   vid, None if target == "earth" else target)
        elif action == "pivot":
            controller.nav_set_pivot(vid, at=_clicked.get(vid))
        elif action == "center":
            controller.nav_center_on_pick(vid, False, at=_clicked.get(vid))
        elif action == "zoom":
            controller.nav_center_on_pick(vid, True, at=_clicked.get(vid))
        elif not path:
            return
        elif action == "show-in-tree":
            show_in_tree(core.activation, core.cards, state, vid, path)
        elif action == "xml":
            _xml_open_from_path(path)
        elif action in ("geometry-slicer", "property-slicer"):
            controller.open_slicer(action, path, vid)
        elif action == "add-to-stats":
            controller.add_to_stats(prop)
        elif action == "calculator":
            controller.open_calculator(prop)
        elif action == "add-to-welllog":
            # on a log drawn on its hole: that log; else the well with its logs read
            pid = tree.find_node_id(prop) if prop else None
            on_log = pid is not None and tree.find_parent_node_id_with_type(pid, "Wellbore") is not None
            controller.add_to_welllog(prop if on_log else path, True)
        elif action in (getattr(ctx, "context_actions_extra", None) or {}):
            ctx.context_actions_extra[action](prop or path, vid)

    @controller.set("view_context_close")
    def view_context_close(view_id):
        state[f"ui_ctx_menu__{str(view_id or '')}"] = {"open": False,
                                                       "items": []}

    @controller.set("nav_projection")
    def nav_projection(view_id, parallel):
        """Perspective <-> parallel. Parallel is what makes two thicknesses
        comparable by eye — a perspective view makes the near one look
        bigger."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        if pvv is None:
            return
        try:
            pvv.CameraParallelProjection = 1 if parallel else 0
            state[f"ui_nav_parallel__{vid}"] = bool(parallel)
        except Exception as exc:
            print(f"[fespp] nav projection ({vid}):", exc, flush=True)
            return
        scheduler.mark_dirty(vid)
        scheduler.flush()
        # linked views share the camera, the projection included
        controller.camera_link_sync(vid)

    @controller.set("view_interaction_mode")
    def view_interaction_mode(view_id, mode):
        """3D <-> 2D interaction of ONE view (its title bar). 2D locks the
        rotation, which is what makes a map-like read possible without
        knocking the camera off axis on the first drag.

        Kept PER VIEW: with one global mode, the button of one view would
        show — and write — the mode of another."""
        vid = str(view_id or "")
        pvv = _pv_view_of(vid)
        want = "2D" if str(mode or "").upper() == "2D" else "3D"
        if pvv is None:
            return
        try:
            pvv.InteractionMode = want
        except Exception as exc:
            print(f"[fespp] interaction mode ({vid}):", exc, flush=True)
            return
        state[f"ui_interaction_mode__{vid}"] = want
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("set_rep_style")
    def set_rep_style(view_id, style):
        """Represent By of one view's composite rep (Display card)."""
        vid = str(view_id or "")
        if not vid or not style:
            return
        state[f"ui_rep_style__{vid}"] = style
        scene = (getattr(ctx, "blockscope_scenes", {}) or {}).get(vid)
        if scene is not None and hasattr(scene, "apply_rep_style"):
            scene.apply_rep_style(style)
        # and what the view draws outside it: isolates (crops, threshold
        # tips), extracts and the copies formulas colour (E1)
        displays.set_style(vid, style)
        scheduler.mark_dirty(vid)
        scheduler.flush()
