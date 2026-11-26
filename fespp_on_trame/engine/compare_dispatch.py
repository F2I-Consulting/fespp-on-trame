"""The Statistics view (`compare` in the code): one free selection of
properties, one tab per PWLS kind, each showing at once its matrix, its overlaid
distributions and the cross-plot of two of its rows.

The selection is a list of items {path, real, ts} in the order it was
built, any kind and any grid or well mixed. What makes a tab honest is the
grouping by PWLS property kind: a porosity is only ever set against another
porosity in a matrix block or a histogram overlay — the mean of a porosity next
to the mean of a pressure says nothing. A path with no `propertyKind` (a derived
recipe, an EPC using standard 2.0.1 kinds) lands in a "no kind" group rather than
being refused.

The cross-plot is the one chart that needs index alignment, so it keeps X's
representation only (see crossplot_dispatch); the matrix and the distributions
take every item, and the rows that follow one: the property on a part of its
grid, or on what a 3D view draws of it (engine/compare_rows). The tree the
selection is made in is engine/compare_tree.

Pure: no trame, no ParaView at import time — the value reads and the
stats helpers are imported inside the functions, so the module is
unit-testable over a fake assembly.
"""
import math

from fespp_on_trame.engine import compare_matrix
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.engine import tree_families

NO_KIND = "no kind"

# What the session has of a property. The assembly names every property the
# file holds — its kind, its representation, its title — without a value
# being read, so a leaf is listed long before it is loaded: LOADED is the
# only state whose figures can be shown, the others say what is missing and
# what to do about it.
LOADED = ""
UNLOADED = "unloaded"
LOADING = "loading"
FAILED = "failed"

# Shown on the leaves whose values are NOT there. A loaded leaf carries no
# sentence: it is the normal state, and repeating it on every row of a tree
# that lists the whole file would be a page of text nobody reads.
_LOAD_INFO = {
    UNLOADED: "Not loaded. Ticking it here reads it into the statistics —"
              " not into a 3D view: its eye in a 3D view's data tree shows it"
              " there.",
    LOADING: "Loading — the figures appear as soon as the reader has the"
             " values.",
    FAILED: "The read did not bring the values in. See Data health for what"
            " the reader said, then untick it here and tick it again to"
            " retry.",
}
# What an item in that state is called on a row, a chip, a dropped trace.
_LOAD_TAG = {LOADING: "loading", FAILED: "read failed"}
_LOAD_NOTE = {LOADING: _LOAD_INFO[LOADING], FAILED: _LOAD_INFO[FAILED]}

# Bar overlays need heavy transparency to stay legible; line and curve
# overlays read fine nearly opaque.
_BAR_OPACITY = 0.55
_LINE_OPACITY = 0.9

_DIST_DEFAULTS = {"mode": "bars", "nbins": 50, "log_y": False,
                  "cumulative": False, "norm": "count"}


def _sd():
    from fespp_on_trame.engine import stats_dispatch
    return stats_dispatch


def _pv():
    from fespp_on_trame.engine import property_values
    return property_values


def _values_for(state, tree, source_registry, array_path, rep_path,
                real_idx=None, ts_idx=None):
    """The value seam (ghost mask, derived recipes, MR / TS picks) — a
    delegate so the tests can feed arrays without ParaView."""
    from fespp_on_trame.engine.property_values import values_for
    return values_for(state, tree, source_registry, array_path, rep_path,
                      real_idx=real_idx, ts_idx=ts_idx)


def _read_error():
    try:
        from fespp_on_trame.engine.property_values import last_error
        return last_error() or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Item identity
# ---------------------------------------------------------------------------

def _int_or_none(v):
    return None if v is None else int(v)


def item_key(path, real, ts, support=""):
    """`path|real|ts` — the realization and time step are part of the
    identity, so PORO at real 3 and PORO at real 4 are two items. A following
    row adds `@support`: PORO on a part is another read than PORO."""
    r = "" if real is None else str(int(real))
    t = "" if ts is None else str(int(ts))
    key = f"{path}|{r}|{t}"
    return f"{key}@{support}" if support else key


def _norm_item(it):
    it = it if isinstance(it, dict) else {}
    return {"path": it.get("path") or "",
            "real": _int_or_none(it.get("real")),
            "ts": _int_or_none(it.get("ts")),
            "uid": str(it.get("uid") or ""),
            "pinned": bool(it.get("pinned")),
            # whether `xplot_seeds` draws it as a Y; an entry that does not
            # say is
            "xplot": bool(it.get("xplot", True)),
            # a following row (engine/compare_rows): what it is read on and
            # the entry it hangs under
            "support": str(it.get("support") or ""),
            "follows": str(it.get("follows") or "")}


def item_id(it):
    """The identity of ONE selection entry — its `uid` when the session gave
    it one, else its item key. Two entries of one property at the same
    realization and time are two rows of the matrix (a pinned copy beside
    its source, until the copy is moved), which the key alone cannot say;
    the reads are still shared by key (`rows_for`)."""
    return it.get("uid") or item_key(it["path"], it["real"], it["ts"],
                                     it.get("support") or "")


# ---------------------------------------------------------------------------
# Per-path facts
# ---------------------------------------------------------------------------

