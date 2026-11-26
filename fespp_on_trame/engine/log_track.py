"""A well log as the plugin's block holds it (a trial: app/features/log_tracks).

FESPP's reader makes a log channel a TUBE: one ring of points per node of
the frame, each wearing the node's value, a node without one written as a
negative zero (counted in ``<array>_nanCount``). What the app reads of it is
here: the hole, the values and the gaps (`rings`), the log as a table of
samples (`samples`, the Values view), and a first width for the graphs
(`first_width`).

The graphs themselves are FESPP's: its well symbols filter
(vtkEnergisticsWellSymbols) builds a log's filled strip, its curve and its
stretches without a value in the well's curtain — the vertical surface
between the hole and its trace at Z = 0 —, square to the hole, a positive
value towards the surface, eased over EASE times their width where the hole
bends, laid on the trajectory's stations between two samples (drawing only:
its point array ``LogSample`` says the sample each point stands for, -1 for
a station); a well plumb all along faces the screen.
"""
import numpy as np

from fespp_on_trame.engine import ranges

#: the first width of the graphs: this share of the largest of the holes
#: they stand on (the diagonal of its bounding box)
WIDTH_SHARE = 0.06
#: the point array of the plugin's filter on a log's tube and graph: the sample of the log each point stands for,
#: -1 for a station of the trajectory (drawing only)
LOG_SAMPLE = "LogSample"
#: the plugin's filter eases a graph's bearing over this many times its
#: width, along the hole: lines set off that far then meet no sooner than
#: they end (what the benches measure against)
EASE = 2.5


def faces_again(faces, laid, screen, dragging):
    """Whether the graphs of a view are laid again facing the screen before
    a render: a graph of the view faces it (a well plumb all along), the
    camera turned since they were laid (`laid`, `screen`: the rounded
    camera), and the frame is drawn at rest (`dragging` false) — the frames
    of a drag keep the graphs as laid, which every graph of the view would
    otherwise be built again for, and the frame at release lays them."""
    return bool(faces) and screen is not None and laid != screen and not dragging


def lay_screen(current, laid, moving):
    """The screen (the rounded camera) the graphs of a view facing it are
    laid for when the view settles its logs: the camera's now (`current`);
    in a frame of a move (`moving`: a drag, a camera flight) the one they
    were laid for (`laid`), kept until the move ends — a lay builds every
    graph of the view again, a frame of a move would wait for it; `laid`
    when the camera has no frame."""
    if moving and laid is not None:
        return laid
    return current if current is not None else laid


def marker_chips(pieces):
    """{tree row: colour} of the markers the views' filters draw, the first
    view's colour kept; a view whose plugin has no such filter (None) gives
    none."""
    chips = {}
    for piece in (pieces or {}).values():
        for row, colour in ((piece or {}).get("marker_chips") or {}).items():
            chips.setdefault(row, colour)
    return chips


def rings(ds, array_name):
    """``(centres (n, 3), values (n,), gap (n,) bool)`` of a log channel's
    block as the plugin makes it — a tube, each frame node a ring of points
    wearing the node's value: the hole at each node (its ring's centre), the
    value there, and whether the node holds none (written as a NEGATIVE zero,
    counted in ``<array>_nanCount``, engine/welllog_dispatch). None when the
    block is no such tube."""
    from vtkmodules.util.numpy_support import vtk_to_numpy
    if ds is None or not hasattr(ds, "GetPoints") or ds.GetPoints() is None:
        return None
    n, sides = ds.GetNumberOfPoints(), ds.GetNumberOfCells()
    pd = ds.GetPointData()
    arr = pd.GetArray(array_name) if pd is not None else None
    if arr is None or not n or not sides or n % sides or n // sides < 2:
        return None
    centres = vtk_to_numpy(ds.GetPoints().GetData()).astype(float).reshape(n // sides, sides, 3).mean(axis=1)
    values = vtk_to_numpy(arr).astype(float).reshape(n // sides, sides)[:, 0].copy()
    return centres, values, ranges.no_value(values, ranges.gap_count(ds, array_name))


def first_width(holes):
    """A first width for graphs standing on `holes` (each (n, 3), data
    space): WIDTH_SHARE of the largest one's extent."""
    sizes = [float(np.linalg.norm(np.ptp(np.asarray(h, float), axis=0))) for h in holes if len(h)]
    return WIDTH_SHARE * max(sizes) if sizes and max(sizes) > 0 else 1.0


def samples(ds, array_name):
    """``(centres (n, 3), values (n,), md (n,) | None)``: a log channel's
    block read as the log it is — one row per frame node, its value NaN
    where it holds none, its measured depth from the plugin's "MD" field
    array — not as the tube drawing it. None when the block is no such
    tube."""
    got = rings(ds, array_name)
    if got is None:
        return None
    centres, values, gap = got
    values = np.where(gap, np.nan, values)
    fd = ds.GetFieldData()
    md = fd.GetArray("MD") if fd is not None else None
    if md is not None and md.GetNumberOfTuples() == len(centres):
        from vtkmodules.util.numpy_support import vtk_to_numpy
        return centres, values, vtk_to_numpy(md).astype(float).ravel()
    return centres, values, None


def frame_table(reads):
    """A log frame read sample by sample from its logs' blocks: `reads`
    [(name, `samples` of its block, or None when it is not read)] ->
    ``(centres (n, 3), md (n,) | None, [(name, values (n,))])``, one row per
    node of the frame — every log of a frame stands on its nodes —, a log
    not read, or read on other nodes, a column of NaN. None when no log is
    read."""
    got = [r for _name, r in reads if r is not None]
    if not got:
        return None
    centres, _values, md = next((r for r in got if r[2] is not None), got[0])
    n = len(centres)
    cols = [(name, np.asarray(r[1], float) if r is not None and len(r[1]) == n else np.full(n, np.nan))
            for name, r in reads]
    return centres, md, cols


def log_summary(values, md):
    """``[samples, MD top, MD base, min, max]`` of one log read sample by
    sample (`samples`): how many samples hold a value, the measured depths of
    the shallowest and deepest of them (NaN without `md`), its least and
    greatest value."""
    v = np.asarray(values, float)
    good = np.isfinite(v)
    m = np.asarray(md, float)[good] if md is not None and len(md) == len(v) else np.zeros(0)
    m = m[np.isfinite(m)]
    return [float(good.sum()),
            float(m.min()) if len(m) else float("nan"), float(m.max()) if len(m) else float("nan"),
            float(v[good].min()) if good.any() else float("nan"),
            float(v[good].max()) if good.any() else float("nan")]


def real_point(ds, point_id):
    """The point of a log's tube or graph drawn by the plugin's filter that
    stands for a sample of the log, the nearest `point_id` — itself when it
    does, or when the block says nothing of it: a station of the trajectory
    is drawing only, what is read there is the nearest sample's."""
    said = ds.GetPointData().GetArray(LOG_SAMPLE) if ds is not None and ds.GetPointData() is not None else None
    if said is None or point_id is None or point_id < 0 or point_id >= said.GetNumberOfTuples():
        return point_id
    if said.GetValue(point_id) >= 0:
        return point_id
    from vtkmodules.util.numpy_support import vtk_to_numpy
    real = np.nonzero(vtk_to_numpy(said) >= 0)[0]
    return int(real[np.argmin(np.abs(real - point_id))]) if len(real) else point_id
