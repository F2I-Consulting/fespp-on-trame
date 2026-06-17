"""Descriptive statistics dispatch — multi-property table (Brique B).

The singleton stats dockview tab (created lazily on first pin by
`multi_view._add_stats_panel`) renders one card per property pinned
in `state.ui_stats_pinned_paths` (toggled via the tree's "Display
stats" icon). Each card's table contains:

  - 1+ **Original** rows — stats on the rep's unfiltered VTK array,
    independent of any view's slicer / clip / threshold. The first
    row is `default` (uses the property's first available real / ts);
    additional rows are user-pinned customisations (each with its
    own real / ts). The user pins via a per-row pin icon and deletes
    via a trash icon — both managed through `state.ui_stats_panel_state`.

  - 1 row per render view — stats on the view's rendered output (post-
    threshold), reading the view's currently-picked realization. The
    user can compare the same property across views and against the
    reference (Original) row.

State outputs:
  - `state.ui_stats_tables[array_path]` — `{title, rows[]}` consumed
    by `DescriptiveStatsPanel`.

NaN handling: each row chains `Threshold(Between(-inf,+inf))` to drop
NaN cells before `DescriptiveStatistics`, so kurtosis / skewness /
moments stay meaningful instead of degenerating to NaN.
"""
from paraview import simple as pvsimple

from fespp_on_trame.app.core.engine import source_resolver, realization_dispatch
from fespp_on_trame.app.utils.naming import make_valid_vtk_name


# ---------------------------------------------------------------------------
# VTK / PV plumbing — transient compute primitives.
# Build a noNaN Threshold + DescriptiveStatistics chain on demand,
# read the output, then delete the proxies. Independent of FESPP's
# state shape: pass a PV proxy and an array name, get a row dict.
# ---------------------------------------------------------------------------


def _drill_to_inner(vtk_out):
    """Unwrap a vtkPartitionedDataSetCollection layer if present.
    Mirrors the helper in `activator.py` — duplicated here to keep
    `stats_dispatch` independent."""
    if vtk_out is None:
        return None
    if hasattr(vtk_out, 'GetPartitionedDataSet'):
        try:
            pds = vtk_out.GetPartitionedDataSet(0)
            if pds is not None and pds.GetNumberOfPartitions() > 0:
                return pds.GetPartitionAsDataObject(0)
        except Exception:
            return vtk_out
    return vtk_out


def _resolve_rendered_inputs(scene_registry, source_registry, rep_path, view_id):
    """Return the list of PV proxies that are actually rendered for
    this (rep, view). Mirrors `source_resolver.sources_for_rep_path`
    but filtered to displays whose `Visibility == 1` in the target
    view — stats should reflect what the user SEES, not every proxy
    in the pipeline.

    Augments the canonical list with the rep's per-view slice / clip
    outputs (from `RepInScene`). When a clip or slice is enabled the
    rep's upstream extractor is HIDDEN by
    `_refresh_parent_rep_visibility` and only the clip / slice proxy
    is visible — `sources_for_rep_path` returns the upstream as the
    "canonical" source, so without this augmentation the visibility
    filter drops everything and the per-view stats row disappears."""
    scene = None
    pv_view = None
    if scene_registry is not None and view_id:
        scene = scene_registry.get_scene(view_id)
        if scene is not None:
            pv_view = scene.pv_view
    if pv_view is None:
        pv_view = pvsimple.GetActiveView()
    if pv_view is None:
        return [], None
    sources, _ = source_resolver.sources_for_rep_path(
        source_registry, rep_path, view=pv_view,
    )
    sources = list(sources)
    # Augment with the per-view slice / clip outputs.
    if scene is not None:
        rep_in_scene = scene.get_rep(rep_path)
        if rep_in_scene is not None:
            try:
                clip_out = rep_in_scene.clip_output()
                if clip_out is not None and clip_out not in sources:
                    sources.append(clip_out)
            except Exception:
                pass
            try:
                slice_out = rep_in_scene.slice_output()
                if slice_out is not None and slice_out not in sources:
                    sources.append(slice_out)
            except Exception:
                pass
    visible = []
    for s in sources:
        if s is None:
            continue
        try:
            disp = pvsimple.GetDisplayProperties(s, view=pv_view)
        except Exception:
            disp = None
        if disp is None:
            continue
        try:
            if int(getattr(disp, "Visibility", 0) or 0):
                visible.append(s)
        except (TypeError, ValueError):
            continue
    return visible, pv_view


def _resolve_assoc(source, array_name):
    """Return "CELLS" or "POINTS" depending on where the array lives
    on the source's output, or None if not found."""
    try:
        client_obj = source.GetClientSideObject()
        out = client_obj.GetOutputDataObject(0)
        inner = _drill_to_inner(out)
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