def _pwls_kind(tree, path):
    """The PWLS kind FESPP wrote on the node, "" when none (a derived
    recipe has no node at all)."""
    if derived_props.is_derived(path) or tree is None or not path:
        return ""
    try:
        nid = tree.find_node_id(path)
        if nid is None:
            return ""
        return tree.find_attribute_value(nid, "propertyKind") or ""
    except Exception:
        return ""


def _kind_label(tree, path):
    return _pwls_kind(tree, path) or NO_KIND


def _attr(tree, path, name):
    if derived_props.is_derived(path) or tree is None or not path:
        return ""
    try:
        nid = tree.find_node_id(path)
        if nid is None:
            return ""
        v = tree.find_attribute_value(nid, name)
        return "" if v is None else str(v)
    except Exception:
        return ""


def _title(tree, path):
    return _sd()._title_and_kind(tree, path)[0] or path


def _labelled(state, tree, path):
    """The property title, carrying the component the session reads."""
    from fespp_on_trame.engine import property_values
    return property_values.labelled(state, tree, path, _title(tree, path))


def _rep_path(tree, path):
    return _sd()._rep_path_for_array_path(tree, path) or ""


def _rep_title(tree, path):
    """The rep's display name — the grid's own name for a grid property,
    not the "SolidColor" geometry leaf its node is titled — carrying the
    wellbore it belongs to when its own name does not tell it apart: a file
    with nine wells lists nine folders all titled "Well Log Frame"."""
    sd = _sd()
    rep = _rep_path(tree, path)
    title = (sd._rep_title_for_array_path(tree, path)
             or rep.rsplit("/", 1)[-1])
    well = _wellbore_title(tree, rep)
    if well and well.lower() not in title.lower():
        return f"{well} · {title}"
    return title


_WELLBORE_TYPES = ("Wellbore", "Well")


def _wellbore_title(tree, rep_path):
    """The title of the wellbore this rep hangs under, "" when it hangs
    under none. Climbed on the PATH: the assembly is a hierarchy and the
    tree exposes no parent link."""
    if tree is None or not rep_path:
        return ""
    parts = rep_path.split("/")
    for i in range(len(parts) - 1, 1, -1):
        try:
            nid = tree.find_node_id("/".join(parts[:i]))
            if nid is None:
                continue
            if (tree.find_type(nid) or "") in _WELLBORE_TYPES:
                return tree.find_title(nid) or ""
        except Exception:
            return ""
    return ""


def rep_family(tree, rep_path):
    """The family — Reservoir / Surface / Well / Seismic — of the
    representation at `rep_path`, as the data tree's cards sort it
    (engine/tree_families.of_path, the one rule). `Other` for a rep no
    family files, and for a property with no rep at all — a tree sorted by
    family must still have a place for it."""
    if tree is not None and rep_path:
        try:
            name, _nid = tree_families.of_path(tree, rep_path)
        except Exception as exc:
            print(f"[fespp] statistics: the family of {rep_path!r} not read ({exc!r})", flush=True)
            name = ""
        if name:
            return name
    return node_kinds.OTHER_FAMILY


def _row_label(state, tree, path, real, ts, on=""):
    """Title (carrying the component read, on a vector property), the part it
    is read `on`, then the realization / time only when the item fixes one —
    unsuffixed, two items of one property would read as identical."""
    label = _labelled(state, tree, path)
    if on:
        label += f" on {on}"
    if real is not None:
        label += f" · real {int(real)}"
    if ts is not None:
        lbl = _sd()._ts_label_for_idx(tree, ts)
        label += f" · {lbl or f't{int(ts)}'}"
    return label


def _is_discrete(tree, path):
    from fespp_on_trame.engine import distribution_dispatch as dd
    sd = _sd()
    kind = sd._title_and_kind(tree, path)[1]
    return dd._is_discrete_kind(sd._prop_kind_for_array_path(tree, path, kind))


def _category_names(tree, source_registry, path, real, codes):
    """``{code: label}`` for the `codes` a discrete item draws, when the
    file names the categories of the property; ``{}`` when it does not."""
    from fespp_on_trame.engine.utils import categories
    labels = {}
    try:
        vtk = _sd()._resolve_vtk_name(tree, path, real)[2]
        try:
            reader = source_registry.shared_source()
        except Exception as exc:
            print(f"[fespp] compare categories: no shared source ({exc})", flush=True)
            reader = None
        labels = categories.labels_for(tree, path, vtk, reader)
    except Exception as exc:
        print(f"[fespp] compare categories ({path}):", exc, flush=True)
    if not labels:
        return {}
    out = {}
    for c in codes:
        try:
            out[float(c)] = categories.label_of(labels, c)
        except (TypeError, ValueError) as exc:
            print(f"[fespp] compare category code {c!r}:", exc, flush=True)
    return out


# ---------------------------------------------------------------------------
# Chips
# ---------------------------------------------------------------------------

def _baseline_index(items, baseline_key):
    """The baseline's position in the rows: the item carrying the id (a uid
    or an item key, both accepted), None when no item does — the rows are then
    plain statistics. A following row is never it."""
    heads = [i for i, it in enumerate(items) if not it.get("support")]
    if baseline_key:
        ids = [item_id(items[i]) for i in heads]
        if baseline_key in ids:
            return heads[ids.index(baseline_key)]
        keys = [item_key(items[i]["path"], items[i]["real"], items[i]["ts"]) for i in heads]
        if baseline_key in keys:
            return heads[keys.index(baseline_key)]
    return None


