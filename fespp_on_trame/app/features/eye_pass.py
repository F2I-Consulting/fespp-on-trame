"""The eye pass of one view (run by the eye service, app/scene/eyes):
the eye set of the view's tree made true on its scene — blocks shown
or hidden, each grid coloured by its one colouring eye, the colour bar
chosen once per gesture — with the memories it keeps per view.

Per-view previous eye set: the "just opened" delta of the implicit
un-hide (a property eye opening shows its rep).

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import source_resolver
from fespp_on_trame.app.views import per_view_state


def register(core, *, _codes_mask_sync, _derived_array_name, _derived_gc, _derived_rep_paths,
             _derived_resolved, _extract_colour, _eye_driven_colors,
             _frame_first, _globe_refresh_marks, _globe_scene, _loaded_content,
             _property_label, _publish_session_rows, _push_active_array_label,
             _push_colormap_state, _push_timereal_state, _real_idx_for,
             _refresh_values, _rep_path_of,
             _settle_isolate, _sync_isolate_colour, _sync_panel_tree_eyes):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_eye_pass, on_eye_changed)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx

    def _holds(sel, name):
        """Whether the block `sel` can be painted by the array `name`: true
        while its datasets are not read yet (it is painted once they are),
        else when one of them holds it."""
        index = getattr(ctx, "assembly_index", None)
        sets = index.datasets(sel) if index is not None and name else []
        if not sets:
            return True
        for ds, _flat in sets:
            for data in (ds.GetCellData(), ds.GetPointData()):
                if data is not None and data.GetArray(name) is not None:
                    return True
        return False
    tree = core.tree
    source_registry = core.source_registry
    selector = core.selector
    scheduler = core.scheduler
    lifecycle = core.lifecycle
    eyes = core.eyes
    _extracts = core.selection.extracts
    # Per-view previous eye set: the "just opened" delta of the implicit
    # un-hide (a property eye opening shows its rep).
    _prev_eye = {}
    # What the eyes resolved — (association, array name, categories, their
    # note) by (view, rep, path, realization) under the loaded content
    # (`_loaded_content`): a step of a stepped read re-dispatches every open
    # eye of every view, and resolving each one again read the data
    # information of every visible channel and property, 26 ms each
    # (measured 12/10, bench `step_cost`). An entry lives while its eye
    # stays open; an eye closed drops it, so a rep unloaded and loaded again
    # is resolved anew.
    _eye_memo = {}

    @lifecycle.on("view_closed")
    def _forget_eyes_of(vid):
        """A closed view's eye memories go with it (02-carte M6)."""
        _eye_driven_colors.pop(vid, None)
        _prev_eye.pop(vid, None)
        for k in [k for k in _eye_memo if isinstance(k, tuple) and k and k[0] == vid]:
            _eye_memo.pop(k, None)
        eyes.forget(vid)

    def _eye_pass(vid, paths):
        # The eye pass of one view, run by the eye service (app/scene/eyes):
        # legacy -> per-view rep visibility reconcile; blockscope -> per-block
        # BlockSelectors on that view's PdcScene (a rep is a selector string,
        # not a proxy).
        if not per_view_state.is_live(vid):
            return
        # Busy flag for the slow Globe paths. When this runs from the eye
        # watcher it is already INSIDE a flush, so `state.flush()` is a no-op
        # (trame skips a re-entrant flush) and the flag never reaches the
        # client; eye clicks are fast enough for that not to matter. It does
        # reach the client on the paths called outside a flush, which are the
        # slow ones (opening a Globe view, inheriting eyes), and the final
        # flush below guarantees the bar switches back off there.
        busy = _globe_scene(vid) is not None
        if busy:
            ctx.view_busy(f"eye:{vid}", [vid], True)
            state.flush()
        try:
            # A grid shows ONE property at a time, a formula included (the
            # PO, 16/10: the derived eye stayed open): the exclusivity rule
            # of the pass covers it, its eye being in the same set
            _apply_eye_change(vid, paths)
            # the docked trees draw the same eyes and have no view of
            # their own: whatever any 3D view shows, they must show too
            _sync_panel_tree_eyes()
            # the Values card of a geometry shows the property its eye
            # opened: another eye, another column (the PO, 16/10); on a
            # folder, another eye can be another node
            core.activation.values_update(vid)
            _refresh_values(vid)
            # the formulas no view shows any more leave the blocks
            _derived_gc()
            _publish_session_rows(vid)
        finally:
            if busy:
                ctx.view_busy(f"eye:{vid}", (), False)
                state.flush()


    @controller.set("on_eye_changed")
    def on_eye_changed(vid, paths):
        """Apply `paths` as the view's eye set now (its callers have
        written it)."""
        eyes.apply(vid, paths)

    @controller.set("on_eye_watch")
    def on_eye_watch(vid, paths):
        """The tree's state watcher: the set changed in the state."""
        eyes.on_watch(vid, paths)

    def _rep_kind(rep_path):
        nid = tree.find_node_id(rep_path) if rep_path else None
        return (tree.find_type(nid) or "") if nid is not None else ""

    def _log_wellbore(rep_path):
        """The node id of the wellbore whose log frame `rep_path` is; None
        for any other representation, or a frame under no wellbore."""
        nid = tree.find_node_id(rep_path) if rep_path else None
        if nid is None or (tree.find_type(nid) or "") != "Frame":
            return None
        return tree.find_parent_node_id_with_type(nid, "Wellbore")

    def _colours_its_rep(path):
        """Is this leaf one that COLOURS its rep — a property rather than a
        marker?

        A rep carries ONE ColorArrayName, so two such eyes on the same rep
        cannot both be true: the second silently replaces the first, and the
        tree would show N open eyes for a single visible colouring.
        Exclusivity is therefore a property of the CHILD, not of the rep's
        visibility policy (a ONE_AT_A_TIME test would catch log frames and
        miss grids). Markers are VISIBILITY_ONLY — their own geometry, many
        at once — and are left alone. A formula colours its grid."""
        if derived_props.is_derived(path):
            return True
        try:
            from fespp_on_trame.engine.element_type import registry
            from fespp_on_trame.engine.element_type.enums import ColorPolicy
            et = registry.for_kind(_rep_kind(path))
            return et is not None and et.color_policy() == ColorPolicy.COLORABLE
        except Exception:
            return False

    def _block_datasets(sel):
        """The leaf datasets of the block `sel` of the shared source."""
        index = getattr(ctx, "assembly_index", None)
        return [ds for ds, _flat in (index.datasets(sel) if index is not None and sel else ())]

    def _held_assoc(sel, name, assoc):
        """Where the block `sel` holds `name`: the shared source says where
        ANY of its blocks does, and a grid's property is on cells where a
        log of the same name is on points."""
        from fespp_on_trame.engine import categorical_palette
        for ds in _block_datasets(sel):
            arr, where = categorical_palette.held_array(ds, name, assoc)
            if arr is not None:
                return where
        return assoc

    def _categories_of(rep_path, name, source, assoc, sel=None):
        """The codes of a discrete or categorical property and their names,
        for the view's LUT to paint one colour per code; (None, why) when
        the property is continuous ("" then) or cannot be painted by code.
        Read on the block `sel` the property colours."""
        from fespp_on_trame.engine import categorical_palette
        try:
            reader = source_registry.shared_source()
        except Exception:
            reader = None
        try:
            return categorical_palette.categories_for(
                tree, rep_path, name, source, assoc, reader=reader, datasets=_block_datasets(sel))
        except Exception as exc:
            print(f"[fespp] categories of {name!r}:", exc, flush=True)
            return None, f"could not read the codes of {name}: {exc}"

    def _wellheads_follow(vid):
        """Wellhead companions (Text reps, outside the composite) follow their
        trajectory in the view they decorate: shown where it is drawn — its
        eye open, its domain the view's —, never on the Earth: a head sits at
        projected coordinates (D8)."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        drawn = scene.shown_selectors() if scene is not None else set()
        for wh in selector.wellheads():
            if getattr(wh, "view_id", None) != vid:
                continue
            tp = tree.find_path(wh.node_id)
            wh.set_visible(bool(tp) and tp in drawn and _globe_scene(vid) is None)

    ctx.wellheads_follow = _wellheads_follow

    def _apply_eye_change(vid, paths):
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is not None:
            from fespp_on_trame.engine.etp_debug import etp_debug as _edbg
            paths = list(paths or [])
            # the view's one colour bar is chosen once for the whole pass
            # (engine/legends), against the tables before it
            scene.begin_bar_gesture()
            rep_of = {p: _rep_path_of(p) for p in paths}
            # Exclusive active property: ONE colouring eye per rep — the
            # most recently opened (last in the list: the widget and the
            # born-visible echo both APPEND) closes its siblings. Only
            # colouring leaves are exclusive: a log Frame shows one channel
            # at a time, a MarkerFrame shows all its markers at once.
            # Every earlier colouring leaf is dropped from the eye set, so
            # the tree shows exactly what is actually painted. A wellbore
            # shows one log at a time, whichever of its log frames holds it:
            # the log opened last closes those of its other frames, and a
            # frame left without a log closes with them (alone it draws
            # nothing).
            last_arr, well_of, last_well = {}, {}, {}
            for p in paths:
                rp = rep_of[p]
                if rp and p != rp and _colours_its_rep(p):
                    last_arr[rp] = p
                    well = _log_wellbore(rp)
                    if well is not None:
                        well_of[p] = well
                        last_well[well] = p
            cleaned = [p for p in paths
                       if not (rep_of[p] and p != rep_of[p]
                               and ((rep_of[p] in last_arr and last_arr[rep_of[p]] != p)
                                    or (p in well_of and last_well[well_of[p]] != p)))]
            bare = ({rep_of[p] for p in well_of if p not in cleaned}
                    - {rep_of[p] for p in cleaned if rep_of[p] and p != rep_of[p]})
            cleaned = [p for p in cleaned if p not in bare]
            if cleaned != paths:
                # Echo back so the loser chips close in the widget; the
                # watcher re-fires with the cleaned list and converges.
                state[f"visible_paths__{vid}"] = cleaned
                paths = cleaned
            # "Implicit un-hide": a property eye that just OPENED
            # shows its rep in this view (a 2nd view starts with every
            # eye closed, so eyeing the property alone would show
            # nothing). DELTA only: a geometry the user closed later
            # stays closed while the property eye merely persists.
            prev = _prev_eye.get(vid, set())
            added = []
            for p in list(paths):
                rp = rep_of.get(p)
                if rp and p != rp and p not in prev and rp not in paths:
                    paths.append(rp)
                    rep_of[rp] = rp
                    added.append(rp)
            if added:
                state[f"visible_paths__{vid}"] = list(paths)
            _prev_eye[vid] = set(paths)
            memo = _eye_memo.setdefault(_loaded_content(), {})
            open_now = set(paths)
            for key in [k for k in memo if k[0] == vid and k[2] not in open_now]:
                memo.pop(key, None)

            def _resolved(rp, p, default_assoc, sel):
                # the eye's array on the block `sel` it colours, from the
                # memo while the eye stayed open, from the data information
                # otherwise
                if derived_props.is_derived(p):
                    # a formula: its array on the grid's blocks
                    got = _derived_resolved(vid, p, p not in prev)
                    return None if got is None else (got[0], got[1], None, "")
                ridx = _real_idx_for(vid, p)
                key = (vid, rp, p, ridx)
                hit = memo.get(key) if p in prev else None
                if hit is not None:
                    return hit
                assoc, name, _s = source_resolver.resolve_array_for_path(
                    source_registry, tree, rp, p, realization_idx=ridx)
                if not name:
                    return None
                assoc = _held_assoc(sel, name, assoc or default_assoc)
                cats, cat_note = _categories_of(rp, name, _s, assoc, sel)
                memo[key] = (assoc, name, cats, cat_note)
                return memo[key]

            want = set()
            eye_colored = {}
            for p in paths:
                rp = rep_of[p]
                if not rp:
                    # BlockScope: a node with no single rep leaf (a Well,
                    # a folder) is ITSELF a valid SUBTREE BlockSelector —
                    # the composite matches every descendant block (a
                    # folder eye = one subtree selector). No
                    # index guard: the index is built on the /Root
                    # hierarchy, not the /data assembly paths, and a
                    # non-matching selector is simply inert.
                    want.add(p)
                    continue
                sel = rp
                # A LOG CHANNEL is already its OWN block of the shared PDC:
                # the Frame node owns no dataset, its channel does, and the
                # C++ side builds that block through a vtkTubeFilter in
                # VaryRadiusByScalar — the tube's very SHAPE is the channel
                # value. So select and colour the CHANNEL leaf, never the
                # Frame folder: selecting the folder pulls every channel in
                # at once and paints it a flat solid colour, so neither the
                # shape nor the colour would follow the eye. Costs zero
                # extra proxy: it is the same composite.
                if _rep_kind(rp) == "Frame":
                    if p == rp:
                        continue      # the folder itself renders nothing
                    want.add(p)
                    try:
                        found = _resolved(rp, p, "POINTS", p)
                        if found is not None:
                            assoc, name, cats, cat_note = found
                            scene.set_color(p, name, assoc or "POINTS",
                                            label=_property_label(p),
                                            categories=cats,
                                            categories_note=cat_note)
                            eye_colored[p] = p
                    except Exception as exc:
                        print(f"[fespp] log channel color ({vid}):", exc,
                              flush=True)
                    continue
                if p == rp:
                    # Geometry/rep eye = the ONLY dataset hide/show.
                    want.add(sel)
                    continue
                # Array eye = colorBy only — it never forces the dataset
                # visible (so the grid can be hidden while its property
                # still colours the derived BlockedWellbores).
                try:
                    # MR property: the VTK arrays are '<name>_real_<n>'
                    # — without a realization index the resolver looks
                    # for the bare name, finds nothing, and the eye
                    # silently colours nothing (`_real_idx_for`, in the
                    # memo's key).
                    found = _resolved(rp, p, "CELLS", sel)
                    if found is not None:
                        assoc, name, cats, cat_note = found
                        formula = derived_props.is_derived(p)
                        label = _derived_array_name(p) if formula else _property_label(p)
                        scene.set_color(sel, name, assoc or "CELLS",
                                        label=label, categories=cats,
                                        categories_note=cat_note)
                        eye_colored[sel] = p
                        # the subsets that mirror the grid's arrays (its
                        # blocked wellbores) do not carry a formula's yet; a
                        # subset read without the array (a fault's faces)
                        # keeps its own colour, white otherwise
                        for dp in ([] if formula else _derived_rep_paths(rp)):
                            dsel = dp
                            if dsel not in eye_colored and _holds(dsel, name):
                                scene.set_color(dsel, name,
                                                assoc or "CELLS",
                                                label=label,
                                                categories=cats,
                                                categories_note=cat_note)
                                eye_colored[dsel] = p
                except Exception:
                    pass
            # SolidColor fallback: a rep whose LAST array eye just
            # closed reverts to its geometry solid colour — clear the
            # anchor this eye set had driven.
            for sel in _eye_driven_colors.get(vid, {}):
                if sel not in eye_colored:
                    try:
                        scene.set_color(sel, "")
                    except Exception:
                        pass
            _eye_driven_colors[vid] = eye_colored
            # the blocks' visibility FIRST: an isolate and an extract
            # decide whether they draw from it (app/scene/occupancy), and
            # following a visibility not yet applied left them to the
            # next pass (W1)
            _edbg(f"eye({vid}): paths={list(paths or [])} want={sorted(want)} "
                  f"visible_before={sorted(scene.visible_selectors())}")
            scene.set_visible_many(want, scene.visible_selectors() - want)
            # a live isolate of this view follows the eye's colour too:
            # its crops are its own displays, the composite's ColorBy
            # never reaches them
            for (ivid, ipath), iso in list((getattr(ctx, "grid_isolates", None) or {}).items()):
                if ivid != vid:
                    continue
                try:
                    isel = ipath
                    # its cell mask follows the colour: when it changed the
                    # grid is settled again (a mask gone may release it)
                    if _sync_isolate_colour(iso, isel, scene):
                        _settle_isolate(vid, ipath, isel, scene)
                except Exception as exc:
                    print(f"[fespp] isolate recolour ({vid}):", exc, flush=True)
            # a grid shown, or painted anew, by a property whose table puts
            # codes at opacity 0 gets the mask that takes their cells out
            try:
                _codes_mask_sync(vid)
            except Exception as exc:
                print(f"[fespp] codes at opacity 0 ({vid}):", exc, flush=True)
            # and so do its selection extracts
            for e in list(_extracts.get(vid, [])):
                _extract_colour(e)
            scene.end_bar_gesture()
            # The Attributes card displays the eye-driven colorBy (no
            # picker there) — keep its label live for the active rep.
            # After the flip: the Colormap card falls back to the table
            # holding the bar, which is only known once the pass is done.
            try:
                _push_active_array_label(vid)
                _push_colormap_state(vid)
                _push_timereal_state(vid)
            except Exception:
                pass
            # an isolated grid is drawn by its isolate, which the composite's
            # visibility never reaches: its displays follow the eye here, and
            # an isolate nothing needs any more (the NaN mask off because
            # the colour moved to a node property) hands the block back
            for (ivid, ipath), iso in list((getattr(ctx, "grid_isolates", None) or {}).items()):
                if ivid != vid:
                    continue
                try:
                    isel = ipath
                    _settle_isolate(vid, ipath, isel, scene)
                except Exception as exc:
                    print(f"[fespp] isolate eye ({vid}):", exc, flush=True)
            _wellheads_follow(vid)
            # One-shot framing HERE, once blocks are actually visible:
            # the _on_loaded_reps check runs before the born-visible
            # cascade lands, and nothing else frames the UTM data into
            # view. Visible is drawn: an object of the other domain is not,
            # and a view framed on nothing would never frame on its switch.
            _globe_refresh_marks(vid)
            # the time-depth model's columns, shown with its grid
            pins = getattr(ctx, "time_depth_pins_refresh", None)
            if pins is not None:
                pins(vid)
            if scene.shown_selectors() and vid not in per_view_state.FRAMED:
                try:
                    if _frame_first(vid):
                        per_view_state.FRAMED.add(vid)
                except Exception:
                    pass
            scheduler.flush()
            return
        # no scene yet (a view not wired): its eyes are applied when the
        # scene is born
        scheduler.flush()
        return
    return (_eye_pass, on_eye_changed)