def _compute_one_variable(input_source, array_name):
    """Build Threshold(no-NaN) → DescriptiveStatistics on `array_name`,
    read the output, delete the filters, return one row dict (Primary
    + Derived stats merged) or None on failure.

    Also tucks an `NaN_count` key into the row: the input has the
    NaN cells, the threshold drops them and the descriptive stats
    only counts the survivors. Computed as `total − Cardinality`
    so a downstream consumer can show both side-by-side."""
    assoc = _resolve_assoc(input_source, array_name)
    if assoc is None:
        return None

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
        primary = client_out.GetBlock(0)
        derived = client_out.GetBlock(1) if client_out.GetNumberOfBlocks() > 1 else None
        if primary is None or primary.GetNumberOfRows() == 0:
            return None

        row = _table_row_to_dict(primary, 0)
        if derived is not None and derived.GetNumberOfRows() > 0:
            row.update(_table_row_to_dict(derived, 0))
        # Q1 / Median / Q3 on the NaN-stripped data. vtkDescriptiveStatistics
        # primary block exposes Cardinality / Mean / Std Dev / Sum / M2-M4 but
        # not quartiles, so we compute them ourselves on the same Threshold
        # output the descriptive stats consumed.
        try:
            from vtkmodules.util.numpy_support import vtk_to_numpy
            import numpy as _np
            client = threshold_proxy.GetClientSideObject()
            thresh_out = client.GetOutputDataObject(0) if client else None
            inner = _drill_to_inner(thresh_out)
            arr_vtk = None
            if inner is not None:
                fd = inner.GetCellData() if assoc == "CELLS" else inner.GetPointData()
                if fd is not None:
                    arr_vtk = fd.GetArray(array_name)
            if arr_vtk is not None and arr_vtk.GetNumberOfTuples() > 0:
                arr_np = vtk_to_numpy(arr_vtk)
                q1, med, q3 = (float(v) for v in _np.percentile(arr_np, [25, 50, 75]))
                row["Q1"] = q1
                row["Median"] = med
                row["Q3"] = q3
        except Exception as exc:
            print(f"[stats] percentile compute failed for {array_name}: {exc}")
        # Surface the variable name in a deterministic key the UI
        # binds to — vtkDescriptiveStatistics emits "Variable" but
        # we lowercase / underscore for consistency with our state
        # convention.
        row["variable"] = array_name
        # NaN count = (cells / points in the input) − (Cardinality
        # after dropping NaN). Both come from the same `assoc`.
        cardinality = row.get("Cardinality")
        if total is not None and isinstance(cardinality, (int, float)):
            row["NaN_count"] = max(0, total - int(cardinality))
        else:
            row["NaN_count"] = None
        return row
    except Exception as exc:
        print(f"[stats] _compute_one_variable({array_name}): {exc}")
        return None
    finally:
        for proxy in (stats_proxy, threshold_proxy):
            if proxy is not None:
                try:
                    pvsimple.Delete(proxy)
                except Exception:
                    pass


def _append_if_multiple(sources):
    """If `sources` has more than one proxy, chain a transient
    `AppendDatasets` filter to merge them into a single dataset.
    Returns `(merged_proxy, owns_merged)` where `owns_merged` tells
    the caller whether to `Delete()` the returned proxy.

    Single-source case: returns the source as-is (`owns_merged=False`)."""
    if not sources:
        return None, False
    if len(sources) == 1:
        return sources[0], False
    try:
        merged = pvsimple.AppendDatasets(
            registrationName="_stats_merge",
            Input=list(sources),
        )
        merged.UpdatePipeline()
        return merged, True
    except Exception as exc:
        print(f"[stats] AppendDatasets failed: {exc}")
        return sources[0], False


# ---------------------------------------------------------------------------
# Tree / state resolution — translate UI identifiers (array_path,
# realisation pick) into VTK names + default indices for the row
# builders below.
# ---------------------------------------------------------------------------


def _rep_path_for_array_path(tree, array_path):
    """Walk the tree from `array_path` up to the enclosing rep node
    and return its path. Used by Brique B to anchor stats compute
    on the property's parent representation."""
    if tree is None or not array_path:
        return ""
    try:
        node_id = tree.find_node_id(array_path)
        if node_id is None:
            return ""
        rep_id = tree.find_representation_node(node_id)
        if rep_id is None:
            return ""
        return tree.find_path(rep_id) or ""
    except Exception:
        return ""


def _rep_title_for_array_path(tree, array_path):
    """Human-readable label for the enclosing rep node of
    `array_path`. Falls back to the last segment of the rep path
    when the tree has no title set, so the card header can still
    disambiguate between two reps that carry a property with the
    same name. Returns "" only when the rep can't be located at
    all (graceful no-op for the UI prefix span)."""
    if tree is None or not array_path:
        return ""
    try:
        node_id = tree.find_node_id(array_path)
        if node_id is None:
            return ""
        rep_id = tree.find_representation_node(node_id)
        if rep_id is None:
            return ""
        title = tree.find_title(rep_id) or ""
        if title:
            return title
        rep_path = tree.find_path(rep_id) or ""
        if rep_path:
            return rep_path.rstrip("/").rsplit("/", 1)[-1]
        return ""
    except Exception:
        return ""