def resolve_items(state, tree, items, baseline_key, pending=None):
    """One chip per item, in selection order: the facts the tabs, the
    baseline and the cross-plot's axes read of it, and the choices its row's
    selects offer. An item whose values are still on their way, or never came,
    carries `load` and says so in its title rather than looking like one that
    has figures."""
    from fespp_on_trame.engine import crossplot_dispatch
    sd = _sd()
    items = [_norm_item(it) for it in items or []]
    items = [it for it in items if it["path"]]
    base = _baseline_index(items, baseline_key)
    chips = []
    for i, it in enumerate(items):
        path = it["path"]
        st = (pending or {}).get(path) or ""
        try:
            opts = crossplot_dispatch.axis_options(state, tree, path)
        except Exception:
            opts = {"reals": [], "ts": []}
        chips.append({
            "key": item_key(path, it["real"], it["ts"]),
            "path": path,
            "load": st,
            "title": _labelled(state, tree, path)
                     + (f" · {_LOAD_TAG[st]}" if st in _LOAD_TAG else ""),
            "rep": _rep_title(tree, path),
            "kind": _kind_label(tree, path),
            "uom": sd._unit_for_array_path(tree, path),
            "real": it["real"],
            "ts": it["ts"],
            "reals": list(opts.get("reals") or []),
            "ts_opts": list(opts.get("ts") or []),
            "baseline": i == base,
        })
    return chips


# ---------------------------------------------------------------------------
# Stats matrix
# ---------------------------------------------------------------------------

def _pore_volume_read(weights):
    """What the Mean (PV) of a grid's rows is weighted by, for the file's
    header; "" without a pore weight. One realization's porosity weighs every
    row, whatever each row reads."""
    if weights.get("pore") is None:
        return ""
    real = weights.get("real_idx")
    return ("volume x net-to-gross x porosity"
            f" ({weights.get('ntg_title') or 'none'}, {weights.get('poro_title') or 'none'}"
            + (f", both read at realization {real})" if real is not None else ")"))


def _item_stats(state, tree, source_registry, it, rep):
    """`(stats | None, note)` of an item: the property's values with the cell
    weights of its grid, what the note says of them, or why there are none."""
    sd = _sd()
    path, note = it["path"], ""
    try:
        vals = _values_for(state, tree, source_registry, path, rep,
                           real_idx=it["real"], ts_idx=it["ts"])
    except Exception as exc:
        vals = None
        note = str(exc)
    if vals is None:
        return None, note or _read_error() or "could not read the values"
    # the cell weights the Volumetrics card uses too, so "Mean (V)" means one
    # thing in the session
    from fespp_on_trame.engine import cell_weights
    weights = cell_weights.weights_for(state, tree, source_registry, rep)
    stats = sd._row_stats_from_values(vals, _title(tree, path),
                                      volume=weights.get("volume"),
                                      pore_volume=weights.get("pore"))
    stats.update(kind="original", real_idx=it["real"], pore_volume=_pore_volume_read(weights))
    return stats, sd._weights_note(tree, path, weights, [stats])


def _row(state, tree, source_registry, it, load=""):
    from fespp_on_trame.engine import compare_rows
    sd = _sd()
    path, real, ts = it["path"], it["real"], it["ts"]
    support = it["support"]
    row = {"label": _row_label(state, tree, path, real, ts),
           "rep": _rep_title(tree, path),
           "kind": _kind_label(tree, path),
           "uom": sd._unit_for_array_path(tree, path),
           "real": real, "ts": ts, "load": load,
           "metrics": {}, "profile": "", "note": "", "pore_volume": "",
           "support": support, "follows": it["follows"], "support_label": ""}
    row.update(compare_rows.row_facts(state, tree, path, real, ts))
    if support:
        row.update(compare_rows.naming(state, tree, it))
    if load in _LOAD_TAG:
        # no values yet (or none ever): the row says which of the two it is
        # and what comes next, in place of figures it does not have
        row["label"] += f" · {_LOAD_TAG[load]}"
        row["note"] = _LOAD_NOTE[load]
        return row
    rep = _rep_path(tree, path)
    if not rep:
        row["note"] = "not loaded"
        return row
    if support:
        stats, row["note"], facts = compare_rows.support_row(state, tree, source_registry, it)
        row.update(facts)
    else:
        stats, row["note"] = _item_stats(state, tree, source_registry, it, rep)
    if stats is None:
        return row
    row["pore_volume"] = stats.get("pore_volume") or ""
    metrics = {}
    for k in compare_matrix._METRIC_KEYS:
        v = stats.get(k)
        if v is None:
            continue
        try:
            metrics[k] = float(v)
        except (TypeError, ValueError):
            continue
    # the filter chain of a view's row writes NaN moments on constant values:
    # a metric that is no number is a metric the row does not have
    row["metrics"] = {k: v for k, v in metrics.items() if math.isfinite(v)}
    row["profile"] = compare_matrix.profile_tag(stats.get("Skewness"),
                                                stats.get("Kurtosis"))
    return row


