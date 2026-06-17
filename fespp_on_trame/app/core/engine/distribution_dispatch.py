"""Distribution dispatch — compute a Plotly histogram figure for one Stats row.

Mirrors stats_dispatch's source-resolution chain (Original rows ride the
unfiltered source_registry source; View rows ride the per-view
post-clip/slice/threshold output via scene_registry.get_scene(view_id)),
but bins with a single numpy.histogram (continuous) or Counter (discrete /
categorical) on the raw vtk array values.

Performance contract: the binning is pre-computed server-side and pushed
as a single Plotly trace, so the WebSocket payload stays at ~few KB
regardless of source array size.
"""
from __future__ import annotations

from collections import Counter

from paraview import simple as pvsimple

from fespp_on_trame.app.core.engine import stats_dispatch


_DEFAULT_NBINS = 50

# Display mode constants. "bars" is the legacy histogram look; "line"
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

# Defaults applied when the per-panel state var isn't initialised yet
# (first compute on panel spawn, or fallback when an option arrives as
# None from the trame state flush).
_DEFAULTS = {
    "display_mode": _MODE_BARS,
    "nbins": _DEFAULT_NBINS,
    "log_y": False,
    "show_stats": False,
    "cumulative": False,
    "norm": _NORM_COUNT,
}

# Vuetify-aligned palette cycled per trace in compute_compare_figure.
# Picked to stay distinguishable on a white background.
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


def _numpy_imports():
    """Lazy-import numpy + vtk_to_numpy so import-time failure doesn't
    break the whole engine boot when distribution support is unused."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    return np, vtk_to_numpy


def _go_imports():
    """Lazy-import plotly.graph_objects so the engine boots even if
    the plotly Python package isn't installed in the venv."""
    import plotly.graph_objects as go
    return go


def _drill_to_inner(vtk_out):
    """Unwrap a vtkPartitionedDataSetCollection layer if present.
    Mirrors stats_dispatch._drill_to_inner."""
    if vtk_out is None:
        return None
    if hasattr(vtk_out, "GetPartitionedDataSet"):
        try:
            pds = vtk_out.GetPartitionedDataSet(0)
            if pds is not None and pds.GetNumberOfPartitions() > 0:
                return pds.GetPartitionAsDataObject(0)
        except Exception:
            return vtk_out
    return vtk_out


def _get_named_array(source, vtk_name):
    """Run UpdatePipeline + locate the array by name on CellData or
    PointData of the source's VTK output. Returns the vtkDataArray or
    None if the name doesn't exist."""
    if source is None or not vtk_name:
        return None
    try:
        source.UpdatePipeline()
        client = source.GetClientSideObject()
        out = client.GetOutputDataObject(0) if client else None
        out = _drill_to_inner(out)
        if out is None:
            return None
        for getter in ("GetCellData", "GetPointData", "GetFieldData"):
            try:
                fd = getattr(out, getter)()
            except Exception:
                continue
            if fd is None:
                continue
            arr = fd.GetArray(vtk_name)
            if arr is not None:
                return arr
    except Exception:
        return None
    return None


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
        # density = counts / (total * binwidth) → integrates to 1.
        denom = total * widths
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
      a KDE without the bandwidth math (we already have the binned
      counts, no reason to redo a kernel sum)."""
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
    The extra returns feed the stats overlay (mean/median/quartiles
    lines), the NaN-badge meta, and the CSV export."""
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


def _stats_overlay_shapes(np, finite_values):
    """Build Plotly `layout.shapes` for mean / median / Q1 / Q3
    vertical lines. Returns a list of dicts (empty list if values
    can't yield useful stats). Each shape is paper-anchored on Y
    (0 → 1) so the line stretches across the whole plot regardless
    of y-axis range."""
    if finite_values is None or len(finite_values) == 0:
        return []
    try:
        mean = float(np.mean(finite_values))
        median = float(np.median(finite_values))
        q1 = float(np.quantile(finite_values, 0.25))
        q3 = float(np.quantile(finite_values, 0.75))
    except Exception:
        return []
    # Mean: solid teal; median: dashed indigo; quartiles: dotted grey.
    # Picked to read clearly against the default blue trace.
    def _line(x, dash, color, width):
        return dict(
            type="line",
            xref="x", yref="paper",
            x0=x, x1=x, y0=0, y1=1,
            line=dict(color=color, width=width, dash=dash),
        )
    return [
        _line(q1, "dot", "#9e9e9e", 1),
        _line(median, "dash", "#3949ab", 2),
        _line(mean, "solid", "#00796b", 2),
        _line(q3, "dot", "#9e9e9e", 1),
    ]