def _title_and_kind(tree, array_path):
    """Return `(title, kind)` for a property tree node.

    `title` is `propTitle` for MR / MR+TS / TS synthetic nodes (which
    carry the original property name there) and `title` for plain
    properties. `kind` is the tree's `kind` attribute (e.g.
    `"MultiRealization"`, `"ContinuousProperty"`)."""
    if tree is None or not array_path:
        return "", ""
    try:
        nid = tree.find_node_id(array_path)
        if nid is None:
            return "", ""
        kind = tree.find_type(nid) or ""
        title = tree.find_title(nid) or ""
        if kind in ("MultiRealization", "MultiRealizationTimeSeries", "TimeSeries"):
            pt = tree.find_attribute_value(nid, "propTitle")
            if pt:
                title = pt
        return title, kind
    except Exception:
        return "", ""


def _prop_kind_for_array_path(tree, array_path, kind):
    """Underlying property kind (`ContinuousProperty` /
    `DiscreteProperty` / `CategoricalProperty`) for a stats card.

    Mirrors `tree_icons.get_primary_icon`: for synthetic kinds (TS /
    MR / MR+TS) the icon should reflect the *property* type, not the
    synthetic wrapper — so the stats card icon matches the tree's
    primary icon. Reads the `propKind` attribute on the node when
    present, falls back to the kind itself."""
    if tree is None or not array_path:
        return kind
    if kind not in ("TimeSeries", "MultiRealization", "MultiRealizationTimeSeries"):
        return kind
    try:
        nid = tree.find_node_id(array_path)
        if nid is None:
            return kind
        pk = tree.find_attribute_value(nid, "propKind")
        if pk:
            return pk
    except Exception:
        pass
    return kind


def _unit_for_array_path(tree, array_path):
    """Return the unit-of-measure string for `array_path` if the
    tree exposes one, else "".

    TODO(uom): the tree currently carries no "uom" attribute. The
    FESPP plugin must call AbstractValuesProperty::getUom() and
    SetAttribute(nodeId, "uom", ...) in
    ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx around
    the same blocks that already set "propKind" (lines ~1295-1309,
    1551-1602, 1665-1712). Same pattern for "resqmlKind" via
    prop->getPropertyKind()->getTitle(). Until that lands this helper
    always returns "" — the distribution panel falls back to the
    property name alone on the x-axis."""
    if not tree or not array_path:
        return ""
    try:
        nid = tree.find_node_id(array_path)
        if nid is None:
            return ""
        return tree.find_attribute_value(nid, "uom") or ""
    except Exception:
        return ""


def _resolve_vtk_name(tree, array_path, real_idx=None):
    """Resolve `(title, kind, vtk_name)` for the property at `array_path`.
    For MR-kind properties `vtk_name` is the suffixed
    `<sanitised_title>_real_<real_idx>`; non-MR returns the sanitised
    title verbatim. Returns `("", "", "")` on lookup failure."""
    title, kind = _title_and_kind(tree, array_path)
    if not title:
        return "", "", ""
    sanitized = make_valid_vtk_name(title)
    if kind in ("MultiRealization", "MultiRealizationTimeSeries") and real_idx is not None:
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
    """Look up the human-friendly label for `TimestepValues[ts_idx]`
    using the same `time_realization.label_for_time_value` resolver
    the global TC and dropdowns use. Returns "" when ts_idx is None
    or out of range, so callers can fold it straight into a label
    suffix without extra conditionals."""
    if ts_idx is None:
        return ""
    try:
        from fespp_on_trame.app.core.engine import time_realization
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
# Row builders — one Original row per `panel_state` entry + one View
# row per render panel that's colouring by the property. Both anchor
# on `_compute_one_variable` for the actual stats compute; they
# differ in the input source (unfiltered rep_data vs. the view's
# rendered output) and the label they produce.
# ---------------------------------------------------------------------------


def _original_source_and_name(state, source_registry, tree,
                              array_path, rep_path, vtk_name, title):
    """Resolve the source + REAL VTK array name for an Original row,
    returning `(source, name, restore)`.

    Wellbore-frame CHANNELS are the special case: the legacy frame
    source (`source_registry.get(rep_path)`) does NOT carry the
    channel's array — it lives only on the channel's OWN per-channel
    EnergisticsExtractor (created on demand even when hidden). We read it
    DIRECTLY (no retarget, no restore — each channel owns a persistent
    source), picking the real name off it. Non-channels: the legacy
    source + sanitized name. `restore` is always a no-op now (kept in the
    signature so callers stay unchanged)."""
    legacy = source_registry.get(rep_path) if source_registry is not None else None
    noop = (lambda: None)
    try:
        node_id = tree.find_node_id(array_path)
        r_id = tree.find_representation_node(node_id) if node_id is not None else None
        is_channel = (
            r_id is not None and r_id != node_id
            and (tree.find_type(r_id) or "") == "Frame"
        )
    except Exception:
        is_channel = False
    if not is_channel:
        return legacy, vtk_name, noop
    try:
        ext = source_resolver.channel_source_for(array_path)
        if ext is None:
            return legacy, vtk_name, noop
        # Real name: prefer the sanitized name (channels are sanitized
        # since the C++ MakeValidNodeName fix); fall back to the raw title
        # defensively (un-rebuilt plugin).
        real_name = vtk_name
        for cand in (vtk_name, title):
            if cand and _resolve_assoc(ext, cand) is not None:
                real_name = cand
                break
        return ext, real_name, noop
    except Exception:
        return legacy, vtk_name, noop