# The row cache of the session: item key -> {"row", "sig"}. A row's values
# change only when its property is read at another component, when the
# weights its Mean (V) / Mean (PV) carry are rebuilt from another porosity
# or net-to-gross, when the session's default realization or current time
# moves under a row that names neither (`_cache_signature`), or when the
# file itself changes (`clear_reads`, beside the geometry's own clear).
# Derived recipes, following rows (engine/compare_rows) and rows without
# values are never cached.
READS = {}
# What an item draws in the overlay: item key -> {"sig", "read"} under the same
# rule, the options it was binned with beside the signature (`_cached_trace`).
TRACES = {}


def clear_reads():
    READS.clear()
    TRACES.clear()


def _cache_signature(state, tree, source_registry, it, rep):
    """What a cached row's values depend on besides its key: the weights
    behind its Mean (V) / Mean (PV), the component read, the cells of the part
    it follows, and — for a row that names no realization or no time step —
    the session's default realization and current time, which such a row
    reads."""
    from fespp_on_trame.engine import cell_weights, stats_supports
    from fespp_on_trame.engine.property_values import axis_key
    path = it["path"]
    w = cell_weights.weights_for(state, tree, source_registry, rep) or {}
    default_real = (_sd()._default_real_idx(state, tree, path)
                    if it["real"] is None else None)
    at_time = _session_time() if it["ts"] is None else None
    support = it.get("support")
    return ((w.get("poro_path"), w.get("ntg_path"), w.get("real_idx")),
            axis_key(state, path), default_real, at_time,
            stats_supports.part_stamp(support) if support else None)


def _session_time():
    """The session's current time, what a row naming no time step reads
    (engine/view_axes)."""
    from fespp_on_trame.engine import view_axes
    return view_axes.session_time()


def _cached_row(cache, key, state, tree, source_registry, it, load, loaded):
    """The row of `it`, from the cache when its values cannot have changed
    since it was read, else read afresh and kept when it has values. A 3D
    view's row reads what the view draws now: it is never kept."""
    from fespp_on_trame.engine import compare_rows, derived_props
    path = it["path"]
    cacheable = (cache is not None and not load and not compare_rows.is_view_row(it)
                 and not derived_props.is_derived(path)
                 and (loaded is None or path in loaded))
    if cacheable and key in cache:
        rep = _rep_path(tree, path)
        try:
            sig = _cache_signature(state, tree, source_registry, it, rep) if rep else None
        except Exception as exc:
            print(f"[fespp] compare cache of {path!r}:", exc, flush=True)
            sig = None
        hit = cache[key]
        if sig is not None and sig == hit["sig"]:
            cache["_hits"] = cache.get("_hits", 0) + 1
            row = dict(hit["row"])
            if it["support"]:
                # a part's name is not in its values: an extract may be renamed
                row.update(compare_rows.naming(state, tree, it))
            return row
    row = _row(state, tree, source_registry, it, load)
    if cache is not None:
        cache["_reads"] = cache.get("_reads", 0) + 1
    if cacheable and row.get("metrics"):
        rep = _rep_path(tree, path)
        try:
            cache[key] = {"row": dict(row),
                          "sig": _cache_signature(state, tree, source_registry, it, rep)}
        except Exception as exc:
            print(f"[fespp] compare cache of {path!r}:", exc, flush=True)
    return row


def _read_by_time(items, read):
    """`read(it)` over the rows with the fewest moves of the pipeline: the
    session's own time step first (no move), then the others grouped by step
    inside one `time_batch`, so two rows at one date share one move and the
    pipeline goes back to the session's time once, not after every row. A 3D
    view's rows, which read what it draws at the view's time, come after the
    batch, inside one `transient_chain`, their proxies unseen."""
    from fespp_on_trame.engine import compare_rows
    from fespp_on_trame.engine.property_values import time_batch
    order = sorted(items, key=lambda it: (it["ts"] is not None,
                                          it["ts"] if it["ts"] is not None else -1))
    with time_batch():
        for it in order:
            if not compare_rows.is_view_row(it):
                read(it)
    on_views = [it for it in order if compare_rows.is_view_row(it)]
    if on_views:
        with _sd().transient_chain():
            for it in on_views:
                read(it)