def _stats_overlay_annotations(np, finite_values, log_y):
    """Tiny labels at the top of each overlay line (Q1 / med / mean
    / Q3) so the user can read which line is which without a legend.
    `log_y` is consulted to bump the annotation off the log floor."""
    if finite_values is None or len(finite_values) == 0:
        return []
    try:
        mean = float(np.mean(finite_values))
        median = float(np.median(finite_values))
        q1 = float(np.quantile(finite_values, 0.25))
        q3 = float(np.quantile(finite_values, 0.75))
    except Exception:
        return []
    def _ann(x, text, color):
        return dict(
            x=x, y=1.0, xref="x", yref="paper",
            text=text, showarrow=False,
            font=dict(size=10, color=color),
            yanchor="bottom", xanchor="center",
        )
    return [
        _ann(q1, "Q1", "#9e9e9e"),
        _ann(median, "med", "#3949ab"),
        _ann(mean, "mean", "#00796b"),
        _ann(q3, "Q3", "#9e9e9e"),
    ]


def _resolve_view_source(scene_registry, source_registry, rep_path, view_id):
    """Mirror stats_dispatch._resolve_rendered_inputs to get the
    rendered source proxy + pv_view for a per-view row. Returns
    (merged_source, pv_view) or (None, None)."""
    rendered, pv_view = stats_dispatch._resolve_rendered_inputs(
        scene_registry, source_registry, rep_path, view_id,
    )
    if not rendered:
        return None, None
    merged, owns_merged = stats_dispatch._append_if_multiple(rendered)
    # The caller is responsible for deleting `merged` if owns_merged.
    return (merged, owns_merged), pv_view


def _resolve_options(**kwargs):
    """Merge caller-supplied option kwargs with `_DEFAULTS`. Any None
    value falls back to the default so the panel UI can leave a state
    var unset on initial spawn and still get a valid compute."""
    out = dict(_DEFAULTS)
    for k, v in kwargs.items():
        if v is None:
            continue
        out[k] = v
    if out.get("display_mode") not in _VALID_MODES:
        out["display_mode"] = _MODE_BARS
    if out.get("norm") not in _VALID_NORMS:
        out["norm"] = _NORM_COUNT
    try:
        nb = int(out.get("nbins") or _DEFAULT_NBINS)
        out["nbins"] = max(1, min(500, nb))
    except (TypeError, ValueError):
        out["nbins"] = _DEFAULT_NBINS
    out["log_y"] = bool(out.get("log_y"))
    out["show_stats"] = bool(out.get("show_stats"))
    out["cumulative"] = bool(out.get("cumulative"))
    return out


