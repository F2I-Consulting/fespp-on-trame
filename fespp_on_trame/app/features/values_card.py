"""values_card — the Values card: one page of the active node's values (a
geometry by its cells or its points, a property on its whole grid or on a
part of it) and every row it keeps as CSV; controllers `node_values` and
`node_values_csv`.

(Out of values_highlights, 21/10: the card reads values, the highlights draw
a selection; `node_highlight`, the card's rows lit in the view, stays
there.) The table itself — filter, page, CSV — is engine/values_table; the
helpers on the node's blocks are app/features/node_helpers'."""
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import geo
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine import values_table
from fespp_on_trame.engine.utils import csv_export


def register(core, *, _block_column, _blocks_for_rep, _cell_points, _derived_array_name,
             _derived_values, _eye_driven_colors, _geometry_columns, _is_property_path,
             _node_blocks, _real_idx_for, _refresh_values, _rep_path_of, _ticked_arrays,
             _panel_tick_read=None):
    """Wire the Values card's controllers."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    source_registry = core.source_registry
    eyes = core.eyes
    selection = core.selection
    _sel_cells = core.selection.cells

    @state.change("ui_loaded_array_paths", "ui_loaded_rep_paths")
    def _values_follow_loads(**_):
        """A property read after the card asked — its tick still loading:
        "Array not loaded" stayed beside a ticked, eyed row (the PO, 21/10)
        — one more ticked under a geometry, or a sub-representation or a
        blocked wellbore ticked (one more part to read a property on):
        every card showing a page, an error included, asks again."""
        for vid, page in list((state.ui_node_values_by_view or {}).items()):
            if page:
                _refresh_values(vid)

    @core.lifecycle.on("session_rows")
    def _values_follow_extracts(vid):
        """An extract made, renamed or dropped, in any view: a property's
        "Read on" offers every view's extracts of its grid (the PO, 21/10:
        a new one showed only once something else moved)."""
        for v, page in list((state.ui_node_values_by_view or {}).items()):
            if page and page.get("supports"):
                _refresh_values(v)

    # view -> the node the card asked to read: its page comes again once it is
    reading = {}

    def _error_page(view_id, err):
        """The page of a node the card cannot read: a marker's depth, else
        the reason — a node not read yet offered to be read (`read`)."""
        from fespp_on_trame.app.features.node_helpers import ARRAY_NOT_READ, NOT_READ
        page = _marker_md_page(view_id) or {"error": err}
        path = core.activation.values_path(view_id) if err in (NOT_READ, ARRAY_NOT_READ) else ""
        nid = tree.find_node_id(path) if path else None
        if nid is not None and _panel_tick_read is not None and "error" in page:
            title = tree.find_title(nid) or "This node"
            page = {"error": f"{title} is not read yet.", "read": path, "read_title": title}
        return page

    def _hit_md(hit):
        """The measured depth the log view's pointer stands at, None off its tracks."""
        md = next((d.get("value") for d in (hit or {}).get("depths") or ()
                   if str(d.get("ref") or "").upper() == "MD"), None)
        return float(md) if isinstance(md, (int, float)) else None

    def _values_logs(vid, page):
        """(wellbore title, {log titles}) of what the Values view of `vid`
        reads sample by sample: a log, or a log frame's logs read by their
        samples; ("", set()) for anything else."""
        path = core.activation.values_path(vid)
        logs = node_facts.sampled_logs(tree, path, page.get("assoc") == "POINTS") if path else []
        nid = tree.find_node_id(path) if logs else None
        wid = tree.find_parent_node_id_with_type(nid, "Wellbore") if nid is not None else None
        titles = {tree.find_title(tree.find_node_id(log)) or "" for log in logs} - {""}
        return ((tree.find_title(wid) or "") if wid is not None else ""), titles

    def _on_values_column(vid, page, hit):
        """The log view's pointer stands on a sample of the column holding
        the log the Values view reads (engine/values_table.on_log_column)."""
        well, logs = _values_logs(vid, page)
        return (_hit_md(hit) is not None and "MD" in (page.get("columns") or ())
                and values_table.on_log_column(hit, well, logs))

    def _page_again(vid, page, md, hold=False):
        """The Values page of `vid` again, the row nearest `md` marked
        (and held) — its filter, Hide NaN and reading kept."""
        node_values({"offset": 0, "only": page.get("only"), "hide_nan": page.get("hide_nan"),
                     "assoc": page.get("assoc") or "", "part": page.get("part") or "",
                     "filters": page.get("filters") or [], "cursor_md": md, "hold": hold}, vid)

    def _held_rows(vid):
        """The rows of the node the Values view of `vid` reads that are held
        (highlighted), [] when they were another node's."""
        path, rows = (getattr(ctx, "values_held", None) or {}).get(str(vid)) or ("", [])
        return list(rows) if path and path == core.activation.values_path(str(vid)) else []

    def _page_said(vid, **keys):
        """The page the Values view of `vid` shows, with `keys` changed."""
        vals = dict(state.ui_node_values_by_view or {})
        if vals.get(vid):
            vals[vid] = dict(vals[vid], **keys)
            state.ui_node_values_by_view = vals

    @controller.set("welllog_cursor")
    def welllog_cursor(hit):
        """The log view's pointer: on a sample of the column holding the log
        the Values view reads, that view turns to the nearest row and marks
        it; anywhere else (another column, off the tracks: `hit` {}) it marks
        none. The sample is lit in the 3D views drawing the logs under the
        pointer, the Values view open or not (app/features/log_tracks)."""
        hit = hit if isinstance(hit, dict) else {}
        md = _hit_md(hit)
        lit = getattr(ctx, "welllog_cursor_lit", None)
        if lit is not None:
            lit(str(hit.get("well") or ""), [str(c) for c in hit.get("curves") or ()] if md is not None else [],
                md if md is not None else 0.0)
        vid = str(getattr(state, "fespp_last_render_panel_id", "") or "")
        page = (state.ui_node_values_by_view or {}).get(vid) or {}
        if _on_values_column(vid, page, hit):
            _page_again(vid, page, md)
        elif page.get("cursor") is not None:
            _page_said(vid, cursor=None)

    @controller.set("values_hover")
    def values_hover(event, view_id):
        """A row of the Values view under the pointer (`event` {row, md}, None
        once it leaves the table), the view reading a log or a frame sample by
        sample: that sample lit in blue on its logs in the 3D views drawing
        them and crossed on their curves in the log view — what the log view's
        own cursor lights."""
        vid = str(view_id or "")
        page = (state.ui_node_values_by_view or {}).get(vid) or {}
        well, logs = _values_logs(vid, page) if isinstance(event, dict) else ("", set())
        pointed = values_table.pointed_sample(event, well, logs)
        lit = getattr(ctx, "welllog_cursor_lit", None)
        if lit is not None:
            lit(pointed["well"] if pointed else "", pointed["curves"] if pointed else [],
                pointed["md"] if pointed else 0.0)
        if pointed != getattr(state, "ui_log_pointer", None):
            state.ui_log_pointer = pointed

    @controller.set("welllog_pick")
    def welllog_pick(hit):
        """A click in the log view: on the column holding the log the Values
        view reads, the sample nearest it is held — its row selected there,
        lit in the views —; a click anywhere else lets it go."""
        hit = hit if isinstance(hit, dict) else {}
        vid = str(getattr(state, "fespp_last_render_panel_id", "") or "")
        page = (state.ui_node_values_by_view or {}).get(vid) or {}
        if _on_values_column(vid, page, hit):
            _page_again(vid, page, _hit_md(hit), hold=True)
        elif _held_rows(vid) and _values_logs(vid, page)[1]:
            controller.node_highlight([], vid)
            _page_said(vid, held=[])

    @controller.set("values_read")
    def values_read(path, view_id):
        """The card's "Read": the node it shows read — into no 3D view, as a
        tick in a panel's tree —, its values paged once it is."""
        if not path or _panel_tick_read is None or tree.find_node_id(path) is None:
            return
        reading[str(view_id)] = path
        print(f"[fespp] journal values ({view_id}): {tree.find_title(tree.find_node_id(path))} read from the card",
              flush=True)
        _panel_tick_read([path], lambda: reading.pop(str(view_id), None))

    @state.change("ui_loaded_array_paths", "ui_loaded_rep_paths")
    def _read_from_the_card(**_):
        loaded = set(getattr(state, "ui_loaded_array_paths", None) or ()) | set(
            getattr(state, "ui_loaded_rep_paths", None) or ())
        for vid, path in list(reading.items()):
            if path in loaded:
                reading.pop(vid, None)
                page = (state.ui_node_values_by_view or {}).get(vid) or {}
                controller.node_values({"offset": 0, "hide_nan": page.get("hide_nan")}, vid)

    def _marker_md_page(view_id):
        """A wellbore marker's measured depth, shaped as the one row its
        Values panel shows.

        The MD is in no XML part: FESPP reads it from the frame's NodeMd
        array in the HDF5 and puts it on the assembly node. Markers are the
        bulk of a well tree, and their depth is the one number a reader
        wants, so this is where it belongs, next to the values of every
        other node. Returns None when the node has no MD.
        """
        path = core.activation.values_path(view_id)
        nid = tree.find_node_id(path) if path else None
        asm = getattr(tree, "_data_assembly", None)
        if nid is None or asm is None:
            return None
        try:
            raw = asm.GetAttributeOrDefault(nid, "md", None)
            md = float(raw) if raw is not None else None
        except Exception as exc:
            print(f"[fespp] marker MD unreadable ({path}): {exc}", flush=True)
            return None
        if md is None:
            return None
        return {"count": 1, "total": 1, "offset": 0, "assoc": "POINTS",
                "columns": ["index", "MD"], "rows": [[0, md]],
                "min": None, "max": None}

    # above as many rows the converted elevation is left out: it is computed
    # for every row, at every page
    CONVERT_MAX = 2_000_000

    def _verticals(rep_path, pos):
        """`pos` [(name, vector)] with the file's Z given as the object's own
        vertical, whatever domain the view draws: the **Elevation** of an
        object in depth (negative downward, as a view in depth draws it), the
        two-way **Time** of an object in time (as the file counts it, positive
        downward) and, next to that time, the Elevation the active velocity
        model converts it to. Time to depth is the one conversion: a depth is
        never given a time. The converted elevation is left out without a
        model or above CONVERT_MAX rows."""
        import numpy as np
        at = {name: k for k, (name, _c) in enumerate(pos)}
        if not {"X", "Y", "Z"} <= set(at):
            return pos
        z = np.asarray(pos[at["Z"]][1], float)
        domain_of = getattr(ctx, "domain_of_path", None)
        if (domain_of(rep_path) if domain_of is not None and rep_path else "depth") != "time":
            return pos[:at["Z"]] + [("Elevation", z)] + pos[at["Z"] + 1:]
        own = [("Time", -z)]
        cube = ctx.time_depth_convert_cube() if getattr(ctx, "time_depth_convert_cube", None) else None
        if cube is not None and 0 < len(z) <= CONVERT_MAX:
            try:
                x, y = (np.asarray(pos[at[name]][1], float) for name in ("X", "Y"))
                own.append(("Elevation", -cube.to_depth(x, y, -z)))
            except Exception as exc:
                print(f"[fespp] values: the time not converted to an elevation ({exc!r})", flush=True)
        return pos[:at["Z"]] + own + pos[at["Z"] + 1:]

    def _labels(view_id, columns):
        """What the card writes over the columns of places: the horizontal
        axes as the object's CRS names them and the vertical as the elevation
        or the time it is in the file, each with its unit — the values are
        the file's, whatever domain the view draws (an object in depth read
        from a view in time stays in depth); a measured depth with the datum
        it counts from and its unit. (labels, titles): `titles` says of the
        elevation of an object in time that it is converted."""
        out, titles = {}, {}
        try:
            path = core.activation.values_path(view_id) or ""
            rep = _rep_path_of(path) if path else ""
            domain_of, domain_crs = getattr(ctx, "domain_of_path", None), getattr(ctx, "domain_crs", None)
            own = domain_of(rep) if domain_of is not None and rep else None
            if own in ("depth", "time") and domain_crs is not None:
                crs = domain_crs(own)
            else:
                view_crs = getattr(ctx, "view_crs", None)
                crs = view_crs(view_id) if view_crs is not None else None
            x, y, z = geo.axes_grid_titles(crs)
            out.update(X=x, Y=y, Z=z)
            if "Elevation" in columns or "Time" in columns:
                converted = "Elevation" in columns and "Time" in columns
                unit = geo.depth_unit(domain_crs("depth") if domain_crs is not None else None) or "m"
                tunit = (str((crs or {}).get("time_unit") or "").strip() if own == "time" else "") or "ms"
                out["Elevation"] = f"Elevation ({unit})" + (" · T→D" if converted else "")
                out["Time"] = f"Time ({tunit})"
                if converted:
                    titles["Elevation"] = "Converted from its time with the active velocity model"
            if "MD" in columns:
                from fespp_on_trame.engine import welllog_dispatch
                nid = tree.find_node_id(core.activation.values_path(view_id) or "")
                asm = getattr(tree, "_data_assembly", None)
                while nid and asm is not None and not welllog_dispatch.is_well(tree, nid):
                    nid = asm.GetParent(nid)
                if nid and nid > 0:
                    unit, _tvd, datum, _xy = welllog_dispatch._depth_refs(
                        core.active_data_source.get_source(), tree, nid)
                    out["MD"] = ("MD" + (f" from {datum['ref']}" if datum and datum.get("ref") else "")
                                 + (f" ({unit})" if unit else ""))
        except Exception as exc:
            print(f"[fespp] values: the columns keep their letters ({exc!r})", flush=True)
        try:
            # a property's or a log's column with its unit, as the file declares it
            out.update(values_table.unit_labels(columns, _column_units(view_id), out))
        except Exception as exc:
            print(f"[fespp] values: the columns keep no unit ({exc!r})", flush=True)
        return out, titles

    def _column_units(view_id):
        """{column name: unit} of the properties and logs under the object the
        Values view of `view_id` reads, a column being named as the view
        names its array (make_valid_vtk_name of the node's title)."""
        from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
        path = core.activation.values_path(view_id) or ""
        rep = _rep_path_of(path) if path else ""
        units = {}
        if derived_props.is_derived(path):
            # a property made in the session: its recipe holds its name and unit
            store = derived_props.get_store()
            rec = store.get(path) if store is not None else None
            if rec and rec.get("uom"):
                units[rec.get("vtk_name") or ""] = rec["uom"]
        asm = getattr(tree, "_data_assembly", None)
        top = tree.find_node_id(rep or path) if (rep or path) else None
        if asm is None or top is None:
            return units
        stack = [top]
        while stack:
            nid = stack.pop()
            uom = node_facts.unit_of(tree, tree.find_path(nid) or "")
            if uom:
                units.setdefault(make_valid_vtk_name(tree.find_title(nid) or ""), uom)
            stack.extend(asm.GetChild(nid, i) for i in range(asm.GetNumberOfChildren(nid)))
        return units

    def _marker_rows(blocks):
        """(names, [MD, X, Y, Z]) of the markers of a marker frame, one per
        block — FESPP draws each as a disk or a sphere, whose facets say
        nothing: its name (the block's "MarkerNames" table at its
        "MarkerNameId"), its measured depth (the block's "MD" field), the
        centre of what is drawn. None when a block is no marker."""
        import numpy as np
        names, rows = [], []
        for ds, _flat in blocks:
            ids = ds.GetCellData().GetArray("MarkerNameId") if ds.GetNumberOfCells() else None
            table = ds.GetFieldData().GetAbstractArray("MarkerNames")
            if ids is None or table is None:
                return None
            k = int(ids.GetTuple1(0))
            names.append(table.GetValue(k) if 0 <= k < table.GetNumberOfValues() else "")
            md = ds.GetFieldData().GetArray("MD")
            b = ds.GetBounds()
            rows.append([md.GetTuple1(0) if md is not None and md.GetNumberOfTuples() else np.nan,
                         (b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
        cols = np.asarray(rows, float).reshape(-1, 4).T
        return names, [cols[0], cols[1], cols[2], cols[3]]

    # how a log frame is read: its logs, one row each, or its samples
    LOG_READINGS = [
        {"value": "CELLS", "label": "Logs",
         "title": "One row per log of the frame: its samples, the measured depths it runs between, its range"},
        {"value": "POINTS", "label": "Samples",
         "title": "One row per sample: its measured depth, where it is, the logs read"}]

    def _frame_logs(view_id):
        """[(title, uom, array name)] of the logs of the log frame the card
        reads, None when it reads anything else (a log itself, a trajectory,
        a grid)."""
        from fespp_on_trame.engine import welllog_dispatch
        from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
        path = core.activation.values_path(view_id)
        rep = _rep_path_of(path) if path else ""
        if not rep or (path != rep and _is_property_path(path)):
            return None
        logs = welllog_dispatch.frame_channels(tree, tree.find_node_id(rep)) or ()
        return [(title, uom, make_valid_vtk_name(title)) for title, uom in logs] or None

    def _log_samples(blocks, name):
        """`log_track.samples` of the block holding the log `name` (each log
        of a frame is a block of its own), None when none is read."""
        from fespp_on_trame.engine import log_track
        for ds, _flat in blocks or ():
            pd = ds.GetPointData() if hasattr(ds, "GetPointData") else None
            if pd is not None and pd.GetArray(name) is not None:
                return log_track.samples(ds, name)
        return None

    def _logs_table(blocks, logs, q):
        """The logs of a frame, one row each: how many samples hold a value,
        the measured depths of the shallowest and deepest of them, its least
        and greatest value (engine/log_track.log_summary) — blank for a log
        not read."""
        import numpy as np
        from fespp_on_trame.engine import log_track
        names = ["samples", "MD top", "MD base", "min", "max"]
        rows = []
        for _title, _uom, name in logs:
            got = _log_samples(blocks, name)
            rows.append(log_track.log_summary(got[1], got[2]) if got is not None else [np.nan] * len(names))
        cols = np.asarray(rows, float).reshape(-1, len(names)).T
        t = _table(names, list(cols), names.index(q["filter"]) if q["filter"] in names else 0,
                   np.zeros(0, dtype=np.int64), "CELLS", True, total=len(logs), index="log")
        t["row_names"] = [f"{title} ({uom})" if uom else title for title, uom, _n in logs]
        # a log is no place in the view: its row lights nothing
        t["rows_lit"] = False
        return t

    def _frame_table(rep_path, blocks, logs, q):
        """A log frame read sample by sample: one row per node of the frame —
        its measured depth, where it is on the hole, the value of each of its
        logs, none where a log holds none or is not read
        (engine/log_track.frame_table) —, not the points of the tubes a view
        draws them with. None when its blocks hold none of its logs."""
        import numpy as np
        from fespp_on_trame.engine import log_track
        got = log_track.frame_table([(name, _log_samples(blocks, name)) for _t, _u, name in logs])
        if got is None:
            return None
        centres, md, cols = got
        pos = [("X", centres[:, 0]), ("Y", centres[:, 1]), ("Z", centres[:, 2])]
        if md is not None:
            pos.insert(0, ("MD", md))
        pos = _verticals(rep_path, pos)
        names = [n for n, _c in pos] + [n for n, _c in cols]
        # the filter starts on the measured depth: each log holds values on a
        # stretch of its own, and Hide NaN on one of them would hide the others'
        fcol = (names.index(q["filter"]) if q["filter"] in names
                else names.index("MD") if "MD" in names else len(pos))
        # a sample highlighted is lit on its logs' graphs or tubes and in the log view; one at a time
        t = _table(names, [c for _n, c in pos] + [c for _n, c in cols], fcol,
                   np.zeros(0, dtype=np.int64), "POINTS", False, total=len(centres), index="sample")
        t["single"] = True
        # Hide NaN leaves out the samples where none of its logs holds a value
        t["nan_all"] = list(range(len(pos), len(names)))
        return t

    _values_query = values_table.query

    def _table(names, cols, fcol, picked, assoc, geometry, *, total=0, highlight="",
               supports=(), part="", cell_blocks=None, cell_of=None, points_at=0, index=None):
        """The card's table as node_values and node_values_csv read it (see
        _values_table for the keys); `index` names the first column, a
        point's id or a cell's unless said otherwise."""
        return {"names": names, "cols": cols, "fcol": fcol, "picked": picked,
                "assoc": assoc, "geometry": geometry, "total": total,
                "index": index or ("point id" if assoc == "POINTS" else "cell id"),
                "highlight": highlight, "supports": list(supports), "part": part,
                "cell_blocks": cell_blocks, "cell_of": cell_of, "points_at": points_at}

    def _csv_name(view_id):
        """The file a Copy CSV of this view's card hands over: one rule, the
        server's (engine/utils/csv_export), said with every page."""
        return csv_export.file_name("values", (state.ui_active_node_by_view or {}).get(view_id) or "")

    def _values_table(view_id, q):
        """The columns the card shows for the active node: {names, cols,
        fcol (the column the filter reads), picked, assoc, geometry, index
        (the first column's name), highlight (the column painting the view),
        supports, part, cell_blocks, cell_of, points_at}; {"page": …} when
        the node has none to page through (an error, a marker's depth).
        Read by its cells, a row's cell has points (the PO, 21/10): the
        grid cell `cell_of[row]` (the row itself when None) of
        `cell_blocks`, listed in a column at `points_at`."""
        from fespp_on_trame.engine import property_values
        path = core.activation.values_path(view_id)
        if derived_props.is_derived(path):
            return _property_table(view_id, path, q)
        blocks, assoc, wanted, err = _node_blocks(view_id)
        # a marker carries no per-cell array to page through; its MD is
        # what it has, and it is not in the XML (see _marker_md_page)
        if err:
            return {"page": _error_page(view_id, err)}
        # a property reads its own array (_node_blocks' rule)
        if path != (_rep_path_of(path) or "") and _is_property_path(path) and wanted:
            return _property_table(view_id, path, q, blocks, assoc, wanted[0])
        import numpy as np
        # a marker frame: one row per marker, a marker its own row alone
        markers = _marker_rows(blocks)
        if markers is not None:
            where = _verticals(_rep_path_of(path) or "", list(zip(["MD", "X", "Y", "Z"], markers[1])))
            names = [n for n, _c in where]
            title = tree.find_title(tree.find_node_id(path)) if path != (_rep_path_of(path) or "") else None
            keep = [i for i, n in enumerate(markers[0]) if title is None or n == title]
            if keep:
                t = _table(names, [c[keep] for _n, c in where],
                           names.index(q["filter"]) if q["filter"] in names else 0,
                           np.zeros(0, dtype=np.int64), "CELLS", False, total=len(keep), index="marker")
                t["row_names"] = [markers[0][i] for i in keep]
                # a row lights its marker: the cells of what is drawn for it,
                # [first, how many] among the node's cells
                counts = [ds.GetNumberOfCells() for ds, _flat in blocks]
                starts = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(int).tolist()
                t["row_cells"] = [[starts[i], counts[i]] for i in keep]
                return t
        if path and path != (_rep_path_of(path) or ""):
            # a wellbore marker not drawn: its depth alone
            md = _marker_md_page(view_id)
            if md:
                return {"page": md}
        # a GEOMETRY node shows where each cell or point is, then the values
        # of its ticked properties (the PO, 15/10). Read by its cells: a
        # cell's id, its I J K on an IJK grid; by its points: a point's id
        # and X Y Z (the manager, 21/10: a cell's centre said nothing). A
        # point set is read by its points unless the reader asks for its
        # cells (the PO, 20/10)
        logs = _frame_logs(view_id)
        # a log frame opens on its samples; "Logs" gives one row per log
        if logs and q["assoc"] == "CELLS":
            return _logs_table(blocks, logs, q)
        framed = _frame_table(_rep_path_of(path), blocks, logs, q) if logs else None
        if framed is not None:
            return framed
        # a well's trajectory, or a log frame read by its samples: its
        # points, each at its measured depth — its one polyline says nothing
        along_hole = all(ds.GetPointData().GetArray("MD") is not None for ds, _f in blocks)
        assoc = q["assoc"] or ("POINTS" if along_hole else _default_assoc(path))
        pos = _verticals(_rep_path_of(path) or "", _geometry_columns(blocks, assoc))
        props = _ticked_arrays(blocks, _rep_path_of(path), assoc)
        # a vector column reads the component the session chose for its
        # property, as the colour, the pick and the highlights do
        comp_of = {p["name"]: property_values.component_choice(state, p["path"]) for p in props}
        names = [p["name"] for p in props]
        # the property whose eye is open in THIS view, the one painting the
        # grid, is marked (the manager, 21/10); a formula drawn in place of
        # the grid is its column, and the marked one
        eyed = _eyed_column(view_id, path, assoc)
        if eyed and eyed[0] not in names:
            names.insert(0, eyed[0])
            comp_of[eyed[0]] = property_values.component_choice(state, eyed[1]) if eyed[1] else None
        dcol = _derived_column(view_id, path, assoc)
        extra = [dcol] if dcol is not None else []
        # with no column, still one row per cell or point: their ids
        total = sum(ds.GetNumberOfPoints() if assoc == "POINTS" else ds.GetNumberOfCells()
                    for ds, _f in blocks)
        if not names and not pos and not extra and not total:
            return {"page": _marker_md_page(view_id) or
                    {"count": 0, "offset": 0, "assoc": assoc,
                     "columns": ["index"], "rows": [], "total": 0}}
        cols = ([c for _n, c in pos]
                + [_block_column(blocks, assoc, w, comp_of.get(w)) for w in names]
                + [c for _n, c in extra])
        names = [n for n, _c in pos] + names + [n for n, _c in extra]
        # the min/max filter reads the column the reader chose, else the
        # first PROPERTY, else the first column (the PO, 20/10: on a
        # geometry it could only read X)
        fcol = (names.index(q["filter"]) if q["filter"] in names
                else len(pos) if len(names) > len(pos) else 0)
        # the selected cells of THIS node, as global indices (blocks order);
        # read by its points, a point set's selected points
        return _table(names, cols, fcol, _picked_globals(view_id, blocks, points=assoc == "POINTS"),
                      assoc, True, total=total,
                      highlight=dcol[0] if dcol is not None else (eyed[0] if eyed else ""),
                      cell_blocks=blocks if assoc == "CELLS" else None, points_at=1 + len(pos))

    def _property_table(view_id, path, q, blocks=None, assoc="CELLS", name=""):
        """A property node: its values over its grid, read like the grid
        (I J K, a cell's points; a point's X Y Z: the PO, 21/10), or over the
        part of the grid the reader picked (`q["part"]`, offered in
        `supports`: the manager, 21/10, wanted the values of one property on
        the whole grid, a sub-representation or a blocked wellbore). A
        formula is no array of the blocks (the PO, 15/10: "Array not loaded"
        on it): its recipe's values, in its grid's blocks order."""
        import numpy as np
        from fespp_on_trame.engine import property_values
        rep_path = (derived_props.parse_path(path)[0] if derived_props.is_derived(path)
                    else _rep_path_of(path))
        parts = stats_supports.parts_of(tree, rep_path,
                                        getattr(state, "ui_loaded_rep_paths", None) or [])
        # the whole grid is always offered: the choice is seen before a
        # part exists (the PO, 21/10: it went unnoticed)
        supports = ([{"value": "", "label": "Whole grid"}]
                    + [{"value": p, "label": stats_supports.part_label(tree, p)}
                       for p in parts])
        if derived_props.is_derived(path):
            name = _derived_array_name(path)
        if q["part"] in parts:
            return _part_table(view_id, path, rep_path, q["part"], name, supports, q["filter"])
        if derived_props.is_derived(path):
            dvals = property_values.values_for(state, tree, source_registry, path, rep_path)
            if dvals is None:
                why = property_values.last_error()
                return {"page": {"error": "Values unavailable" + (f": {why}" if why else ".")}}
            col = np.asarray(dvals, dtype=float).ravel()
            blocks = _blocks_for_rep(rep_path) or []
            n_cells = sum(ds.GetNumberOfCells() for ds, _f in blocks)
            n_pts = sum(ds.GetNumberOfPoints() for ds, _f in blocks)
            assoc = "POINTS" if col.size == n_pts and col.size != n_cells else "CELLS"
        else:
            logged = _log_table(rep_path, blocks, name, q, supports)
            if logged is not None:
                return logged
            # the component the session chose for a vector property
            col = _block_column(blocks, assoc, name, property_values.component_choice(state, path))
        pos = _verticals(rep_path, _geometry_columns(blocks, assoc))
        names = [n for n, _c in pos] + [name]
        return _table(names, [c for _n, c in pos] + [col],
                      names.index(q["filter"]) if q["filter"] in names else len(pos),
                      _picked_globals(view_id, blocks, points=assoc == "POINTS"), assoc, False,
                      supports=supports, cell_blocks=blocks if assoc == "CELLS" else None,
                      points_at=1 + len(pos))

    def _log_table(rep_path, blocks, name, q, supports):
        """A well's log read as the log it is: one row per sample — its
        measured depth, where it is on the hole, its value, none where it
        holds none (engine/log_track.samples) —, not the points of the tube
        a view draws it with. None when its blocks are no log."""
        import numpy as np
        from fespp_on_trame.engine import log_track
        read = [log_track.samples(ds, name) for ds, _flat in blocks or ()]
        if not read or any(r is None for r in read):
            return None
        centres = np.concatenate([r[0] for r in read])
        values = np.concatenate([r[1] for r in read])
        pos = [("X", centres[:, 0]), ("Y", centres[:, 1]), ("Z", centres[:, 2])]
        if all(r[2] is not None for r in read):
            pos.insert(0, ("MD", np.concatenate([r[2] for r in read])))
        pos = _verticals(rep_path, pos)
        names = [n for n, _c in pos] + [name]
        t = _table(names, [c for _n, c in pos] + [values],
                   names.index(q["filter"]) if q["filter"] in names else len(pos),
                   np.zeros(0, dtype=np.int64), "POINTS", False, total=len(values),
                   supports=supports, index="sample")
        # a sample highlighted is lit on its graph or tube (app/features/log_tracks) and in the log view;
        # one at a time
        t["single"] = True
        return t

    def _part_table(view_id, path, rep_path, part, name, supports, fname=""):
        """The property read on a part of its grid (engine/stats_supports,
        the Statistics rows' reading): one row per cell of the part — per
        interval of a blocked wellbore, with its length — and the grid cell
        it lies in (-1: in none), with that cell's I J K and points (the PO,
        21/10: a part read like its grid)."""
        import numpy as np
        got = stats_supports.part_values(state, tree, source_registry, part, path, rep_path,
                                         real_idx=_real_idx_for(view_id, path))
        m = stats_supports.cell_map(source_registry, part, rep_path, tree) if got else None
        if m is None:
            return {"page": {"error": f"{stats_supports.title_of(tree, part)}: "
                                      f"{stats_supports.last_error() or 'its values could not be read'}",
                             "supports": supports, "part": part}}
        ids = np.asarray(m[0], dtype=np.int64)
        grid = _blocks_for_rep(rep_path) or []
        # the grid's I J K read at each row's grid cell (-1 where it lies in
        # none); the grid cells are the cell map's, the blocks' order
        ijk = []
        if grid and sum(ds.GetNumberOfCells() for ds, _f in grid) == m[2]:
            ok = ids >= 0
            for n, c in _geometry_columns(grid, "CELLS"):
                v = np.full(ids.size, -1, dtype=np.int64)
                v[ok] = c[ids[ok]]
                ijk.append((n, v))
        names = ["grid cell"] + [n for n, _c in ijk] + [name]
        cols = [ids] + [c for _n, c in ijk] + [got["values"]]
        if got["length"] is not None:
            names.append("length")
            cols.append(np.asarray(got["length"], dtype=float))
        # the 3D selection holds grid cells, not the part's rows
        return _table(names, cols, names.index(fname) if fname in names else 1 + len(ijk),
                      np.zeros(0, dtype=np.int64), "CELLS", False,
                      index="interval" if got["length"] is not None else "cell",
                      supports=supports, part=part, cell_blocks=grid or None, cell_of=ids,
                      points_at=2 + len(ijk))

    def _conditions(t, q):
        """The card's rows of conditions for engine/values_table — [(column
        index, min, max, op)] — and as the page says them back, each
        column named ("" = the table's default, its first property)."""
        names = t["names"]
        rows = q["filters"] or [{"column": q["filter"], "min": q["min"], "max": q["max"], "op": "and"}]
        conds, said = [], []
        for f in rows:
            col = f["column"] or (names[t["fcol"]] if names else "")
            conds.append((names.index(col) if col in names else -1, f["min"], f["max"], f["op"]))
            said.append(dict(f, column=col))
        return conds, said

    @state.change("ui_active_node_by_view", "fespp_last_render_panel_id")
    def _values_view_title(**_):
        """The Values view's tab names what it reads."""
        mv = core.mv()
        name = (state.ui_active_node_by_view or {}).get(getattr(state, "fespp_last_render_panel_id", "") or "") or ""
        for pid in (mv.panel_ids_of_kind("values") if mv is not None else ()):
            mv.retitle(pid, f"Values · {name}" if name else "Values")

    @controller.set("values_node_moved")
    def values_node_moved(view_id):
        """The card reads another node: its page goes, and the card asks for
        the new one as its key moves. A node with nothing read has nothing to
        wait for: its page, which says so, comes at once."""
        page = {}
        try:
            if not derived_props.is_derived(core.activation.values_path(view_id)):
                err = _node_blocks(view_id)[3]
                if err:
                    page = _error_page(view_id, err)
        except Exception as exc:
            print(f"[fespp] values of another node ({view_id}):", exc, flush=True)
        vals = dict(state.ui_node_values_by_view or {})
        vals[view_id] = page
        state.ui_node_values_by_view = vals

    @controller.set("node_values")
    def node_values(req, view_id, limit=200):
        """One PAGE of the active node's values for the Attributes card
        (`_values_query` reads the request, `_values_table` the columns,
        engine/values_table filters and pages them); the page says how many
        cells of the node are selected (`picked`) and which of its rows are
        (`picked_rows`). Numpy over the client-side blocks."""
        vals = dict(state.ui_node_values_by_view or {})

        def _out(d):
            # every page says its Hide NaN, an error's included: a page asked
            # again by the server (a read, a tick) keeps it
            vals[view_id] = dict(d, hide_nan=d.get("hide_nan", q["hide_nan"]))
            state.ui_node_values_by_view = vals

        q = _values_query(req)
        try:
            t = _values_table(view_id, q)
            if "page" in t:
                return _out(t["page"])
            conds, said = _conditions(t, q)
            offset, cursor = q["offset"], None
            if q["cursor_md"] is not None and "MD" in t["names"]:
                # the row nearest the log view's cursor, among those the filter keeps: its page
                kept, _r = values_table.rows_of(t["cols"], t["fcol"], t["picked"], q["only"], q["min"], q["max"],
                                                t["total"], conds, q["hide_nan"], t.get("nan_all", ()))
                near, at = values_table.nearest_row(t["cols"][t["names"].index("MD")], kept, q["cursor_md"], limit)
                if near is not None:
                    cursor, offset = near, at
                    if q["hold"]:
                        # held: selected in the table, lit in the views and the log view
                        controller.node_highlight([near], view_id, centre=False)
            page = values_table.page(t["names"], t["cols"], t["fcol"], t["picked"], q["only"],
                                     offset, limit, q["min"], q["max"], t["assoc"],
                                     t["geometry"], index=t["index"], total=t["total"],
                                     conds=conds, hide_nan=q["hide_nan"], nan_all=t.get("nan_all", ()))
            page["cursor"] = cursor
            page["held"] = _held_rows(view_id)
            labels, titles = _labels(view_id, page.get("columns") or ())
            page.update(highlight=t["highlight"], supports=t["supports"], part=t["part"],
                        filters=said, csv_name=_csv_name(view_id), labels=labels, titles=titles)
            if _frame_logs(view_id):
                page["readings"] = LOG_READINGS
            if t.get("row_names"):
                # a marker frame: each row under its marker's name
                page["row_names"] = {str(r[0]): t["row_names"][r[0]] for r in page["rows"]}
            for key in ("row_cells", "rows_lit", "single"):
                if t.get(key) is not None:
                    page[key] = t[key]
            if t.get("cell_blocks"):
                # each row's cell: its points' ids and X Y Z, for this page
                cell = _row_cells(t, [r[0] for r in page["rows"]])
                pts = _cell_points(t["cell_blocks"], [c for c in cell if c >= 0])
                page["points"] = {str(gi): pts.get(c) for gi, c in zip((r[0] for r in page["rows"]), cell)
                                  if c in pts}
                page["points_at"] = t["points_at"]
            _out(page)
        except Exception as exc:
            print(f"[fespp] node values error ({view_id}):", exc, flush=True)
            _out({"error": f"Values unavailable: {exc}"})

    @controller.set("values_extract")
    def values_extract(mode, view_id):
        """The Values card's Keep / Remove (the manager, 29/10): the cells its
        rows highlight — or the 3D selection holds — kept, or taken out, as a
        new object under the grid: the tree row's own gesture
        (app/features/extracts.selection_extract)."""
        vid = str(view_id or "")
        path = core.activation.values_path(vid)
        rep = _rep_path_of(path) if path else ""
        if not rep:
            print(f"[fespp] values extract ({vid}): no object active", flush=True)
            return
        controller.selection_extract({"path": rep, "mode": "remove" if mode == "remove" else "keep"}, vid)

    @controller.set("node_values_csv")
    def node_values_csv(req, view_id):
        """Every row the card keeps — all its pages, the first
        values_table.CSV_MAX_ROWS — as the CSV its Copy CSV hands over (the
        manager, 21/10). The answer goes to `ui_node_values_csv_by_view`
        under the request's number `n`, which the widget waits for: {n,
        name, text} or {n, error}."""
        n = req.get("n") if isinstance(req, dict) else None

        def _answer(d):
            # only the last answer is kept: a text can weigh megabytes
            state.ui_node_values_csv_by_view = {view_id: dict(d, n=n)}

        q = _values_query(req)
        title = (state.ui_active_node_by_view or {}).get(view_id) or ""
        name = _csv_name(view_id)
        try:
            t = _values_table(view_id, q)
            if "page" in t:
                page = t["page"]
                if not page.get("columns"):
                    return _answer({"error": page.get("error") or "nothing to export"})
                # a marker's depth: the one row it shows
                return _answer({"name": name, "text": csv_export.render(
                    csv_export.header_lines("values", [("node", title)]),
                    page["columns"], page["rows"])})
            conds, _said = _conditions(t, q)
            kept, _r = values_table.rows_of(t["cols"], t["fcol"], t["picked"], q["only"],
                                            q["min"], q["max"], t["total"], conds, q["hide_nan"], t.get("nan_all", ()))
            cap = values_table.CSV_MAX_ROWS
            bounds = values_table.conditions_text(t["names"], conds)
            header = csv_export.header_lines("values", [
                ("node", title),
                ("read on", stats_supports.title_of(tree, t["part"]) if t["part"] else None),
                ("read by", t["index"] + "s" if t.get("row_names")
                 else "points" if t["assoc"] == "POINTS" else "cells"),
                ("filter", bounds),
                ("selected only", "yes" if q["only"] else None),
                ("NaN", values_table.nan_said(t["names"], t["cols"], t["fcol"], conds, t.get("nan_all", ()))
                 if q["hide_nan"] else None),
                ("rows", f"the first {cap} of {kept.size}" if kept.size > cap else kept.size),
            ])
            points = None
            if t.get("cell_blocks"):
                # each row's cell's points, by id (their X Y Z are the rows
                # of the same node read by its points)
                cell = _row_cells(t, kept[:cap].tolist())
                pts = _cell_points(t["cell_blocks"], [c for c in cell if c >= 0],
                                   xyz=False, cap=None)
                points = [(pts.get(c) or {}).get("ids", []) for c in cell]
            _answer({"name": name, "text": values_table.csv_text(
                t["names"], t["cols"], kept, header, index=t["index"],
                points=points, points_at=t.get("points_at", 0), row_names=t.get("row_names"))})
        except Exception as exc:
            print(f"[fespp] node values csv error ({view_id}):", exc, flush=True)
            _answer({"error": str(exc)})

    def _row_cells(t, rows):
        """The grid cell of each row of a table: the row itself, or a part's
        `cell_of` (-1 where it lies in none)."""
        cell_of = t.get("cell_of")
        if cell_of is None:
            return [int(gi) for gi in rows]
        return [int(cell_of[gi]) if 0 <= gi < cell_of.size else -1 for gi in rows]

    def _default_assoc(path):
        """How a geometry node is read when the reader has not said: a point
        set by its points (FESPP draws it as ONE poly-vertex cell holding
        every point: one row of cells says nothing), anything else by its
        cells."""
        rep_path = _rep_path_of(path) if path else ""
        nid = tree.find_node_id(rep_path) if rep_path else None
        return "POINTS" if nid is not None and (tree.find_type(nid) or "") == "PointSet" else "CELLS"

    def _eyed_column(view_id, path, assoc):
        """(array name, property path) of the property painting the node's
        grid in this view — the one whose eye is open — when its values are
        of `assoc`; None when the grid is drawn in one colour."""
        rep_path = _rep_path_of(path) if path else ""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        if not rep_path or scene is None:
            return None
        sel = rep_path
        entry = scene.block_state.get(sel)
        if entry is None or not entry.color_array or (entry.assoc or "CELLS") != assoc:
            return None
        return entry.color_array, (_eye_driven_colors.get(view_id) or {}).get(sel) or ""

    def _derived_column(view_id, path, assoc):
        """("ƒ name", values) of the formula drawn in place of the node's
        grid in this view, its values of `assoc`; None when none is."""
        import numpy as np
        rep_path = _rep_path_of(path) if path else ""
        for dpath in eyes.get(view_id):
            hit = _derived_values.get(dpath) if derived_props.is_derived(dpath) else None
            if rep_path and hit is not None and _rep_path_of(dpath) == rep_path and hit[1] == assoc:
                return _derived_array_name(dpath), np.asarray(hit[0], dtype=float).ravel()
        return None

    def _picked_globals(view_id, blocks, points=False):
        """The cells of `blocks` this view's selection holds, as global
        indices in the blocks' order (the Values table's index column);
        with `points`, the points it holds of a point set's blocks (the
        selection keeps point ids for those, app/scene/selection)."""
        import numpy as np
        picked, gi = [], 0
        sel = _sel_cells.get(view_id) or {}
        as_points = selection.points_of(view_id)
        for ds, flat in blocks:
            n = ds.GetNumberOfPoints() if points else ds.GetNumberOfCells()
            if (flat in as_points) == points:
                picked += [gi + c for c in sel.get(flat, ()) if 0 <= c < n]
            gi += n
        return np.array(sorted(set(picked)), dtype=np.int64)
