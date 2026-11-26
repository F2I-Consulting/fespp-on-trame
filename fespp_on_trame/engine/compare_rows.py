"""The rows of the Statistics matrix beside the selection itself.

`ui_compare_items` is the selection. At each refresh the items of a tab are
expanded into the rows of the matrix: an item, then right under it its
FOLLOWING rows (`with_following`):

  * a part's row: one per open part of the item's grid (a sub-representation,
    a blocked wellbore, an extract: engine/stats_supports), under each
    unpinned item, read at that item's realization and time step;
  * a 3D view's row: one per view that shows the property and cuts or filters
    its grid, under the first unpinned item of the property, read on what the
    view draws, at the view's realization and time. It comes with no gesture
    and goes with the filter.

A following row is sorted, read against the baseline, drawn in the overlaid
distribution and written in the CSV like any other; it has no picker and no
pin, is never the baseline and never on a cross-plot axis. A filter or an
extract can change it with no signature to tell, so it is never kept in the
row cache (`compare_dispatch.READS`), and no state says that a 3D view's row
moved: `cuts_read` is what tells.

`row_facts` is what every row of the matrix says of itself beside its figures.
"""
from fespp_on_trame.engine import compare_dispatch as cd
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine import view_axes

#: the `support` of a 3D view's row: this, then the view id
VIEW_PREFIX = "view:"

_LAST_ERROR = {"msg": ""}


def last_error():
    """Why the last `support_values` call returned None."""
    return _LAST_ERROR["msg"]


def is_view_row(it):
    return str(it.get("support") or "").startswith(VIEW_PREFIX)


def view_of(support):
    return support[len(VIEW_PREFIX):]


# ---------------------------------------------------------------------------
# The rows that follow an item
# ---------------------------------------------------------------------------

def _following(item, support, real, ts):
    """A following row of `item`. Its uid derives from the item's, so it is
    stable across refreshes."""
    base = cd.item_id(item)
    return {"path": item["path"], "real": real, "ts": ts,
            "uid": f"{base}@{support}", "pinned": False, "xplot": False,
            "support": support, "follows": base}


def _cutting_views(state, path, rep):
    """The 3D views that show the property and cut or filter its grid. A view
    showing the whole grid draws it through its composite: its row would be
    the item's again, so it has none."""
    sd = cd._sd()
    out = []
    for panel in getattr(state, "fespp_render_panels", None) or ():
        vid = panel.get("id") if isinstance(panel, dict) else None
        if not vid or path not in (getattr(state, f"visible_paths__{vid}", None) or ()):
            continue
        try:
            if sd._resolve_rendered_inputs(rep, vid)[0]:
                out.append(vid)
        except Exception as exc:
            print(f"[fespp] statistics: what {vid} draws of {rep!r} is not known ({exc})",
                  flush=True)
    return out


def with_following(state, tree, items, parts):
    """The rows of the matrix over the selection `items`, in matrix order:
    each item, then its parts' rows, then its views' rows. `parts` is the
    session's open parts (`ui_compare_parts`)."""
    out, viewed = [], set()
    parts = list(dict.fromkeys(parts or ()))
    for it in items or ():
        it = cd._norm_item(it)
        if not it["path"] or it["support"]:
            continue
        out.append(it)
        if it["pinned"]:
            continue
        path = it["path"]
        rep = cd._rep_path(tree, path)
        if not rep:
            continue
        out.extend(_following(it, part, it["real"], it["ts"]) for part in parts
                   if stats_supports.belongs_to(tree, part, rep))
        if path not in viewed:
            viewed.add(path)
            # it names no realization nor time step: it reads the view's
            out.extend(_following(it, f"{VIEW_PREFIX}{vid}", None, None)
                       for vid in _cutting_views(state, path, rep))
    return out


def _view_time(vid):
    """The time a 3D view shows; None when it cannot say."""
    from fespp_on_trame.engine import view_resources
    try:
        return float(view_resources.pv_view_of(vid).ViewTime)
    except Exception as exc:
        print(f"[fespp] statistics: the time of {vid} is not known ({exc})", flush=True)
        return None


