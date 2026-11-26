"""The statistics of a property, as the Statistics view reads them.

`engine/compare_dispatch` and `engine/compare_rows` build the rows of the
matrix; what they read comes from here:

  * the descriptive statistics of an array, in numpy (`_row_stats_from_values`,
    `add_weighted_means`) or through a transient filter chain on a proxy
    (`_compute_one_variable`, `transient_chain`);
  * a 3D view's row, on what the view draws (`_build_view_row`);
  * what a row says about its weighted means (`_weights_note`), and whether a
    Sum of the property means anything (`sum_meaningful`);
  * the tree's answers several panels share: a property's representation,
    title, kind, unit and VTK name, its default realization, the label of a
    time step.

NaN handling: each row chains `Threshold(Between(-inf,+inf))` to drop
NaN cells before `DescriptiveStatistics`, so kurtosis / skewness /
moments stay meaningful instead of degenerating to NaN.
"""
from contextlib import contextmanager

from paraview import simple as pvsimple

from fespp_on_trame.engine import realization_dispatch
from fespp_on_trame.engine.blockscope import assembly_index
from fespp_on_trame.engine import element_type
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import view_axes
from fespp_on_trame.engine.utils.naming import make_valid_vtk_name


# ---------------------------------------------------------------------------
# VTK / PV plumbing — transient compute primitives.
# Build a noNaN Threshold + DescriptiveStatistics chain on demand,
# read the output, then delete the proxies. Independent of FESPP's
# state shape: pass a PV proxy and an array name, get a row dict.
# ---------------------------------------------------------------------------


def _statistics_tables(stats_out):
    """(primary, derived) model tables of a vtkDescriptiveStatistics output,
    or (None, None).

    Up to VTK 9.5 (ParaView 6.0) the output is a vtkMultiBlockDataSet whose
    blocks 0 and 1 are the two tables; from VTK 9.6 (ParaView 6.1) it is a
    vtkPartitionedDataSetCollection holding the same two tables, in the same
    order ("Primary Statistics", "Derived Statistics"), one per partitioned
    dataset. Both forms are read here: `GetBlock` does not exist on the
    newer one."""
    if stats_out is None:
        return None, None
    if stats_out.IsA("vtkPartitionedDataSetCollection"):
        tables = []
        for i in range(stats_out.GetNumberOfPartitionedDataSets()):
            pds = stats_out.GetPartitionedDataSet(i)
            tables.append(pds.GetPartitionAsDataObject(0)
                          if pds is not None and pds.GetNumberOfPartitions() > 0
                          else None)
    else:
        tables = [stats_out.GetBlock(i) for i in range(stats_out.GetNumberOfBlocks())]
    return (tables[0] if tables else None,
            tables[1] if len(tables) > 1 else None)


def _resolve_rendered_inputs(rep_path, view_id):
    """`(what a 3D view draws of the grid, pv_view)` when it cuts or filters it
    (engine/drawn_cells): what its isolate shows (its cuts, its kept volumes,
    the tips of its threshold chain, its cell mask), else what its composite
    keeps of a cut scene. A view that shows the whole grid draws nothing of the
    kind: its row would be the item's row again, so it has none."""
    from trame.app import get_server
    from fespp_on_trame.engine import drawn_cells, view_resources
    pv_view = view_resources.pv_view_of(view_id)
    if pv_view is None:
        return [], pv_view
    ctx = get_server().context
    iso = (getattr(ctx, "grid_isolates", None) or {}).get((view_id, rep_path))
    scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
    # an isolate that hides the NaN cells alone draws every value of the grid
    # (a statistic counts no NaN): its row would be the item's again
    only_nan = (iso is not None and callable(getattr(iso, "get_chain", None)) and callable(getattr(iso, "snapshot", None))
                and not iso.get_chain() and (iso.snapshot() or {}).get("mode") == "full"
                and not getattr(iso, "hidden_codes", None) and not drawn_cells.scene_boxes(scene))
    drawn = drawn_cells.of_isolate(iso, pv_view) if iso is not None and not only_nan else []
    if not drawn and scene is not None:
        drawn = drawn_cells.of_scene(scene, rep_path, getattr(ctx, "assembly_index", None))
    return drawn, pv_view


