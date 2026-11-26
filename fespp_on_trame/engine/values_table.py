"""The Values card's table: the active node's columns, filtered, paged and
handed over as CSV.

The card's controller (app/features/values_card) reads the columns
off the blocks, one numpy vector each in global index order (the blocks'
order); everything after that is here, pure numpy, so the unit tests drive
it directly. The CSV follows the shared layout of engine/utils/csv_export.
"""
# the rows a Copy CSV hands over at most: the text crosses the websocket
# whole, and a million-cell grid would weigh a hundred megabytes
CSV_MAX_ROWS = 100_000


def groups_of(conds, ncols):
    """The filter rows as groups: [[(column index, min, max), ...], ...].
    `conds` = [(column index, min, max, op)], `op` joining a row to the
    one before: "and" (∩) binds tighter than "or" (∪), so a row is kept
    when it passes every condition of one ∪ group — the Thresholds card's
    rule. A condition with no bound, or on no column, asks nothing; a
    group asking nothing is no group."""
    groups = [[]]
    for i, (c, lo, hi, op) in enumerate(conds or ()):
        if i and op == "or":
            groups.append([])
        if (lo is not None or hi is not None) and 0 <= c < ncols:
            groups[-1].append((c, lo, hi))
    return [g for g in groups if g]


def conditions_text(names, conds):
    """The filter as a CSV header says it: `(K in [2, 3] and I in [1, 9]) or
    Facies in [1, 1]`; None when it asks nothing."""
    def one(c, lo, hi):
        return f"{names[c]} in [{'' if lo is None else lo}, {'' if hi is None else hi}]"
    groups = groups_of(conds, len(names))
    if not groups:
        return None
    if len(groups) == 1:
        return " and ".join(one(*c) for c in groups[0])
    return " or ".join(("(" + " and ".join(one(*c) for c in g) + ")") if len(g) > 1 else one(*g[0])
                       for g in groups)


def range_of(col):
    """[min, max] of a column, NaN left out; [None, None] when it has none."""
    import numpy as np
    v = col.astype(float)
    v = v[~np.isnan(v)]
    return [float(v.min()), float(v.max())] if v.size else [None, None]


def nan_read(cols, fcol, conds=None):
    """The columns `hide_nan` reads: those of the filter's rows (bound or
    not), else column `fcol` — a NaN there hides the row."""
    read = {c for c, *_r in conds if 0 <= c < len(cols)} if conds else set()
    if not read and 0 <= fcol < len(cols):
        read = {fcol}
    return sorted(c for c in read if cols[c].dtype.kind == "f")


def unit_labels(columns, units, labelled=()):
    """{column: "column (unit)"} for the columns of values (a property, a
    log) whose unit of measure is known (`units` {column: uom}); the
    columns already labelled (places, depths) are left to their label."""
    out = {}
    for col in columns or ():
        uom = str((units or {}).get(col) or "").strip()
        if uom and col not in labelled:
            out[col] = f"{col} ({uom})"
    return out


def pointed_sample(event, well, logs):
    """The log view's pointer for a row of the Values view under the mouse
    (`event` {row, md}, None once it leaves the table), the view reading the
    logs `logs` of the wellbore `well`: {well, md, curves} — the sample
    crossed on those curves — or None (no row, no depth, no log)."""
    md = event.get("md") if isinstance(event, dict) else None
    if isinstance(md, bool) or not isinstance(md, (int, float)) or md != md or md in (float("inf"), float("-inf")):
        return None
    if not well or not logs:
        return None
    return {"well": str(well), "md": float(md), "curves": sorted(str(t) for t in logs)}


def nan_said(names, cols, fcol, conds=None, nan_all=()):
    """What Hide NaN leaves out, as an export's header says it; None when
    nothing."""
    said = [names[c] for c in nan_read(cols, fcol, conds)]
    parts = ["hidden in " + ", ".join(said)] if said else []
    if [c for c in nan_all or () if 0 <= c < len(cols)]:
        parts.append("rows with none in " + ", ".join(names[c] for c in nan_all if 0 <= c < len(cols)) + " hidden")
    return "; ".join(parts) or None


