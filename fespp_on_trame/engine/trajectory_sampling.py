"""Sampling a grid property along a wellbore trajectory — the synthetic log.

A trajectory is a polyline in the grid's CRS; a grid property is a cell
array. Walk the trajectory at a fixed measured-depth step, find the cell each
point falls in, read the property there: the result is the log the grid
"would have recorded", which the well-log panel draws next to the measured
curves of the same kind — the model against the data, on one depth axis.

The trajectory block carries the TRUE measured depth of its stations when
the file stores one (FESPP writes it as the "MD" point array, one value per
station): the samples then carry md too, and the well stays drawn on MD
beside its measured logs. On a trajectory without stored MD (or from a
plugin build that does not emit the array) the samples carry TVD (-Z, as
everywhere in the panel) and NO md: the panel then DRAWS that whole well
on TVD — exact
for the measured logs and for the synthetic one alike, whereas a
chord-length pseudo-MD would sit beside true MD channels with an unknown
offset. Only the drawing moves: every thickness and every summation is
integrated on the true vertical depth whatever is drawn (see
`welllog_dispatch`), so adding a synthetic log changes the axis under the
curves and no figure of the zones table. The stored MD, else the chord
length, is what paces the sampling along the hole. The cell is located on the
SAME dataset `property_values.values_for` reads, so the value index and the
blanked-cell mask line up by construction.
"""
import math

from fespp_on_trame.engine import stats_dispatch, welllog_dispatch
from fespp_on_trame.engine.blockscope import assembly_index
from fespp_on_trame.engine.property_values import values_for

_TRAJ_ROLES = ("WellboreTrajectory",)
_TRAJ_KINDS = ("Trajectory",)

_LAST_ERROR = {"msg": ""}


def last_error():
    """Why the last `synthetic_curve` call returned None ("" after a
    success)."""
    return _LAST_ERROR["msg"]


def chord_md(points):
    """``[(x, y, z, md)]`` from ``[(x, y, z)]`` in polyline order, md being
    the cumulative chord length from the first point."""
    out, md, prev = [], 0.0, None
    for x, y, z in points:
        if prev is not None:
            md += math.dist(prev, (x, y, z))
        out.append((float(x), float(y), float(z), md))
        prev = (x, y, z)
    return out


def resample(stations, step):
    """Points every ``step`` of md along the stations (linear in between),
    the last station included so the log reaches the bottom of the hole."""
    if not stations or step <= 0:
        return list(stations)
    out, i, target = [], 0, stations[0][3]
    last = stations[-1][3]
    while target < last and i < len(stations) - 1:
        a, b = stations[i], stations[i + 1]
        if target > b[3]:
            i += 1
            continue
        span = b[3] - a[3]
        t = (target - a[3]) / span if span > 0 else 0.0
        out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]),
                    a[2] + t * (b[2] - a[2]), target))
        target += step
    out.append(stations[-1])
    return out


def trajectory_stations(shared, traj_path):
    """The trajectory's points in POLYLINE order (the cell's, not the point
    ids'), with their md — the file's when the block carries it, else the
    chord length."""
    return stations_and_md(shared, traj_path)[0]


def stations_and_md(shared, traj_path):
    """``(stations, true_md)``: the stations as `trajectory_stations` gives
    them, and whether their md is the file's measured depth (True) or the
    chord length (False)."""
    ds = welllog_dispatch._fetch_block(shared, traj_path)
    if ds is None or not ds.GetNumberOfPoints():
        return [], False
    order = _polyline_order(ds)
    true_md = _true_md(ds)
    if true_md is not None:
        return [(*(float(c) for c in ds.GetPoint(i)), float(true_md[i]))
                for i in order], True
    return chord_md([ds.GetPoint(i) for i in order]), False


def _true_md(ds):
    """The "MD" point array of the trajectory block — the measured depth of
    each station as the file stores it — as a list, or None when the block
    carries none (a trajectory without stored MD, a plugin build without
    the array) or one that does not pair with the points."""
    try:
        arr = ds.GetPointData().GetArray("MD")
    except Exception:
        return None
    if arr is None or arr.GetNumberOfTuples() != ds.GetNumberOfPoints():
        return None
    vals = [arr.GetTuple1(i) for i in range(arr.GetNumberOfTuples())]
    return vals if all(v == v for v in vals) else None