def _build_original_row(state, source_registry, tree,
                        array_path, rep_path,
                        original_entry):
    """Compute one Original row for the property.

    Anchors on the rep's unfiltered source — Original rows show the
    property's baseline distribution, independent of any view's
    slicer / clip / threshold. For a wellbore-frame CHANNEL the legacy
    frame source lacks the channel array, so `_original_source_and_name`
    reads the per-view extractor retargeted at the channel instead (and
    restores it afterwards).

    `original_entry` carries `id` (UI-stable), `pinned` bool, and
    `real_idx` / `ts_idx` (None → fall back to defaults).

    When `ts_idx` is set, the global PV `TimeKeeper.Time` is
    temporarily moved to that timestep so the source's pipeline
    emits data at that time. Saved / restored around the compute so
    the rest of the engine doesn't see the transient time shift."""
    real_idx = original_entry.get("real_idx")
    if real_idx is None:
        real_idx = _default_real_idx(state, tree, array_path)
    title, kind, vtk_name = _resolve_vtk_name(tree, array_path, real_idx)
    if not vtk_name:
        return None
    source, vtk_name, _restore_channel = _original_source_and_name(
        state, source_registry, tree, array_path, rep_path, vtk_name, title,
    )
    if source is None:
        return None
    is_ts_kind = kind in ("TimeSeries", "MultiRealizationTimeSeries")
    ts_idx = original_entry.get("ts_idx")
    # Auto-resolve TS like we do for real_idx: when the entry hasn't
    # picked a specific timestep, fall back to the current global
    # `state.time_index` (= "follow the time slider"). Keeps the
    # selector visually populated and the label informative — the
    # earlier behaviour left ts_idx=None forever, so the strip's TS
    # dropdown stayed blank and the label hid the timestep entirely
    # even when the rep IS time-series.
    if is_ts_kind and ts_idx is None:
        try:
            ti = getattr(state, "time_index", None)
            if ti is not None:
                ts_idx = int(ti)
        except Exception:
            pass
    saved_time = None
    if is_ts_kind and ts_idx is not None:
        try:
            tk = pvsimple.GetTimeKeeper()
            ts_values = list(tk.TimestepValues or [])
            if 0 <= int(ts_idx) < len(ts_values):
                saved_time = float(tk.Time)
                tk.Time = float(ts_values[int(ts_idx)])
                source.UpdatePipeline(tk.Time)
        except Exception:
            saved_time = None
    try:
        row = _compute_one_variable(source, vtk_name)
    finally:
        if saved_time is not None:
            try:
                tk = pvsimple.GetTimeKeeper()
                tk.Time = saved_time
                source.UpdatePipeline(saved_time)
            except Exception:
                pass
        # Restore the channel extractor's ExtractPath (no-op for
        # non-channels) so the live render is left untouched.
        _restore_channel()
    if row is None:
        return None
    ts_label = _ts_label_for_idx(tree, ts_idx) if is_ts_kind else ""
    # Source label = property title; Realization Index and Time
    # Step now live in dedicated columns (kind-gated). Custom
    # pinned rows share the same label as default — the user
    # disambiguates them visually by the (real, ts) cell values.
    row.update({
        "kind": "original",
        "id": original_entry.get("id", "default"),
        "pinned": bool(original_entry.get("pinned", False)),
        "real_idx": int(real_idx) if real_idx is not None else None,
        "ts_idx": int(ts_idx) if ts_idx is not None else None,
        "ts_label": ts_label,
        "label": title or array_path,
    })
    return row


