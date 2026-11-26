"""The ParaView selection of what a view holds: cells, and points.

FESPP draws a point set as ONE poly-vertex cell holding every point: a
cell selection of any part of it is that one cell, the whole set (the PO,
20/10: a rectangle on part of a point set took all of it). ParaView
selects points natively, so a point set is selected by its POINTS: the
held selection keeps point ids for its blocks (app/scene/selection,
`points`), and the proxy is given one composite id source of cells and
one of points, appended by ParaView's own AppendSelections when both are
there — the helper `paraview.selection` combines selections with."""


def is_point_cloud(ds):
    """Whether `ds` is drawn as vertices only, fewer cells than points (a
    point set: one poly-vertex for all its points) — its cells cannot pick
    one point, its points must be selected."""
    return bool(ds is not None and ds.IsA("vtkPolyData")
                and ds.GetNumberOfVerts() > 0
                and ds.GetNumberOfLines() == 0 and ds.GetNumberOfPolys() == 0
                and ds.GetNumberOfStrips() == 0
                and ds.GetNumberOfCells() < ds.GetNumberOfPoints())


def triplets(by_flat, flats=None):
    """[flat, 0, id, …] of `by_flat` ({flat: [ids]}), only the flats in
    `flats` when given, in flat order."""
    return [v for f in sorted(by_flat) if flats is None or f in flats
            for i in by_flat[f] for v in (f, 0, int(i))]


def split(by_flat, points):
    """(cell triplets, point triplets) of a held selection whose flats in
    `points` hold point ids."""
    points = set(points or ())
    cells = triplets(by_flat, set(by_flat) - points)
    return cells, triplets(by_flat, points & set(by_flat))


def set_on(proxy, cell_ids, point_ids, port=0):
    """Give `proxy` (a source proxy, its server-manager object) the
    selection of `cell_ids` and `point_ids` ([flat, proc, id, …]): one
    composite id source each, appended when both are there. False when
    both are empty (nothing is set)."""
    from paraview import servermanager as _svm
    from paraview.modules.vtkRemotingViews import vtkSMSelectionHelper
    sm = getattr(proxy, "SMProxy", proxy)
    srcs = []
    if cell_ids:
        srcs.append(_svm.sources.CompositeDataIDSelectionSource(IDs=list(cell_ids), FieldType="CELL"))
    if point_ids:
        srcs.append(_svm.sources.CompositeDataIDSelectionSource(IDs=list(point_ids), FieldType="POINT"))
    if not srcs:
        return False
    if len(srcs) == 1:
        sm.SetSelectionInput(port, srcs[0].SMProxy, 0)
        return True
    # what paraview.selection does to add one selection to another
    both = vtkSMSelectionHelper.NewAppendSelectionsFromSelectionSource(srcs[0].SMProxy)
    more = vtkSMSelectionHelper.NewAppendSelectionsFromSelectionSource(srcs[1].SMProxy)
    vtkSMSelectionHelper.AddSelection(both, more)
    sm.SetSelectionInput(port, both, 0)
    both.UnRegister(None)
    more.UnRegister(None)
    return True