def rows_of(cols, fcol, picked, only, fmin, fmax, total=0, conds=None, hide_nan=False, nan_all=()):
    """`(kept, frange)`: the global indices of the rows the card keeps, and
    the range of column `fcol` (the card's min / max fields start there).
    `only` keeps the `picked` rows (an int64 array of global indices); the
    min / max filter reads column `fcol` — a NaN, an inactive cell, is
    never in range. `conds` (groups_of) replaces that one filter with the
    card's rows of conditions. `hide_nan` leaves out the rows with no value
    in a column the filter reads (`nan_read`), bound or not, and the rows
    with no value in any of the `nan_all` columns (a frame's logs: a sample
    where none of them holds one). With no column, `total` rows: a surface's
    cells with no property ticked are still its cells."""
    import numpy as np
    total = int(cols[0].shape[0]) if cols else int(total or 0)
    frange = range_of(cols[fcol]) if cols and 0 <= fcol < len(cols) and total else [None, None]
    idx = picked if only else np.arange(total)
    if hide_nan and cols:
        for c in nan_read(cols, fcol, conds):
            idx = idx[~np.isnan(cols[c][idx].astype(float))]
        every = [c for c in nan_all or () if 0 <= c < len(cols)]
        # a column of integers always holds a value: no row is empty in all of them
        if every and all(cols[c].dtype.kind == "f" for c in every):
            idx = idx[~np.all(np.isnan(np.stack([cols[c][idx] for c in every])), axis=0)]
    groups = groups_of([(fcol, fmin, fmax, "and")] if conds is None else conds, len(cols))
    if groups:
        keep = np.zeros(idx.shape[0], dtype=bool)
        for g in groups:
            mask = np.ones(idx.shape[0], dtype=bool)
            for c, lo, hi in g:
                v = cols[c][idx].astype(float)
                if lo is not None:
                    mask &= v >= lo
                if hi is not None:
                    mask &= v <= hi
            keep |= mask
        idx = idx[keep]
    return idx, frange


def query(req):
    """The card's request: `offset`, the `min` / `max` filter on column
    `filter` ("" its default), `only` the cells the selection tool holds
    in 3D (the manager, 15/10: they had to be hunted for in the table),
    `assoc` how a geometry is read ("" lets the node decide: a point set
    by its points), `part` the part of its grid a property is read on
    ("" the whole grid), `filters` the rows of conditions [{column, min,
    max, op}] ("and" ∩, "or" ∪; the one `filter` / `min` / `max` when
    absent), `hide_nan` the rows with no value in a column the filter
    reads left out (on unless said: the card's box starts ticked, and a page
    the server asks again for keeps it), `cursor_md` the measured depth the log view's cursor
    stands on (the page holding the nearest row, marked), `hold` that row
    held as well (a click in the log view). A bare number is an offset."""
    q = {"offset": 0, "min": None, "max": None, "only": False, "hold": False,
         "assoc": "", "filter": "", "part": "", "filters": [], "hide_nan": True, "cursor_md": None}
    try:
        if not isinstance(req, dict):
            q["offset"] = max(0, int(req or 0))
            return q
        q["offset"] = max(0, int(req.get("offset") or 0))
        q["only"] = bool(req.get("only"))
        q["hide_nan"] = req.get("hide_nan") is None or bool(req.get("hide_nan"))
        md = req.get("cursor_md")
        q["cursor_md"] = float(md) if md not in (None, "") else None
        q["hold"] = bool(req.get("hold"))
        want = str(req.get("assoc") or "").upper()
        q["assoc"] = want if want in ("CELLS", "POINTS") else ""
        q["filter"] = str(req.get("filter") or "")
        q["part"] = str(req.get("part") or "")
        for k in ("min", "max"):
            v = req.get(k)
            q[k] = float(v) if v not in (None, "") else None
        rows = req.get("filters")
        if isinstance(rows, list) and rows:
            q["filters"] = [{"column": str(f.get("column") or ""),
                             "min": float(f["min"]) if f.get("min") not in (None, "") else None,
                             "max": float(f["max"]) if f.get("max") not in (None, "") else None,
                             "op": "or" if f.get("op") == "or" else "and"}
                            for f in rows if isinstance(f, dict)]
            # the first row decides the default column and the range said back
            q["filter"] = q["filters"][0]["column"] if q["filters"] else q["filter"]
    except (TypeError, ValueError) as exc:
        print(f"[fespp] values request {req!r}: {exc} — from the first page", flush=True)
        q["offset"] = 0
    return q