def _resolve_assoc(source, array_name):
    """Return "CELLS" or "POINTS" depending on where the array lives
    on the source's output, or None if not found."""
    try:
        client_obj = source.GetClientSideObject()
        out = client_obj.GetOutputDataObject(0)
        inner = assembly_index.inner(out)
        if inner is None:
            return None
        cd = inner.GetCellData() if hasattr(inner, "GetCellData") else None
        pd = inner.GetPointData() if hasattr(inner, "GetPointData") else None
        if cd is not None and cd.GetArray(array_name) is not None:
            return "CELLS"
        if pd is not None and pd.GetArray(array_name) is not None:
            return "POINTS"
    except Exception:
        return None
    return None


def _table_row_to_dict(table, row_idx):
    """Convert one row of a vtkTable to a plain JSON-safe dict.
    Numeric columns become floats; string columns become strings."""
    out = {}
    if table is None or row_idx >= table.GetNumberOfRows():
        return out
    for col_idx in range(table.GetNumberOfColumns()):
        col = table.GetColumn(col_idx)
        if col is None:
            continue
        name = col.GetName()
        if not name:
            continue
        try:
            if col.IsA("vtkDataArray"):
                val = float(col.GetTuple1(row_idx))
            else:
                val = col.GetValue(row_idx)
                val = str(val) if val is not None else ""
        except Exception:
            val = None
        out[name] = val
    return out


def _total_count_for_assoc(source, assoc):
    """Total cell / point count on `source` for the given
    `assoc` ("CELLS" / "POINTS"). Used to derive the NaN count
    (= total − Cardinality), since the descriptive-stats compute
    only sees the post-Threshold output."""
    try:
        info = source.GetDataInformation()
        if assoc == "POINTS":
            return int(info.GetNumberOfPoints())
        return int(info.GetNumberOfCells())
    except Exception:
        return None


