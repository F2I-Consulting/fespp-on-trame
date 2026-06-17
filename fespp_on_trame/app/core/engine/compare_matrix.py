"""Compare-stats matrix primitives.

The floating Compare-stats panel (kind=stats_compare) is a
server-side-rendered matrix of items (cart rows) x metrics
(Cardinality, Mean, ...). This module provides the pure
primitives the panel reads: metric-visibility filter, sort,
highlight annotations (extrema / baseline-delta / heat-map),
and CSV export. No PV / state access -- only takes a list of
item dicts as produced by stats_dispatch.publish_compare_items.
"""


_METRIC_KEYS = (
    "Cardinality", "NaN_count", "Minimum", "Maximum", "Mean",
    "Standard Deviation", "Variance", "Sum", "Q1", "Median", "Q3",
    "Skewness", "Kurtosis", "M2", "M3", "M4",
)

_METRIC_LABELS = {
    "Cardinality": "Value count",
    "NaN_count": "No value count",
    "Minimum": "Min", "Maximum": "Max", "Mean": "Mean",
    "Standard Deviation": "Std Dev", "Variance": "Variance",
    "Sum": "Sum", "Q1": "Q1", "Median": "Median", "Q3": "Q3",
    "Skewness": "Skewness", "Kurtosis": "Kurtosis",
    "M2": "M2", "M3": "M3", "M4": "M4",
}


def visible_metric_keys(hidden_metrics):
    """Return metric keys in canonical order, minus the ones
    the user hid via the metric-visibility multi-select."""
    hidden = set(hidden_metrics or [])
    return tuple(k for k in _METRIC_KEYS if k not in hidden)


def sort_items(items, sort_key, sort_asc):
    """Return items sorted by sort_key (a metric key). Stable
    sort; None/non-numeric values sink to the bottom."""
    if not sort_key:
        return list(items)

    def _key(it):
        v = it.get(sort_key)
        if v is None:
            return (1, 0.0)
        try:
            return (0, float(v) * (1 if sort_asc else -1))
        except (TypeError, ValueError):
            return (1, 0.0)

    return sorted(items, key=_key)


def highlight_annotations(items, mode, baseline_key=None, normalize=False):
    """Return a dict {metric_key: {item_idx: tag}} where tag is
    one of:
      - 'min' / 'max' (for extrema mode, strings)
      - 'pos' / 'neg' / 'eq' (for baseline mode, sign of delta)
      - float 0..1 (for heatmap mode, relative position in range)

    Heatmap intensity formula:
      - normalize=False (default): per-metric min/max rescale.
        Each metric column has its own colour scale; a value at the
        bottom of one column gets the same colour as the bottom of
        another even though the absolute magnitudes differ.
      - normalize=True: z-score per metric, clipped to ±3σ, mapped
        to [0, 1]. With this on, a cell two standard deviations
        above the metric's mean reads the same colour as a cell
        two stddev above the mean on a different metric — useful
        for spotting "this realization is consistently high
        across all metrics" patterns.

    The panel UI converts string tags to CSS classes and the float
    heatmap intensity to a CSS `hsl()` gradient via inline style."""
    out = {}
    if not items or not mode:
        return out
    for mk in _METRIC_KEYS:
        vals = []
        for i, it in enumerate(items):
            v = it.get(mk)
            try:
                vals.append((i, float(v)))
            except (TypeError, ValueError):
                pass
        if not vals:
            continue
        if mode == "extrema":
            lo = min(vals, key=lambda t: t[1])
            hi = max(vals, key=lambda t: t[1])
            out.setdefault(mk, {})[lo[0]] = "min"
            out.setdefault(mk, {})[hi[0]] = "max"
        elif mode == "baseline" and baseline_key:
            base_idx = next(
                (i for i, it in enumerate(items)
                 if it.get("key") == baseline_key), None,
            )
            if base_idx is None:
                continue
            base = next(
                (v for i, v in vals if i == base_idx), None,
            )
            if base is None:
                continue
            for i, v in vals:
                if i == base_idx:
                    continue
                delta = v - base
                out.setdefault(mk, {})[i] = "pos" if delta > 0 else (
                    "neg" if delta < 0 else "eq"
                )
        elif mode == "heatmap":
            if normalize:
                # Z-score per metric, then clip to ±3σ and rescale
                # to [0, 1]. σ=0 collapses the metric to a uniform
                # 0.5 grey — no spread to colour.
                n = len(vals)
                mean = sum(v for _, v in vals) / n
                var = sum((v - mean) ** 2 for _, v in vals) / n
                std = var ** 0.5
                if std == 0:
                    for i, _ in vals:
                        out.setdefault(mk, {})[i] = 0.5
                    continue
                for i, v in vals:
                    z = (v - mean) / std
                    if z > 3:
                        z = 3
                    elif z < -3:
                        z = -3
                    out.setdefault(mk, {})[i] = (z + 3) / 6.0
            else:
                lo = min(v for _, v in vals)
                hi = max(v for _, v in vals)
                if hi == lo:
                    for i, _ in vals:
                        out.setdefault(mk, {})[i] = 0.5
                    continue
                for i, v in vals:
                    out.setdefault(mk, {})[i] = (v - lo) / (hi - lo)
    return out