def cuts_read(state, tree, items, isolates, scenes):
    """What the 3D views' rows of `items` read and no state says: per property
    and view that cuts its grid, how it cuts it (`scenes`: view -> its scene,
    what the boxes of the whole scene say; `isolates`: (view, rep) -> the
    view's isolate of the grid) and at what time. Compared with the last one,
    it tells whether those rows moved: one came, one went, or one reads
    something else."""
    from fespp_on_trame.engine import drawn_cells
    out = {}
    for path in dict.fromkeys(it.get("path") for it in items or ()):
        rep = cd._rep_path(tree, path) if path else ""
        if not rep:
            continue
        for vid in _cutting_views(state, path, rep):
            read = {"scene": drawn_cells.scene_boxes(scenes.get(vid)), "time": _view_time(vid)}
            iso = isolates.get((vid, rep))
            if iso is not None:
                read.update(cuts=iso.snapshot(), chain=iso.get_chain(),
                            nan=iso.hide_nan_array, codes=iso.hidden_codes)
            out[f"{path}|{vid}"] = read
    return out


def naming(state, tree, it):
    """`{"label", "support_label"}` of a following row: the name it goes by,
    and what it is read on, in place of the representation."""
    path, support = it["path"], it["support"]
    if is_view_row(it):
        title = view_axes.view_title(state, view_of(support))
        return {"label": f"{cd._labelled(state, tree, path)} On {title}",
                "support_label": title}
    return {"label": cd._row_label(state, tree, path, it["real"], it["ts"],
                                   on=stats_supports.title_of(tree, support)),
            "support_label": stats_supports.part_label(tree, support)}


def where_read(it, row):
    """Where a following row was read, for the file's header."""
    label = row.get("support_label") or it["support"]
    where = [f"the filtered display of {label}" if is_view_row(it)
             else f"{label} of {row.get('rep') or 'its grid'}"]
    if row.get("real_read") is not None:
        where.append(f"real {row['real_read']}")
    if row.get("ts_text"):
        where.append(row["ts_text"])
    return ", ".join(where)


# ---------------------------------------------------------------------------
# What a following row reads
# ---------------------------------------------------------------------------

def _read_on_part(state, tree, source_registry, it, rep, weights):
    """`(stats | None, note)` of the property read on a part of its grid, at
    the item's realization and time step: None when the part cannot be read,
    the note then says why."""
    sd = cd._sd()
    path, part = it["path"], it["support"]
    label = stats_supports.part_label(tree, part)
    got = stats_supports.part_values(state, tree, source_registry, part, path, rep,
                                     real_idx=it["real"], ts_idx=it["ts"], weights=weights)
    if got is None:
        return None, f"{label}: {stats_supports.last_error()}."
    stats = sd._row_stats_from_values(got["values"], label,
                                      volume=got["volume"], pore_volume=got["pore"])
    if got["length"] is not None:
        # a blocked wellbore: one value per interval, and the mean along the
        # hole, each interval weighted by its length
        mean, n, _why = sd.weighted_mean(got["values"], got["length"])
        stats["length_n"] = n
        if mean is not None:
            stats["Mean (L)"] = mean
    stats.update(kind="support", real_idx=it["real"])
    if got["missing"]:
        return stats, (f"{label}: {got['missing']} of its cells lie in no cell of the"
                       " grid and count as no value.")
    return stats, ""


def _part_stats(state, tree, source_registry, it, rep):
    """`(stats | None, note, facts)` of the property read on a part of its
    grid, weighted by the grid's weights taken on the part's cells; a blocked
    wellbore is weighted along the hole, and what the grid's weights say is
    not about it."""
    from fespp_on_trame.engine import cell_weights
    sd = cd._sd()
    path, part = it["path"], it["support"]
    weights = cell_weights.weights_for(state, tree, source_registry, rep)
    try:
        stats, note = _read_on_part(state, tree, source_registry, it, rep, weights)
    except Exception as exc:
        print(f"[fespp] statistics: {path!r} on the part {part!r}: {exc}", flush=True)
        return None, f"{stats_supports.part_label(tree, part)}: could not be read ({exc}).", {}
    if stats is None:
        return None, note, {}
    said = sd._weights_note(tree, path, {} if "length_n" in stats else weights, [stats])
    return stats, " ".join(x for x in (note, said) if x), {}


