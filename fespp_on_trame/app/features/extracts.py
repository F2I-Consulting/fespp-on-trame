"""Selection extracts: a grid's highlighted cells KEPT or REMOVED as an
ExtractSelection of its block (the "+" on the grid's tree row, the PO
15/10), their rows in the session's tree (eye, remove), and their specs
saved with a session and made again when it is restored (D2).

(Moved out of app/boot, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.engine.state_defaults import z_scale_of


def register(core, *, _derived_fanout, _derived_forget, _display_title, _extract_cells,
             _extract_colour, _extract_layout, _extract_seq, _globe_scene,
             _live_render_vids, _nav_note, _pdc_flats, _publish_session_rows, _push_active_array_label, _pv_view_of,
             _refresh_calculator, _refresh_values, _rep_path_of, _row_of_rep):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    active_data_source = core.active_data_source
    eyes = core.eyes
    displays = core.displays
    scheduler = core.scheduler
    _derived_store = core.derived_store
    selection = core.selection
    _sel_cells = core.selection.cells
    _sel_origin = core.selection.origin
    _extracts = core.selection.extracts
    def _drop_extract(e, publish=True):
        displays.remove(e["vid"], f"extract:{e['id']}")
        pvv = _pv_view_of(e["vid"])
        for proxy in (e.get("ex"), e.get("blk")):
            try:
                if proxy is e.get("ex") and pvv is not None:
                    pvsimple.Hide(proxy, pvv)
                pvsimple.Delete(proxy)
            except Exception as exc:
                print(f"[fespp] extract drop ({e['vid']}):", exc, flush=True)
        lst = _extracts.get(e["vid"], [])
        if e in lst:
            lst.remove(e)
        if _sel_origin.get(e["vid"]) == e["id"]:
            selection.clear_origin(e["vid"])
        if publish:
            _extract_layout(e["vid"], e["selector"], e["rep_path"])
            _publish_session_rows(e["vid"])

    @controller.set("selection_extract")
    def selection_extract(payload, view_id):
        """The "+" of a grid's tree row: {path, mode} — "keep" the cells
        highlighted in this view, or "remove" them."""
        from paraview import servermanager as _svm
        vid = str(view_id or "")
        if _globe_scene(vid) is not None:
            # an extract is drawn in local metres: never on the Earth (D13)
            _nav_note(vid, "No extract on the Earth: keep or remove cells in a 3D view")
            return
        p = payload or {}
        mode = "remove" if p.get("mode") == "remove" else "keep"
        row = str(p.get("path") or "")
        rep_path = _rep_path_of(row) or row
        # the assembly path IS the selector (engine/blockscope/assembly_index)
        selector = rep_path
        pvv = _pv_view_of(vid)
        if not selector or pvv is None:
            _nav_note(vid, "This grid is not drawn in this view")
            return
        own = list(ctx.assembly_index.flat_indices(rep_path, subtree=False))
        spec = p.get("cells")
        if spec is not None:
            # a saved session's extract made again: its cells by the grid's
            # block ordinal, as runs (session_restore_extracts)
            from fespp_on_trame.engine.utils.runs import from_runs
            picked = {own[i]: from_runs(runs) for i, runs in spec
                      if 0 <= int(i) < len(own)}
            base = None
            invert = bool(p.get("invert"))
            field = "POINT" if p.get("field") == "POINT" else "CELL"
        else:
            picked = {f: c for f, c in (_sel_cells.get(vid) or {}).items() if f in own}
            if not picked:
                _nav_note(vid, "No cell of this grid is highlighted in this view")
                return
            # a point set's selection is of its points: they are what is kept
            # or taken out (app/scene/selection_sources)
            field = "POINT" if set(picked) <= selection.points_of(vid) else "CELL"
            # a selection made ON an extract works from it: "remove" takes the
            # cells out of THAT extract, not out of the whole grid (the PO, 15/10)
            base = next((x for x in _extracts.get(vid, [])
                         if x["id"] == _sel_origin.get(vid) and x["rep_path"] == rep_path), None)
            if base is not None and field == "POINT":
                # an extract of points carries no cell ids to work from: the
                # points are kept or taken out of the whole point set
                base = None
            if base is not None and mode == "remove":
                import numpy as np
                held = _extract_cells(base)
                picked = {f: np.setdiff1d(cells, np.asarray(picked.get(f, []), dtype="int64")).tolist()
                          for f, cells in held.items()}
                invert = False
            else:
                invert = mode == "remove"
        _extract_seq[0] += 1
        eid = f"x{_extract_seq[0]}"
        blk = ex = None
        try:
            src = active_data_source.get_display_source()
            pysrc = src if hasattr(src, "SMProxy") else _svm._getPyProxy(src)
            blk = pvsimple.ExtractBlock(registrationName=f"selection_{eid}_block__{vid}", Input=pysrc)
            try:
                blk.Assembly = "Assembly"
            except Exception as exc:
                print(f"[fespp] extract block assembly ({vid}):", exc, flush=True)
            blk.Selectors = [selector]
            blk.UpdatePipeline()
            # the grid's datasets in the extracted block, in the source's
            # order: the selection's composite indices are re-based on them
            bout = blk.GetClientSideObject().GetOutputDataObject(0)
            blk_flats = _pdc_flats(bout, rep_path)
            mapping = dict(zip(own, blk_flats)) if len(own) == len(blk_flats) else {}
            ids = []
            for f, cells in picked.items():
                bf = mapping.get(f)
                if bf is not None:
                    for c in cells:
                        ids += [bf, 0, int(c)]
            if not ids:
                raise RuntimeError("the highlighted cells could not be matched to the grid's block"
                                   if base is None else "nothing of the extract would be left")
            selsrc = _svm.sources.CompositeDataIDSelectionSource(
                IDs=ids, FieldType=field, InsideOut=1 if invert else 0)
            ex = pvsimple.ExtractSelection(registrationName=f"selection_{eid}__{vid}",
                                           Input=blk, Selection=selsrc)
            ex.UpdatePipeline()
            info_ = ex.GetDataInformation()
            n = int(info_.GetNumberOfPoints() if field == "POINT" else info_.GetNumberOfCells())
            disp = pvsimple.Show(ex, pvv)
            disp.Representation = getattr(state, f"ui_rep_style__{vid}", None) or "Surface"
            disp.Scale = [1.0, 1.0, z_scale_of(state, vid)]
        except Exception as exc:
            print(f"[fespp] selection extract ({vid}):", exc, flush=True)
            for proxy in (ex, blk):
                try:
                    if proxy is not None:
                        pvsimple.Delete(proxy)
                except Exception as exc2:
                    print(f"[fespp] extract cleanup ({vid}):", exc2, flush=True)
            _nav_note(vid, f"The selection could not be extracted: {exc}")
            return
        k = sum(len(c) for c in (_sel_cells.get(vid) or {}).values()) if base is not None else len(ids) // 3
        grid = _display_title(rep_path, rep_path.rsplit("/", 1)[-1])
        word = "points" if field == "POINT" else "cells"
        title = (f"Kept #{eid[1:]} · {numfmt.fmt_int(n)} {word}" if mode == "keep"
                 else f"Removed #{eid[1:]} · {numfmt.fmt_int(n)} {word} left")
        if base is not None:
            title += f" (from #{base['id'][1:]})"
        from fespp_on_trame.engine.utils.runs import to_runs
        e = {"id": eid, "vid": vid, "path": f"session://{vid}/{eid}", "row": _row_of_rep(rep_path),
             "rep_path": rep_path, "selector": selector, "mode": mode, "visible": True,
             "blk": blk, "ex": ex, "disp": disp, "title": title,
             # what a session keeps to make it again: the cells by the grid's
             # block ordinal (a composite index changes from one load to the
             # next), as runs, and whether they are kept or taken out
             "spec": {"cells": [[own.index(f), to_runs(c)] for f, c in picked.items() if f in own],
                      "invert": invert, "field": field},
             "info": (f"{grid}: the {numfmt.fmt_int(k)} highlighted {word[:-1]}(s) "
                      + ("kept" if mode == "keep" else "taken out")
                      + " — made in this session, not in the file; the grid comes back"
                        " when this is hidden or deleted")}
        if p.get("title"):
            # a saved session's name for it
            e["title"] = " ".join(str(p["title"]).split())[:80]
            e["named"] = True
        _extracts.setdefault(vid, []).append(e)
        displays.add(vid, f"extract:{eid}", "extract", disp, follows_style=True,
                     close=lambda e=e: _drop_extract(e, publish=False))
        _extract_colour(e)
        # the extract it was made from steps aside (kept in the tree, hidden)
        if base is not None and base["visible"]:
            base["visible"] = False
            try:
                pvsimple.Hide(base["ex"], pvv)
            except Exception as exc:
                print(f"[fespp] extract: hide #{base['id']} ({vid}):", exc, flush=True)
        # the selection stays: a Keep can be followed by a Remove of the same
        # cells, and the reader clears it
        _extract_layout(vid, selector, rep_path)
        _publish_session_rows(vid)
        _nav_note(vid, title)

    def _session_extract(vid, path):
        for e in _extracts.get(vid, []):
            if e["path"] == path:
                return e
        return None

    @controller.set("session_view_extracts")
    def session_view_extracts(view_id):
        """What a session keeps of this view's selection extracts, in the
        order they were made (04-verification D2); `path` is what the rest of
        the document names one by, it comes back under another."""
        return [{"path": e["path"], "rep_path": e["rep_path"], "row": e["row"], "mode": e["mode"],
                 "cells": e["spec"]["cells"], "invert": bool(e["spec"]["invert"]),
                 "field": e["spec"].get("field", "CELL"),
                 # a name the reader gave it
                 "title": e["title"] if e.get("named") else None,
                 "visible": bool(e["visible"])}
                for e in _extracts.get(str(view_id), []) if e.get("spec")]

    @controller.set("session_restore_extracts")
    def session_restore_extracts(view_id, specs):
        """The view's selection extracts made as saved: the ones it holds
        go first, then each saved one is made again, shown or hidden. Returns
        {the path one was saved under: its path now}."""
        vid = str(view_id or "")
        for e in list(_extracts.get(vid, [])):
            _drop_extract(e)
        back = {}
        for sp in specs or ():
            n_before = len(_extracts.get(vid, []))
            selection_extract({"path": sp.get("row") or sp.get("rep_path") or "",
                               "mode": sp.get("mode") or "keep",
                               "cells": sp.get("cells") or [],
                               "invert": bool(sp.get("invert")),
                               "field": sp.get("field") or "CELL",
                               "title": sp.get("title")}, vid)
            lst = _extracts.get(vid, [])
            if len(lst) > n_before:
                back[sp.get("path")] = lst[-1]["path"]
                if not sp.get("visible", True):
                    session_row_eye({"path": lst[-1]["path"]}, vid)
        return back

    @controller.set("session_row_eye")
    def session_row_eye(payload, view_id):
        """The eye of a session row: an extract shown or hidden in its view
        (the grid gives it its place, or takes it back)."""
        vid = str(view_id or "")
        path = str((payload or {}).get("path") or "")
        if derived_props.is_derived(path):
            # an eye like any property's (app/scene/eyes)
            eyes.toggle(vid, path)
            _publish_session_rows(vid)
            # the geometry's Values card follows the formula's eye too, and
            # so does the Attributes card's "Colored by"
            _refresh_values(vid)
            _push_active_array_label(vid)
            return
        e = _session_extract(vid, path)
        if e is None:
            return
        _extract_shown(vid, e, not e["visible"])
        _extract_layout(vid, e["selector"], e["rep_path"])
        _publish_session_rows(vid)

    def _extract_shown(vid, e, shown):
        """The extract `e` drawn in view `vid`, or not."""
        e["visible"] = shown
        pvv = _pv_view_of(vid)
        try:
            if shown:
                pvsimple.Show(e["ex"], pvv)
            else:
                pvsimple.Hide(e["ex"], pvv)
        except Exception as exc:
            print(f"[fespp] extract eye ({vid}):", exc, flush=True)

    @controller.set("extracts_step_aside")
    def extracts_step_aside(rep_path, view_id):
        """The closed eye of a geometry an extract stands in for, opened:
        the grid drawn again, every extract shown in its place hidden (their
        rows stay, their eyes closed)."""
        vid = str(view_id or "")
        mine = [e for e in _extracts.get(vid, []) if e["rep_path"] == rep_path and e["visible"]]
        for e in mine:
            _extract_shown(vid, e, False)
        if mine:
            _extract_layout(vid, mine[0]["selector"], rep_path)
            _publish_session_rows(vid)

    @controller.set("session_row_rename")
    def session_row_rename(payload, view_id):
        """The pencil of an extract's row: its name, as the reader writes it
        (the PO, 20/10) — kept in a saved session. An empty name is no name:
        the row keeps the one it had. {path, title} (or `name`, a harness's
        word: its `title` would read as a node to find)."""
        vid = str(view_id or "")
        p = payload or {}
        e = _session_extract(vid, str(p.get("path") or ""))
        title = " ".join(str(p.get("title") or p.get("name") or "").split())[:80]
        if e is None or not title or title == e["title"]:
            return
        e["title"] = title
        e["named"] = True
        # the tree rows (and, through them, the Statistics rows), then the
        # view: its legends name the extract by its new name (the PO, 21/10)
        _publish_session_rows(vid)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("session_row_remove")
    def session_row_remove(payload, view_id):
        """The × of a session row: an extract deleted (its grid comes back),
        or a derived property dropped from the calculator."""
        vid = str(view_id or "")
        path = str((payload or {}).get("path") or "")
        e = _session_extract(vid, path)
        if e is not None:
            _drop_extract(e)
            return
        if derived_props.is_derived(path):
            for v2 in _live_render_vids():
                cur = eyes.get(v2)
                if path in cur:
                    eyes.set(v2, [p for p in cur if p != path])
            _derived_forget(path)
            _derived_store.delete(path)
            _derived_store.publish(state)
            for pid2 in list(getattr(state, "ui_calc_panels", None) or []):
                _refresh_calculator(pid2)
            _derived_fanout(scrub_paths=[path])