def _polyline_order(ds):
    """The point ids in the order the polyline cell walks them — the
    stations' order down the hole, which the point ids need not follow."""
    order = None
    try:
        from vtkmodules.vtkCommonCore import vtkIdList
        ids = vtkIdList()
        lines = ds.GetLines()
        if lines is not None and lines.GetNumberOfCells():
            lines.InitTraversal()
            if lines.GetNextCell(ids) and ids.GetNumberOfIds() > 1:
                order = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]
    except Exception:
        order = None
    if order is None:
        order = range(ds.GetNumberOfPoints())
    return list(order)


def sample_grid(dataset, values, points, with_md=False):
    """``[[value, tvd, md]]`` — ``values[cell]`` at each point, None
    outside the grid or where the value is blanked (NaN). The md slot is
    the station's true measured depth when `with_md` (the trajectory
    stores one) and None otherwise, on purpose (see the module
    docstring): a chord length is not a measured depth."""
    from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator
    loc = vtkStaticCellLocator()
    loc.SetDataSet(dataset)
    loc.BuildLocator()
    n = len(values)
    out = []
    for x, y, z, md in points:
        cid = loc.FindCell((x, y, z))
        v = None
        if 0 <= cid < n:
            fv = float(values[cid])
            v = None if fv != fv else fv
        out.append([v, -z, md if with_md else None])
    return out


def _dataset_of(state, source_registry, tree, array_path, rep_path):
    """The rep's inner dataset — the one the property's values index."""
    title = stats_dispatch._title_and_kind(tree, array_path)[0] or ""
    source, _name = stats_dispatch._original_source_and_name(
        state, source_registry, tree, array_path, rep_path, "", title)
    if source is None:
        return None
    try:
        source.UpdatePipeline()
        client = source.GetClientSideObject()
        out = client.GetOutputDataObject(0) if client else None
        return assembly_index.inner(out)
    except Exception:
        return None


def synthetic_curve(state, tree, source_registry, well_path, array_path,
                    step=1.0):
    """``{name, unit, kind, samples: [[value, tvd, md]]}`` of the grid
    property at ``array_path`` sampled along the wellbore's trajectory, or
    None with the reason in ``last_error()``."""
    _LAST_ERROR["msg"] = ""
    wid = tree.find_node_id(well_path)
    if wid is None:
        _LAST_ERROR["msg"] = "wellbore not in the tree"
        return None
    trajs = welllog_dispatch._descendants_of_kinds(
        tree, wid, _TRAJ_ROLES, _TRAJ_KINDS)
    if not trajs:
        _LAST_ERROR["msg"] = "the wellbore has no trajectory"
        return None
    try:
        shared = source_registry.shared_source()
    except Exception:
        shared = None
    if shared is None:
        _LAST_ERROR["msg"] = "no data source"
        return None
    stations, true_md = stations_and_md(shared, tree.find_path(trajs[0]))
    if len(stations) < 2:
        _LAST_ERROR["msg"] = "the trajectory has fewer than two stations"
        return None
    rep_path = stats_dispatch._rep_path_for_array_path(tree, array_path)
    values = values_for(state, tree, source_registry, array_path, rep_path)
    if values is None:
        _LAST_ERROR["msg"] = "the property is not loaded"
        return None
    dataset = _dataset_of(state, source_registry, tree, array_path, rep_path)
    if dataset is None:
        _LAST_ERROR["msg"] = "the property's grid is not loaded"
        return None
    if dataset.GetNumberOfCells() != len(values):
        _LAST_ERROR["msg"] = "the property's values do not index its grid"
        return None
    pid = tree.find_node_id(array_path)
    title = stats_dispatch._title_and_kind(tree, array_path)[0] or "property"
    return {
        "name": f"{title} (grid)",
        "unit": welllog_dispatch._attr(tree, pid, "uom"),
        "kind": welllog_dispatch._attr(tree, pid, "propertyKind"),
        "samples": sample_grid(dataset, values,
                               resample(stations, float(step or 1.0)),
                               with_md=true_md),
    }


def curves_for(state, tree, source_registry, requests):
    """``{well_path: [curve]}`` for the panel's ``[{well, prop, step}]``
    requests; a request that cannot be served is skipped, with a print —
    the panel shows what it has, and the log says why the rest is missing."""
    out = {}
    for r in requests or []:
        well, prop = r.get("well"), r.get("prop")
        if not well or not prop:
            continue
        curve = synthetic_curve(state, tree, source_registry, well, prop,
                                r.get("step") or 1.0)
        if curve is None:
            print(f"[fespp] synthetic log skipped for {prop!r}:"
                  f" {last_error()}", flush=True)
            continue
        out.setdefault(well, []).append(curve)
    return out