def _view_stats(state, tree, source_registry, it, rep):
    """`(stats | None, note, facts)` of the property on what a 3D view draws
    of its grid. The caller holds `stats_dispatch.transient_chain`: the read
    builds proxies."""
    from fespp_on_trame.engine import drawn_cells
    sd = cd._sd()
    path, vid = it["path"], view_of(it["support"])
    title = view_axes.view_title(state, vid)
    drawn_cells.forget_error()
    try:
        stats = sd._build_view_row(state, source_registry, tree, path, rep, vid, title)
    except Exception as exc:
        print(f"[fespp] statistics: {path!r} on {vid}: {exc}", flush=True)
        stats = None
    if stats is None:
        why = drawn_cells.last_error() or "what it draws of this property could not be read"
        return None, f"{title}: {why}.", {}
    ts_label = stats.get("ts_label") or ""
    facts = {"real_read": stats.get("real_idx"), "ts_text": ts_label, "ts_label": ts_label}
    return stats, sd._weights_note(tree, path, {}, [stats]), facts


def support_row(state, tree, source_registry, it):
    """`(stats | None, note, facts)` of a following row: its statistics, what
    it has to say about them or why it has none, and what only its read knows
    of the row (a view's realization and time)."""
    rep = cd._rep_path(tree, it["path"])
    read = _view_stats if is_view_row(it) else _part_stats
    return read(state, tree, source_registry, it, rep)


def _view_values(state, tree, path, rep, vid):
    """The property's values on what a 3D view draws of its grid."""
    from fespp_on_trame.engine import drawn_cells, property_values
    sd = cd._sd()
    name = sd._resolve_vtk_name(tree, path, view_axes.real_for(state, tree, vid, path))[2]
    vals = drawn_cells.values(sd._resolve_rendered_inputs(rep, vid)[0], name,
                              property_values.component_choice(state, path))
    if vals is None:
        _LAST_ERROR["msg"] = drawn_cells.last_error()
    return vals


def support_values(state, tree, source_registry, it):
    """The values the charts draw for a following row: the property on the
    part, or on what the view draws; None with the reason in `last_error()`."""
    _LAST_ERROR["msg"] = ""
    path, support = it["path"], it["support"]
    rep = cd._rep_path(tree, path)
    try:
        if is_view_row(it):
            return _view_values(state, tree, path, rep, view_of(support))
        got = stats_supports.part_values(state, tree, source_registry, support, path, rep,
                                         real_idx=it["real"], ts_idx=it["ts"])
    except Exception as exc:
        print(f"[fespp] statistics: the values of {path!r} on {support!r}: {exc}", flush=True)
        _LAST_ERROR["msg"] = str(exc)
        return None
    if got is None:
        _LAST_ERROR["msg"] = stats_supports.last_error()
        return None
    return got["values"]


# ---------------------------------------------------------------------------
# What a row says of itself
# ---------------------------------------------------------------------------

def _recipe_caps(tree, path):
    store = derived_props.get_store()
    return (store.axis_caps(tree, path) if store is not None
            else {"is_mr": False, "is_ts": False, "reals": []})


def _real_read(state, tree, path, real):
    """The realization a row reads: the one it names, else the default one;
    None on a property with no realization."""
    if real is not None:
        return real
    if derived_props.is_derived(path):
        reals = _recipe_caps(tree, path)["reals"]
        return reals[0] if reals else None
    return cd._sd()._default_real_idx(state, tree, path)


def _ts_text(tree, path, kind, ts):
    """The time step a row reads, in words: the one it names, else on a time
    series the session's current one; "" on a property with no time step."""
    from fespp_on_trame.engine import element_type, time_realization, view_axes
    if ts is not None:
        return cd._sd()._ts_label_for_idx(tree, ts) or f"t{int(ts)}"
    is_ts = (_recipe_caps(tree, path)["is_ts"] if derived_props.is_derived(path)
             else element_type.for_kind(kind).is_time_series())
    at = view_axes.session_time() if is_ts else None
    return time_realization.label_for_time_value(tree, at) if at is not None else ""


def row_facts(state, tree, path, real, ts):
    """What a row of the matrix says of itself beside its figures: its value
    type, whether a Sum of it means anything, the realization and the time
    step it reads (a row may name neither)."""
    sd = cd._sd()
    title, kind = sd._title_and_kind(tree, path)
    prop_kind = sd._prop_kind_for_array_path(tree, path, kind)
    return {
        "value_type": ("Derived" if derived_props.is_derived(path)
                       else sd._PROP_TYPE_LABELS.get(prop_kind, "")),
        "sum_meaningful": sd.sum_meaningful(prop_kind, sd._unit_for_array_path(tree, path),
                                            cd._pwls_kind(tree, path), title),
        "real_read": _real_read(state, tree, path, real),
        "ts_text": _ts_text(tree, path, kind, ts),
    }