def _build_view_row(state, scene_registry, source_registry, tree,
                    array_path, rep_path, view_id, view_title):
    """Compute one View N row for the property.

    Anchors on the view's rendered output (`sources_for_rep_path`
    filtered by Visibility=1), so slicer / clip / threshold effects
    are reflected in the stats. The realization index is read from
    the view's `ui_active_realization_by_array_by_view` bucket
    (falls back to the first available).

    Returns None when the view doesn't currently colour the rep by
    `array_path` — a property's stats table should only list views
    that are actually displaying it (a render panel renders ONE
    property per rep at a time; showing stats for views that ignore
    the property would be noise)."""
    by_view = getattr(state, "ui_active_array_by_rep_by_view", None) or {}
    panel_map = by_view.get(view_id) or {}
    if panel_map.get(rep_path) != array_path:
        return None
    real_idx = realization_dispatch.get_active_realization_for_view(
        state, view_id, array_path,
    )
    if real_idx is None:
        real_idx = _default_real_idx(state, tree, array_path)
    title, kind, vtk_name = _resolve_vtk_name(tree, array_path, real_idx)
    if not vtk_name:
        return None
    rendered, pv_view = _resolve_rendered_inputs(
        scene_registry, source_registry, rep_path, view_id,
    )
    if not rendered:
        return None
    merged, owns_merged = _append_if_multiple(rendered)
    try:
        row = _compute_one_variable(merged, vtk_name)
    finally:
        if owns_merged and merged is not None:
            try:
                pvsimple.Delete(merged)
            except Exception:
                pass
    if row is None:
        return None
    # View rows are rendered at the view's OWN time — each render
    # panel has a per-view TimeControl that writes `view.ViewTime`
    # without touching the global TimeKeeper, so two panels can
    # diverge. Read the actual `pv_view.ViewTime` and resolve it
    # through the tree-attached label helper (the same one the
    # global TC / TS dropdown items use). Falls back to
    # `state.time_index` when the view's time can't be read.
    is_ts_kind = kind in ("TimeSeries", "MultiRealizationTimeSeries")
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
                # entry (per-view TCs snap to TimestepValues, so
                # this is normally an exact float match).
                for i, v in enumerate(values):
                    if abs(float(v) - view_time) < 1e-9:
                        view_ts_idx = i
                        break
                try:
                    from fespp_on_trame.app.core.engine import time_realization
                    view_ts_label = time_realization.label_for_time_value(
                        tree, view_time,
                    ) or ""
                except Exception:
                    view_ts_label = ""
            except Exception:
                pass
    row.update({
        "kind": "view",
        "id": view_id,
        "label": f"{title or array_path} On {view_title}",
        "real_idx": int(real_idx) if real_idx is not None else None,
        "ts_idx": view_ts_idx,
        "ts_label": view_ts_label,
    })
    return row


# ---------------------------------------------------------------------------
# Publish — assemble `ui_stats_tables` from the pinned set + the
# user's `ui_stats_panel_state` + the current render-panel list.
# Entrypoint wired by `boot._refresh_descriptive_stats`.
# ---------------------------------------------------------------------------


_DEFAULT_ORIGINAL_ENTRY = {
    "id": "default",
    "pinned": False,
    "real_idx": None,
    "ts_idx": None,
}


def _compute_ts_items(tree):
    """`[{value: idx, label: human_label}, …]` for every entry in
    `TimeKeeper.TimestepValues`. Labels come from
    `time_realization.label_for_time_value` — the same resolver the
    global TC and per-view TC labels use, so the stats dropdown
    matches what the user sees elsewhere. Returns `[]` on PV
    failure or when no timesteps are loaded."""
    items = []
    try:
        from fespp_on_trame.app.core.engine import time_realization
        tk = pvsimple.GetTimeKeeper()
        raw_values = list(tk.TimestepValues or [])
    except Exception:
        return items
    for idx, tv in enumerate(raw_values):
        try:
            label = time_realization.label_for_time_value(tree, float(tv))
        except Exception:
            label = f"time{float(tv):.6f}"
        items.append({"value": idx, "label": label or str(idx)})
    return items


def _available_realizations_for(tree, array_path, kind):
    """`[int, …]` of loaded realisation indices, or `[]` when the
    property isn't MR / MR+TS (the panel uses the length to gate the
    Real dropdown's visibility)."""
    if kind not in ("MultiRealization", "MultiRealizationTimeSeries"):
        return []
    try:
        return list(realization_dispatch.available_realization_indices(
            tree, array_path,
        ))
    except Exception:
        return []


def _build_table_for_path(state, scene_registry, source_registry, tree,
                           array_path, render_panels, panel_state, ts_items):
    """Build one entry of `ui_stats_tables` — Original rows from the
    user's `panel_state` + one View row per render panel that's
    colouring by this property. Returns the dict ready to drop into
    `tables[array_path]`."""
    rep_path = _rep_path_for_array_path(tree, array_path)
    rep_title = _rep_title_for_array_path(tree, array_path)
    title, kind = _title_and_kind(tree, array_path)
    if not rep_path:
        return {
            "title": title or array_path,
            "rep_title": rep_title,
            "rows": [],
            "available_realizations": [],
            "available_timesteps": [],
        }
    originals = ((panel_state.get(array_path) or {}).get("originals")
                  or [_DEFAULT_ORIGINAL_ENTRY])
    rows = []
    for entry in originals:
        row = _build_original_row(
            state, source_registry, tree, array_path, rep_path, entry,
        )
        if row is not None:
            rows.append(row)
    for panel in render_panels:
        pid = panel.get("id") if isinstance(panel, dict) else None
        ptitle = panel.get("title") if isinstance(panel, dict) else ""
        if not pid:
            continue
        row = _build_view_row(
            state, scene_registry, source_registry, tree,
            array_path, rep_path, pid, ptitle or pid,
        )
        if row is not None:
            rows.append(row)
    is_mr = kind in ("MultiRealization", "MultiRealizationTimeSeries")
    is_ts = kind in ("TimeSeries", "MultiRealizationTimeSeries")
    prop_kind = _prop_kind_for_array_path(tree, array_path, kind)
    try:
        from fespp_on_trame.app.ui.drawer.config.tree_icons import (
            get_primary_icon,
        )
        icon = get_primary_icon(kind, prop_kind)
    except Exception:
        icon = "mdi-chart-box-outline"
    return {
        "title": title or array_path,
        "rep_title": rep_title,
        "rows": rows,
        "kind": kind,
        "prop_kind": prop_kind,
        "icon": icon,
        "is_mr": is_mr,
        "is_ts": is_ts,
        "available_realizations": _available_realizations_for(
            tree, array_path, kind,
        ),
        "available_timesteps": ts_items if is_ts else [],
    }


