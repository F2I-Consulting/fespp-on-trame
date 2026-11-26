"""The Statistics matrix's primitives.

The Statistics view's matrix (engine/compare_dispatch) is a table of
items (the selected properties) x metrics (Cardinality, Mean, ...).
This module provides the pure primitives it reads: the canonical
metric list, the sort, the highlight annotations (the sign of each
cell against the baseline, or the extrema of a block without one) and
the deltas to the baseline. No PV / state access: it only takes item
dicts carrying a `row` of metrics. The metric LABELS live in the
widget (`metrics.js`), which is what renders them.
"""
import numbers


# "Mean (V)" / "Mean (PV)" are the volume- and pore-volume-weighted means
# (engine/cell_weights), "Mean (L)" the mean along the hole of a blocked
# wellbore's row (engine/stats_supports); they sit beside the arithmetic
# "Mean", which stays.
# Mirrored in widgets/_shared/numfmt.js (STAT_UNIT_POWER) and widgets/compare
# metrics.js: move all three together.
_METRIC_KEYS = (
    "Cardinality", "NaN_count", "Minimum", "Maximum", "Mean",
    "Mean (V)", "Mean (PV)", "Mean (L)",
    "Standard Deviation", "Variance", "Sum", "P10", "Q1", "Median", "Q3", "P90",
    "Skewness", "Kurtosis", "M2", "M3", "M4",
)


# How far two reads of the same values stand apart: numpy and the filter chain
# behind a 3D view's row do not sum in the same order. A figure close to zero
# is measured against what its noise scales with, not against itself.
_NOISE = 1e-9
_IN_THE_UNIT = frozenset((
    "Minimum", "Maximum", "Mean", "Mean (V)", "Mean (PV)", "Mean (L)",
    "Standard Deviation", "P10", "Q1", "Median", "Q3", "P90"))


def _noise_scale(metric, row):
    """What the noise of `metric` scales with on `row`, besides the figure."""
    if metric in ("Skewness", "Kurtosis"):
        return 1.0
    if metric == "M3":
        return abs(row.get("M2") or 0.0) ** 1.5
    spread = abs(row.get("Standard Deviation") or 0.0)
    if metric == "Sum":
        return spread * abs(row.get("Cardinality") or 0.0)
    return spread if metric in _IN_THE_UNIT else 0.0


def _delta(metric, v, base, row):
    """`v - base`, 0 when the two are the same read's noise apart."""
    delta = v - base
    scale = max(abs(v), abs(base), _noise_scale(metric, row))
    return 0.0 if abs(delta) <= _NOISE * scale else delta


# What the matrix sorts on besides its metrics: the total count (defined +
# undefined, which the widget adds up from the two counts) and the name of the
# representation a row reads, its own column. Mirrored in widgets/compare
# metrics.js (COUNT_COLUMNS, REP_COLUMN).
TOTAL = "Total"
REPRESENTATION = "Representation"
SORT_KEYS = (REPRESENTATION, TOTAL) + _METRIC_KEYS


def sortable(row):
    """What a row of the matrix is sorted on: its metrics, its total count
    when it has counts, and the representation the screen writes for it —
    where a following row is read, else its item's representation."""
    metrics = row.get("metrics") or {}
    out = dict(metrics)
    if metrics.get("Cardinality") is not None:
        out[TOTAL] = float(metrics["Cardinality"]) + float(metrics.get("NaN_count") or 0.0)
    out[REPRESENTATION] = row.get("support_label") or row.get("rep") or ""
    return out


def sort_items(items, sort_key, sort_asc):
    """Return items sorted by sort_key (a metric key, `TOTAL` or
    `REPRESENTATION`). Stable sort; numbers by value, words alphabetically
    whatever their case; None, an empty word and a value that is neither
    sink to the bottom whatever the direction."""
    if not sort_key:
        return list(items)

    def _value(it):
        v = it.get(sort_key)
        if isinstance(v, str):
            return (1, v.casefold()) if v else None
        if v is None or isinstance(v, bool):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if f != f else (0, f)

    keyed = [(it, _value(it)) for it in items]
    ranked = sorted((pair for pair in keyed if pair[1] is not None),
                    key=lambda pair: pair[1], reverse=not sort_asc)
    return [it for it, _v in ranked] + [it for it, v in keyed if v is None]