def rows_for(state, tree, source_registry, items, pending=None, cache=None,
             loaded=None):
    """{id: row} for the selection — the value reads, i.e. the expensive
    half of the matrix. One row per selection entry (`item_id`), one READ
    per distinct item key: a pinned copy still at its source's realization
    and time shares the read; an item still waiting for its load is not
    read at all; with a `cache` (READS), a row read before and whose
    values cannot have changed is not read again; what is read goes in the
    order of `_read_by_time`. Each row carries what its pickers offer (`reals`,
    `ts_opts`, none on a following row), where it was read (`real`, `ts`) and
    whether it is a pinned copy."""
    from fespp_on_trame.engine import crossplot_dispatch
    items = [it for it in (_norm_item(it) for it in items or []) if it["path"]]
    if cache is not None:
        cache["_hits"], cache["_reads"] = 0, 0
    reads, axes, rows = {}, {}, {}

    def _read(it):
        key = item_key(it["path"], it["real"], it["ts"], it["support"])
        if key not in reads:
            reads[key] = _cached_row(
                cache, key, state, tree, source_registry, it,
                (pending or {}).get(it["path"]) or "", loaded)

    _read_by_time(items, _read)
    for it in items:
        key = item_key(it["path"], it["real"], it["ts"], it["support"])
        if not it["support"] and it["path"] not in axes:
            try:
                axes[it["path"]] = crossplot_dispatch.axis_options(
                    state, tree, it["path"])
            except Exception as exc:
                # the row keeps its figures and loses its pickers: said
                print(f"[fespp] compare axes of {it['path']!r}:", exc, flush=True)
                axes[it["path"]] = {"reals": [], "ts": []}
        rid = item_id(it)
        if rid in rows:
            continue
        row = dict(reads[key])
        pickers = {} if it["support"] else axes[it["path"]]
        row.update({
            "uid": it["uid"], "key": key, "path": it["path"],
            "pinned": it["pinned"],
            "title": _labelled(state, tree, it["path"]),
            "reals": list(pickers.get("reals") or []),
            "ts_opts": list(pickers.get("ts") or []),
            "support": it["support"], "follows": it["follows"],
        })
        rows[rid] = row
    return rows


def blocks_from_rows(items, rows, baseline_key, sort_key, sort_asc):
    """(blocks, annotations) over rows already computed — pure ordering,
    so sorting the matrix never re-reads a single array."""
    items = [it for it in (_norm_item(it) for it in items or []) if it["path"]]
    rows = rows or {}
    base = _baseline_index(items, baseline_key)
    base_key = item_id(items[base]) if base is not None else ""
    order = []
    for it in items:
        key = item_id(it)
        if key in rows and key not in order:
            order.append(key)

    by_kind = {}
    for key in order:
        by_kind.setdefault(rows[key].get("kind") or NO_KIND, []).append(key)

    blocks, annotations = [], {}
    for kind, keys in by_kind.items():
        rest = [k for k in keys if k != base_key]
        if sort_key:
            shaped = [dict(compare_matrix.sortable(rows[k]), key=k) for k in rest]
            rest = [s["key"] for s in compare_matrix.sort_items(
                shaped, sort_key, bool(sort_asc))]
        else:
            # the baseline goes first: what follows it stays right under it
            rest.sort(key=lambda k: rows[k].get("follows") != base_key)
        keys = ([base_key] if base_key in keys else []) + rest
        # the block's unit for its headers: the one every row agrees on,
        # else none — and a word that it is mixed. A row without a unit
        # counts as its own case: it must not be written under the others'
        declared = sorted({rows[k].get("uom") for k in keys if rows[k].get("uom")})
        undeclared = any(not rows[k].get("uom") for k in keys)
        units = declared + (["none declared"] if declared and undeclared else [])
        blocks.append({"kind": kind, "keys": keys,
                       "uom": declared[0] if len(units) == 1 else "",
                       "uom_mixed": len(units) > 1,
                       "units": units,
                       # whether a column has anything to say in this block
                       "sum_meaningful": any(rows[k].get("sum_meaningful", True) for k in keys),
                       "has_length": any("Mean (L)" in (rows[k].get("metrics") or {}) for k in keys)})
        mode = "baseline" if base_key in keys else "extrema"
        block_items = [{"key": k, "row": rows[k].get("metrics") or {}}
                       for k in keys]
        tags = compare_matrix.highlight_annotations_for_items(
            block_items, mode,
            baseline_key=base_key if mode == "baseline" else None)
        for metric, by_idx in tags.items():
            for idx, tag in by_idx.items():
                annotations.setdefault(keys[idx], {})[metric] = tag
    return blocks, annotations


def deltas_from_rows(items, rows, baseline_key):
    """{key: {metric: {"abs", "rel"}}} — every row's difference to the
    baseline of its kind, absolute in the metric's unit and relative in
    percent of the baseline; the baseline row and a kind without it have
    no entry. Pure arithmetic over rows already computed, like the
    ordering above: what the matrix writes under each cell."""
    items = [it for it in (_norm_item(it) for it in items or []) if it["path"]]
    rows = rows or {}
    base = _baseline_index(items, baseline_key)
    if base is None:
        return {}
    base_key = item_id(items[base])
    base_kind = (rows.get(base_key) or {}).get("kind") or NO_KIND
    keys, seen = [], set()
    for it in items:
        key = item_id(it)
        if key in rows and key not in seen \
                and (rows[key].get("kind") or NO_KIND) == base_kind:
            keys.append(key)
            seen.add(key)
    block_items = [{"key": k, "row": rows[k].get("metrics") or {}} for k in keys]
    out = {}
    for metric, by_idx in compare_matrix.baseline_deltas_for_items(
            block_items, base_key).items():
        for idx, d in by_idx.items():
            out.setdefault(keys[idx], {})[metric] = d
    return out


def matrix(state, tree, source_registry, items, baseline_key, sort_key,
           sort_asc, pending=None, cache=None, loaded=None):
    """(blocks, rows, annotations) of the matrix: one block per PWLS kind
    in first-appearance order, the baseline row first in its block and the
    others sorted by `sort_key` (selection order when none); annotations
    are deltas against the baseline inside its block, extrema elsewhere."""
    rows = rows_for(state, tree, source_registry, items, pending,
                    cache=cache, loaded=loaded)
    blocks, annotations = blocks_from_rows(items, rows, baseline_key,
                                           sort_key, sort_asc)
    return blocks, rows, annotations


