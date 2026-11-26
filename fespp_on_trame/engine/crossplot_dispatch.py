"""Cross-plot dispatch: property A against one or more properties B,
coloured by C.

The porosity–permeability cloud, Vsh–porosity, impedance–porosity… is the
working plot of petrophysics: it shows the RELATIONSHIP between two
quantities, where a histogram only shows each one alone. This module owns the
pure computation for the ``crossplot`` view kind; ``boot`` spawns the panel
and wires the option watchers, exactly like the distribution panels.

One panel = one X, several Y: each Y is its own chart (the widget lays them
out two per row), and a chart can be PINNED, i.e. frozen as a snapshot that
survives every later change of the axes, so "porosity vs NTG of real 3"
stays on screen while real 4 is examined next to it. A chart can also be
FOCUSED: the panel then shows that one chart, full size.

Alignment is the whole correctness question of a cross-plot, and it is why
the choices are restricted to ONE rep:

  - on a grid / mesh rep, every property is an array over the same cells, so
    value i of A and value i of B are the SAME cell: pairing by index is
    exact, as ``diff.py`` also relies on;
  - on a wellbore Frame, each channel is its OWN tube block, but all channels
    of a frame sample the same frame nodes in the same order, so pairing the
    per-ring samples by index is exact too (the well-log panel relies on the
    same property).

Pairing across two DIFFERENT reps would silently compare unrelated cells and
is refused rather than approximated.

State outputs (per panel, suffixed by the dockview panel id):
  - ``ui_crossplot_figures_<pid>``: one Plotly figure per drawn chart, keyed.
  - ``ui_crossplot_meta_<pid>``: {kept, total, nan, note, rep_path, axes,
    focus}.
  - ``ui_crossplot_charts_<pid>``: [{key, title, pinned, kept, note}].
"""
from math import ceil

from paraview import simple as pvsimple

from fespp_on_trame.engine import stats_dispatch
from fespp_on_trame.engine.utils.color_palette import color_for_index

# A grid property can carry hundreds of thousands of cells and the figure
# crosses the websocket; above this many points the cloud is subsampled
# uniformly and the meta says so: a silent cap would read as "all the data".
MAX_POINTS = 20000

# Beyond this many distinct values the colour property is treated as
# continuous even if its kind says discrete: 200 legend entries help nobody.
MAX_CATEGORIES = 24

_MARKER_BASE = {"size": 4, "opacity": 0.65}


def _rgb(i):
    # The palette's #RRGGBBAA without the alpha, which plotly's validator
    # refuses.
    return color_for_index(i)[:7]


def _numpy():
    import numpy as np
    return np


def axis_key(state, array_path):
    """The identity of an axis for plotly's `uirevision`: the property and
    the component read of it (property_values.axis_key)."""
    from fespp_on_trame.engine import property_values
    return property_values.axis_key(state, array_path)


def _axis_title(state, tree, array_path, real_idx=None, ts_idx=None):
    name, step = _axis_parts(state, tree, array_path, real_idx, ts_idx)
    return f"{name}{step}"


def _axis_parts(state, tree, array_path, real_idx=None, ts_idx=None):
    """(the property's name, what the realization / date adds to it).

    The player groups the charts of ONE property in a track and steps
    through what the second part names, so the two halves are built
    apart."""
    from fespp_on_trame.engine import property_values
    # The property's single display name (title, component, unit); the
    # colour bar and the Colormap card spell it the same way.
    name = property_values.display_label(state, tree, array_path,
                                         fallback=array_path)
    # The realization / time must be IN the axis name: the same property on
    # both axes is exactly the two-realizations / two-dates use, and without
    # the suffix the two axes would read as identical.
    step = ""
    if real_idx is not None:
        step += f" — real {int(real_idx)}"
    if ts_idx is not None:
        lbl = stats_dispatch._ts_label_for_idx(tree, ts_idx)
        step += f" — {lbl or f't{ts_idx}'}"
    return name, step


def same_rep_choices(tree, loaded_array_paths, anchor_path=None):
    """[{title, value}] of the loaded properties usable with `anchor_path`
    on one axis of the same plot: those living on the SAME rep (all loaded
    ones when there is no anchor yet). This is the diff dialog's B-filter
    rule, for the same reason: only same-rep arrays are index-aligned."""
    anchor_rep = (stats_dispatch._rep_path_for_array_path(tree, anchor_path)
                  if anchor_path else None)
    out = []
    for p in loaded_array_paths or []:
        title, kind = stats_dispatch._title_and_kind(tree, p)
        if not title:
            continue
        if anchor_rep is not None:
            if stats_dispatch._rep_path_for_array_path(tree, p) != anchor_rep:
                continue
        out.append({"title": title, "value": p})
    return out


