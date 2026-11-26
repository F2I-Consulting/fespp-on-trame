"""What the Statistics view's overlaid histograms are built with
(compare_dispatch.dist_figure): a trace per row, binned with a single
numpy.histogram (continuous) or per category (discrete / categorical).

Performance contract: the binning is pre-computed server-side and pushed
as a single Plotly trace, so the WebSocket payload stays at a few KB
regardless of source array size.
"""
from __future__ import annotations


_DEFAULT_NBINS = 50

# Display mode constants. "bars" is the classic histogram look; "line"
# is a step plot (line.shape="hv") that reads better when bin count is
# high; "curve" is a smoothed spline through bin centers (visually
# similar to a kernel-density curve but cheaper — no KDE bandwidth math).
_MODE_BARS = "bars"
_MODE_LINE = "line"
_MODE_CURVE = "curve"
_VALID_MODES = (_MODE_BARS, _MODE_LINE, _MODE_CURVE)

# Normalisation modes. "count" is raw bin counts; "density" makes the
# trace integrate to 1 (counts / (total * widths)); "probability" sums
# to 1 (counts / total). Density is the right pick when comparing
# distributions of different sample sizes; probability is the right
# pick when reading "what fraction of cells fall in this bin".
_NORM_COUNT = "count"
_NORM_DENSITY = "density"
_NORM_PROBABILITY = "probability"
_VALID_NORMS = (_NORM_COUNT, _NORM_DENSITY, _NORM_PROBABILITY)

# Vuetify-aligned palette cycled per trace by the Statistics view's
# overlay (compare_dispatch.dist_figure). Picked to stay
# distinguishable on a white background.
_COLORWAY = [
    "#1976d2",  # blue (matches Vuetify primary)
    "#388e3c",  # green
    "#f57c00",  # orange
    "#7b1fa2",  # purple
    "#c2185b",  # pink
    "#00796b",  # teal
    "#e64a19",  # deep orange
    "#5d4037",  # brown
    "#455a64",  # blue grey
    "#fbc02d",  # amber
]


def _is_discrete_kind(prop_kind):
    """Discrete / categorical properties get a per-category bar chart
    instead of a binned histogram. mean / std on unordered categories
    is meaningless; the histogram view is the only one that says
    something useful."""
    if not isinstance(prop_kind, str):
        return False
    pk = prop_kind.lower()
    return "discrete" in pk or "categorical" in pk


def _apply_norm(counts, total, widths, norm):
    """Normalize a counts vector per the requested mode. `widths` is
    needed for density; pass an array of ones for the discrete path
    where each category occupies one unit on the x-axis."""
    if total <= 0 or counts is None:
        return counts
    if norm == _NORM_DENSITY:
        # density = counts / (total * binwidth) → integrates to 1. `widths`
        # arrives as a plain list on the discrete path, hence numpy: an int
        # times a list is list repetition, not a product.
        import numpy as np
        denom = float(total) * np.asarray(widths, dtype=float)
        return counts / denom
    if norm == _NORM_PROBABILITY:
        return counts / float(total)
    return counts


def _shape_trace_for_mode(centers, heights, widths, mode, color="#1976d2"):
    """Build a Plotly trace dict from (centers, heights, widths) per
    the selected display mode.

    - bars: standard histogram-style bar trace.
    - line: step plot (line.shape="hv") with markers at each bin.
    - curve: smoothed spline through bin centers — visually close to
      a KDE without the bandwidth math (the binned counts are already
      there, no reason to redo a kernel sum)."""
    if mode == _MODE_LINE:
        return dict(
            type="scatter",
            mode="lines+markers",
            x=centers,
            y=heights,
            line=dict(color=color, shape="hv", width=2),
            marker=dict(color=color, size=4),
        )
    if mode == _MODE_CURVE:
        return dict(
            type="scatter",
            mode="lines",
            x=centers,
            y=heights,
            line=dict(color=color, shape="spline", smoothing=0.8, width=2),
            fill="tozeroy",
            fillcolor="rgba(25, 118, 210, 0.18)",
        )
    return dict(
        type="bar",
        x=centers,
        y=heights,
        width=widths,
        marker=dict(color=color, opacity=0.85),
    )


def _build_continuous_trace(values, np, *, nbins=_DEFAULT_NBINS,
                            mode=_MODE_BARS, cumulative=False,
                            norm=_NORM_COUNT, color="#1976d2"):
    """numpy.histogram → trace whose shape depends on `mode`. NaN
    values are dropped pre-binning so kurtosis / skewness stay
    meaningful; same contract as stats_dispatch's Threshold(no-NaN)
    chain.

    Returns (trace, kept_count, finite_values, bin_centers, bin_heights, bin_widths).
    The extra returns feed the overlay's meta."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, 0, finite, None, None, None
    counts, edges = np.histogram(finite, bins=int(max(1, nbins)))
    centers = (edges[:-1] + edges[1:]) / 2.0
    widths = (edges[1:] - edges[:-1])
    heights = counts.astype(float)
    if cumulative:
        heights = np.cumsum(heights)
    heights = _apply_norm(heights, int(finite.size), widths, norm)
    trace = _shape_trace_for_mode(
        centers.tolist(), heights.tolist(), widths.tolist(), mode, color=color,
    )
    return (
        trace, int(finite.size), finite,
        centers.tolist(), heights.tolist(), widths.tolist(),
    )


def _build_discrete_trace(values, np, *, mode=_MODE_BARS,
                          cumulative=False, norm=_NORM_COUNT,
                          color="#1976d2"):
    """Per-category trace for discrete / categorical arrays. NaN
    filtered out. Categories sorted ascending so reading is
    predictable across re-renders. Bar is the natural shape; line /
    curve are still allowed for visual consistency with continuous
    panels when the user toggles mode."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, 0, finite, None, None, None
    cats, counts = np.unique(finite, return_counts=True)
    widths = [1.0] * len(cats)  # one unit per category for density math
    heights = counts.astype(float)
    if cumulative:
        heights = np.cumsum(heights)
    heights = _apply_norm(heights, int(finite.size), widths, norm)
    trace = _shape_trace_for_mode(
        cats.tolist(), heights.tolist(), widths, mode, color=color,
    )
    return (
        trace, int(finite.size), finite,
        cats.tolist(), heights.tolist(), widths,
    )


def diverging_colors(centers, widths):
    """One colour per bar of a difference: cool below zero, warm above,
    grey for a bin that straddles it."""
    from fespp_on_trame.engine.utils.color_palette import (
        DIVERGING_NEG, DIVERGING_POS, DIVERGING_ZERO)
    out = []
    for c, w in zip(centers, widths):
        c, half = float(c), abs(float(w)) / 2.0
        if c + half <= 0.0:
            out.append(DIVERGING_NEG)
        elif c - half >= 0.0:
            out.append(DIVERGING_POS)
        else:
            out.append(DIVERGING_ZERO)
    return out


def zero_line():
    """A dashed vertical line at x = 0, the whole plot high."""
    return dict(type="line", xref="x", yref="paper", x0=0, x1=0, y0=0, y1=1,
                line=dict(color="black", width=1, dash="dash"))