def publish_descriptive_stats(state, scene_registry, source_registry, tree,
                              view_id=None):
    """Recompute `state.ui_stats_tables` for every property in
    `state.ui_stats_pinned_paths`. Empty dict when no property is
    pinned.

    `view_id` is ignored — the Brique B model is property-driven,
    not active-view-driven. The argument is kept to preserve the
    Brique A call sites in boot.py without forcing edits there.

    Active-source preservation: each transient filter chain
    (`Threshold` + `DescriptiveStatistics` + `AppendDatasets`)
    calls `SetActiveSource(self)` on the new proxy; deleting them
    at the end leaves the active source pointing at a destroyed
    proxy and `pvsimple.GetActiveSource()` returns None elsewhere.
    Snapshot on entry, restore before returning so the transient
    chain stays invisible to the rest of the engine."""
    pinned = list(getattr(state, "ui_stats_pinned_paths", []) or [])
    if not pinned:
        if state.ui_stats_tables:
            state.ui_stats_tables = {}
        # Brique A legacy state — keep cleared so the (now-removed)
        # single-table panel doesn't show stale rows.
        if getattr(state, "ui_descriptive_stats", None):
            state.ui_descriptive_stats = []
        return

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
    # etc.) can fire between our SetActiveView(None) above and the
    # restore in the finally below, and several of them probe the
    # active view via pvsimple — without this off-toggle the console
    # spams "No active view found" once per fan-out event. The window
    # is short and the warnings we'd lose are caused by us; nothing
    # the user needs to see.
    _prev_warn_display = None
    try:
        from vtkmodules.vtkCommonCore import vtkObject as _vtkObject
        _prev_warn_display = _vtkObject.GetGlobalWarningDisplay()
        _vtkObject.GlobalWarningDisplayOff()
    except Exception:
        _prev_warn_display = None
    prev_active_source = pvsimple.GetActiveSource()
    try:
        panel_state = dict(getattr(state, "ui_stats_panel_state", {}) or {})
        render_panels = getattr(state, "fespp_render_panels", []) or []
        ts_items = _compute_ts_items(tree)
        tables = {
            array_path: _build_table_for_path(
                state, scene_registry, source_registry, tree,
                array_path, render_panels, panel_state, ts_items,
            )
            for array_path in pinned
        }
        # Bump a publish version so the panel's v-for keys change
        # on every recompute. Vue keeps the previous DOM mounted
        # when keys are stable, even though the row dicts have new
        # references — bumping the key here forces a remount so
        # the cell text bindings and VSelect v-models pick up the
        # fresh values.
        prev_version = int(getattr(state, "ui_stats_publish_version", 0) or 0)
        state.ui_stats_publish_version = prev_version + 1
        state.ui_stats_tables = tables
        # Clear the Brique A legacy single-row var so nothing stale
        # leaks through to a DescriptiveStatsPanel build that still
        # binds to it.
        if getattr(state, "ui_descriptive_stats", None):
            state.ui_descriptive_stats = []
    finally:
        if prev_active_source is not None:
            try:
                pvsimple.SetActiveSource(prev_active_source)
            except Exception:
                pass
        # Restore the active view we cleared on entry. We cleared
        # it to neutralize the pipeline-listener side-effects of
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
# Panel state mutators — toggle the pinned set, patch / pin / unpin
# Original rows. Each rebuilds the entire `panel_state` dict
# top-down with fresh inner dicts; trame's state sync sometimes
# misses mutations that pass through shared inner references.
# ---------------------------------------------------------------------------


def toggle_stats_pinned(state, array_path):
    """Add or remove `array_path` in `state.ui_stats_pinned_paths`.
    No-op for empty path. Initialises the per-property panel state
    with the default Original row on add."""
    if not array_path:
        return
    pinned = list(getattr(state, "ui_stats_pinned_paths", []) or [])
    panel_state = dict(getattr(state, "ui_stats_panel_state", {}) or {})
    if array_path in pinned:
        pinned.remove(array_path)
        panel_state.pop(array_path, None)
    else:
        pinned.append(array_path)
        panel_state.setdefault(array_path, {
            "originals": [{
                "id": "default",
                "pinned": False,
                "real_idx": None,
                "ts_idx": None,
            }],
        })
    state.ui_stats_pinned_paths = pinned
    state.ui_stats_panel_state = panel_state