def _numeric(rows, metric):
    """[(index, float)] of the rows carrying a number for `metric`. A
    missing metric (None, an en dash) is the common case, not an error."""
    vals = []
    for i, r in enumerate(rows):
        v = r.get(metric)
        if isinstance(v, bool) or not isinstance(v, numbers.Real):
            continue
        vals.append((i, float(v)))
    return vals


def highlight_annotations(rows, mode, base_idx=None):
    """{metric: {row index: tag}}: the tag a cell is drawn with.

    `mode = "baseline"`: the sign of each row's difference to the row at
    `base_idx` ("pos" / "neg" / "eq"; the baseline itself "eq").
    `mode = "extrema"`: "min" / "max" on the two ends of each metric, when
    they differ, for a block with no baseline in it. Anything else annotates
    nothing."""
    out = {}
    if not rows or not mode:
        return out
    for mk in _METRIC_KEYS:
        vals = _numeric(rows, mk)
        if not vals:
            continue
        if mode == "extrema":
            lo = min(vals, key=lambda t: t[1])
            hi = max(vals, key=lambda t: t[1])
            if lo[1] == hi[1]:
                continue
            out.setdefault(mk, {})[lo[0]] = "min"
            out.setdefault(mk, {})[hi[0]] = "max"
        elif mode == "baseline" and base_idx is not None:
            base = next((v for i, v in vals if i == base_idx), None)
            if base is None:
                continue
            for i, v in vals:
                delta = _delta(mk, v, base, rows[i])
                out.setdefault(mk, {})[i] = (
                    "eq" if i == base_idx or delta == 0
                    else ("pos" if delta > 0 else "neg"))
    return out


def baseline_deltas(rows, base_idx):
    """{metric: {row index: {"abs", "rel"}}}: each row's difference to
    the baseline row, absolute in the metric's unit and relative in
    percent of the baseline (None when the baseline is 0). The baseline
    row has no entry: it is what the others are read against."""
    out = {}
    if not rows or base_idx is None:
        return out
    for mk in _METRIC_KEYS:
        vals = _numeric(rows, mk)
        base = next((v for i, v in vals if i == base_idx), None)
        if base is None:
            continue
        for i, v in vals:
            if i == base_idx:
                continue
            delta = _delta(mk, v, base, rows[i])
            out.setdefault(mk, {})[i] = {
                "abs": delta,
                "rel": (delta / base * 100.0) if base != 0 else None,
            }
    return out


def _base_index(items, baseline_key):
    """Index of the item whose `key` is `baseline_key`, or None."""
    if not baseline_key:
        return None
    for i, it in enumerate(items or []):
        if (it or {}).get("key") == baseline_key:
            return i
    return None


def highlight_annotations_for_items(items, mode, baseline_key=None):
    """`highlight_annotations` over `item["row"]`, the baseline found by
    its `item["key"]`; indexed by the items' order."""
    rows = [(it or {}).get("row") or {} for it in (items or [])]
    return highlight_annotations(rows, mode, _base_index(items, baseline_key))


def baseline_deltas_for_items(items, baseline_key):
    """`baseline_deltas` over `item["row"]`, the baseline found by its
    `item["key"]`; indexed by the items' order."""
    rows = [(it or {}).get("row") or {} for it in (items or [])]
    return baseline_deltas(rows, _base_index(items, baseline_key))


def profile_tag(skewness, kurtosis):
    """Classify a distribution from its skewness + kurtosis.

    Thresholds (conventional but tunable), checked in this order:
      - |excess kurt| > 3 (regardless of skew) → heavy_tail
      - skew >= 0.5 → skewed_right
      - skew <= -0.5 → skewed_left
      - |skew| < 0.5 AND |excess kurt| < 1 → symmetric
    Returns "" when either input is missing or non-numeric, or when no
    rule matches, so the panel template can hide the chip."""
    if skewness is None or kurtosis is None:
        return ""
    try:
        sk = float(skewness)
        ku = float(kurtosis)
    except (TypeError, ValueError):
        return ""
    # The value is read as EXCESS kurtosis (0 for a normal distribution),
    # which is what vtkDescriptiveStatistics reports. A source that gives
    # raw (Pearson) kurtosis must subtract 3 before calling this.
    excess = ku
    if abs(excess) > 3:
        return "heavy_tail"
    if sk >= 0.5:
        return "skewed_right"
    if sk <= -0.5:
        return "skewed_left"
    if abs(sk) < 0.5 and abs(excess) < 1:
        return "symmetric"
    return ""