def on_log_column(hit, well, logs):
    """Whether the log view's pointer (`hit` {well, curves}: the wellbore and
    the curves of the column under it) stands in a column holding one of the
    logs `logs` (titles) of the wellbore `well` the Values view reads: only
    there does it mark or hold a row of the Values view."""
    if not isinstance(hit, dict) or not well or not logs:
        return False
    return (str(hit.get("well") or "") == well
            and bool({str(c) for c in hit.get("curves") or ()} & set(logs)))


def nearest_row(depths, kept, at, limit):
    """The row whose depth (`depths`, the table's MD column) is nearest `at`
    among the rows `kept` (rows_of), and the offset of its page of `limit`
    rows: (row, offset); (None, None) when none of them has a depth."""
    import numpy as np
    md = np.asarray(depths, dtype=float)[np.asarray(kept, dtype=np.int64)]
    if not md.size or np.isnan(md).all():
        return None, None
    pos = int(np.nanargmin(np.abs(md - float(at))))
    return int(kept[pos]), (pos // limit) * limit


def row(cols, gi):
    """Row `gi` as plain values: a NaN reads None, an integer stays one."""
    import numpy as np
    return [(None if np.isnan(c[gi]) else float(c[gi])) if c.dtype.kind == "f"
            else (c[gi].item() if hasattr(c[gi], "item") else c[gi])
            for c in cols]


def page(names, cols, fcol, picked, only, offset, limit, fmin, fmax,
         assoc, geometry, index="index", total=0, conds=None, hide_nan=False, nan_all=()):
    """One page of the table over `cols`, kept by `rows_of`; the page says
    which of its rows are picked, which columns the filter can read and
    the range of each one a condition reads (`ranges`, where its fields
    start). `index` names the first column (a point's id, a cell's, a
    blocked wellbore's interval)."""
    total = int(cols[0].shape[0]) if cols else int(total or 0)
    idx, frange = rows_of(cols, fcol, picked, only, fmin, fmax, total, conds, hide_nan, nan_all)
    read = {c for c, *_r in (conds or ()) if 0 <= c < len(cols)}
    shown = idx[offset:offset + limit].tolist()
    picked_set = set(picked.tolist())
    return {"count": int(idx.shape[0]), "total": total, "offset": offset,
            "assoc": assoc, "columns": [index] + list(names),
            "rows": [[gi] + row(cols, gi) for gi in shown],
            "geometry": geometry, "filter_on": names[fcol] if names else "",
            "filter_columns": list(names), "filter_range": frange,
            "ranges": {names[c]: range_of(cols[c]) for c in read},
            "min": fmin, "max": fmax, "only": only, "hide_nan": bool(hide_nan),
            "picked": len(picked_set),
            "picked_rows": [gi for gi in shown if gi in picked_set]}


def csv_text(names, cols, kept, header, index="index", cap=CSV_MAX_ROWS,
             points=None, points_at=0, row_names=None):
    """The CSV of the `kept` rows (every page, the first `cap`), raw values
    under the provenance `header` lines (csv_export.header_lines).
    `points`: per kept row, the ids of its cell's points, written
    space-separated in a "points" column at `points_at` (a position among
    the columns, the index first). `row_names`: what the first column says
    of each row in place of its number (a marker's name, a log's)."""
    from fespp_on_trame.engine.utils import csv_export
    columns = [index] + list(names)
    shown = kept[:cap].tolist()
    first = (lambda gi: row_names[gi]) if row_names else int
    if points is None:
        rows = ([first(gi)] + row(cols, gi) for gi in shown)
    else:
        columns.insert(points_at, "points")

        def _with(gi, ids):
            r = [first(gi)] + row(cols, gi)
            r.insert(points_at, " ".join(str(i) for i in ids))
            return r
        rows = (_with(gi, ids) for gi, ids in zip(shown, points))
    return csv_export.render(header, columns, rows)