# ---------------------------------------------------------------------------
# Distributions of one kind
# ---------------------------------------------------------------------------

def _dist_opts(opts):
    from fespp_on_trame.engine import distribution_dispatch as dd
    o = dict(_DIST_DEFAULTS)
    for k, v in (opts or {}).items():
        if v is not None and k in o:
            o[k] = v
    if o["mode"] not in dd._VALID_MODES:
        o["mode"] = dd._MODE_BARS
    if o["norm"] not in dd._VALID_NORMS:
        o["norm"] = dd._NORM_COUNT
    try:
        o["nbins"] = max(1, min(500, int(o["nbins"])))
    except (TypeError, ValueError):
        o["nbins"] = _DIST_DEFAULTS["nbins"]
    o["log_y"] = bool(o["log_y"])
    o["cumulative"] = bool(o["cumulative"])
    return o


def _y_title(o):
    title = {"count": "Count", "density": "Density",
             "probability": "Probability"}.get(o["norm"], "Count")
    return f"Cumulative {title.lower()}" if o["cumulative"] else title


def _hover_of(trace, label, y_title, names=None, bins=None, unit=""):
    """What a bar of a distribution says on hover: the item's whole name
    above, then one line per value — its category (`names`, code -> label),
    else the class it counts (`bins`, the lower and upper bound of each, in
    `unit`). A count keeps every digit; no number has a thousands separator."""
    if names is not None:
        trace["customdata"] = [names.get(float(c)) or f"{float(c):g}" for c in trace.get("x") or []]
        what = "Category: %{customdata}"
    else:
        trace["customdata"] = bins
        what = "From %{customdata[0]:.5~g} to %{customdata[1]:.5~g}" + (f" {unit}" if unit else "")
    height = "%{y:d}" if y_title.endswith(("Count", "count")) else "%{y:.6~r}"
    trace["hovertemplate"] = f"<b>{label}</b><br>{what}<br>{y_title}: {height}<extra></extra>"


def _row_trace(state, tree, source_registry, it, rep, o):
    """What a row draws in the overlay, whatever it is named and painted:
    `{"why"}` when its values cannot be read, else how many it holds (`total`,
    `kept`), their `span`, its `trace` (None with no finite value) and how to
    tell a bar of it: a discrete property's `codes` and their `names`, else the
    `bins`."""
    from fespp_on_trame.engine import compare_rows
    from fespp_on_trame.engine import distribution_dispatch as dd
    import numpy as np
    path = it["path"]
    if it["support"]:
        vals = compare_rows.support_values(state, tree, source_registry, it)
        why = compare_rows.last_error()
    else:
        try:
            vals = _values_for(state, tree, source_registry, path, rep,
                               real_idx=it["real"], ts_idx=it["ts"])
        except Exception as exc:
            print(f"[fespp] compare distribution of {path!r}:", exc, flush=True)
            vals = None
        why = _read_error()
    if vals is None:
        return {"why": why or "unreadable"}
    vals = np.asarray(vals, dtype=float).ravel()
    fin = vals[np.isfinite(vals)]
    discrete = _is_discrete(tree, path)
    build = dd._build_discrete_trace if discrete else dd._build_continuous_trace
    kwargs = {"mode": o["mode"], "cumulative": o["cumulative"], "norm": o["norm"]}
    if not discrete:
        kwargs["nbins"] = o["nbins"]
    trace, kept, *rest = build(vals, np, **kwargs)
    read = {"total": int(vals.size), "kept": int(kept), "trace": trace, "discrete": discrete,
            "span": (float(fin.min()), float(fin.max())) if fin.size else None}
    if trace is not None and discrete:
        read["codes"] = [float(c) for c in (trace.get("x") or [])]
        read["names"] = _category_names(tree, source_registry, path, it["real"], read["codes"])
    elif trace is not None:
        read["bins"] = [[c - w / 2.0, c + w / 2.0] for c, w in zip(rest[1], rest[3])]
    return read


def _cached_trace(cache, state, tree, source_registry, it, o, loaded):
    """What a row draws, from the cache when its values cannot have changed
    since it was read (the rule of `_cached_row`): a gesture on a 3D view then
    reads the rows of that view, not every pinned time step again."""
    from fespp_on_trame.engine import compare_rows
    path = it["path"]
    rep = _rep_path(tree, path)
    if not rep:
        return {"why": "not loaded"}
    cacheable = (cache is not None and not compare_rows.is_view_row(it)
                 and not derived_props.is_derived(path)
                 and (loaded is None or path in loaded))
    if not cacheable:
        return _row_trace(state, tree, source_registry, it, rep, o)
    key = item_key(path, it["real"], it["ts"], it["support"])
    try:
        sig = (dict(o), _cache_signature(state, tree, source_registry, it, rep))
    except Exception as exc:
        print(f"[fespp] compare traces of {path!r}:", exc, flush=True)
        return _row_trace(state, tree, source_registry, it, rep, o)
    hit = cache.get(key)
    if hit is not None and hit["sig"] == sig:
        return hit["read"]
    read = _row_trace(state, tree, source_registry, it, rep, o)
    if read.get("trace") is not None:
        cache[key] = {"sig": sig, "read": read}
    return read