def _compute_one_variable(input_source, array_name, component=None):
    """One stats row for `array_name` on `input_source`, or None on failure.

    Builds Threshold(no-NaN) → DescriptiveStatistics, reads the output,
    deletes the filters and returns one row dict (Primary + Derived stats
    merged).

    The row also carries a `NaN_count` key: the input has the NaN cells,
    the threshold drops them and the descriptive stats only count the
    survivors, so it is computed as `total − Cardinality` and a consumer
    can show both side by side.

    A VECTOR property (several values per element) takes the numpy row on
    one value per element — `component`, or the magnitude — like every
    other panel: the filter chain would read component 0 and the quartiles
    would mix every component."""
    assoc = _resolve_assoc(input_source, array_name)
    if assoc is None:
        return None
    try:
        from fespp_on_trame.engine import property_values as _pv
        arr, ghost = _pv._named_and_ghost(input_source, array_name)
        if arr is not None and arr.GetNumberOfComponents() > 1:
            from vtkmodules.util.numpy_support import vtk_to_numpy
            import numpy as _np
            vals = _pv.reduce_components(vtk_to_numpy(arr), component)
            if ghost is not None:
                gm = _np.array(vtk_to_numpy(ghost), copy=True).ravel()
                if len(gm) == len(vals):
                    vals[gm != 0] = _np.nan
            return _row_stats_from_values(vals, array_name)
    except Exception:
        pass

    safe_name = make_valid_vtk_name(array_name)
    threshold_proxy = None
    stats_proxy = None
    total = _total_count_for_assoc(input_source, assoc)
    try:
        # Threshold(Between, -inf, +inf) drops NaN cells. The filter
        # treats NaN as out-of-range because any comparison with NaN
        # returns False.
        threshold_proxy = pvsimple.Threshold(
            registrationName=f"_stats_noNaN_{safe_name}",
            Input=input_source,
        )
        threshold_proxy.Scalars = [assoc, array_name]
        threshold_proxy.LowerThreshold = -1.0e308
        threshold_proxy.UpperThreshold = 1.0e308
        threshold_proxy.UpdatePipeline()

        stats_proxy = pvsimple.DescriptiveStatistics(
            registrationName=f"_stats_desc_{safe_name}",
            Input=threshold_proxy,
        )
        try:
            stats_proxy.VariablesofInterest = [array_name]
        except Exception:
            # Older ParaView builds wrap the property as a tuple list.
            stats_proxy.VariablesofInterest = [(array_name,)]
        stats_proxy.UpdatePipeline()

        client_out = stats_proxy.GetClientSideObject().GetOutputDataObject(0)
        if client_out is None:
            return None
        primary, derived = _statistics_tables(client_out)
        if primary is None or primary.GetNumberOfRows() == 0:
            return None

        row = _table_row_to_dict(primary, 0)
        if derived is not None and derived.GetNumberOfRows() > 0:
            row.update(_table_row_to_dict(derived, 0))
        # P10 / Q1 / Median / Q3 / P90 on the NaN-stripped data. The
        # vtkDescriptiveStatistics primary block exposes Cardinality / Mean /
        # Std Dev / Sum / M2-M4 but no percentiles, so they are computed here
        # on the same Threshold output the descriptive stats consumed.
        try:
            from vtkmodules.util.numpy_support import vtk_to_numpy
            import numpy as _np
            client = threshold_proxy.GetClientSideObject()
            thresh_out = client.GetOutputDataObject(0) if client else None
            inner = assembly_index.inner(thresh_out)
            arr_vtk = None
            if inner is not None:
                fd = inner.GetCellData() if assoc == "CELLS" else inner.GetPointData()
                if fd is not None:
                    arr_vtk = fd.GetArray(array_name)
            if arr_vtk is not None and arr_vtk.GetNumberOfTuples() > 0:
                arr_np = vtk_to_numpy(arr_vtk)
                p10, q1, med, q3, p90 = (
                    float(v) for v in _np.percentile(arr_np, [10, 25, 50, 75, 90]))
                row["P10"] = p10
                row["Q1"] = q1
                row["Median"] = med
                row["Q3"] = q3
                row["P90"] = p90
        except Exception:
            pass
        # The variable name under the lowercase key the UI binds to, the
        # state convention; vtkDescriptiveStatistics emits "Variable".
        row["variable"] = array_name
        # NaN count = (cells / points in the input) − (Cardinality
        # after dropping NaN). Both come from the same `assoc`.
        cardinality = row.get("Cardinality")
        if total is not None and isinstance(cardinality, (int, float)):
            row["NaN_count"] = max(0, total - int(cardinality))
        else:
            row["NaN_count"] = None
        return row
    except Exception:
        return None
    finally:
        for proxy in (stats_proxy, threshold_proxy):
            if proxy is not None:
                try:
                    pvsimple.Delete(proxy)
                except Exception:
                    pass