def compute_histogram_figure(state, tree, scene_registry, source_registry,
                             array_path, row_kind, row_id, *,
                             nbins=None, display_mode=None, log_y=None,
                             show_stats=None, cumulative=None, norm=None,
                             return_meta=False):
    """Return a `plotly.graph_objects.Figure` for one Stats row, or
    None if the underlying source / array can't be resolved.

    row_kind: "original" | "view"
    row_id  : "default" / "custom-N" for original rows, panel_id for view rows.

    Options (each can be left None to take the default):
      - display_mode: "bars" | "line" | "curve"
      - nbins: 1..500 (clamped); ignored for discrete properties.
      - log_y: bool — sets yaxis.type="log".
      - show_stats: bool — overlay mean / median / quartiles vertical lines.
      - cumulative: bool — heights become np.cumsum(counts).
      - norm: "count" | "density" | "probability" — heights normalisation.

    `return_meta=True` flips the return type to `(fig, meta)` where
    meta is `{"kept": int, "total": int, "nan": int, "bin_centers": [...],
    "bin_heights": [...], "bin_widths": [...]}` — the binned data is
    surfaced so CSV export doesn't need to re-run the compute."""
    opts = _resolve_options(
        display_mode=display_mode, nbins=nbins, log_y=log_y,
        show_stats=show_stats, cumulative=cumulative, norm=norm,
    )
    np, vtk_to_numpy = _numpy_imports()
    go = _go_imports()
    title, kind = stats_dispatch._title_and_kind(tree, array_path)
    prop_kind = stats_dispatch._prop_kind_for_array_path(tree, array_path, kind)
    rep_path = stats_dispatch._rep_path_for_array_path(tree, array_path)
    if not rep_path:
        return None
    # Resolve real / ts for the row. Original rows read panel_state,
    # View rows read the view's active real + pv_view.ViewTime.
    panel_state = dict(getattr(state, "ui_stats_panel_state", {}) or {})
    real_idx = None
    ts_idx = None
    pv_view = None
    # Snapshot PV globals so a transient AppendDatasets or a
    # mid-function exception cannot leak the per-row compute's
    # active source / active view back into the main render path.
    # Restored unconditionally in the finally below.
    saved_active_source = None
    saved_active_view = None
    try:
        saved_active_source = pvsimple.GetActiveSource()
    except Exception:
        saved_active_source = None
    try:
        saved_active_view = pvsimple.GetActiveView()
    except Exception:
        saved_active_view = None
    cleanup_merged = None
    _restore_channel = (lambda: None)
    _orig_real_name = None
    if row_kind == "view":
        from fespp_on_trame.app.core.engine import realization_dispatch
        real_idx = realization_dispatch.get_active_realization_for_view(
            state, row_id, array_path,
        )
        if real_idx is None:
            real_idx = stats_dispatch._default_real_idx(state, tree, array_path)
        (merged, owns_merged), pv_view = _resolve_view_source(
            scene_registry, source_registry, rep_path, row_id,
        )
        if merged is None:
            return None
        cleanup_merged = merged if owns_merged else None
        source = merged
    else:
        # Original row — find the matching panel_state entry.
        originals = ((panel_state.get(array_path) or {}).get("originals") or [])
        entry = next(
            (e for e in originals if e.get("id") == row_id),
            None,
        )
        if entry is None:
            entry = stats_dispatch._DEFAULT_ORIGINAL_ENTRY
        real_idx = entry.get("real_idx")
        ts_idx = entry.get("ts_idx")
        if real_idx is None:
            real_idx = stats_dispatch._default_real_idx(state, tree, array_path)
        # Channel-aware source + REAL array name (wellbore channels: the
        # array lives only on the per-view extractor and is raw-named).
        _otitle, _okind, _ovtk = stats_dispatch._resolve_vtk_name(
            tree, array_path, real_idx,
        )
        source, _orig_real_name, _restore_channel = stats_dispatch._original_source_and_name(
            state, source_registry, tree, array_path, rep_path, _ovtk, _otitle,
        )
        if source is None:
            return None
    vtitle, vkind, vtk_name = stats_dispatch._resolve_vtk_name(
        tree, array_path, real_idx,
    )
    if _orig_real_name:
        vtk_name = _orig_real_name   # raw title for wellbore channels
    if not vtk_name:
        if cleanup_merged is not None:
            try:
                pvsimple.Delete(cleanup_merged)
            except Exception:
                pass
        _restore_channel()
        return None
    # Set the time-step. For Original rows pick the entry's ts_idx
    # (or fall back to state.time_index). For View rows the view's
    # ViewTime is already authoritative on the source.
    saved_time = None
    is_ts_kind = kind in ("TimeSeries", "MultiRealizationTimeSeries")
    if row_kind == "original" and is_ts_kind and ts_idx is not None:
        try:
            tk = pvsimple.GetTimeKeeper()
            values = list(tk.TimestepValues or [])
            if 0 <= int(ts_idx) < len(values):
                saved_time = float(tk.Time)
                tk.Time = float(values[int(ts_idx)])
                source.UpdatePipeline(float(values[int(ts_idx)]))
        except Exception:
            saved_time = None
    finite_values = None
    bin_centers = None
    bin_heights = None
    bin_widths = None
    n_kept = 0
    n_total = 0
    try:
        arr = _get_named_array(source, vtk_name)
        if arr is None:
            return None
        values = vtk_to_numpy(arr)
        n_total = int(values.size) if hasattr(values, "size") else len(values)
        is_discrete = _is_discrete_kind(prop_kind)
        # Property name + (unit) when available, falling back to the
        # property name alone.
        unit = stats_dispatch._unit_for_array_path(tree, array_path)
        prop_label = title or array_path
        xaxis_value_label = f"{prop_label} ({unit})" if unit else prop_label
        if is_discrete:
            (
                trace, n_kept, finite_values,
                bin_centers, bin_heights, bin_widths,
            ) = _build_discrete_trace(
                values, np,
                mode=opts["display_mode"],
                cumulative=opts["cumulative"],
                norm=opts["norm"],
            )
            xaxis_title = "Category"
        else:
            (
                trace, n_kept, finite_values,
                bin_centers, bin_heights, bin_widths,
            ) = _build_continuous_trace(
                values, np, nbins=opts["nbins"],
                mode=opts["display_mode"],
                cumulative=opts["cumulative"],
                norm=opts["norm"],
            )
            xaxis_title = xaxis_value_label
        if trace is None:
            return None
    finally:
        if saved_time is not None:
            try:
                tk = pvsimple.GetTimeKeeper()
                tk.Time = saved_time
                # Re-execute the source at the restored time so a
                # subsequent color-by / scalar-bar refresh doesn't
                # pull stale data binned at the histogram timestep.
                try:
                    source.UpdatePipeline(saved_time)
                except Exception:
                    pass
            except Exception:
                pass
        if cleanup_merged is not None:
            try:
                pvsimple.Delete(cleanup_merged)
            except Exception:
                pass
        # Restore the channel extractor's ExtractPath (no-op for
        # non-channels) so the live render is left untouched.
        _restore_channel()
        # Restore PV globals so no fan-out handler sees a transient
        # source / view from the histogram compute as the "active".
        try:
            if saved_active_source is not None:
                pvsimple.SetActiveSource(saved_active_source)
        except Exception:
            pass
        try:
            if saved_active_view is not None:
                pvsimple.SetActiveView(saved_active_view)
        except Exception:
            pass
    # Chart title: "<property>" for Original rows, "<property> On View N"
    # for View rows, with an optional (real, ts) suffix that
    # disambiguates two rows on the same property differing only by
    # realization or time-step.
    is_ts_kind_local = kind in ("TimeSeries", "MultiRealizationTimeSeries")
    is_mr_kind_local = kind in ("MultiRealization", "MultiRealizationTimeSeries")
    ts_label = ""
    if is_ts_kind_local:
        if row_kind == "view" and pv_view is not None:
            try:
                from fespp_on_trame.app.core.engine import time_realization
                view_time = float(pv_view.ViewTime)
                ts_label = time_realization.label_for_time_value(
                    tree, view_time,
                ) or ""
            except Exception:
                ts_label = ""
        elif row_kind == "original" and ts_idx is not None:
            try:
                ts_label = stats_dispatch._ts_label_for_idx(
                    tree, int(ts_idx),
                ) or ""
            except Exception:
                ts_label = ""
    label_parts = []
    if is_mr_kind_local and real_idx is not None:
        label_parts.append(f"real {int(real_idx)}")
    if ts_label:
        label_parts.append(ts_label)
    suffix = f" ({', '.join(label_parts)})" if label_parts else ""
    view_title = ""
    if row_kind == "view":
        view_titles = getattr(state, "fespp_render_panels", []) or []
        view_title = next(
            (p.get("title") for p in view_titles
             if isinstance(p, dict) and p.get("id") == row_id),
            row_id,
        )
        chart_title = f"{title or array_path} On {view_title}{suffix}"
    else:
        chart_title = f"{title or array_path}{suffix}"
    # Y axis title reflects normalisation + cumulative mode so the
    # reader doesn't have to guess what the bars represent.
    yaxis_title = {
        _NORM_COUNT: "Count",
        _NORM_DENSITY: "Density",
        _NORM_PROBABILITY: "Probability",
    }.get(opts["norm"], "Count")
    if opts["cumulative"]:
        yaxis_title = f"Cumulative {yaxis_title.lower()}"
    yaxis_kwargs = dict(title=dict(text=yaxis_title))
    if opts["log_y"]:
        yaxis_kwargs["type"] = "log"
    shapes = (
        _stats_overlay_shapes(np, finite_values)
        if opts["show_stats"] else []
    )
    annotations = (
        _stats_overlay_annotations(np, finite_values, opts["log_y"])
        if opts["show_stats"] else []
    )
    fig = go.Figure(
        data=[trace],
        layout=go.Layout(
            title=dict(text=chart_title),
            xaxis=dict(title=dict(text=xaxis_title)),
            yaxis=yaxis_kwargs,
            margin=dict(l=50, r=20, t=60, b=40),
            bargap=0.05 if not _is_discrete_kind(prop_kind) else 0.15,
            autosize=True,
            showlegend=False,
            shapes=shapes,
            annotations=annotations,
        ),
    )
    if return_meta:
        meta = {
            "kept": int(n_kept or 0),
            "total": int(n_total or 0),
            "nan": int(max(0, (n_total or 0) - (n_kept or 0))),
            "bin_centers": bin_centers or [],
            "bin_heights": bin_heights or [],
            "bin_widths": bin_widths or [],
            "xaxis_title": xaxis_title,
            "yaxis_title": yaxis_title,
            "chart_title": chart_title,
            "legend_label": (", ".join(label_parts) if label_parts
                              else (view_title if row_kind == "view"
                                    else (title or array_path))),
        }
        return fig, meta
    return fig