def _paint(trace, colour):
    for part in ("line", "marker"):
        if part in trace:
            trace[part]["color"] = colour


def dist_figure(state, tree, source_registry, items, opts, pending=None, cache=None, loaded=None):
    """(figure | None, meta) — the overlaid histograms of the rows of ONE
    kind, one trace per row under the same binning options, the rows that
    follow an item included. A discrete or categorical property bins per
    category. meta = {kept, total, note, traces}: `note` says what could not
    be drawn, and a None figure always comes with one. With a `cache` (TRACES),
    an item read before and whose values cannot have changed is not read again;
    what is read goes in the order of `_read_by_time`."""
    from fespp_on_trame.engine import compare_rows
    from fespp_on_trame.engine import distribution_dispatch as dd
    import copy
    sd = _sd()
    o = _dist_opts(opts)
    items = [it for it in (_norm_item(it) for it in items or []) if it["path"]]
    meta = {"kept": 0, "total": 0, "note": "", "traces": 0}
    traces, dropped = [], []
    span = [float("inf"), float("-inf")]     # of every finite value drawn
    # the names of the categories the discrete items draw, code -> label
    # (the file's own names), and
    # every code drawn
    cat_names, drawn_codes, all_discrete = {}, set(), True
    # an item keeps its colour whatever rows come and go under it
    painted = ([i for i, it in enumerate(items) if not it["support"]]
               + [i for i, it in enumerate(items) if it["support"]])
    colours = {i: dd._COLORWAY[n % len(dd._COLORWAY)] for n, i in enumerate(painted)}
    reads = {}

    def _read(it):
        reads[id(it)] = _cached_trace(cache, state, tree, source_registry, it, o, loaded)

    _read_by_time([it for it in items if (pending or {}).get(it["path"]) not in _LOAD_TAG], _read)
    for i, it in enumerate(items):
        path = it["path"]
        label = (compare_rows.naming(state, tree, it)["label"] if it["support"]
                 else _row_label(state, tree, path, it["real"], it["ts"]))
        read = reads.get(id(it))
        if read is None:
            dropped.append(f"{label} ({_LOAD_TAG[pending[path]]})")
            continue
        if "why" in read:
            dropped.append(f"{label} ({read['why']})")
            continue
        if read["span"]:
            span = [min(span[0], read["span"][0]), max(span[1], read["span"][1])]
        meta["total"] += read["total"]
        if read["trace"] is None:
            dropped.append(f"{label} (no finite value)")
            continue
        meta["kept"] += read["kept"]
        trace = copy.deepcopy(read["trace"])
        _paint(trace, colours[i])
        trace["name"] = label
        if read["discrete"]:
            drawn_codes.update(read["codes"])
            cat_names.update(read["names"])
            _hover_of(trace, label, _y_title(o), names=cat_names)
        else:
            all_discrete = False
            _hover_of(trace, label, _y_title(o), bins=read["bins"],
                      unit=sd._unit_for_array_path(tree, path))
        if o["mode"] == dd._MODE_BARS:
            trace["opacity"] = _BAR_OPACITY
            trace["marker"].pop("opacity", None)
        else:
            trace["opacity"] = _LINE_OPACITY
            trace.pop("fill", None)
            trace.pop("fillcolor", None)
        traces.append(trace)
    meta["traces"] = len(traces)
    if dropped:
        meta["note"] = "not drawn: " + "; ".join(dropped)
    if not traces:
        meta["note"] = meta["note"] or "No item to draw."
        return None, meta

    first = items[0]["path"]
    kinds = {_kind_label(tree, it["path"]) for it in items}
    x_title = (kinds.pop() if len(kinds) == 1 and NO_KIND not in kinds
               else _labelled(state, tree, first))
    uom = sd._unit_for_array_path(tree, first)
    if uom:
        x_title = f"{x_title} ({uom})"
    yaxis = {"title": {"text": _y_title(o)}}
    if o["log_y"]:
        yaxis["type"] = "log"
    xaxis = {"title": {"text": x_title}}
    if all_discrete and cat_names:
        # categories named by the file: the axis says the names, not codes
        from fespp_on_trame.engine.utils import categories
        codes = sorted(drawn_codes)
        xaxis.update(tickmode="array", tickvals=codes,
                     ticktext=[cat_names.get(c) or categories.label_of({}, c) for c in codes])
    shapes = []
    # every item a difference: the axis is symmetric around a zero line;
    # a lone trace also takes the diverging bar colours (an overlay keeps
    # one colour per item so they can be told apart)
    if all(derived_props.is_difference(it["path"]) for it in items):
        m = max(abs(span[0]), abs(span[1])) if span[0] <= span[1] else 0.0
        if m > 0:
            xaxis["range"] = [-m, m]
        shapes.append(dd.zero_line())
        if len(traces) == 1 and o["mode"] == dd._MODE_BARS and traces[0].get("width"):
            traces[0]["marker"]["color"] = dd.diverging_colors(
                traces[0]["x"], traces[0]["width"])
    import plotly.graph_objects as go
    fig = go.Figure(
        data=traces,
        layout=go.Layout(
            xaxis=xaxis, yaxis=yaxis, shapes=shapes,
            # level with the cross-plot beside it (engine/crossplot_dispatch);
            # its legend upright at its right: many rows do not crush the plot
            margin={"l": 54, "r": 12, "t": 44, "b": 49},
            barmode="overlay", bargap=0.05, autosize=True,
            showlegend=True, legend={"orientation": "v", "x": 1.01, "y": 1, "yanchor": "top"},
            # the user's zoom survives a refresh (an item added, another
            # bin count) while the axes mean the same thing: the kind on
            # X, the component read of every item drawn, and what the
            # heights stand for on Y
            uirevision=(f"{x_title}|{o['log_y']}|{o['norm']}"
                        f"|{o['cumulative']}|" + ",".join(
                            _pv().axis_key(state, it["path"]) for it in items
                            if not it["support"])),
        ),
    )
    return fig, meta