@contextmanager
def transient_chain():
    """Build and delete transient filters with nothing else seeing them.

    Each transient filter chain (`Threshold` + `DescriptiveStatistics`) calls
    `SetActiveSource(self)` on the new proxy; deleting
    them at the end would leave the active source pointing at a destroyed
    proxy, so `pvsimple.GetActiveSource()` would return None elsewhere. The
    active source and the active view are snapshotted on entry and restored
    on exit, and VTK's warnings are silenced in between."""
    prev_active_view = None
    try:
        prev_active_view = pvsimple.GetActiveView()
    except Exception:
        prev_active_view = None
    try:
        pvsimple.SetActiveView(None)
    except Exception:
        pass
    # Silence VTK warnings during the no-active-view window. Other
    # @state.change handlers (active.reservoir, time-slider rerouting,
    # etc.) can fire between the SetActiveView(None) above and the
    # restore in the finally below, and several of them probe the
    # active view via pvsimple, which would print "No active view found"
    # once per fan-out event. The window is short and the only warnings
    # lost are the ones this window causes.
    _prev_warn_display = None
    try:
        from vtkmodules.vtkCommonCore import vtkObject as _vtkObject
        _prev_warn_display = _vtkObject.GetGlobalWarningDisplay()
        _vtkObject.GlobalWarningDisplayOff()
    except Exception:
        _prev_warn_display = None
    prev_active_source = pvsimple.GetActiveSource()
    try:
        yield
    finally:
        if prev_active_source is not None:
            try:
                pvsimple.SetActiveSource(prev_active_source)
            except Exception:
                pass
        # Restore the active view cleared on entry. It is cleared to
        # neutralize the pipeline-listener side-effects of
        # SetActiveSource on the transient Threshold proxy (the
        # listener treats an active-source change as a user
        # navigation and may re-run apply_color_array against the
        # active view, wiring a scalar bar). Restoring it here
        # returns the render path to its pre-compute state.
        try:
            pvsimple.SetActiveView(prev_active_view)
        except Exception:
            pass
        # Restore VTK global warning display so unrelated
        # downstream code keeps emitting its warnings.
        try:
            if _prev_warn_display is not None:
                from vtkmodules.vtkCommonCore import vtkObject as _vtkObject
                _vtkObject.SetGlobalWarningDisplay(_prev_warn_display)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tree / state resolution — translate UI identifiers (array_path,
# realisation pick) into VTK names + default indices for the row
# builders below.
# ---------------------------------------------------------------------------


def _rep_path_for_array_path(tree, array_path):
    """Path of the representation that encloses `array_path`, else "" — a
    `derived://` path's grid included (engine/node_facts, the one answer;
    the name stays for its many callers)."""
    return node_facts.rep_path_for(tree, array_path)


def _rep_title_for_array_path(tree, array_path):
    """Human-readable label of the rep node that encloses `array_path` — a
    `derived://` path's grid included — or the rep path's last segment
    when the tree has no title, so two reps carrying a property of the same
    name are still told apart; "" when the rep cannot be
    located (engine/node_facts, the one answer)."""
    return node_facts.rep_title(tree, array_path)


# Human labels of a property's VALUE TYPE, what a row's hover says.
# The PWLS property kind (volume, depth, …) is a different thing: it
# names the tab the row sits in.
_PROP_TYPE_LABELS = {
    "ContinuousProperty": "Continuous property",
    "DiscreteProperty": "Discrete property",
    "CategoricalProperty": "Categorical property",
}


def _title_and_kind(tree, array_path):
    """Return `(title, kind)` for a property: its name in the file (the
    `propTitle` of the reader's series nodes) and its node type,
    "DerivedProperty" for a recipe (engine/node_facts, the one answer)."""
    return (node_facts.property_title(tree, array_path),
            node_facts.kind_of(tree, array_path))


def _prop_kind_for_array_path(tree, array_path, kind):
    """Underlying property kind (`ContinuousProperty` /
    `DiscreteProperty` / `CategoricalProperty`) of a property.

    Mirrors `tree_icons.get_primary_icon`: for synthetic kinds (TS /
    MR / MR+TS) the answer is the *property* type, not the synthetic
    wrapper. Reads the property TYPE on the node when present, else falls
    back to the kind itself."""
    from fespp_on_trame.engine import derived_props
    if derived_props.is_derived(array_path):
        store = derived_props.get_store()
        d = store.get(array_path) if store else None
        return (d or {}).get("prop_kind") or "ContinuousProperty"
    if tree is None or not array_path:
        return kind
    if kind not in node_facts.SERIES_KINDS:
        return kind
    try:
        nid = tree.find_node_id(array_path)
        if nid is None:
            return kind
        pk = tree.find_prop_type(nid)
        if pk:
            return pk
    except Exception:
        pass
    return kind


def sum_meaningful(prop_kind, uom, kind_title="", title=""):
    """Whether a Sum of the property's values means anything.

    It does not on a fraction or a ratio (a porosity, a saturation, a net-to-gross:
    adding the fractions of different cells gives nothing), read off the
    unit (a %, a v/v), the PWLS quantity class of the property kind or of
    the title, or the health domain of the kind; nor on a categorical
    property, whose values are codes. The block hides the column then,
    instead of printing a number a reader would have to know to ignore.
    Unknown reads as meaningful: the column stays."""
    from fespp_on_trame.engine import (
        health_dispatch, node_kinds, reconcile_dispatch,
    )
    if (prop_kind or "") == "CategoricalProperty":
        return False
    u = (uom or "").strip().lower()
    if u in node_kinds.PERCENT_UNITS or (u and u in node_kinds.FRACTION_UNITS):
        return False
    cls = reconcile_dispatch.quantity_class_of(kind_title, title)
    if reconcile_dispatch._norm_class(cls) == "fraction":
        return False
    return not any(health_dispatch.expected_domain(t) == "fraction"
                   for t in (kind_title, title) if t)


def _unit_for_array_path(tree, array_path):
    """The unit of measure of `array_path`, else "".

    The `uom` attribute FESPP writes on a property node (the RESQML unit as
    declared), or the unit a derived property was given. The reader's
    time-series / multi-realization grouping nodes carry none
    (engine/node_facts, the one answer)."""
    return node_facts.unit_of(tree, array_path)


def _resolve_vtk_name(tree, array_path, real_idx=None):
    """Resolve `(title, kind, vtk_name)` for the property at `array_path`.

    For MR-kind properties `vtk_name` is the suffixed
    `<sanitised_title>_real_<real_idx>`; non-MR returns the sanitised
    title verbatim. Returns `("", "", "")` on lookup failure."""
    from fespp_on_trame.engine import derived_props
    if derived_props.is_derived(array_path):
        store = derived_props.get_store()
        d = store.get(array_path) if store else None
        if d is None:
            return "", "", ""
        # an item's row of a derived property reads through the value seam
        # and ignores this name; a view's row finds the derived array on the
        # rendered output by it
        return store.title(array_path), "DerivedProperty", d["vtk_name"]
    title, kind = _title_and_kind(tree, array_path)
    if not title:
        return "", "", ""
    sanitized = make_valid_vtk_name(title)
    if element_type.for_kind(kind).is_multi_realization() and real_idx is not None:
        return title, kind, realization_dispatch.suffixed_array_name(
            sanitized, int(real_idx),
        )
    return title, kind, sanitized


def _default_real_idx(state, tree, array_path):
    """First available realization index for an MR property, or None
    when the property isn't MR / has no realizations registered."""
    try:
        return realization_dispatch.default_realization_for(
            state, tree, array_path,
        )
    except Exception:
        return None


def _ts_label_for_idx(tree, ts_idx):
    """Human-friendly label of `TimestepValues[ts_idx]`, else "".

    Uses the same `time_realization.label_for_time_value` resolver as the
    global time control and the dropdowns. Returns "" when ts_idx is None
    or out of range, so callers can fold it straight into a label suffix
    without extra conditionals."""
    if ts_idx is None:
        return ""
    try:
        from fespp_on_trame.engine import time_realization
        tk = pvsimple.GetTimeKeeper()
        values = list(tk.TimestepValues or [])
        if 0 <= int(ts_idx) < len(values):
            return time_realization.label_for_time_value(
                tree, float(values[int(ts_idx)]),
            ) or ""
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Row builders — the values of a row, and its statistics: in numpy on what the
# value seam reads, on what a 3D view draws as `_compute_one_variable` of one
# display, as engine/drawn_cells of several.
# ---------------------------------------------------------------------------


def _original_source_and_name(state, source_registry, tree,
                              array_path, rep_path, vtk_name, title):
    """`(source, name)` of a row on the whole grid: the rep's source and the
    sanitized name. A log channel's values are read off its frame by ring
    sampling (`property_values.values_for`), not off this source."""
    src = source_registry.get(rep_path) if source_registry is not None else None
    return src, vtk_name


def _is_channel_array(tree, array_path):
    """A log channel: its rep is a wellbore frame and the node is not that
    frame. Its VTK array is the TUBE's — every frame node repeated nSides
    times, a gap written as -0.0 — so only the value seam's ring sampling
    reads it as measured."""
    try:
        node_id = tree.find_node_id(array_path)
        r_id = tree.find_representation_node(node_id) if node_id is not None else None
        return (r_id is not None and r_id != node_id
                and element_type.for_kind(tree.find_type(r_id) or "").is_channel_frame())
    except Exception:
        return False


def weighted_mean(values, weights):
    """``(mean, n, why)`` — Σ w·v ÷ Σ w over the elements where the value is
    finite AND the weight is finite AND w > 0.

    `why` is ``""`` when a mean came out, ``"none"`` when no element
    qualified — every cell blanked or degenerate — and ``"length"`` when the
    two arrays do not index the same elements at all: a property carried on
    the NODES of a grid arrives with (ni+1)(nj+1)(nk+1) values against
    ni·nj·nk volumes, and telling the reader that every cell is blanked
    would be false as well as unactionable. Computed on the RAW
    index space, before the finite-value compaction, so a value and its
    weight stay paired."""
    import numpy as np
    v = np.asarray(values, dtype=float).ravel()
    w = np.asarray(weights, dtype=float).ravel()
    if len(w) != len(v):
        return None, 0, "length"
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0.0)
    n = int(ok.sum())
    if n == 0:
        return None, 0, "none"
    return float(np.sum(w[ok] * v[ok]) / np.sum(w[ok])), n, ""