def axis_options(state, tree, array_path):
    """What ONE axis can additionally pick for this property: its available
    realization indices (MR) and its timestep labels (TS). Empty lists for a
    plain property, for which the panel shows no extra select at all."""
    from fespp_on_trame.engine import element_type, realization_dispatch
    from fespp_on_trame.engine import derived_props
    out = {"reals": [], "ts": []}
    if not array_path:
        return out
    if derived_props.is_derived(array_path):
        store = derived_props.get_store()
        caps = (store.axis_caps(tree, array_path) if store is not None
                else {"is_mr": False, "is_ts": False, "reals": []})
        is_mr, is_ts = caps["is_mr"], caps["is_ts"]
        reals = caps["reals"]
    else:
        kind = stats_dispatch._title_and_kind(tree, array_path)[1]
        et = element_type.for_kind(kind)
        is_mr, is_ts = et.is_multi_realization(), et.is_time_series()
        reals = (realization_dispatch
                 .available_realization_indices(tree, array_path)
                 if is_mr else [])
    if is_mr:
        out["reals"] = [{"title": f"real {i}", "value": int(i)}
                        for i in reals]
    if is_ts:
        try:
            tk = pvsimple.GetTimeKeeper()
            values = list(tk.TimestepValues or [])
        except Exception:
            values = []
        out["ts"] = [
            {"title": stats_dispatch._ts_label_for_idx(tree, i) or f"t{i}",
             "value": int(i)}
            for i in range(len(values))]
    return out


def _values_for(state, tree, source_registry, array_path, rep_path,
                real_idx=None, ts_idx=None):
    """Delegate to `property_values.values_for`, the single consumer seam.

    It applies the ghost-cell mask (blanked grid cells carry a 0.0 FILL
    that a raw numpy read would return as bogus zeros) and evaluates
    `derived://` recipes."""
    from fespp_on_trame.engine.property_values import values_for
    return values_for(state, tree, source_registry, array_path, rep_path,
                      real_idx=real_idx, ts_idx=ts_idx)


# ---------------------------------------------------------------------------
# Y rows, chart keys and the axis-keyed selection geometry
# ---------------------------------------------------------------------------

def y_entry(y):
    """One Y row as {path, real, ts}, whatever the widget sent."""
    y = y if isinstance(y, dict) else {}
    real, ts = y.get("real"), y.get("ts")
    return {"path": y.get("path") or None,
            "real": int(real) if real is not None else None,
            "ts": int(ts) if ts is not None else None}


def _axis_pair(geom):
    """(x values, y values) of an axis-keyed geometry dict. Plotly names
    the keys after the subplot's axes (x / y on the first subplot, x2 / y2
    on the second…), so the pair is found by prefix, not by name."""
    if not isinstance(geom, dict):
        return None, None
    xk = next((k for k in geom if k.startswith("x")), None)
    yk = next((k for k in geom if k.startswith("y")), None)
    if xk is None or yk is None:
        return None, None
    return geom.get(xk), geom.get(yk)


def _axis_ids(sel):
    geom = (sel or {}).get("range") or (sel or {}).get("lasso") or {}
    if not isinstance(geom, dict):
        return None, None
    xk = next((k for k in geom if k.startswith("x")), None)
    yk = next((k for k in geom if k.startswith("y")), None)
    return xk, yk


def chart_key_for_selection(meta_axes, sel):
    """The chart key ("live:i" / "pin:n") a box / lasso was drawn on.

    That is the key the widget names (`sel["chart"]`; every chart is a
    figure of its own, so its axes are always x / y), else, for a caller
    that sends only the geometry, the first chart whose axis ids match the
    geometry's. None when nothing matches."""
    chart = (sel or {}).get("chart") if isinstance(sel, dict) else None
    if chart and chart in (meta_axes or {}):
        return chart
    xk, yk = _axis_ids(sel)
    if xk is None or yk is None:
        return None
    for key, axes in (meta_axes or {}).items():
        if list(axes or ()) == [xk, yk]:
            return key
    return None


