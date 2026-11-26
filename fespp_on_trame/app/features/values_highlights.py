"""values_highlights — what lights cells in a view: the Values card's rows
(`node_highlight`), "highlight where" and the well cells, and the
selection they leave.

(Moved out of app/boot, overhaul slice 10; the Values card itself went to
values_card on 21/10.)"""
import time
from paraview import simple as pvsimple
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import source_resolver
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.app.scene import selection_sources


def register(core, *, _block_column, _blocks_for_rep, _clear_selection_of,
             _derived_array_name, _drop_block_highlight, _is_property_path,
             _node_blocks, _own_selection, _publish_sel_counts, _real_idx_for,
             _rep_path_of, _say_took):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_record_selection, _select_ids)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    scheduler = core.scheduler
    selection = core.selection
    ctx = core.ctx
    # view -> {log path: [its samples highlighted]}: a log drawn as a graph is
    # no block of the source's representations, its graph draws them
    # (app/features/log_tracks)
    ctx.log_samples_lit = {}
    state.ui_log_lit = {}
    # the sample under the pointer in the Values view, crossed in the log view (values_card.values_hover)
    state.ui_log_pointer = None
    # view -> (the node the Values view reads, its rows highlighted): a row
    # held from the log view is said back to the table
    ctx.values_held = {}

    def _rows_logs(vid, path):
        """The logs a row of the card is a sample of (engine/node_facts), a
        frame's when the card reads it sample by sample."""
        page = (state.ui_node_values_by_view or {}).get(vid) or {}
        return node_facts.sampled_logs(tree, path, page.get("assoc") == "POINTS")

    def _lit_log_samples(view_id, indices, centre=False):
        """The samples of the logs the card's rows are (`indices`, its rows)
        highlighted on their graphs, or none any more; True when its rows are
        log samples. `centre`: the log view brings the first of them to its
        middle (a row clicked in the Values view, not a sample clicked in the
        log view itself)."""
        vid = str(view_id)
        path = core.activation.values_path(vid) if indices else ""
        logs = _rows_logs(vid, path)
        if logs:
            ctx.log_samples_lit[vid] = {log: sorted(int(i) for i in indices) for log in logs}
        else:
            ctx.log_samples_lit.pop(vid, None)
        # and in the log view: their measured depths, on the logs' curves of their well
        said = {}
        if logs:
            import numpy as np
            from fespp_on_trame.engine import log_track
            blocks, _assoc, wanted, err = _node_blocks(vid)
            if path in logs:
                read = [log_track.samples(ds, wanted[0]) for ds, _flat in blocks or ()] if wanted and not err else []
                mds = [got[2] for got in read if got is not None and got[2] is not None]
            else:
                # a frame's rows are its nodes, which every log of it stands on: the depths of any of them
                from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
                names = {make_valid_vtk_name(tree.find_title(tree.find_node_id(log)) or "") for log in logs}
                mds = []
                for ds, _flat in (blocks or ()) if not err else ():
                    pd = ds.GetPointData() if hasattr(ds, "GetPointData") else None
                    name = next((n for n in names if pd is not None and pd.GetArray(n) is not None), None)
                    got = log_track.samples(ds, name) if name else None
                    if got is not None and got[2] is not None:
                        mds = [got[2]]
                        break
            if mds:
                md = np.concatenate(mds)
                picked = sorted(int(i) for i in indices if 0 <= int(i) < len(md))[:5000]
                wid = tree.find_parent_node_id_with_type(tree.find_node_id(path), "Wellbore")
                well = (tree.find_title(wid) or "") if wid is not None else ""
                titles = [tree.find_title(tree.find_node_id(log)) or "" for log in logs]
                if well and picked:
                    said = {well: {t: [float(md[i]) for i in picked] for t in titles if t}}
                    if centre:
                        _log_view_centred(well, next((t for t in titles if t), ""), float(md[picked[0]]))
        if said != (getattr(state, "ui_log_lit", None) or {}):
            state.ui_log_lit = said
        return bool(logs)
    def _log_view_centred(well, curve, md):
        """Every log view brings the measured depth `md` of the curve `curve`
        of the wellbore `well` to its middle (its focus, `n` counting the asks)."""
        mv = core.mv()
        for pid in (mv.panel_ids_of_kind("welllog") if mv is not None else ()):
            var = f"welllog_focus__{pid}"
            n = int((getattr(state, var, None) or {}).get("n") or 0) + 1
            state[var] = {"well": well, "curve": curve, "md": md, "n": n}
    from fespp_on_trame.app.boot import HIGHLIGHT_MAX_IDS, composite_id_triplets, highlight_plan, well_path_samples

    @controller.set("node_highlight")
    def node_highlight(indices, view_id, centre=True):
        """Highlight the cells / points of the active node's block whose
        GLOBAL indices (the Values table's index column) are given — a
        ParaView ID selection on the composite source, drawn by every
        representation of that source. [] clears it."""
        ctx.values_held[str(view_id)] = (core.activation.values_path(str(view_id)),
                                         [int(i) for i in indices or []])
        try:
            is_log = _lit_log_samples(view_id, list(indices or []), centre)
            # a log's samples (a frame's, read sample by sample) are lit by its
            # graph or tube alone: no selection of the source's, whose points
            # are no sample's place
            if is_log or not (indices or []):
                _select_ids(None, "CELLS", [], str(view_id))
                selection.drop(str(view_id), pick=False)
            else:
                blocks, assoc, _wanted, err = _node_blocks(view_id)
                if err:
                    return
                page = (state.ui_node_values_by_view or {}).get(view_id) or {}
                if page.get("rows_lit") is False:
                    return      # rows that are no place in the view: a frame's logs
                # a geometry read by its points: the rows are points
                if page.get("geometry") and page.get("assoc") in ("CELLS", "POINTS"):
                    assoc = page["assoc"]
                # a marker frame: a row is a marker, lit by every cell of what
                # is drawn for it — and not held: no cell to keep or remove
                ranges = page.get("row_cells")
                if ranges:
                    indices = sorted({c for i in indices if 0 <= int(i) < len(ranges)
                                      for c in range(ranges[int(i)][0], sum(ranges[int(i)]))})
                    assoc = "CELLS"
                    if not indices:
                        return
                # a property read on a part: a row is a cell (an interval) of
                # the part, drawn as the grid cell it lies in
                if page.get("part"):
                    path = core.activation.values_path(view_id)
                    m = stats_supports.cell_map(source_registry, page["part"],
                                                _rep_path_of(path), tree)
                    ids = m[0] if m is not None else []
                    indices = sorted({int(ids[i]) for i in indices
                                      if 0 <= int(i) < len(ids) and ids[int(i)] >= 0})
                    if not indices:
                        return
                _select_ids(blocks, assoc, indices, str(view_id))
                # highlighted CELLS are a selection like a pick's: the grid's
                # tree row then offers "+" (keep / remove them)
                if assoc == "CELLS" and not ranges:
                    by_flat, gi, want = {}, 0, sorted(int(i) for i in indices)
                    for ds, flat in blocks:
                        n = ds.GetNumberOfCells()
                        cells = [g - gi for g in want if gi <= g < gi + n]
                        if cells and flat >= 0:
                            by_flat[flat] = cells
                        gi += n
                    selection.hold(str(view_id), by_flat)
                elif assoc == "POINTS":
                    # a point set's rows are its points: a selection of them,
                    # kept as points (app/scene/selection_sources)
                    by_flat = _point_cloud_selection(blocks, indices)
                    if by_flat:
                        selection.hold(str(view_id), by_flat, points=set(by_flat))
            selection.clear_origin(str(view_id))
            _publish_sel_counts(str(view_id))
        except Exception as exc:
            print(f"[fespp] node highlight error ({view_id}):", exc, flush=True)
            return
        scheduler.mark_all_dirty()
        scheduler.flush()

    @controller.set("highlight_where")
    def highlight_where(payload, view_id):
        """Highlight the cells / points of the active PROPERTY whose value is
        within `payload` = [lo, hi] (None = an open bound) — the assistant's
        "light the cells where PHIT > 0.2". The selection `node_highlight`
        draws, found here from the same blocks and the same array the Values
        table pages through: every other cell stays in sight, nothing is
        filtered. NaN never matches, nor does an inactive cell (its 0.0 fill
        is flagged by `vtkGhostType`, as property_values folds it). A vector
        is read on the session's chosen component (ui_vector_component), as
        the colour and the statistics read it. Returns {count, total, valid,
        array, assoc} — `valid` the cells that carry a value — or {error};
        past HIGHLIGHT_MAX_IDS matches nothing is selected (an earlier
        highlight is put out) and `too_many` carries the limit."""
        from fespp_on_trame.engine import property_values
        try:
            lo, hi = (list(payload or []) + [None, None])[:2]
            lo = float(lo) if lo is not None else None
            hi = float(hi) if hi is not None else None
        except (TypeError, ValueError):
            return {"error": f"Bounds not understood: {payload!r}."}
        if lo is None and hi is None:
            return {"error": "No bound given."}
        path = core.activation.values_path(view_id)
        if not _is_property_path(path):
            return {"error": "The active node is not a property: activate one first."}
        try:
            blocks, assoc, wanted, err = _node_blocks(view_id)
            if err:
                return {"error": err}
            if node_facts.is_derived(path):
                # a recipe's values, in its grid's blocks order (an inactive
                # cell is already NaN in them)
                import numpy as np
                dv = property_values.values_for(state, tree, source_registry, path,
                                                _rep_path_of(path))
                if dv is None:
                    return {"error": "The values of this derived property cannot be read now."}
                v, ghost = np.asarray(dv, dtype=float).ravel(), None
                wanted = [_derived_array_name(path)]
            elif not wanted:
                return {"error": "The active property has no values here."}
            else:
                v = _block_component(blocks, assoc, wanted[0],
                                     property_values.component_choice(state, path))
                ghost = _block_column(blocks, assoc, "vtkGhostType", ghosts=False)
            plan = highlight_plan(v, ghost, lo, hi)
            if plan["too_many"]:
                print(f"[fespp] highlight where ({view_id}): {plan['count']} matches,"
                      f" over {plan['too_many']} — nothing selected", flush=True)
                # the reply says nothing is lit: an earlier highlight goes out
                _select_matches(blocks, assoc, [], str(view_id))
                _record_selection(str(view_id), blocks, assoc, [])
            else:
                _select_matches(blocks, assoc, plan["idx"], str(view_id))
                _record_selection(str(view_id), blocks, assoc, plan["idx"])
        except Exception as exc:
            print(f"[fespp] highlight where error ({view_id}):", exc, flush=True)
            return {"error": f"Highlight unavailable: {exc}"}
        scheduler.mark_all_dirty()
        scheduler.flush()
        out = {k: plan[k] for k in ("count", "total", "valid")}
        out.update(array=wanted[0], assoc=assoc)
        if plan["too_many"]:
            out["too_many"] = plan["too_many"]
        return out

    @controller.set("well_cells_where")
    def well_cells_where(payload, view_id):
        """Light the grid cells the wells go through (the assistant's
        "highlight the cells the wells cross").

        Found from the geometry, no blocked wellbore needed: each trajectory
        (`payload["trajectories"]`, rep paths) is walked a metre at a time
        (well_path_samples) and every point looked up in the grid
        (`payload["grid"]`, its rep path) with a static cell locator; a cell
        is crossed when a point falls in it. With `payload["array"]` (a
        property path of the grid) and `lo` / `hi`, a crossed cell is in the
        zone when its value is within (NaN and ghost cells never are). Those
        are lit (every crossed cell when no zone is given) as one composite
        ID selection, like highlight_where. Returns {"per": {trajectory
        path: {"crossed", "in"}}, "lit", "total"} (+ "too_many" past
        HIGHLIGHT_MAX_IDS, nothing lit) or {"error"}."""
        import numpy as np
        from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator
        from fespp_on_trame.engine import property_values
        grid_path = str(payload.get("grid") or "")
        trajs = [str(p) for p in (payload.get("trajectories") or []) if p]
        if not grid_path or not trajs:
            return {"error": "No grid or no trajectory given."}
        try:
            blocks = _blocks_for_rep(grid_path)
            if not blocks:
                return {"error": "The grid is not loaded."}
            locators, bases, base = [], [], 0
            for ds, _f in blocks:
                loc = vtkStaticCellLocator()
                loc.SetDataSet(ds)
                loc.BuildLocator()
                locators.append(loc)
                bases.append(base)
                base += ds.GetNumberOfCells()
            zone = None
            prop = payload.get("array")
            if prop:
                _a, name, _s = source_resolver.resolve_array_for_path(
                    source_registry, tree, grid_path, prop, realization_idx=_real_idx_for(view_id, prop))
                if not name:
                    return {"error": "Array not loaded (check it / open its eye)."}
                v = _block_component(blocks, "CELLS", name, property_values.component_choice(state, prop))
                ghost = _block_column(blocks, "CELLS", "vtkGhostType", ghosts=False)
                lo = float(payload["lo"]) if payload.get("lo") is not None else None
                hi = float(payload["hi"]) if payload.get("hi") is not None else None
                plan = highlight_plan(v, ghost, lo, hi, limit=base + 1)
                zone = np.zeros(base, dtype=bool)
                zone[plan["idx"]] = True
            per, lit = {}, set()
            t0 = time.perf_counter()
            for tp in trajs:
                pts = _trajectory_points(tp)
                if pts is None:
                    per[tp] = {"crossed": 0, "in": 0, "loaded": False}
                    continue
                hit = set()
                for x in well_path_samples(pts):
                    x = (float(x[0]), float(x[1]), float(x[2]))
                    for k, loc in enumerate(locators):
                        cid = loc.FindCell(x)
                        if cid >= 0:
                            hit.add(bases[k] + int(cid))
                            break
                inside = {c for c in hit if zone[c]} if zone is not None else hit
                per[tp] = {"crossed": len(hit), "in": len(inside)}
                lit |= inside
            out = {"per": per, "lit": len(lit), "total": base}
            if len(lit) > HIGHLIGHT_MAX_IDS:
                out["too_many"] = HIGHLIGHT_MAX_IDS
                _select_matches(blocks, "CELLS", [], str(view_id))
                _record_selection(str(view_id), blocks, "CELLS", [])
            else:
                lit_idx = np.fromiter(sorted(lit), dtype=np.int64, count=len(lit))
                _select_matches(blocks, "CELLS", lit_idx, str(view_id))
                _record_selection(str(view_id), blocks, "CELLS", lit_idx)
            _say_took("well cells", t0, f"({len(trajs)} wells, {len(lit)} cells lit)")
        except Exception as exc:
            print(f"[fespp] well cells error ({view_id}):", exc, flush=True)
            return {"error": f"Well cells unavailable: {exc}"}
        scheduler.mark_all_dirty()
        scheduler.flush()
        return out

    def _trajectory_points(rep_path):
        """The points of a trajectory's line(s), in order along them, as an
        (n, 3) array; None when the block is not loaded or has no point."""
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        out = []
        for ds, _f in _blocks_for_rep(rep_path):
            if ds.GetNumberOfPoints() == 0 or ds.GetPoints() is None:
                continue
            p = vtk_to_numpy(ds.GetPoints().GetData()).astype(float)
            ids = []
            for c in range(ds.GetNumberOfCells()):
                cell = ds.GetCell(c)
                if cell.GetCellDimension() != 1:
                    continue
                pid = cell.GetPointIds()
                ids += [pid.GetId(i) for i in range(pid.GetNumberOfIds())]
            out.append(p[ids] if ids else p)
        return np.concatenate(out) if out else None

    def _block_component(blocks, assoc, name, component):
        """`_block_column` without the ghost mask: the highlights apply
        their own (blanked cells are left out of a match, not NaN-ed)."""
        return _block_column(blocks, assoc, name, component, ghosts=False)

    def _record_selection(vid, blocks, assoc, indices):
        """A highlight made by value or by the table is a SELECTION of this
        view like a pick's: its cells are kept per block, so the grid's tree
        row offers "+" (keep / remove them) and the Values card marks them
        (the PO, 15/10: a highlight asked of the assistant gave no "+")."""
        import numpy as np
        by_flat = {}
        if assoc == "CELLS" and indices is not None and len(indices):
            gi = 0
            want = np.asarray(indices, dtype=np.int64)
            for ds, flat in blocks:
                n = ds.GetNumberOfCells()
                local = want[(want >= gi) & (want < gi + n)] - gi
                if local.size and flat >= 0:
                    by_flat[flat] = local.tolist()
                gi += n
        if assoc == "POINTS" and indices is not None and len(indices):
            # a point set's points are a selection like its cells would be
            by_flat = _point_cloud_selection(blocks, indices)
            if by_flat:
                selection.hold(vid, by_flat, points=set(by_flat))
                _publish_sel_counts(vid)
                return
        if by_flat:
            selection.hold(vid, by_flat)
        else:
            selection.drop(vid, pick=False)
        _publish_sel_counts(vid)

    def _point_cloud_selection(blocks, indices):
        """{flat: [point ids]} of the global point `indices` (the Values
        table's index column read by points) that fall in a point set's
        blocks — the only blocks a selection keeps as points."""
        import numpy as np
        out, gi = {}, 0
        want = np.asarray(indices, dtype=np.int64)
        for ds, flat in blocks:
            n = ds.GetNumberOfPoints()
            if flat >= 0 and selection_sources.is_point_cloud(ds):
                local = want[(want >= gi) & (want < gi + n)] - gi
                if local.size:
                    out[flat] = local.tolist()
            gi += n
        return out

    def _select_matches(blocks, assoc, indices, vid):
        """highlight_where's selection: ONE composite ID selection, its
        triplets built in numpy (composite_id_triplets), view `vid`'s; no
        match clears it."""
        from paraview import servermanager as _svm
        _drop_block_highlight()   # this gesture owns the ONE selection channel
        pysrc = _svm._getPyProxy(active_data_source.get_display_source())
        sizes = [ds.GetNumberOfPoints() if assoc == "POINTS" else ds.GetNumberOfCells()
                 for ds, _f in blocks]
        triplets = composite_id_triplets(sizes, [f for _d, f in blocks], indices)
        if triplets.size:
            pvsimple.SelectCompositeDataIDs(
                IDs=triplets.tolist(),
                FieldType="POINT" if assoc == "POINTS" else "CELL",
                Source=pysrc)
            _own_selection(vid)
        else:
            _clear_selection_of(vid, pysrc)

    def _select_ids(blocks, assoc, indices, vid):
        """Turn GLOBAL indices (cumulative across the rep's blocks, the Values
        table's index column) into a composite ID selection on the active
        source, view `vid`'s — drawn in that view only. Empty indices clear
        it."""
        from paraview import servermanager as _svm
        _drop_block_highlight()   # this gesture owns the ONE selection channel
        src = active_data_source.get_display_source()
        pysrc = _svm._getPyProxy(src)
        ids = [int(i) for i in (indices or [])]
        if not ids or not blocks:
            _clear_selection_of(vid, pysrc)
            return
        triplets, gi = [], 0
        wanted_set = set(ids)
        for ds, flat in blocks:
            n = (ds.GetNumberOfPoints() if assoc == "POINTS"
                 else ds.GetNumberOfCells())
            for g in wanted_set:
                if gi <= g < gi + n and flat >= 0:
                    triplets += [flat, 0, g - gi]
            gi += n
        if triplets:
            pvsimple.SelectCompositeDataIDs(
                IDs=triplets,
                FieldType="POINT" if assoc == "POINTS" else "CELL",
                Source=pysrc)
            _own_selection(vid)
        else:
            _clear_selection_of(vid, pysrc)
    return (_record_selection, _select_ids)