def add_weighted_means(row, values, volume=None, pore_volume=None):
    """Write the two weighted means into `row`.

    A weight that qualifies on no element leaves its key ABSENT: the matrix
    dashes it and the note says why.

    Each mean carries its own count — `weighted_n` and `pore_n` — because
    they are not the same: the pore weight is NaN wherever the porosity or
    the net-to-gross is blanked, so `Mean (PV)` can rest on far fewer cells
    than `Mean (V)`, and the note must not cover one with the other's
    figure. `weights_index_na` records the two array lengths when the values
    do not index the cells."""
    import numpy as np
    if volume is not None:
        mean, wn, why = weighted_mean(values, volume)
        row["weighted_n"] = wn
        if why == "length":
            row["weights_index_na"] = [int(np.asarray(values).size),
                                       int(np.asarray(volume).size)]
        if mean is not None:
            row["Mean (V)"] = mean
    if pore_volume is not None:
        mean, pn, _why = weighted_mean(values, pore_volume)
        row["pore_n"] = pn
        if mean is not None:
            row["Mean (PV)"] = mean
    return row


def _row_stats_from_values(values, name, volume=None, pore_volume=None):
    """The native row, from numpy.

    EXACTLY the keys of the matrix's metrics, with vtkDescriptiveStatistics'
    own conventions (the two agree to 1e-9): ddof=1 spread, SAMPLE
    skewness G1 = g1·√(n(n−1))/(n−2) and SAMPLE kurtosis
    G2 = ((n+1)·g2+6)·(n−1)/((n−2)(n−3)), NaN_count = total − finite.

    `volume` and `pore_volume` are the optional per-cell weights of
    `cell_weights`: they add `Mean (V)` / `Mean (PV)` BESIDE the
    arithmetic `Mean`, which never moves."""
    import numpy as np
    values = np.asarray(values, dtype=float).ravel()
    fin = values[np.isfinite(values)]
    n = int(len(fin))
    row = {
        "Cardinality": float(n),
        "NaN_count": float(len(values) - n),
        "variable": name,
        "Variable": name,
    }
    if n == 0:
        if volume is not None:
            row["weighted_n"] = 0
        return row
    mean = float(np.mean(fin))
    row.update({
        "Minimum": float(np.min(fin)),
        "Maximum": float(np.max(fin)),
        "Mean": mean,
        "Sum": float(np.sum(fin)),
    })
    add_weighted_means(row, values, volume, pore_volume)
    # P10 / P90 are percentiles of the CELL values (a tenth of the cells
    # below P10), the convention of the calculator's chips — not the
    # reserves convention, which reads across realizations
    p10, q1, med, q3, p90 = (
        float(v) for v in np.percentile(fin, [10, 25, 50, 75, 90]))
    row.update({"P10": p10, "Q1": q1, "Median": med, "Q3": q3, "P90": p90})
    if n >= 2:
        std1 = float(np.std(fin, ddof=1))
        row.update({"Standard Deviation": std1, "Variance": std1 ** 2})
    if n >= 4:
        m2 = float(np.mean((fin - mean) ** 2))
        m3 = float(np.mean((fin - mean) ** 3))
        m4 = float(np.mean((fin - mean) ** 4))
        # M2..M4 as vtkDescriptiveStatistics writes them on a view row:
        # the SUMS of the powered deviations (M2 = (n-1)·variance), not
        # their means, so the M columns agree whichever path made the row
        row.update({"M2": m2 * n, "M3": m3 * n, "M4": m4 * n})
        if m2 > 0:
            g1 = m3 / m2 ** 1.5
            g2 = m4 / m2 ** 2 - 3.0
            row["Skewness"] = g1 * (n * (n - 1)) ** 0.5 / (n - 2)
            row["Kurtosis"] = (((n + 1) * g2 + 6) * (n - 1)
                               / ((n - 2) * (n - 3)))
    return row


