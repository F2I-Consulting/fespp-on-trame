"""A representation highlighted from the tree's right-click (a second call on
the same node clears it): its blocks highlighted in every view, a
trajectory's wellhead tinted with it, the highlight cleared or the rep
unselected.

(Split out of app/features/crossplot_charts, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.engine import view_routing


def register(core, *, _clear_extract_highlights, _clear_selection_of,
             _nav_note, _own_selection, _path_for_flat_index,
             _publish_sel_counts, _refresh_values, _rep_path_of, _row_of_rep):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_drop_block_highlight, _hl_state)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    active_data_source = core.active_data_source
    selector = core.selector
    scheduler = core.scheduler
    selection = core.selection
    _sel_cells = core.selection.cells
    _sel_origin = core.selection.origin
    _drop_sel_inputs = core.selection.drop_inputs
    # Last block highlighted via the tree's right-click, so a second call on
    # the same node CLEARS instead of re-selecting — highlight / un-highlight
    # with one gesture, no extra menu entry.
    _hl_state = {"path": ""}

    def _tint_wellhead(rep_path, on):
        """The wellhead (flag + name) of a highlighted TRAJECTORY follows the
        highlight: it is a companion text rep, outside the PDC, so the block
        selection cannot light it — without this the well body glows while
        its name stays mute, which is backwards when the point of the gesture
        is "which well is this?"."""
        nid = tree.find_node_id(rep_path) if rep_path else None
        if nid is None or (tree.find_type(nid) or "") != "Trajectory":
            return
        owner = selection.owner_vid
        for wh in selector.wellheads():
            if getattr(wh, "node_id", None) != nid:
                continue
            # lit in the view holding the selection only; put out everywhere
            if on and owner and getattr(wh, "view_id", None) not in (None, owner):
                continue
            try:
                wh.set_highlight(on)
            except Exception:
                pass

    def _drop_block_highlight():
        """Another gesture (pick, crossplot lasso, Values-table row) just
        wrote the source's ONE selection channel: the tree-block highlight
        is gone with it, so its wellhead tint and toggle state must not
        outlive it — else the name stays lit on a dead highlight and the
        next right-click Highlight toggles OFF instead of on."""
        if _hl_state["path"]:
            _tint_wellhead(_hl_state["path"], False)
            _hl_state["path"] = ""
            _publish_highlight()

    def _publish_highlight():
        """The tree row whose object "Select <name>" lit: what the trees'
        right-click menus read to offer "Unselect <name>" there instead —
        a panel's tree whatever the view, a 3D view's tree in the view that
        holds the selection only."""
        rep = _hl_state["path"]
        row = _row_of_rep(rep) if rep else ""
        state.ui_highlighted_row = row
        owner = selection.owner_vid
        state.ui_highlighted_row_by_view = {owner: row} if row and owner else {}

    @controller.set("clear_highlight")
    def clear_highlight():
        """Put out the whole-block selection "Select <name>" made, whichever
        row made it ("Unselect <name>" of that object, `unselect_rep`).
        Nothing silent: with nothing lit, the view says so rather than
        letting a click land on nothing."""
        vid = view_routing.resolve_active_render_panel(state)
        if not _hl_state["path"]:
            if vid:
                _nav_note(vid, "Nothing is highlighted in 3D")
            return
        from paraview import servermanager as _svm
        try:
            pysrc = _svm._getPyProxy(active_data_source.get_display_source())
            pvsimple.ClearSelection(pysrc)
            selection.owner_vid = ""
        except Exception as exc:
            print("[fespp] clear highlight:", exc, flush=True)
            if vid:
                _nav_note(vid, f"The highlight could not be cleared ({exc})")
            return
        _drop_block_highlight()
        if vid:
            _nav_note(vid, "")
        scheduler.mark_all_dirty()
        scheduler.flush()

    @controller.set("unselect_rep")
    def unselect_rep(path, view_id=None):
        """Right-click "Unselect <name>": the object of tree row `path`
        leaves the selection — its whole block when "Select <name>" lit it,
        else its cells picked in view `view_id` (every view when None); the
        other objects of the same pick stay selected."""
        from paraview import servermanager as _svm
        rep = _rep_path_of(path) or path
        if _hl_state["path"] and _hl_state["path"] == rep:
            clear_highlight()
            return
        row = _row_of_rep(rep)
        pysrc = _svm._getPyProxy(active_data_source.get_display_source())
        for vid in ([str(view_id)] if view_id else list(_sel_cells)):
            cells = _sel_cells.get(vid) or {}
            keep = {}
            for flat, ids in cells.items():
                p = _path_for_flat_index(flat)
                r = (_rep_path_of(p) if p else None) or p
                if not r or _row_of_rep(r) != row:
                    keep[flat] = ids
            if len(keep) == len(cells):
                continue        # nothing of it selected in this view
            # a point set's ids stay points (app/scene/selection_sources)
            kept_points = selection.points_of(vid) & set(keep)
            try:
                _clear_extract_highlights(vid)
                if keep:
                    from fespp_on_trame.app.scene import selection_sources
                    selection_sources.set_on(pysrc, *selection_sources.split(keep, kept_points))
                else:
                    _clear_selection_of(vid, pysrc)
            except Exception as exc:
                print(f"[fespp] unselect ({vid}):", exc, flush=True)
                _nav_note(vid, f"The selection could not be changed ({exc})")
                continue
            if keep:
                selection.hold(vid, keep, pick=True, origin=_sel_origin.get(vid),
                               points=kept_points)
            else:
                selection.drop(vid)
                state[f"ui_nav_has_pick__{vid}"] = False
                state[f"ui_pick_info__{vid}"] = "(no cell selected)"
            _publish_sel_counts(vid)
            _refresh_values(vid)
            scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("highlight_rep")
    def highlight_rep(path, view_id=None):
        """Right-click "Select <name>": select the node's WHOLE block, so
        the object lights up in every view — among a hundred wellbores,
        "which tube is this row?" needs an answer that costs one click.
        Deliberately a RIGHT-CLICK action and not a side effect of activating
        the node: ParaView has ONE selection channel per source, and an
        implicit highlight on every tree click would keep destroying a
        cross-plot lasso. Same node again = clear (and "Remove the highlight"
        clears it from anywhere, which is the entry that says so)."""
        from paraview import servermanager as _svm
        # the view it is asked from (the 3D view's menu), else the 3D view
        # one works in (a tree's menu, a panel's): it shows there only
        vid = str(view_id or view_routing.resolve_active_render_panel(state) or "")
        try:
            rep_path = _rep_path_of(path) if path else ""
            src = active_data_source.get_display_source()
            pysrc = _svm._getPyProxy(src)
            # The previous wellhead is untinted only AFTER each branch's
            # selection call succeeds: untinting first would, on a failure
            # right after, leave the old block lit with its name mute —
            # the exact state this companion tint exists to prevent.
            prev_path = _hl_state["path"]
            if not rep_path or prev_path == rep_path:
                pvsimple.ClearSelection(pysrc)
                selection.owner_vid = ""
                _hl_state["path"] = ""
                _tint_wellhead(prev_path, False)
            else:
                selector = rep_path
                sel = pvsimple.BlockSelectorsSelectionSource(
                    BlockSelectors=[selector],
                    # FESPP's own assembly: under the default hierarchy a
                    # /data selector matches nothing
                    BlockSelectorsAssemblyName="Assembly")
                import paraview.vtk as _vtk
                from paraview import selection as _pvselection
                repr_ = pvsimple.GetRepresentation(pysrc)
                rc = _vtk.vtkCollection()
                rc.AddItem(repr_.SMProxy)
                sc = _vtk.vtkCollection()
                sc.AddItem(sel.SMProxy)
                _pvselection._collectSelectionPorts(rc, sc)
                pysrc.UpdateVTKObjects()
                _own_selection(vid)
                _hl_state["path"] = rep_path
                _tint_wellhead(prev_path, False)
                _tint_wellhead(rep_path, True)
                # a whole block lit is no set of cells: the last pick's go,
                # and the grid's "+" with them (D9)
                selection.drop(vid, pick=False)
                _drop_sel_inputs(vid)
                _publish_sel_counts(vid)
        except Exception as exc:
            print("[fespp] highlight rep error:", exc, flush=True)
            return
        _publish_highlight()
        scheduler.mark_all_dirty()
        scheduler.flush()
    return (_drop_block_highlight, _hl_state)