def _patch_original_entry(state, array_path, original_id, **patches):
    """Rebuild `state.ui_stats_panel_state` with a deep-cloned entry
    where the matching original row has `**patches` applied. The
    rebuild matters: trame's state sync sometimes drops mutations
    that pass through shared inner-dict references, so we replace
    every dict on the path top-down. Caller-friendly wrapper for
    `set_original_real_idx` / `set_original_ts_idx`."""
    if not array_path or not original_id:
        return False
    old_panel_state = getattr(state, "ui_stats_panel_state", {}) or {}
    new_panel_state = {}
    matched = False
    for k, entry in old_panel_state.items():
        if k != array_path:
            new_panel_state[k] = entry
            continue
        new_originals = []
        for o in ((entry or {}).get("originals") or []):
            if o.get("id") == original_id:
                new_o = {**o, **patches}
                matched = True
            else:
                new_o = dict(o)
            new_originals.append(new_o)
        new_panel_state[k] = {
            **((entry or {})),
            "originals": new_originals,
        }
    if not matched:
        # No entry yet for this array_path — seed a default and
        # apply the patch on it so a TS / real pick on an
        # uninitialised property still lands.
        new_panel_state[array_path] = {
            "originals": [{
                "id": "default",
                "pinned": False,
                "real_idx": None,
                "ts_idx": None,
                **patches,
            }],
        }
        matched = True
    state.ui_stats_panel_state = new_panel_state
    return matched


def set_original_real_idx(state, array_path, original_id, real_idx):
    """Patch the realization index on an Original row. Used by the
    UI's per-row real selector. `real_idx=None` reverts to default
    (the first available)."""
    _patch_original_entry(
        state, array_path, original_id,
        real_idx=int(real_idx) if real_idx is not None else None,
    )


def set_original_ts_idx(state, array_path, original_id, ts_idx):
    """Patch the timestep index on an Original row. Used by the
    UI's per-row TS selector. `ts_idx=None` reverts to the global
    `state.time_index` (= "follow the time slider")."""
    _patch_original_entry(
        state, array_path, original_id,
        ts_idx=int(ts_idx) if ts_idx is not None else None,
    )


def pin_original(state, array_path, original_id):
    """Pin the `default` Original row's current selectors into a new
    `custom-<n>` row, then **reset the default row** to auto (real/ts
    back to None). The new custom row carries the snapshotted values
    AND is itself editable — the user can keep tweaking it
    independently of the default, which now goes back to "follow the
    property's defaults".

    No-op on a non-default `original_id` (custom rows can't be
    re-pinned; the snapshot semantic only makes sense from the
    auto-resolved default).

    Implementation note: like the per-row patchers, we rebuild every
    dict on the path top-down. Mutating shared inner references
    sometimes doesn't survive trame's state sync."""
    if not array_path or not original_id:
        return
    old_panel_state = getattr(state, "ui_stats_panel_state", {}) or {}
    entry = old_panel_state.get(array_path) or {"originals": []}
    originals = list((entry or {}).get("originals") or [])
    target = next((o for o in originals if o.get("id") == original_id), None)
    if target is None or target.get("id") != "default":
        return
    used_ids = {o.get("id") for o in originals}
    n = 1
    while f"custom-{n}" in used_ids:
        n += 1
    custom = {
        "id": f"custom-{n}",
        "pinned": True,
        "real_idx": target.get("real_idx"),
        "ts_idx": target.get("ts_idx"),
    }
    # Rebuild every entry with fresh dicts; the default row gets
    # reset to None, the new custom is appended.
    new_originals = []
    for o in originals:
        if o.get("id") == "default":
            new_originals.append({**o, "real_idx": None, "ts_idx": None})
        else:
            new_originals.append(dict(o))
    new_originals.append(custom)
    new_panel_state = {}
    for k, v in old_panel_state.items():
        if k == array_path:
            new_panel_state[k] = {**(entry or {}), "originals": new_originals}
        else:
            new_panel_state[k] = v
    if array_path not in new_panel_state:
        new_panel_state[array_path] = {"originals": new_originals}
    state.ui_stats_panel_state = new_panel_state


def unpin_original(state, array_path, original_id):
    """Remove a pinned Original row. The `default` row can't be
    removed (no-op). Rebuilds the panel state top-down so the
    mutation survives trame's state sync (in-place mutation of
    inner dicts isn't enough)."""
    if not array_path or not original_id or original_id == "default":
        return
    old_panel_state = getattr(state, "ui_stats_panel_state", {}) or {}
    entry = old_panel_state.get(array_path) or {"originals": []}
    new_originals = [
        dict(o) for o in (entry.get("originals") or [])
        if o.get("id") != original_id
    ]
    new_panel_state = {}
    for k, v in old_panel_state.items():
        if k == array_path:
            new_panel_state[k] = {**(entry or {}), "originals": new_originals}
        else:
            new_panel_state[k] = v
    state.ui_stats_panel_state = new_panel_state


# ---------------------------------------------------------------------------
# Side-by-side comparison cart — toggle rows into a list, project
# them as resolved `{key, row, propertyTitle}` items for the
# `StatsComparePanel` to iterate.
# ---------------------------------------------------------------------------