def compute_compare_figure(state, tree, scene_registry, source_registry,
                           selection_keys, *, nbins=None,
                           display_mode=None, log_y=None,
                           show_stats=None, cumulative=None, norm=None,
                           return_meta=False):
    """Aggregate multiple row histograms into a single go.Figure
    with `barmode="overlay"` (or stacked scatters in line/curve mode)
    and per-trace opacity so the shapes stack legibly. Each
    `selection_keys` entry is the same `{array_path}|{row_kind}|{row_id}`
    string the compare cart stores in
    `state.ui_stats_compare[array_path]` (unified per-property compare
    cart shared with the compare-stats panel; the caller resolves the
    active property's cart and forwards the list). Returns None when
    fewer than 2 traces resolve.

    Same option kwargs as `compute_histogram_figure` — every trace
    inherits them so all rows render under the same view (bars vs
    curve, count vs density, etc.). Stats overlay is intentionally
    NOT drawn on the compare figure: mean / median lines per-row
    would clutter the plot fast.

    `return_meta=True` flips to `(fig, meta)` where meta carries
    `{kept, total, nan, traces: [{name, bin_centers, bin_heights,
    bin_widths}]}` — same shape as single-row meta plus a per-trace
    array for CSV export."""
    opts = _resolve_options(
        display_mode=display_mode, nbins=nbins, log_y=log_y,
        show_stats=show_stats, cumulative=cumulative, norm=norm,
    )
    # Compare panel never overlays the per-row mean / median lines;
    # they overlap each other and obscure the trace shapes. The
    # toggle on a compare panel is exposed as a no-op visually.
    opts_for_rows = dict(opts)
    opts_for_rows["show_stats"] = False
    go = _go_imports()
    traces = []
    per_trace_meta = []
    total_kept = 0
    total_total = 0
    for idx, key in enumerate(selection_keys):
        try:
            array_path, row_kind, row_id = key.split("|", 2)
        except ValueError:
            continue
        try:
            result = compute_histogram_figure(
                state, tree, scene_registry, source_registry,
                array_path, row_kind, row_id,
                display_mode=opts_for_rows["display_mode"],
                nbins=opts_for_rows["nbins"],
                log_y=opts_for_rows["log_y"],
                show_stats=False,
                cumulative=opts_for_rows["cumulative"],
                norm=opts_for_rows["norm"],
                return_meta=True,
            )
        except Exception as exc:
            continue
        if result is None:
            continue
        fig, row_meta = result
        if fig is None or not fig.data:
            continue
        label = (row_meta or {}).get("legend_label") or key
        trace = fig.data[0]
        trace.name = label
        # Per-trace opacity is shape-dependent: bar overlays need
        # heavy transparency, line/curve overlays read fine at full.
        trace.opacity = 0.55 if opts["display_mode"] == _MODE_BARS else 0.9
        try:
            colour = _COLORWAY[idx % len(_COLORWAY)]
            if opts["display_mode"] == _MODE_BARS:
                trace.marker.color = colour
                trace.marker.opacity = None
            else:
                if trace.line is not None:
                    trace.line.color = colour
                if trace.marker is not None:
                    trace.marker.color = colour
                if opts["display_mode"] == _MODE_CURVE:
                    trace.fillcolor = None
                    trace.fill = None
        except Exception:
            pass
        traces.append(trace)
        per_trace_meta.append({
            "name": label,
            "bin_centers": row_meta.get("bin_centers") or [],
            "bin_heights": row_meta.get("bin_heights") or [],
            "bin_widths": row_meta.get("bin_widths") or [],
            "kept": row_meta.get("kept") or 0,
            "total": row_meta.get("total") or 0,
        })
        total_kept += int(row_meta.get("kept") or 0)
        total_total += int(row_meta.get("total") or 0)
    if len(traces) < 2:
        return (None, None) if return_meta else None
    yaxis_title = {
        _NORM_COUNT: "Count",
        _NORM_DENSITY: "Density",
        _NORM_PROBABILITY: "Probability",
    }.get(opts["norm"], "Count")
    if opts["cumulative"]:
        yaxis_title = f"Cumulative {yaxis_title.lower()}"
    yaxis_kwargs = dict(title=dict(text=yaxis_title))
    if opts["log_y"]:
        yaxis_kwargs["type"] = "log"
    compare_x_label = "Value"
    if selection_keys:
        try:
            first_path = selection_keys[0].split("|", 1)[0]
            first_title, _first_kind = stats_dispatch._title_and_kind(tree, first_path)
            _unit = stats_dispatch._unit_for_array_path(tree, first_path)
            _prop_label = first_title or first_path
            compare_x_label = (f"{_prop_label} ({_unit})" if _unit
                                else _prop_label)
        except Exception:
            pass
    fig = go.Figure(
        data=traces,
        layout=go.Layout(
            title=dict(text=f"Compare distributions ({len(traces)} rows)"),
            xaxis=dict(title=dict(text=compare_x_label)),
            yaxis=yaxis_kwargs,
            margin=dict(l=50, r=20, t=50, b=40),
            barmode="overlay",
            bargap=0.05,
            autosize=True,
            showlegend=True,
            legend=dict(orientation="h", y=-0.15),
        ),
    )
    if return_meta:
        meta = {
            "kept": total_kept,
            "total": total_total,
            "nan": max(0, total_total - total_kept),
            "traces": per_trace_meta,
            "xaxis_title": compare_x_label,
            "yaxis_title": yaxis_title,
            "chart_title": f"Compare distributions ({len(traces)} rows)",
        }
        return fig, meta
    return fig