def selection_cell_ids(state, tree, source_registry, x_path, y_path, *,
                       x_real=None, x_ts=None, y_real=None, y_ts=None,
                       log_x=False, log_y=False, sel=None):
    """FULL-RESOLUTION cell ids inside a box / lasso drawn on the cloud.

    The client sends only the selection's GEOMETRY (~100 bytes), never its
    points: plotly point objects weigh megabytes for a large box and cover
    only the SUBSAMPLED points, so the 3D highlight would miss most of the
    cells of the region. Recomputing the mask here over the full arrays
    costs one array read and answers the actual question: "the cells in
    this region".

    `sel` = {"range": {x: [a,b], y: [c,d]}} or {"lasso": {x: [...], y: [...]}};
    the keys are the subplot's axis ids (x2 / y2 on the second chart…).
    On a LOG axis plotly reports the geometry in log10 axis units, so the
    values are exponentiated back before masking. Returns (ids, note)."""
    np = _numpy()
    rep_x = stats_dispatch._rep_path_for_array_path(tree, x_path)
    if not rep_x or not sel:
        return [], ""
    xs = _values_for(state, tree, source_registry, x_path, rep_x,
                     real_idx=x_real, ts_idx=x_ts)
    ys = _values_for(state, tree, source_registry, y_path, rep_x,
                     real_idx=y_real, ts_idx=y_ts)
    if xs is None or ys is None or xs.size != ys.size:
        return [], ""

    rx, ry = _axis_pair(sel.get("range"))
    lx, ly = _axis_pair(sel.get("lasso"))
    mask = np.isfinite(xs) & np.isfinite(ys)
    if rx and ry:
        rx, ry = list(rx), list(ry)
        if log_x:
            rx = [10.0 ** v for v in rx]
        if log_y:
            ry = [10.0 ** v for v in ry]
        x0, x1 = min(rx), max(rx)
        y0, y1 = min(ry), max(ry)
        mask &= (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
    elif lx and ly:
        px = np.asarray(lx, dtype=float)
        py = np.asarray(ly, dtype=float)
        if log_x:
            px = 10.0 ** px
        if log_y:
            py = 10.0 ** py
        # Ray-casting point-in-polygon, vectorised over every sample.
        inside = np.zeros(xs.shape, dtype=bool)
        j = len(px) - 1
        for i in range(len(px)):
            cond = ((py[i] > ys) != (py[j] > ys))
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (px[j] - px[i]) * (ys - py[i]) / (py[j] - py[i]) + px[i]
            inside ^= cond & (xs < xint)
            j = i
        mask &= inside
    else:
        return [], ""
    ids = np.nonzero(mask)[0]
    from fespp_on_trame.engine.utils import numfmt
    note = f"{numfmt.fmt_int(ids.size)} {sample_unit(tree, rep_x)} selected"
    # Above MAX_POINTS the cloud draws one point in N while the region is
    # read over every value: the badge says the count is not the drawn dots.
    stride = int(ceil(xs.size / MAX_POINTS)) if xs.size > MAX_POINTS else 1
    if stride > 1:
        note += (f" at full resolution (the chart draws 1 point in {stride};"
                 " the region is read over every value)")
    return ids.tolist(), note


# ---------------------------------------------------------------------------
# The figure: X read once, one chart per Y, pinned snapshots re-added
# ---------------------------------------------------------------------------

def _x_context(state, tree, source_registry, x_path, color_path, *,
               x_real, x_ts, log_x, max_points=None):
    """Everything the charts share: the X samples, the colour samples and
    their categories, and ONE uniform subsample stride computed from the
    rep's cell count, so every chart shows the same candidate cells and a
    NaN of one Y never shifts the sampling of another. A non-empty `error`
    means no live chart can be drawn, and says why."""
    np = _numpy()
    ctx = {"rep": "", "unit": "values", "error": "", "note": "", "total": 0,
           "nan": 0, "nonpos": 0, "stride": 1, "xs": None, "x_ok": None,
           "x_ok_full": None, "ids": None, "cs": None, "cats": None,
           "cat_labels": {}, "cat_colors": {}, "c_title": "", "x_title": ""}
    if not x_path:
        ctx["error"] = "Pick a property for X."
        return ctx
    rep_x = stats_dispatch._rep_path_for_array_path(tree, x_path)
    if not rep_x:
        ctx["error"] = "X property is not loaded."
        return ctx
    ctx["rep"] = rep_x
    ctx["unit"] = sample_unit(tree, rep_x)
    ctx["x_title"] = _axis_title(state, tree, x_path, x_real, x_ts)
    xs = _values_for(state, tree, source_registry, x_path, rep_x,
                     real_idx=x_real, ts_idx=x_ts)
    if xs is None:
        ctx["error"] = "Could not read the X values (is it checked?)."
        return ctx
    total = int(xs.size)
    ctx["total"] = total
    # Counted apart, over the whole array: a sample without a value and a
    # value a log axis cannot place are two different reasons not to draw.
    x_ok = np.isfinite(xs)
    ctx["nan"] = total - int(x_ok.sum())
    if log_x:
        nonpos = x_ok & (xs <= 0)
        ctx["nonpos"] = int(nonpos.sum())
        x_ok &= ~nonpos
    cap = int(max_points or MAX_POINTS)
    stride = int(ceil(total / cap)) if total > cap else 1
    ctx["stride"] = stride
    # The ORIGINAL index of every candidate sample: it is what a lasso on
    # the cloud sends back, and what the 3D highlight is keyed by. It rides
    # through every mask below or the selection would light the wrong cells.
    ids = np.arange(total)[::stride]
    ctx["ids"] = ids
    ctx["xs"] = xs[::stride]
    ctx["x_ok"] = x_ok[::stride]
    ctx["x_ok_full"] = x_ok
    if stride > 1:
        _note(ctx, f"uniform subsample: 1 point in {stride}")
    if color_path:
        if stats_dispatch._rep_path_for_array_path(tree, color_path) != rep_x:
            _note(ctx, "color ignored: the color property must live "
                       "on the same grid / frame")
        else:
            cs = _values_for(state, tree, source_registry, color_path, rep_x)
            if cs is not None and cs.size == total:
                cs = cs[::stride]
                c_kind = stats_dispatch._title_and_kind(tree, color_path)[1]
                cats = np.unique(cs[np.isfinite(cs)])
                discrete = ("Discrete" in c_kind or "Categorical" in c_kind
                            or cats.size <= MAX_CATEGORIES) and cats.size > 0
                ctx["cs"] = cs
                # Categories fixed HERE, over the whole candidate set, so the
                # legend colours are the same in every chart.
                ctx["cats"] = (cats.tolist()
                               if discrete and cats.size <= MAX_CATEGORIES
                               else None)
                ctx["c_title"] = _axis_title(state, tree, color_path)
                # The legend names the categories when the file does.
                if ctx["cats"] is not None:
                    from fespp_on_trame.engine.utils import categories
                    # the realization the colour values were read at (the
                    # default one): a multi-realization name carries it
                    c_real = stats_dispatch._default_real_idx(state, tree, color_path)
                    c_vtk = stats_dispatch._resolve_vtk_name(tree, color_path, c_real)[2]
                    ctx["cat_labels"] = categories.labels_for(
                        tree, color_path, c_vtk, _shared_source(source_registry))
                    # The traces use the colours the 3D views paint the
                    # codes with, so a facies is the same colour everywhere.
                    from fespp_on_trame.engine import categorical_palette as _catp
                    ctx["cat_colors"] = _catp.colors_by_code(
                        ctx["cats"], c_vtk, _catp.view_scenes())
                    missing = categories.labels_note(tree, color_path, ctx["cat_labels"])
                    if missing:
                        _note(ctx, f"color: {missing}")
    return ctx


def _shared_source(source_registry):
    try:
        return source_registry.shared_source()
    except Exception:
        return None


def sample_unit(tree, rep_path):
    """What one value of a property on `rep_path` stands for, for the
    badge: a "cell" of a grid, a "sample" (one frame node) of a well-log
    frame, else a "value". A log has N samples, not N cells, and the tube
    points it is drawn with are not what is counted."""
    nid = tree.find_node_id(rep_path) if rep_path else None
    kind = (tree.find_type(nid) or "") if nid is not None else ""
    if kind in ("IjkGrid", "UnstructuredGrid", "Sub", "BlockedWellbore"):
        return "cells"
    if kind == "Frame":
        return "samples"
    return "values"


def _note(ctx, text):
    """Notes accumulate: the subsample and a colour warning are both true
    at once, and the badge shows every one."""
    ctx["note"] = f"{ctx['note']} · {text}" if ctx["note"] else text


def _compact(a):
    """The numbers of a trace at seven significant digits, relative to the
    largest of them. A chart is read at a few hundred pixels, and the full
    seventeen digits of a float would double the bytes of every figure for
    nothing; a box or lasso is recomputed server-side at full precision."""
    np = _numpy()
    a = np.asarray(a, dtype=float)
    if not a.size:
        return []
    top = np.nanmax(np.abs(a)) if np.isfinite(a).any() else 0.0
    if not np.isfinite(top) or top == 0:
        return a.tolist()
    return np.round(a, 6 - int(np.floor(np.log10(top)))).tolist()


def _traces(ctx, keep, ys):
    """The plotly trace DICTS of one chart over the candidate samples that
    `keep` retains. Plain dicts, so a pinned snapshot is JSON and can be
    re-added verbatim on every rebuild."""
    from fespp_on_trame.engine.utils import categories
    np = _numpy()
    xs, ids, cs = ctx["xs"][keep], ctx["ids"][keep], ctx["cs"]
    ys = ys[keep]
    traces = []
    if cs is not None:
        cs = cs[keep]
        if ctx["cats"] is not None:
            # One trace per category gives a real legend, zone by zone; the
            # legendgroup ties the category across every chart of the grid.
            for i, cat in enumerate(ctx["cats"]):
                m = cs == cat
                if not m.any():
                    continue
                traces.append({
                    "type": "scattergl", "mode": "markers",
                    "x": _compact(xs[m]), "y": _compact(ys[m]),
                    "customdata": ids[m].tolist(),
                    "name": categories.label_of(ctx.get("cat_labels"), cat),
                    "legendgroup": f"{cat:g}",
                    "marker": dict(_MARKER_BASE,
                                   color=(ctx.get("cat_colors") or {}).get(
                                       float(cat), _rgb(i))),
                })
            # A sample whose colour is a gap is still a sample: one grey
            # trace, otherwise it would vanish while `kept` still counts it.
            m = ~np.isfinite(cs)
            if m.any():
                traces.append({
                    "type": "scattergl", "mode": "markers",
                    "x": _compact(xs[m]), "y": _compact(ys[m]),
                    "customdata": ids[m].tolist(),
                    "name": "unclassified", "legendgroup": "unclassified",
                    "marker": dict(_MARKER_BASE, color="#9e9e9e"),
                })
            return traces
        traces.append({
            "type": "scattergl", "mode": "markers",
            "x": _compact(xs), "y": _compact(ys), "customdata": ids.tolist(),
            "name": "",
            "marker": dict(_MARKER_BASE, color=_compact(cs),
                           colorscale="Viridis",
                           colorbar={"title": ctx["c_title"], "thickness": 14}),
        })
        return traces
    traces.append({
        "type": "scattergl", "mode": "markers",
        "x": _compact(xs), "y": _compact(ys), "customdata": ids.tolist(),
        "name": "", "marker": dict(_MARKER_BASE, color=_rgb(0)),
    })
    return traces


def _live_chart(state, tree, source_registry, ctx, x_path, y, i, *,
                x_real, x_ts, log_y):
    """The chart of ys[i]: its traces when it can be drawn, else the note
    saying why it cannot. An undrawable chart is still listed in `charts`,
    so the widget can show the reason on the row instead of a blank."""
    np = _numpy()
    y = y_entry(y)
    y_path = y["path"]
    chart = {"key": f"live:{i}", "pinned": False, "kept": 0, "note": "",
             "nan_y": 0, "nonpos_y": 0,
             "traces": [], "x_title": ctx["x_title"], "y_title": "",
             "y_path": y_path or "", "title": f"Y{i + 1} — no property"}
    if not y_path:
        return chart
    chart["y_title"] = _axis_title(state, tree, y_path, y["real"], y["ts"])
    chart["title"] = f"{chart['y_title']} vs {ctx['x_title']}"
    if ctx["error"]:
        chart["note"] = ctx["error"]
        return chart
    if stats_dispatch._rep_path_for_array_path(tree, y_path) != ctx["rep"]:
        # Refused, not approximated: across reps value i of A and value i
        # of B are unrelated cells, and the cloud would be fiction.
        chart["note"] = "X and Y must live on the same grid / frame."
        return chart
    if y_path == x_path and (x_real, x_ts) == (y["real"], y["ts"]):
        chart["note"] = ("Same property, same realization, same time — that "
                         "is the diagonal. Pick a different real / time.")
        return chart
    ys = _values_for(state, tree, source_registry, y_path, ctx["rep"],
                     real_idx=y["real"], ts_idx=y["ts"])
    if ys is None:
        chart["note"] = "Could not read the Y values (is it checked?)."
        return chart
    if ys.size != ctx["total"]:
        chart["note"] = (f"X has {ctx['total']} values, Y has {ys.size} — "
                         f"not aligned.")
        return chart
    # The pairs X has that Y cannot complete, counted over the whole array
    # like X's own gaps, so the badge's numbers add up.
    y_ok = np.isfinite(ys)
    chart["nan_y"] = int((ctx["x_ok_full"] & ~y_ok).sum())
    if log_y:
        y_nonpos = y_ok & (ys <= 0)
        chart["nonpos_y"] = int((ctx["x_ok_full"] & y_nonpos).sum())
        y_ok &= ~y_nonpos
    ys = ys[::ctx["stride"]]
    keep = ctx["x_ok"] & y_ok[::ctx["stride"]]
    kept = int(keep.sum())
    if kept == 0:
        chart["note"] = "No finite (X, Y) pair to plot."
        return chart
    chart["kept"] = kept
    chart["traces"] = _traces(ctx, keep, ys)
    return chart


def snapshot_chart(state, tree, source_registry, x_path, y, color_path, *,
                   x_real=None, x_ts=None, log_x=False, log_y=False):
    """A pinned chart: the traces of Y against X as drawn at pin time,
    frozen with their titles. Boot keeps it server-side and re-adds it
    verbatim on every rebuild, so it survives any later change of the axes
    and even the unload of its properties. None when the chart cannot be
    drawn."""
    ctx = _x_context(state, tree, source_registry, x_path, color_path,
                     x_real=x_real, x_ts=x_ts, log_x=log_x)
    chart = _live_chart(state, tree, source_registry, ctx, x_path, y, 0,
                        x_real=x_real, x_ts=x_ts, log_y=log_y)
    if not chart["traces"]:
        return None
    y = y_entry(y)
    # The label tags the WHOLE chart with a realization / time, so it is
    # only honest when the two axes agree (or one of them has none): real 3
    # vs real 4 is already said by the axis titles, and "(real 3)" would
    # then read as the chart's realization.
    parts = []
    real = _shared_tag(x_real, y["real"])
    if real is not None:
        parts.append(f"real {real}")
    ts = _shared_tag(x_ts, y["ts"])
    if ts is not None:
        parts.append(stats_dispatch._ts_label_for_idx(tree, ts) or f"t{ts}")
    return {"traces": chart["traces"], "x_title": chart["x_title"],
            "y_title": chart["y_title"], "label": ", ".join(parts),
            "kept": chart["kept"], "log_x": bool(log_x), "log_y": bool(log_y)}


def _shared_tag(a, b):
    """The realization / time step the two axes share: the one that is
    set when only one is, None when both are set and differ."""
    if a is None or b is None:
        return a if a is not None else b
    return a if a == b else None


def _pinned_chart(snap, n):
    label = f" ({snap['label']})" if snap.get("label") else ""
    # A snapshot is frozen: its own track, with nothing to step through.
    return {"key": f"pin:{n}", "pinned": True, "kept": int(snap.get("kept", 0)),
            "group": f"pin:{n}",
            "group_title": f"📌 {snap.get('y_title', '')} vs {snap.get('x_title', '')}",
            "step_title": snap.get("label", ""),
            "note": "", "traces": list(snap.get("traces") or []),
            "x_title": snap.get("x_title", ""),
            "y_title": snap.get("y_title", ""),
            "title": f"📌 {snap.get('y_title', '')} vs {snap.get('x_title', '')}"
                     f"{label}",
            "log_x": bool(snap.get("log_x")), "log_y": bool(snap.get("log_y"))}


# Beyond this many charts a figure is drawn as SVG (`scatter`), not WebGL
# (`scattergl`): a browser holds about sixteen WebGL contexts, and every
# chart past that budget comes up BLANK (no axes, no grid, nothing). SVG has
# no such limit but costs one DOM node per point, hence the smaller cloud
# (forty-nine charts of it are still about 150,000 nodes on one page).
GL_CHARTS = 8
MAX_POINTS_SVG = 3000

# The most charts a panel draws: "every time step" of a long series asks
# for hundreds, and a hundred SVG charts are already 300,000 points on one
# page. The rest is not drawn, and the note says so.
MAX_CHARTS = 100


def crossplot_plan(state, tree, source_registry, x_path, ys, color_path=None,
                   *, x_real=None, x_ts=None, log_x=False, log_y=False,
                   pins=(), focus=None, film=False):
    """What every chart of the panel shares, read ONCE.

    That is the X samples and the colour (`ctx`), the pinned snapshots
    (drawn as they were kept) and one HEAD per Y row (key, title, the Y
    named) without reading a Y value yet. The widget draws the heads at
    once, each with a loading mark, while `crossplot_chart` reads them one
    by one. Past GL_CHARTS charts ON SCREEN AT ONCE the cloud is the
    smaller SVG one, for every chart: on screen means every chart in the
    grid, but one per TRACK when the widget plays them (`film`). A browser
    holds about sixteen WebGL contexts, and the ones past that come up
    blank."""
    ys = [y_entry(y) for y in (ys or [])]
    pins = list(pins or ())
    room = max(0, MAX_CHARTS - len(pins))
    asked = len(ys)
    ys = ys[:room]
    # What the browser holds at once: every chart in the grid, one chart per
    # TRACK in the player (a track is a Y property, whatever the dates it is
    # read at). Past the budget everything becomes SVG, the player included.
    on_screen = (len(pins) + len({y["path"] for y in ys if y["path"]})
                 + sum(1 for y in ys if not y["path"])) if film else (
        len(pins) + len(ys))
    many = on_screen > GL_CHARTS
    ctx = _x_context(state, tree, source_registry, x_path, color_path,
                     x_real=x_real, x_ts=x_ts, log_x=log_x,
                     max_points=MAX_POINTS_SVG if many else None)
    if asked > len(ys):
        _note(ctx, f"{asked + len(pins)} charts asked: the first {MAX_CHARTS}"
                   " are drawn")
    heads = [_pinned_chart(snap, n) for n, snap in enumerate(pins)]
    for i, y in enumerate(ys):
        heads.append(_live_head(state, tree, ctx, y, i))
    return {"ctx": ctx, "heads": heads, "ys": ys, "x_path": x_path,
            "x_real": x_real, "x_ts": x_ts, "log_x": bool(log_x),
            "log_y": bool(log_y), "focus": focus, "gl": not many,
            "film": bool(film),
            # Plotly keeps the user's zoom / pan across a data update as
            # long as the axis's uirevision is unchanged. It is keyed by the
            # PROPERTY on the axis, the component read of it and its scale,
            # so a new time step or realization redraws inside the same
            # framing, while another property, another component or a log
            # toggle re-frames (a zoom made on X kept for an axis labelled Z
            # would be a lie). A pinned chart never redraws its data; its
            # titles are its identity.
            "x_key": axis_key(state, x_path) if x_path else "",
            "y_keys": {f"live:{i}": (axis_key(state, y["path"]) if y["path"] else "")
                       for i, y in enumerate(ys)},
            # The legend once per category and the colour bar once over the
            # whole grid: what the charts drawn so far have already shown.
            "legend_seen": set(), "scale_shown": False}


def _live_head(state, tree, ctx, y, i):
    """The chart of ys[i] before its values are read: its key, its title
    (the property it names), no figures yet; `loading` says so."""
    y_path = y["path"]
    head = {"key": f"live:{i}", "pinned": False, "kept": 0, "note": "",
            "nan_y": 0, "nonpos_y": 0, "loading": bool(y_path),
            "traces": [], "x_title": ctx["x_title"], "y_title": "",
            "y_path": y_path or "", "title": f"Y{i + 1} — no property",
            # The TRACK this chart belongs to: the Y property, whatever the
            # realization or the date it is read at. The player steps
            # through the charts of one track, one play button per track.
            "group": y_path or f"live:{i}",
            "group_title": f"Y{i + 1} — no property", "step_title": ""}
    if y_path:
        name, step = _axis_parts(state, tree, y_path, y["real"], y["ts"])
        head["y_title"] = f"{name}{step}"
        head["title"] = f"{head['y_title']} vs {ctx['x_title']}"
        head["group_title"] = f"{name} vs {ctx['x_title']}"
        head["step_title"] = step.replace(" — ", "", 1).replace(" — ", " · ")
    else:
        head["loading"] = False
    return head


def crossplot_chart(plan, i, state, tree, source_registry):
    """The chart at position i of the plan, its values read now: the
    pinned snapshots are already whole, a live one is computed."""
    head = plan["heads"][i]
    if head["pinned"]:
        return dict(head, loading=False)
    n = i - sum(1 for h in plan["heads"] if h["pinned"])
    chart = _live_chart(state, tree, source_registry, plan["ctx"],
                        plan["x_path"], plan["ys"][n], n,
                        x_real=plan["x_real"], x_ts=plan["x_ts"],
                        log_y=plan["log_y"])
    chart["loading"] = False
    # The track the head named: the values are read here, the track was
    # decided by the head. Without this the published chart falls back to
    # its own key and every chart becomes a track of one.
    for k in ("group", "group_title", "step_title"):
        chart[k] = head.get(k) or chart.get(k) or ""
    return chart


def chart_public(c):
    """What the widget captions: the chart without its traces. `group` is
    the track it belongs to (its Y property: the player gives one play
    button per track), `group_title` names the track and `step_title` what
    this chart is within it (its realization, its date)."""
    return {"key": c["key"], "title": c["title"], "pinned": c["pinned"],
            "kept": c["kept"], "nan_y": c.get("nan_y", 0),
            "nonpos_y": c.get("nonpos_y", 0), "note": c["note"],
            "loading": bool(c.get("loading")),
            "group": c.get("group") or c["key"],
            "group_title": c.get("group_title") or c["title"],
            "step_title": c.get("step_title") or ""}


def crossplot_figure(plan, chart):
    """ONE plotly figure for a chart that has traces; None when it has
    none, or when the plan focuses on another chart.

    The widget lays the figures out itself (rows of two, square), each under
    its own caption, so a figure carries no title and its axes are always
    x / y. The legend and the colour bar are shown once over the whole grid:
    the plan remembers what the figures built before have already shown.
    The film is the exception, where a chart is alone on screen and carries
    its own."""
    import plotly.graph_objects as go
    if not chart["traces"]:
        return None
    if plan["focus"] and chart["key"] != plan["focus"]:
        return None
    ctx, log_x, log_y = plan["ctx"], plan["log_x"], plan["log_y"]
    x_rev = f"{ctx['rep']}|{plan['x_key']}|{'log' if log_x else 'lin'}"
    fig = go.Figure()
    any_legend = False
    once = not plan.get("film")
    seen = plan["legend_seen"] if once else set()
    for t in chart["traces"]:
        group = t.get("legendgroup") or t.get("name") or ""
        show = bool(group) and group not in seen
        if show:
            seen.add(group)
            any_legend = True
        t = dict(t, showlegend=show)
        if "colorscale" in (t.get("marker") or {}):
            t["marker"] = dict(t["marker"],
                               showscale=not (once and plan["scale_shown"]))
            plan["scale_shown"] = True
        if plan["gl"]:
            fig.add_trace(go.Scattergl(dict(t, type="scattergl")))
        else:
            fig.add_trace(go.Scatter(dict(t, type="scatter")))
    c = chart
    lx = c.get("log_x", log_x) if c["pinned"] else log_x
    ly = c.get("log_y", log_y) if c["pinned"] else log_y
    if c["pinned"]:
        cx_rev = f"{c['key']}|{c['x_title']}|{lx}"
        cy_rev = f"{c['key']}|{c['y_title']}|{ly}"
    else:
        cx_rev = x_rev
        cy_rev = f"{plan['y_keys'][c['key']]}|{'log' if ly else 'lin'}"
    fig.update_xaxes(title_text=c["x_title"], uirevision=cx_rev,
                     type="log" if lx else "linear")
    fig.update_yaxes(title_text=c["y_title"], uirevision=cy_rev,
                     type="log" if ly else "linear")
    # No title (the widget's caption is the title) and tight margins: the
    # chart is a small square in a grid.
    fig.update_layout(
        margin={"l": 54, "r": 12, "t": 8, "b": 44},
        legend={"orientation": "v", "x": 1.02, "y": 1},
        showlegend=any_legend,
        uirevision=x_rev,
    )
    return fig


def crossplot_meta(plan, charts, drawn):
    """{kept, total, nan, note, rep_path, axes, drawn, focus, charts} over
    the charts computed so far: the honest badge and the caption list.
    `focus` is the key actually drawn alone (None when the requested one is
    not drawable, in which case the grid is shown instead)."""
    ctx = plan["ctx"]
    focus = plan["focus"]
    focused = [c for c in charts if c["traces"] and c["key"] == focus] if focus else []
    note = ctx["note"] or ctx["error"]
    if not any(c["traces"] for c in charts):
        # Nothing on screen: the note must say why, not how it is sampled.
        live = [c["note"] for c in charts if not c["pinned"] and c["note"]]
        note = ctx["error"] or (live[0] if live else "")
    # kept = the candidate cells on screen at least once, not the sum over
    # the charts: three charts of a 5,000-cell grid are not 15,000 points.
    # The Y-side gaps are those of the chart that gives `kept` (one live
    # chart is the common case); every chart carries its own.
    on_screen = focused or [c for c in charts if c["traces"]]
    best = max(on_screen, key=lambda c: c["kept"], default=None)
    return {"kept": best["kept"] if best else 0,
            "total": ctx["total"], "unit": ctx["unit"],
            "nan": ctx["nan"], "nonpos": ctx["nonpos"],
            "nan_y": best.get("nan_y", 0) if best else 0,
            "nonpos_y": best.get("nonpos_y", 0) if best else 0,
            "note": note, "rep_path": ctx["rep"],
            "axes": {k: ["x", "y"] for k in drawn}, "drawn": list(drawn),
            "focus": focus if focused else None,
            "charts": [chart_public(c) for c in charts]}


def compute_crossplot_figures(state, tree, source_registry, x_path, ys,
                              color_path=None, *, x_real=None, x_ts=None,
                              log_x=False, log_y=False, pins=(), focus=None,
                              film=False):
    """Every chart of the panel at once (the plan, each chart read, one
    figure per drawn chart) for a caller that does not need them one by
    one (the tests, a probe). Returns (figures, meta) with the figures in
    the order of `meta["drawn"]`. The application reads the charts
    progressively instead (boot._refresh_crossplot)."""
    plan = crossplot_plan(state, tree, source_registry, x_path, ys,
                          color_path, x_real=x_real, x_ts=x_ts, log_x=log_x,
                          log_y=log_y, pins=pins, focus=focus, film=film)
    charts, figs, drawn = [], [], []
    for i in range(len(plan["heads"])):
        c = crossplot_chart(plan, i, state, tree, source_registry)
        charts.append(c)
    # A focus names a DRAWN chart, or it is not a focus and the grid is drawn.
    if focus and not any(c["traces"] and c["key"] == focus for c in charts):
        plan["focus"] = None
    for c in charts:
        fig = crossplot_figure(plan, c)
        if fig is not None:
            figs.append(fig)
            drawn.append(c["key"])
    return figs, crossplot_meta(plan, charts, drawn)