def publish_compare_items(state, tree, scene_registry, source_registry, array_path):
    """Build the rendered comparison item list for the property at
    `array_path`. Returns a list[dict] with each cart row resolved to
    its current source / realization / timestep + every numeric stat
    (Cardinality, Mean, ..., Q1, Median, Q3, ...). Drives the new
    Compare-stats floating panel render and the export-CSV trigger.

    Per-property cart: reads `ui_stats_compare[array_path]` — the
    cart is bound to exactly one property (the UI only renders the
    Cmp column / Compare button on MR/TS cards), so mixing
    apples / kg / counts across properties is structurally
    impossible."""
    if not array_path:
        return []
    carts = getattr(state, "ui_stats_compare", {}) or {}
    selection = list(carts.get(array_path) or [])
    tables = getattr(state, "ui_stats_tables", {}) or {}
    items = []
    for key in selection:
        try:
            array_path, kind, row_id = key.split("|", 2)
        except ValueError:
            continue
        table = tables.get(array_path)
        if not isinstance(table, dict):
            continue
        rows = table.get("rows") or []
        match = next(
            (r for r in rows
             if r.get("kind") == kind and r.get("id") == row_id),
            None,
        )
        if match is None:
            continue
        # Compose a compact column label from the row's MR / TS
        # identity so the Compare-stats panel header shows
        # "real 23, 2019-12-31" instead of the raw cart key
        # (which is the full array_path|kind|row_id triple).
        # View rows reuse their own label ("VOIL On View 1") since
        # that already encodes the view's identity.
        if kind == "view":
            column_label = match.get("label") or row_id
        else:
            parts = []
            r_idx = match.get("real_idx")
            if r_idx is not None:
                parts.append(f"real {int(r_idx)}")
            ts_label = match.get("ts_label") or ""
            if ts_label:
                parts.append(ts_label)
            # The rep parent label used to be prepended here so two
            # reps with the same property name could be told apart.
            # Per user feedback that put redundant rep prefix on
            # every item header; the panel toolbar chip now carries
            # the rep prefix once instead (see ui_stats_compare_panel
            # render — chip reads "<rep_title> / <property> - N rows").
            column_label = (
                ", ".join(parts) if parts
                else (match.get("label") or row_id)
            )
        items.append({
            "key": key,
            "row": match,
            "propertyTitle": table.get("title") or array_path,
            "column_label": column_label,
        })
    # Min / max highlight: for every numeric metric, find which
    # items carry the extremum across the current selection and
    # tag them. The dialog reads `extrema[metric_key]` ("min" /
    # "max" / absent) and paints the cell. Done server-side
    # because Vue `:style` bindings can't easily aggregate across
    # the v-for iteration peers without leaking computed state.
    _COMPARE_METRIC_KEYS = (
        "Cardinality", "NaN_count", "Minimum", "Maximum", "Mean",
        "Standard Deviation", "Variance", "Sum", "Q1", "Median", "Q3",
        "Skewness", "Kurtosis", "M2", "M3", "M4",
    )
    if len(items) >= 2:
        for item in items:
            item["extrema"] = {}
        for metric_key in _COMPARE_METRIC_KEYS:
            numeric = []
            for idx, item in enumerate(items):
                v = (item.get("row") or {}).get(metric_key)
                if isinstance(v, (int, float)) and v == v:  # not NaN
                    numeric.append((idx, float(v)))
            if len(numeric) < 2:
                continue
            min_val = min(v for _, v in numeric)
            max_val = max(v for _, v in numeric)
            # When every cell in the row is identical, there's no
            # meaningful min/max to highlight — skip so the cells
            # stay neutral.
            if min_val == max_val:
                continue
            for idx, v in numeric:
                if v == max_val:
                    items[idx]["extrema"][metric_key] = "max"
                elif v == min_val:
                    items[idx]["extrema"][metric_key] = "min"
    if state.ui_stats_compare_items != items:
        state.ui_stats_compare_items = items
    return items


def toggle_compare(state, array_path, item_key):
    """Toggle item_key in the (single) compare cart for
    array_path. The Compare-stats panel (numeric) and the
    Compare-distribution panel (overlay) both read this same
    cart — selecting a row puts it into both views at once."""
    _toggle_per_property_cart(
        state, "ui_stats_compare", array_path, item_key,
    )


def clear_compare(state, array_path):
    """Empty the compare cart for array_path."""
    _clear_per_property_cart(
        state, "ui_stats_compare", array_path,
    )


def _toggle_per_property_cart(state, state_key, array_path, item_key):
    if not array_path or not item_key:
        return
    carts = dict(getattr(state, state_key, {}) or {})
    bucket = list(carts.get(array_path) or [])
    if item_key in bucket:
        bucket.remove(item_key)
    else:
        bucket.append(item_key)
    carts[array_path] = bucket
    setattr(state, state_key, carts)


def _clear_per_property_cart(state, state_key, array_path):
    if not array_path:
        return
    carts = dict(getattr(state, state_key, {}) or {})
    if array_path in carts:
        carts.pop(array_path, None)
        setattr(state, state_key, carts)