def _build_view_row(state, source_registry, tree,
                    array_path, rep_path, view_id, view_title):
    """Compute one "3D view N" row for the property.

    Anchors on what the view draws (`_resolve_rendered_inputs`), so slicer /
    threshold / mask effects are reflected in the stats, each cell once
    however many of its displays hold it. The realization is the view's
    (`view_axes.real_for`).

    Returns None when the view doesn't currently colour the rep by
    `array_path` — a property's rows only list views that are actually
    displaying it (a render panel renders ONE property per rep at a time;
    showing stats for views that ignore the property would be noise)."""
    # the view colours the grid by the property whose eye is open there (one
    # colouring eye per grid, app/scene/eyes)
    if array_path not in (getattr(state, f"visible_paths__{view_id}", None) or []):
        return None
    real_idx = view_axes.real_for(state, tree, view_id, array_path)
    title, kind, vtk_name = _resolve_vtk_name(tree, array_path, real_idx)
    if not vtk_name:
        return None
    rendered, pv_view = _resolve_rendered_inputs(rep_path, view_id)
    if not rendered:
        return None
    from fespp_on_trame.engine import drawn_cells, property_values
    component = property_values.component_choice(state, array_path)
    if _is_channel_array(tree, array_path):
        # a channel is the same log in every view: the measured samples
        vals = property_values.values_for(
            state, tree, source_registry, array_path, rep_path,
            real_idx=real_idx)
        row = _row_stats_from_values(vals, vtk_name) if vals is not None else None
    elif drawn_cells.is_plain(rendered):
        row = _compute_one_variable(rendered[0].proxy, vtk_name, component=component)
    else:
        vals = drawn_cells.values(rendered, vtk_name, component)
        row = _row_stats_from_values(vals, vtk_name) if vals is not None else None
    if row is None:
        return None
    # View rows are rendered at the view's OWN time — each render
    # panel has a per-view TimeControl that writes `view.ViewTime`
    # without touching the global TimeKeeper, so two panels can
    # diverge. The actual `pv_view.ViewTime` is read and resolved
    # through the tree-attached label helper (the same one the global
    # time control and the TS dropdown items use), falling back to
    # `state.time_index` when the view's time cannot be read.
    is_ts_kind = element_type.for_kind(kind).is_time_series()
    view_ts_idx = None
    view_ts_label = ""
    if is_ts_kind:
        view_time = None
        try:
            if pv_view is not None:
                view_time = float(pv_view.ViewTime)
        except Exception:
            view_time = None
        if view_time is None:
            try:
                ti = getattr(state, "time_index", None)
                if ti is not None:
                    tk = pvsimple.GetTimeKeeper()
                    values = list(tk.TimestepValues or [])
                    if 0 <= int(ti) < len(values):
                        view_time = float(values[int(ti)])
                        view_ts_idx = int(ti)
            except Exception:
                pass
        if view_time is not None:
            try:
                tk = pvsimple.GetTimeKeeper()
                values = list(tk.TimestepValues or [])
                # Match the view's time to a known TimestepValues
                # entry (a per-view time control snaps to TimestepValues,
                # so this is normally an exact float match).
                for i, v in enumerate(values):
                    if abs(float(v) - view_time) < 1e-9:
                        view_ts_idx = i
                        break
                try:
                    from fespp_on_trame.engine import time_realization
                    view_ts_label = time_realization.label_for_time_value(
                        tree, view_time,
                    ) or ""
                except Exception:
                    view_ts_label = ""
            except Exception:
                pass
    prop_label = property_values.display_label(state, tree, array_path,
                                               fallback=title or array_path)
    row.update({
        "kind": "view",
        "id": view_id,
        "view_title": view_title,
        "label": f"{prop_label} On {view_title}",
        "real_idx": int(real_idx) if real_idx is not None else None,
        "ts_idx": view_ts_idx,
        "ts_label": view_ts_label,
    })
    return row


