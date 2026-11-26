"""The selection state of a view, shared by picking, the cursor, the
Values card and the extracts: the picked cells by view, their origin
and owner, the highlight inputs, the ids under a pick region, and
the clearing of a view's selection.

(Moved out of app/boot, overhaul slice 10.)"""
from paraview import simple as pvsimple


def register(core, *, _publish_sel_counts):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_clear_extract_highlights, _clear_selection_of, _display_xy, _leaf_dataset, _own_selection, _path_for_flat_index, _pick_region, _refresh_values, _selection_ids, _selection_off)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    active_data_source = core.active_data_source
    scheduler = core.scheduler
    selection = core.selection
    _extracts = core.selection.extracts
    _drop_sel_inputs = core.selection.drop_inputs
    # View picking (hand button) + cursor position (crosshair button).
    def _display_xy(ev, pvv):
        """Client element offsets [ox, oy, cw, ch] -> VTK display pixel
        (origin bottom-left) in the PV view's own size."""
        ox, oy, cw, ch = [float(v) for v in ev[:4]]
        w, h = [int(v) for v in pvv.ViewSize]
        x = int(round(ox * w / max(1.0, cw)))
        y = int(round((ch - oy) * h / max(1.0, ch)))
        return max(0, min(w - 1, x)), max(0, min(h - 1, y))

    def _path_for_flat_index(flat):
        """Assembly node path of the PDC leaf dataset with PV composite
        (flat) index `flat` — what a surface pick reports: the deepest
        node owning it (the assembly index)."""
        return ctx.assembly_index.selector_for_flat(flat)

    def _pick_region(ev, pvv):
        """Client [x0, y0, x1, y1, cw, ch] (element offsets of the press and
        the release) -> VTK display rectangle [xmin, ymin, xmax, ymax]; a
        click is a one-pixel region."""
        x0, y0 = _display_xy([ev[0], ev[1], ev[4], ev[5]], pvv)
        x1, y1 = _display_xy([ev[2], ev[3], ev[4], ev[5]], pvv)
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]

    def _selection_ids(sel_src):
        """[flat, proc, cell, ...] triples of an index selection source."""
        prop = sel_src.GetProperty("IDs") if sel_src is not None else None
        if prop is None:
            return []
        return [int(prop.GetElement(k)) for k in range(prop.GetNumberOfElements())]

    def _leaf_dataset(flat):
        """The source's leaf dataset with flat index `flat` (the index)."""
        return ctx.assembly_index.dataset(flat)

    # the per-view selection state (cells, last pick, origin, inputs, owner,
    # extracts) is app/scene/selection's (core.selection)

    def _clear_extract_highlights(vid):
        """A pick on an extract highlights ITS cells: cleared with the rest."""
        for e in list(_extracts.get(vid) or []):
            try:
                pvsimple.ClearSelection(e["ex"])
            except Exception as exc:
                print(f"[fespp] extract highlight ({vid}):", exc, flush=True)

    def _refresh_values(vid):
        """Recompute the Attributes card's page as it stands (same offset,
        filters and "selected only"), when it shows one — an error page
        too: the property it could not read may have arrived since (the PO,
        21/10). A property ticked or unticked, or a new selection, changes
        what it holds."""
        page = (state.ui_node_values_by_view or {}).get(vid) or {}
        if not page:
            return
        controller.node_values({"offset": 0 if page.get("only") else page.get("offset", 0),
                                "min": page.get("min"), "max": page.get("max"),
                                "only": bool(page.get("only")),
                                "hide_nan": page.get("hide_nan"),
                                "filter": page.get("filter_on") or "",
                                "filters": page.get("filters") or [],
                                "part": page.get("part") or "",
                                "assoc": page.get("assoc") if page.get("geometry") else None}, vid)

    # The shared source has ONE selection (ParaView's). It belongs to the
    # view that made it, the only one that draws it (the PO, 16/10: a
    # selection made in one view must not show in the others): selecting in
    # another view moves it there, and the first view's cards forget theirs.
    state.setdefault("ui_highlighted_row_by_view", {})

    def _own_selection(vid):
        """The source's selection is now view `vid`'s: drawn there only."""
        vid = str(vid or "")
        selection.owner_vid = vid
        for v, scene in list((getattr(ctx, "blockscope_scenes", None) or {}).items()):
            try:
                scene.show_selection(v == vid)
            except Exception as exc:
                print(f"[fespp] selection owner ({v}):", exc, flush=True)
            if v != vid:
                _forget_selection(v)

    def _clear_selection_of(vid, pysrc=None):
        """Clear the source's selection when view `vid` holds it, or nobody
        does: a view holding none must not take another view's away (an
        empty click there, its selection tool turned off). True if cleared."""
        if selection.owner_vid not in ("", str(vid or "")):
            return False
        from paraview import servermanager as _svm
        src = active_data_source.get_display_source() if pysrc is None else None
        if pysrc is None and src is None:
            return False
        pvsimple.ClearSelection(pysrc if pysrc is not None else _svm._getPyProxy(src))
        selection.owner_vid = ""
        return True

    def _forget_selection(vid):
        """View `vid` no longer holds the selection: its cards say so."""
        had = selection.drop(vid)
        _drop_sel_inputs(vid)
        _clear_extract_highlights(vid)
        if had:
            state[f"ui_nav_has_pick__{vid}"] = False
            state[f"ui_pick_info__{vid}"] = "(no cell selected)"
            _publish_sel_counts(vid)
            _refresh_values(vid)
            scheduler.mark_dirty(vid)

    def _selection_off(vid):
        """No selection tool left on in this view: its selection goes, in
        3D and in the Attributes card (the manager, 15/10: turning the tool
        off left the cells highlighted) — another view's stays."""
        if getattr(state, f"ui_pick_mode__{vid}", False) or getattr(
                state, f"ui_frustum_mode__{vid}", False):
            return
        try:
            _clear_selection_of(vid)
        except Exception as exc:
            print(f"[fespp] selection off ({vid}):", exc, flush=True)
        selection.drop(vid)
        _drop_sel_inputs(vid)
        _clear_extract_highlights(vid)
        state[f"ui_nav_has_pick__{vid}"] = False
        state[f"ui_pick_info__{vid}"] = ""
        _publish_sel_counts(vid)
        _refresh_values(vid)
        scheduler.mark_all_dirty()
        scheduler.flush()
    return (_clear_extract_highlights, _clear_selection_of, _display_xy, _leaf_dataset, _own_selection, _path_for_flat_index, _pick_region, _refresh_values, _selection_ids, _selection_off)