# ---------------------------------------------------------------------------
# Cross-plot seeds
# ---------------------------------------------------------------------------

def xplot_seeds(state, tree, items, x_key, pending=None):
    """The cross-plot axes: X = the item `x_key` names, else the first (X is
    the abscissa, not a chart); one Y per other item flagged `xplot`, on the
    same representation — index alignment is what makes the cloud honest. An
    item elsewhere is dropped with its reason in `skipped`, and so is X's own
    diagonal. An item not flagged is not a drop: it is not listed."""
    out = {"x": None, "xreal": None, "xts": None, "ys": [], "skipped": []}
    items = [it for it in (_norm_item(it) for it in items or []) if it["path"]]
    base = _baseline_index(items, x_key)
    if base is None:
        base = next((i for i, it in enumerate(items) if not it["support"]), None)
    if base is None:
        return out
    x = items[base]
    out.update({"x": x["path"], "xreal": x["real"], "xts": x["ts"]})
    x_rep = _rep_path(tree, x["path"])
    x_rep_title = _rep_title(tree, x["path"]) or "the grid of X"
    for i, it in enumerate(items):
        if i == base or not it["xplot"]:
            continue
        label = _row_label(state, tree, it["path"], it["real"], it["ts"])
        st = (pending or {}).get(it["path"]) or ""
        if st in _LOAD_TAG:
            out["skipped"].append(f"{label}: {_LOAD_TAG[st]}")
            continue
        if _rep_path(tree, it["path"]) != x_rep:
            out["skipped"].append(f"{label}: not on {x_rep_title}")
            continue
        if (it["path"], it["real"], it["ts"]) == (x["path"], x["real"], x["ts"]):
            out["skipped"].append(f"{label}: same as X (the diagonal)")
            continue
        out["ys"].append({"path": it["path"], "real": it["real"],
                          "ts": it["ts"]})
    return out


# ---------------------------------------------------------------------------
# The matrix as a file
# ---------------------------------------------------------------------------

def csv_payload(items, rows, baseline_key, kind=""):
    """`{"name", "header"}` the Statistics view's Copy CSV writes its matrix
    under — the kind of the tab, its baseline, the items with where each
    was read, and where the rows that follow them were. The widget writes the
    rows it holds under this header."""
    from fespp_on_trame.engine import compare_rows
    from fespp_on_trame.engine.utils import csv_export as ce
    items = [it for it in (_norm_item(it) for it in items or []) if it["path"]]
    rows = rows or {}
    if not items or not rows:
        return dict(ce.EMPTY_PAYLOAD)
    base = _baseline_index(items, baseline_key)
    fields = []
    if kind:
        fields.append(("kind", kind))
    if base is not None:
        bk = item_id(items[base])
        fields.append(("baseline", (rows.get(bk) or {}).get("label") or bk))
    fields.append(("items", str(sum(1 for it in items if not it["support"]))))
    for it in items:
        key = item_id(it)
        r = rows.get(key) or {}
        if it["support"]:
            fields.append(("following row",
                           f"{r.get('label') or key} ({compare_rows.where_read(it, r)})"
                           + (f" - {r['note']}" if r.get("note") else "")))
            continue
        where = [r.get("rep") or ""]
        if it["real"] is not None:
            where.append(f"real {it['real']}")
        if it["ts"] is not None:
            where.append(f"time step {it['ts']}")
        fields.append(("item", f"{r.get('label') or key} ({', '.join(w for w in where if w)})"
                       + (f" - {r['note']}" if r.get("note") else "")))
    pore_volumes = {}
    for it in items:
        r = rows.get(item_id(it)) or {}
        if r.get("pore_volume"):
            pore_volumes.setdefault(r.get("rep") or "", r["pore_volume"])
    fields.extend(("pore volume", f"{rep}: {read}") for rep, read in pore_volumes.items())
    fields.append(("unit", "the one the rows share, else each row names its own"))
    fields.append(("metrics", "raw values; value_count and no_value_count are"
                              " counts; variance, m2, m3, m4 in the unit to the"
                              " power 2, 2, 3, 4; mean_volume_weighted is"
                              " weighted by the cell volume and"
                              " mean_pore_volume_weighted by volume x"
                              " net-to-gross x porosity, mean_length_weighted by"
                              " the interval length on a blocked wellbore's row,"
                              " n/a where the weights could not be obtained - see"
                              " each item's line"))
    return ce.payload("statistics", fields)