def items_to_csv(items, hidden_metrics=None):
    """Export the comparison matrix (items x metrics) as CSV.
    Column order: label, then every visible metric in canonical
    order. Hidden metrics are skipped (the user dropped them
    via the toolbar)."""
    cols = visible_metric_keys(hidden_metrics)
    header = ["row"] + [_METRIC_LABELS[k] for k in cols]
    lines = [",".join(_csv_escape(c) for c in header)]
    for it in items:
        row = [_csv_escape(it.get("column_label") or it.get("label") or it.get("key") or "")]
        stats = it.get("row") or {}
        for k in cols:
            v = stats.get(k)
            if v is None:
                row.append("")
            else:
                try:
                    row.append(_csv_num(float(v)))
                except (TypeError, ValueError):
                    row.append(_csv_escape(v))
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def profile_tag(skewness, kurtosis):
    """Classify a distribution from its skewness + kurtosis.

    Thresholds (conventional but tunable):
      - |skew| < 0.5 AND |excess kurt| < 1 → symmetric
      - skew >= 0.5 → skewed_right
      - skew <= -0.5 → skewed_left
      - excess kurt > 3 (regardless of skew) → heavy_tail
    Returns "" when either input is missing or non-numeric, so
    the panel template can hide the chip gracefully."""
    try:
        sk = float(skewness)
        ku = float(kurtosis)
    except (TypeError, ValueError):
        return ""
    # vtkDescriptiveStatistics returns Pearson kurtosis (excess
    # over normal = kurtosis − 3). Some pipelines return raw
    # kurtosis; we treat the value as excess (centered on 0).
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


def highlight_annotations_for_items(items, mode, baseline_key=None, normalize=False):
    """Wrapper over highlight_annotations that drills into
    item['row'] to read metrics. Returns the same shape dict
    but indexed by the items list order. `normalize` only
    affects heatmap mode (z-score vs per-metric min/max)."""
    rows = [(it or {}).get("row") or {} for it in (items or [])]
    # The baseline lookup needs the wrapper (it carries the cart key),
    # not the inner row dict.
    base_idx = None
    if baseline_key:
        for i, it in enumerate(items or []):
            if it.get("key") == baseline_key:
                base_idx = i
                break
    out = highlight_annotations(rows, mode, baseline_key=None, normalize=normalize)
    # Baseline mode is re-tagged here by index, since we resolved the
    # baseline INDEX above rather than the key.
    if mode == "baseline" and base_idx is not None:
        out = {}
        for mk in _METRIC_KEYS:
            vals = []
            for i, r in enumerate(rows):
                v = r.get(mk)
                try:
                    vals.append((i, float(v)))
                except (TypeError, ValueError):
                    pass
            if not vals:
                continue
            base = next((v for i, v in vals if i == base_idx), None)
            if base is None:
                continue
            for i, v in vals:
                if i == base_idx:
                    out.setdefault(mk, {})[i] = "eq"
                    continue
                delta = v - base
                tag = "pos" if delta > 0 else ("neg" if delta < 0 else "eq")
                out.setdefault(mk, {})[i] = tag
                # Stash absolute + relative delta numerically
                # for the panel template to render inline.
                out.setdefault("_deltas", {}).setdefault(mk, {})[i] = {
                    "abs": delta,
                    "rel": (delta / base * 100.0) if base != 0 else None,
                }
    return out


def _csv_escape(s):
    s = str(s)
    if any(c in s for c in ',"\n'):
        return '"' + s.replace('"', '""') + '"'
    return s


def _csv_num(v):
    try:
        return ("{:.6g}").format(float(v))
    except (TypeError, ValueError):
        return _csv_escape(v)