def _weights_note(tree, array_path, weights, rows):
    """The note a row carries about its weighted means: on its hover and in
    the CSV.

    It says why a weight could not be had, which rows carry none, and on
    how many cells the weighting was actually taken when that is not every
    valued cell."""
    from fespp_on_trame.engine.utils import numfmt
    notes = []
    if _is_channel_array(tree, array_path):
        notes.append("A log channel has no cell volume: the weighted means"
                     " are reported on grid properties only.")
    elif weights.get("note"):
        notes.append(weights["note"])
    if any(r.get("kind") == "view" for r in rows):
        notes.append("A view row shows the filtered display, whose cells are"
                     " not the grid's: the weighted means are reported on the"
                     " rows of the whole grid only.")
    # a property that does not index the cells at all is NOT a grid of
    # blanked cells: it is a property read off the nodes, and saying so is
    # the only sentence the reader can act on
    unindexed = next((r for r in rows if r.get("weights_index_na")), None)
    if unindexed is not None:
        m, n = unindexed["weights_index_na"]
        title = _title_and_kind(tree, array_path)[0] or array_path
        grid = _rep_title_for_array_path(tree, array_path) or "this grid"
        notes.append(f"'{title}' does not index the cells of {grid}"
                     f" ({numfmt.fmt_int(m)} values for {numfmt.fmt_int(n)}"
                     " cells): no weighted mean.")
    else:
        for r in rows:
            wn, card = r.get("weighted_n"), r.get("Cardinality")
            if wn is None or card is None or int(wn) == int(card):
                continue
            notes.append(
                f"The volume-weighted means are computed on {numfmt.fmt_int(wn)}"
                f" of the {numfmt.fmt_int(card)} valued cells:"
                f" {numfmt.fmt_int(int(card) - int(wn))} have no volume (blanked"
                " or degenerate).")
            break
    # and the pore-volume mean rests on its own count: a blanked porosity or
    # net-to-gross blanks the weight without blanking the cell
    for r in rows:
        wn, pn = r.get("weighted_n"), r.get("pore_n")
        if wn is None or pn is None or int(pn) == int(wn) or int(pn) == 0:
            continue
        terms = " or ".join(t for t in (weights.get("poro_title"),
                                        weights.get("ntg_title")) if t)
        notes.append(
            f"The pore-volume-weighted mean is computed on"
            f" {numfmt.fmt_int(pn)} of those {numfmt.fmt_int(wn)} cells:"
            f" {numfmt.fmt_int(int(wn) - int(pn))} have no pore volume"
            f" (a blanked or non-positive {terms or 'weight term'}).")
        break
    # the pore volume is BUILT from the porosity and the net-to-gross, so on
    # those two properties the weight is the property itself
    if array_path and array_path == weights.get("poro_path"):
        notes.append("The pore volume is built from this very property, so"
                     " Mean (PV) here is the porosity weighted by itself —"
                     " always above the plain mean. The net-rock-weighted"
                     " average porosity is PV ÷ NRV on the Volumetrics card.")
    elif array_path and array_path == weights.get("ntg_path"):
        notes.append("The pore volume is built from this very property, so"
                     " Mean (PV) here is the net-to-gross weighted by"
                     " itself — always above the plain mean.")
    # one realization's porosity weighs every row, whatever each row reads
    wreal = weights.get("real_idx")
    others = sorted({int(r["real_idx"]) for r in rows
                     if r.get("real_idx") is not None and wreal is not None
                     and int(r["real_idx"]) != int(wreal)})
    if others:
        notes.append(
            f"The pore-volume weight is read once, at realization {wreal}:"
            f" a row at realization {', '.join(str(o) for o in others)} is"
            f" weighted by realization {wreal}'s porosity, not its own.")
    return " ".join(notes)