def build_csv_from_meta(meta):
    """Render a CSV string from the meta dict returned by
    `compute_histogram_figure(..., return_meta=True)` or
    `compute_compare_figure(..., return_meta=True)`.

    Single-row meta → 3 columns: center, height, width.
    Compare meta (has `traces`) → one column triplet per trace,
    rows aligned by index (shorter traces pad with empty cells).

    The intent is "drop into Excel and chart it elsewhere", not a
    canonical bin-edge dump — we keep centers + widths so the
    consumer can reconstruct edges if needed."""
    traces = meta.get("traces")
    if traces:
        # Compare mode: side-by-side per-trace blocks.
        max_len = max(
            (len(t.get("bin_centers") or []) for t in traces),
            default=0,
        )
        header = []
        for t in traces:
            base = t.get("name") or "trace"
            header.extend([f"{base}_center", f"{base}_{meta.get('yaxis_title', 'height').lower()}", f"{base}_width"])
        lines = [",".join(_csv_escape(c) for c in header)]
        for i in range(max_len):
            row = []
            for t in traces:
                centers = t.get("bin_centers") or []
                heights = t.get("bin_heights") or []
                widths = t.get("bin_widths") or []
                row.extend([
                    _csv_num(centers[i]) if i < len(centers) else "",
                    _csv_num(heights[i]) if i < len(heights) else "",
                    _csv_num(widths[i]) if i < len(widths) else "",
                ])
            lines.append(",".join(row))
        return "\n".join(lines) + "\n"
    centers = meta.get("bin_centers") or []
    heights = meta.get("bin_heights") or []
    widths = meta.get("bin_widths") or []
    height_label = (meta.get("yaxis_title") or "Count").lower()
    header = f"center,{height_label},width"
    lines = [header]
    for i in range(len(centers)):
        lines.append(",".join([
            _csv_num(centers[i]),
            _csv_num(heights[i]) if i < len(heights) else "",
            _csv_num(widths[i]) if i < len(widths) else "",
        ]))
    return "\n".join(lines) + "\n"


def _csv_escape(s):
    """Minimal CSV cell escape for headers — quote if it contains a
    comma, quote, or newline."""
    s = str(s)
    if any(c in s for c in ',"\n'):
        return '"' + s.replace('"', '""') + '"'
    return s


def _csv_num(v):
    """Render a numeric cell with `repr`-like precision but as a plain
    string — Python's default float formatting is good enough for
    distribution data (kept ~17 sig figs)."""
    if v is None:
        return ""
    try:
        return f"{float(v):.6g}"
    except (TypeError, ValueError):
        return _csv_escape(v)
