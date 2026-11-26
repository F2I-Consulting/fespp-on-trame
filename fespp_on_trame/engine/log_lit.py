"""The samples highlighted of the logs a 3D view draws, as ONE geometry
(app/features/log_tracks): on a graph a line from the hole to the curve and a
dot on the curve, on a tube the sample's ring a little wider. The rows of the
Values view held and the log view's cursor are drawn apart, each in its
colour (app/features/log_tracks)."""
import numpy as np
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData

from fespp_on_trame.engine.log_track import LOG_SAMPLE

#: a tube's ring lit this many times as wide as the tube there
RING = 1.25
#: most this many samples lit a log
MOST = 5000


def geometry(lit, strips, tubes, zs=1.0, ring=RING, most=MOST):
    """(vtkPolyData, {"lines", "rings"}) of the samples `lit` ({log: [sample
    indices]}). A log in `strips` is drawn as a graph — its strip: the hole's
    n points, then the curve's n, wearing LogSample —; else its datasets in
    `tubes` are its tube's rings, each point wearing its sample. Z is drawn
    `zs` times as tall."""
    points, lines, dots = vtkPoints(), vtkCellArray(), vtkCellArray()
    counted = {"lines": 0, "rings": 0}

    def _add(xyz):
        return points.InsertNextPoint(float(xyz[0]), float(xyz[1]), float(xyz[2]) * zs)

    for sel, samples in (lit or {}).items():
        # a trajectory's station between two samples (-1) stands for none
        samples = [int(s) for s in list(samples)[:most] if int(s) >= 0]
        if sel in strips:
            ds = strips[sel]
            said = ds.GetPointData().GetArray(LOG_SAMPLE) if ds is not None else None
            if said is None:
                continue
            n = ds.GetNumberOfPoints() // 2
            node = vtk_to_numpy(said)[:n]
            for s in samples:
                hit = np.nonzero(node == s)[0]
                if hit.size:
                    i = int(hit[0])
                    hole, curve = _add(ds.GetPoint(i)), _add(ds.GetPoint(n + i))
                    lines.InsertNextCell(2, [hole, curve])
                    dots.InsertNextCell(1, [curve])
                    counted["lines"] += 1
            continue
        for ds in tubes.get(sel) or ():
            said = ds.GetPointData().GetArray(LOG_SAMPLE) if ds is not None else None
            if said is None:
                continue
            node = vtk_to_numpy(said)
            pts = vtk_to_numpy(ds.GetPoints().GetData()).astype(float)
            for s in samples:
                around = pts[node == s]
                if len(around) < 3:
                    continue
                centre = around.mean(axis=0)
                ids = [_add(centre + ring * (q - centre)) for q in around]
                lines.InsertNextCell(len(ids) + 1, ids + ids[:1])
                counted["rings"] += 1
    data = vtkPolyData()
    data.SetPoints(points)
    data.SetLines(lines)
    data.SetVerts(dots)
    return data, counted
