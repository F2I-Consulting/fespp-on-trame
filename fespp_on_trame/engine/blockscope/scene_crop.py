"""The X / Y / Z cut of a whole 3D view — the Geometry slicer on the SCENE
(the PO, 29/10: "a slice on the whole scene: when no node is active, the
card is on the scene").

The same rule as the object slicer in X / Y / Z (engine/sources/xyz_crop):
a cell is kept when it MEETS a box of the card — its extent along each axis
meets the box's range; a cut at one value keeps the cells the plane
crosses; the boxes show together (∪, the card's ∩ already compiled into the
boxes it hands, engine/slicer_card).

ONE pipeline per view, whatever the number of boxes, on the shared display
source the view's composite representation draws
(engine/blockscope/pdc_scene), updated when a render pulls it like every
other filter, and keeping the source's structure — its blocks, their flat
indices, its assembly — so the representation's block selectors, colours
and tables apply as they are, and a pick on the cut is a pick on the
source:

- `FesppScenePrep` (`prep_into`), run again when the source changes, each
  grid's geometry prepared ONCE (a cache by its cells and points: a
  property loaded or a log ticked while the scene is cut costs its own leaf
  only): each cell's id (`vtkOriginalCellIds`, what picking reads back); an
  IJK grid made the unstructured grid it is (an explicit structured grid's
  shallow copy costs 30–45 ms against 0.1 ms, and every stage after makes
  some — measured on drogon); the lines and points made cells of their own
  (a well, a log channel, a polyline set is ONE poly-line cell in the
  plugin's output, a point set ONE poly-vertex: kept whole otherwise — the
  PO, 29/10: the logs and the markers are cut with the trajectory); every
  cell's extent (`CELLBOX`, field data, axis-major: one axis is one
  contiguous run), a 2D grid's (a horizon, a `vtkStructuredGrid`) read off
  its point grid — the PO, 29/10 evening: a horizon ticked on a cut scene
  showed whole; and, for an IJK grid, its FACE TABLE (`_face_table`): which
  of the faces between two cells I, J or K apart are one face (the same
  four points — not across a fault's split nodes), and the faces no
  neighbour shares (the grid's outside, the faults). A leaf with cells and
  no points is passed untouched;
- `FesppSceneCut` (`cut_into`), the boxes as its property: the cells a box
  meets (`mask_of`, numpy, all the boxes at once); an IJK grid drawn as the
  POLYDATA OF ITS EXPOSED FACES, straight from the table — a shared face
  with one cell kept and the other not, a lone face of a kept cell — the
  grid's points shared, each face carrying its cell's values: no cell
  copied, no surface to extract (ParaView's Threshold then the
  representation's surface filter cost 40–80 ms a step on drogon's 930 000
  cells — the PO, 29/10 evening: "still too slow"); any other leaf as the
  cells kept (a Threshold inside the filter, on that leaf alone).

The two filters are Python VTK algorithms loaded as a ParaView plugin
(engine/blockscope/scene_cut_filters).

What the versions of 29/10 taught (each measured or reproduced):
- ParaView's Clip, a plane for each face a box narrows and a pipeline and
  a representation for each box: 170–210 ms a step on drogon, growing with
  every plane — the PO measured 1.5 s on ADME;
- a ProgrammableFilter collects Python's garbage after every run: 33 ms of
  the app's heap a step;
- a TrivialProducer fed by hand needed `UpdatePipeline` forced from the
  scene's projection, in the middle of a read;
- an ExtractBlock of the blocks the view draws renumbers them: a log ticked
  while the scene was cut (on ADME) shifted the flat indices under the
  representation, and the render after crashed the session (SIGSEGV after
  every filter had run — the scenario `etp_scene_cut_logs`, traced with
  FESPP_SCENE_CUT_TRACE). The source's structure costs nothing once the
  explicit grid is made unstructured;
- a face table hashed over every face of the grid (a lexsort of 5.6
  million faces) costs 2 s to build and 60 ms a step to read (one gather
  per face): the IJK structure gives the neighbours for nothing, and a
  step reads three contiguous comparisons.
"""
import json
import os

from fespp_on_trame.engine.node_kinds import is_ijk_grid
from fespp_on_trame.engine.sources.xyz_crop import _WHOLE

# the card's object meaning "the whole scene of the view"
SCENE = "@scene"
# the source's cell ids, as ExtractSelection names them (picking reads it)
ORIGINAL_IDS = "vtkOriginalCellIds"
# each cell's extent, field data, axis-major: x0 (every cell), x1, y0, y1, z0, z1 (prep)
CELLBOX = "__fespp_cellbox"
# an IJK grid's face table, field data (prep): the grid's cell dims and the
# face of a cell and of its I, J, K neighbour that are one face; whether the
# faces between neighbours ARE one (I pairs, J pairs, K pairs); the lone
# faces (cell, face)
FACE_META = "__fespp_facemeta"
FACE_MATCH = "__fespp_facematch"
FACE_LONE = "__fespp_facelone"
# … and the hexahedron each IJK cell is (-1: hidden, left out of the grid)
FACE_CELLS = "__fespp_facecells"
# the mark a leaf's cells are kept by (inside the cut)
KEEP = "__fespp_keep"
VTK_HEXAHEDRON = 12
# the six faces of a hexahedron, each in cyclic order (VTK's points:
# 0-1-2-3 one layer, 4-5-6-7 the next)
_HEX_FACES = ((0, 3, 7, 4), (1, 2, 6, 5), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 2, 1), (4, 5, 6, 7))
_SCRATCH = (CELLBOX, FACE_META, FACE_MATCH, FACE_LONE, FACE_CELLS, KEEP, "ConnectivityFlags",
            "BLOCK_I", "BLOCK_J", "BLOCK_K")


# ---------------------------------------------------------------- a trace
def _trace(msg):
    """A line to FESPP_SCENE_CUT_TRACE when set (a scenario chasing a crash):
    written by a system call, so it survives the process dying."""
    path = os.environ.get("FESPP_SCENE_CUT_TRACE")
    if not path:
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (msg + "\n").encode())
    finally:
        os.close(fd)


# ---------------------------------------------------------------- the leaves
def _leaves(src):
    """(iterator position, leaf) of a collection's non-empty dataset leaves."""
    it = src.NewIterator()
    it.SetVisitOnlyLeaves(True)
    it.SetSkipEmptyNodes(True)
    it.InitTraversal()
    while not it.IsDoneWithTraversal():
        ds = it.GetCurrentDataObject()
        if ds is not None and ds.IsA("vtkDataSet"):
            yield it, ds
        it.GoToNextItem()


def _consistent(ds):
    """Whether a leaf can be read: cells need points. A leaf the reader is
    still filling (a lazy ETP log, the PO, 29/10) is passed untouched, kept
    whole by the cut, until the next run."""
    n = ds.GetNumberOfCells()
    if not n:
        return False
    pts = ds.GetPoints() if hasattr(ds, "GetPoints") else None
    return pts is not None and ds.GetNumberOfPoints() > 0


def _field(ds, name):
    return ds.GetFieldData().GetArray(name)


def _add_field(ds, name, values):
    from vtkmodules.util.numpy_support import numpy_to_vtk
    arr = numpy_to_vtk(values, deep=1)
    arr.SetName(name)
    ds.GetFieldData().AddArray(arr)


def _drop_scratch(ds):
    for name in _SCRATCH:
        ds.GetFieldData().RemoveArray(name)
        ds.GetCellData().RemoveArray(name)


# ---------------------------------------------------------------- prep
def _split(ds):
    """A polydata of lines or points only as one cell a segment or a point."""
    if not ds.IsA("vtkPolyData") or ds.GetNumberOfPolys() or ds.GetNumberOfStrips():
        return ds
    if not (ds.GetNumberOfLines() or ds.GetNumberOfVerts()):
        return ds
    from vtkmodules.vtkFiltersCore import vtkTriangleFilter
    f = vtkTriangleFilter()
    f.SetInputData(ds)
    f.PassLinesOn()
    f.PassVertsOn()
    f.Update()
    out = f.GetOutput().NewInstance()
    out.ShallowCopy(f.GetOutput())
    return out


def _with_ids(ds):
    """A shallow copy of `ds` with its cells' ids (ORIGINAL_IDS), what the
    picking reads back — made here rather than by PointAndCellIds, which
    read a log ADME was still filling and crashed the session (29/10)."""
    import numpy as np
    from vtkmodules.util.numpy_support import numpy_to_vtk
    out = ds.NewInstance()
    out.ShallowCopy(ds)
    arr = numpy_to_vtk(np.arange(ds.GetNumberOfCells(), dtype=np.int64), deep=1)
    arr.SetName(ORIGINAL_IDS)
    out.GetCellData().AddArray(arr)
    return out


def _extents_of_cells(ds):
    """(6, n): every cell's extent, from its cell arrays (an unstructured
    grid, a polydata); None when they cannot be read."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    n = ds.GetNumberOfCells()
    if ds.IsA("vtkPolyData"):
        arrays = [ds.GetVerts(), ds.GetLines(), ds.GetPolys(), ds.GetStrips()]
    elif hasattr(ds, "GetCells") and ds.GetCells() is not None:
        arrays = [ds.GetCells()]
    else:
        return None
    pts = vtk_to_numpy(ds.GetPoints().GetData())
    box = np.empty((6, n))
    row = 0
    for ca in arrays:
        m = ca.GetNumberOfCells() if ca is not None else 0
        if not m:
            continue
        off = vtk_to_numpy(ca.GetOffsetsArray()).astype(np.int64)
        conn = vtk_to_numpy(ca.GetConnectivityArray()).astype(np.int64)
        if not len(conn) or conn.max() >= len(pts):
            return None
        starts = np.minimum(off[:-1], len(conn) - 1)
        for a in range(3):
            c = pts[conn, a].astype(np.float64)
            box[2 * a, row:row + m] = np.minimum.reduceat(c, starts)
            box[2 * a + 1, row:row + m] = np.maximum.reduceat(c, starts)
        row += m
    return box if row == n else None


def _dims(ds):
    """A structured grid's point dims (nx, ny, nz)."""
    dims = [0, 0, 0]
    ds.GetDimensions(dims)
    return dims


def _extents_of_grid(ds):
    """(6, n): a structured grid's cells' extents, off its point grid (a
    horizon is a 2D grid of quads: no cell array to read); None when the
    points do not fill the grid."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    nx, ny, nz = _dims(ds)
    pts = vtk_to_numpy(ds.GetPoints().GetData())
    if len(pts) != nx * ny * nz or ds.GetNumberOfCells() != max(nx - 1, 1) * max(ny - 1, 1) * max(nz - 1, 1):
        return None
    lo = hi = pts.astype(np.float64).reshape(nz, ny, nx, 3)
    if nx > 1:
        lo, hi = np.fmin(lo[:, :, :-1], lo[:, :, 1:]), np.fmax(hi[:, :, :-1], hi[:, :, 1:])
    if ny > 1:
        lo, hi = np.fmin(lo[:, :-1], lo[:, 1:]), np.fmax(hi[:, :-1], hi[:, 1:])
    if nz > 1:
        lo, hi = np.fmin(lo[:-1], lo[1:]), np.fmax(hi[:-1], hi[1:])
    n = ds.GetNumberOfCells()
    box = np.empty((6, n))
    box[0::2] = lo.reshape(n, 3).T
    box[1::2] = hi.reshape(n, 3).T
    return box


def _boxed(ds):
    """`ds` with every cell's extent as the field array CELLBOX; `ds` itself
    when it cannot be read (kept whole by the cut)."""
    box = _extents_of_grid(ds) if ds.IsA("vtkStructuredGrid") else _extents_of_cells(ds)
    if box is None:
        return ds
    out = ds.NewInstance()
    out.ShallowCopy(ds)
    _add_field(out, CELLBOX, box.ravel())
    return out


def _face_table(conn, dims, orig=None):
    """An IJK grid's face table, from its hexahedra's points (`conn`, (n,
    8)), its cell dims and the IJK cell each hexahedron is (`orig`, None
    when the grid is whole and in order: a grid's hidden cells are left
    out when it is made unstructured — drogon hides 270 000): (meta, match,
    lone, cell map) — see FACE_META; None when the hexahedra do not fit the
    dims or no face pairs with its neighbour's. Which of a cell's six faces
    meets which of its I (J, K) neighbour's is read off the first pairs
    that share four points — the plugin's point order, whatever it is —
    then every pair is checked: a fault's split nodes leave both faces
    lone, as ParaView's surface filter does; a hidden neighbour too."""
    import numpy as np
    ni, nj, nk = (int(d) for d in dims)
    big = ni * nj * nk
    n = len(conn)
    if orig is None:
        if n != big or n == 0:
            return None
        orig = np.arange(n)
    if not n or len(orig) != n or orig.min() < 0 or orig.max() >= big:
        return None
    cell_map = np.full(big, -1, dtype=np.int64)
    cell_map[orig] = np.arange(n)
    faces = np.array(_HEX_FACES)
    ids = np.arange(big).reshape(nk, nj, ni)
    matched = np.zeros((n, 6), dtype=bool)
    match, meta = [], [ni, nj, nk]
    for step, lo_ijk in ((1, ids[:, :, :-1]), (ni, ids[:, :-1, :]), (ni * nj, ids[:-1, :, :])):
        lo_ijk = lo_ijk.ravel()
        if not len(lo_ijk):
            meta += [-1, -1]
            continue
        lo_all, hi_all = cell_map[lo_ijk], cell_map[lo_ijk + step]
        both = (lo_all >= 0) & (hi_all >= 0)
        lo, hi = lo_all[both], hi_all[both]
        same = np.zeros(len(lo_ijk), dtype=bool)
        if len(lo):
            sample = slice(0, min(len(lo), 2000))
            best, fa, fb = 0, -1, -1
            keys_lo = [np.sort(conn[lo[sample][:, None], faces[f]], axis=1) for f in range(6)]
            keys_hi = [np.sort(conn[hi[sample][:, None], faces[f]], axis=1) for f in range(6)]
            for a in range(6):
                for b in range(6):
                    hits = int(np.all(keys_lo[a] == keys_hi[b], axis=1).sum())
                    if hits > best:
                        best, fa, fb = hits, a, b
            if best == 0:
                return None
            paired = np.all(np.sort(conn[lo[:, None], faces[fa]], axis=1)
                            == np.sort(conn[hi[:, None], faces[fb]], axis=1), axis=1)
            matched[lo[paired], fa] = True
            matched[hi[paired], fb] = True
            same[both] = paired
            meta += [fa, fb]
        else:
            meta += [-1, -1]
        match.append(same)
    lone = np.argwhere(~matched)
    return (np.array(meta, dtype=np.int64), np.concatenate(match).astype(np.uint8),
            lone.astype(np.int64).ravel(), cell_map)


def _geometry_key(ds):
    """What a grid's geometry is made of: its cells and points, by address
    and modification time (a property loaded leaves them)."""
    parts = [ds.GetPoints()]
    if hasattr(ds, "GetCells"):
        parts.append(ds.GetCells())
    return tuple((p.GetAddressAsString(""), p.GetMTime()) for p in parts if p is not None) + (
        ds.GetClassName(), ds.GetNumberOfCells())


def _grid_geometry(ds):
    """A grid's geometry prepared, once: {geo: the bare unstructured grid
    (its points and cells, no data), orig: the source cell of each of its
    cells or None when they are the source's in order, box: CELLBOX's
    values, faces: the face table or None}."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    orig, dims = None, None
    if ds.IsA("vtkExplicitStructuredGrid"):
        from vtkmodules.vtkFiltersCore import vtkExplicitStructuredGridToUnstructuredGrid
        f = vtkExplicitStructuredGridToUnstructuredGrid()
        f.SetInputData(_with_ids(ds))
        f.Update()
        ug = f.GetOutput()
        ids = vtk_to_numpy(ug.GetCellData().GetArray(ORIGINAL_IDS)).astype(np.int64)
        if not np.array_equal(ids, np.arange(len(ids))):
            orig = ids
        e = ds.GetExtent()
        dims = (e[1] - e[0], e[3] - e[2], e[5] - e[4])
    elif is_ijk_grid(ds):
        # a lattice: its hexahedra in the grid's own order
        from vtkmodules.vtkFiltersCore import vtkAppendFilter
        f = vtkAppendFilter()
        f.SetInputData(ds)
        f.Update()
        ug = f.GetOutput()
        e = ds.GetExtent()
        dims = (e[1] - e[0], e[3] - e[2], e[5] - e[4])
    else:
        ug = ds
    geo = ug.NewInstance()
    geo.ShallowCopy(ug)
    geo.GetCellData().Initialize()
    geo.GetPointData().Initialize()
    geo.GetFieldData().Initialize()
    faces = None
    n = geo.GetNumberOfCells()
    if dims is not None and n and geo.IsHomogeneous() and geo.GetCellType(0) == VTK_HEXAHEDRON:
        conn = vtk_to_numpy(geo.GetCells().GetConnectivityArray())
        if len(conn) == 8 * n:
            faces = _face_table(conn.reshape(n, 8), dims, orig)
    return {"geo": geo, "orig": orig, "box": _extents_of_cells(geo), "faces": faces}


def _attach(out, ds, orig):
    """The source leaf's data on the prepared grid `out`: its cell arrays
    by reference (gathered through `orig` when the cells moved), its point
    and field arrays."""
    cd = ds.GetCellData()
    if orig is None:
        if out.GetNumberOfCells() == ds.GetNumberOfCells():
            out.GetCellData().PassData(cd)
    else:
        _gather(cd, out.GetCellData(), orig)
    if out.GetNumberOfPoints() == ds.GetNumberOfPoints():
        out.GetPointData().PassData(ds.GetPointData())
    out.GetFieldData().PassData(ds.GetFieldData())
    _drop_scratch(out)


def _prep_grid(ds, cache, seen):
    """An IJK or unstructured grid prepared: its geometry from `cache`
    (made once, kept in `seen` for the next run), the source's data on it,
    its cells' ids, extents and face table."""
    import numpy as np
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    key = _geometry_key(ds)
    hit = cache.get(key) or seen.get(key)
    if hit is None:
        import time
        t0 = time.perf_counter()
        hit = _grid_geometry(ds)
        # said: a grid prepared again at every read of a log would be the
        # cache missing its key (29/10)
        print(f"[fespp] scene cut: a grid of {ds.GetNumberOfCells()} cells prepared in"
              f" {(time.perf_counter() - t0) * 1000:.0f} ms"
              f" ({'with' if hit['faces'] is not None else 'without'} its face table)", flush=True)
    seen[key] = hit
    out = hit["geo"].NewInstance()
    out.ShallowCopy(hit["geo"])
    _attach(out, ds, hit["orig"])
    # the cells' ids: the ones the leaf carries already (an isolate's
    # display, whose cells are the grid's through its crops and
    # thresholds), else their own
    up = ds.GetCellData().GetArray(ORIGINAL_IDS)
    if up is not None and up.GetNumberOfTuples() == ds.GetNumberOfCells():
        ids = vtk_to_numpy(up).astype(np.int64)
        if hit["orig"] is not None:
            ids = ids[hit["orig"]]
    else:
        ids = hit["orig"] if hit["orig"] is not None else np.arange(out.GetNumberOfCells(), dtype=np.int64)
    arr = numpy_to_vtk(ids, deep=1)
    arr.SetName(ORIGINAL_IDS)
    out.GetCellData().AddArray(arr)
    if hit["box"] is not None:
        _add_field(out, CELLBOX, hit["box"].ravel())
    if hit["faces"] is not None:
        meta, match, lone, cell_map = hit["faces"]
        _add_field(out, FACE_META, meta)
        _add_field(out, FACE_MATCH, match)
        _add_field(out, FACE_LONE, lone)
        _add_field(out, FACE_CELLS, cell_map)
    return out


def _prep_leaf(ds, cache, seen):
    if is_ijk_grid(ds) or ds.IsA("vtkUnstructuredGrid"):
        return _prep_grid(ds, cache, seen)
    # a leaf carrying its cells' ids already (an isolate's display) keeps them
    carried = ds.GetCellData().GetArray(ORIGINAL_IDS) is not None
    return _boxed(_split(ds if carried else _with_ids(ds)))


def output_class(stage, input_class, layered=False):
    """The class a stage's output must have for an input of `input_class`
    that is ONE dataset (an object cut alone, an isolate's display): the
    prep makes an IJK grid unstructured (`layered`: a structured grid with
    layers of cells, a lattice, not a horizon), the cut draws a horizon as
    its quads. A collection keeps its class, its leaves change freely."""
    if stage == "prep" and (input_class == "vtkExplicitStructuredGrid"
                            or (input_class == "vtkStructuredGrid" and layered)):
        return "vtkUnstructuredGrid"
    if stage == "cut" and input_class == "vtkStructuredGrid" and not layered:
        return "vtkPolyData"
    return input_class


def _as_class(ds, cls):
    """`ds` as a `cls`: an output object of one class takes no shallow copy
    of another (the cut of HOD, a horizon, kept the whole horizon: its
    quads could not go into a structured grid — 30/10)."""
    if ds.IsA(cls):
        return ds
    if cls == "vtkUnstructuredGrid":
        from vtkmodules.vtkFiltersCore import vtkAppendFilter
        f = vtkAppendFilter()
    elif cls == "vtkPolyData":
        from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter
        f = vtkGeometryFilter()
    else:
        print(f"[fespp] scene cut: a {ds.GetClassName()} cannot be drawn as a {cls}", flush=True)
        return ds
    f.SetInputData(ds)
    f.Update()
    out = f.GetOutput().NewInstance()
    out.ShallowCopy(f.GetOutput())
    return out


def prep_into(src, dst, cache=None):
    """`dst` made the prepared `src` (FesppScenePrep): each cell's id, an
    IJK grid unstructured with its face table, lines and points split,
    every cell's extent beside it. `cache` ({geometry key: geometry}) is
    left holding this run's grids only."""
    seen = {}
    cache = {} if cache is None else cache
    dst.ShallowCopy(src)
    if src.IsA("vtkCompositeDataSet"):
        for it, ds in _leaves(src):
            if _consistent(ds):
                dst.SetDataSet(it, _prep_leaf(ds, cache, seen))
    elif src.IsA("vtkDataSet") and _consistent(src):
        dst.ShallowCopy(_as_class(_prep_leaf(src, cache, seen), dst.GetClassName()))
    cache.clear()
    cache.update(seen)


# ---------------------------------------------------------------- the cut
def mask_of(ds, boxes):
    """The cells of `ds` a box of `boxes` ([[x0, x1], [y0, y1], [z0, z1]]
    each) meets, True each (numpy); None when `ds` carries no extents
    (kept whole)."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    n = ds.GetNumberOfCells()
    cb = ds.GetFieldData().GetArray(CELLBOX)
    if cb is None or cb.GetNumberOfTuples() != 6 * n:
        return None
    v = vtk_to_numpy(cb).reshape(6, n)
    keep = np.zeros(n, dtype=bool)
    for b in np.asarray(boxes, dtype=np.float64).reshape(-1, 3, 2):
        keep |= ((v[0] <= b[0, 1]) & (v[1] >= b[0, 0])
                 & (v[2] <= b[1, 1]) & (v[3] >= b[1, 0])
                 & (v[4] <= b[2, 1]) & (v[5] >= b[2, 0]))
    return keep


def _exposed_faces(ds, keep):
    """(quads, owners) of an IJK grid cut to `keep`: each exposed face's
    four points, in cyclic order, and the kept cell it belongs to — a shared
    face with one side kept, a lone face of a kept cell."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    meta = vtk_to_numpy(_field(ds, FACE_META)).astype(np.int64)
    match = vtk_to_numpy(_field(ds, FACE_MATCH)).astype(bool)
    lone = vtk_to_numpy(_field(ds, FACE_LONE)).astype(np.int64).reshape(-1, 2)
    cell_map = vtk_to_numpy(_field(ds, FACE_CELLS)).astype(np.int64)
    orig = vtk_to_numpy(ds.GetCellData().GetArray(ORIGINAL_IDS)).astype(np.int64)
    n = ds.GetNumberOfCells()
    conn = vtk_to_numpy(ds.GetCells().GetConnectivityArray()).reshape(n, 8)
    faces = np.array(_HEX_FACES)
    ni, nj, nk = (int(d) for d in meta[:3])
    # kept, on the whole IJK box (a hidden cell is never kept)
    k3 = np.zeros(ni * nj * nk, dtype=bool)
    k3[orig] = keep
    k3 = k3.reshape(nk, nj, ni)
    ids = np.arange(ni * nj * nk).reshape(nk, nj, ni)
    quads, owners = [], []
    at = 0
    for step, lo_ids, lo_keep, hi_keep, fa, fb in (
            (1, ids[:, :, :-1], k3[:, :, :-1], k3[:, :, 1:], meta[3], meta[4]),
            (ni, ids[:, :-1, :], k3[:, :-1, :], k3[:, 1:, :], meta[5], meta[6]),
            (ni * nj, ids[:-1, :, :], k3[:-1, :, :], k3[1:, :, :], meta[7], meta[8])):
        size = lo_ids.size
        if not size:
            continue
        shown = (lo_keep != hi_keep).ravel() & match[at:at + size]
        at += size
        if fa < 0:
            continue
        lo_ijk = lo_ids.ravel()[shown]
        lo, hi = cell_map[lo_ijk], cell_map[lo_ijk + step]
        lo_kept = keep[lo]
        quads.append(np.where(lo_kept[:, None], conn[lo[:, None], faces[fa]], conn[hi[:, None], faces[fb]]))
        owners.append(np.where(lo_kept, lo, hi))
    if len(lone):
        shown = keep[lone[:, 0]]
        cells, which = lone[shown, 0], lone[shown, 1]
        quads.append(conn[cells[:, None], faces[which]])
        owners.append(cells)
    if not quads:
        return np.zeros((0, 4), dtype=np.int64), np.zeros(0, dtype=np.int64)
    return np.concatenate(quads).astype(np.int64), np.concatenate(owners).astype(np.int64)


_NOT_CARRIED = set()    # the arrays the cut could not carry, said once each


def _gather(src, dst, rows):
    """`src`'s arrays, the `rows` (indices or a mask) of each, into `dst`;
    the cut's scratch arrays left out, an array numpy cannot read (a bit
    array) left out and said once."""
    import numpy as np
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    for i in range(src.GetNumberOfArrays()):
        arr = src.GetArray(i)
        if arr is None or not arr.GetName() or arr.GetName() in _SCRATCH:
            continue
        try:
            values = vtk_to_numpy(arr)[rows]
        except Exception as exc:
            if arr.GetName() not in _NOT_CARRIED:
                _NOT_CARRIED.add(arr.GetName())
                print(f"[fespp] scene cut: array {arr.GetName()!r} not carried ({exc})", flush=True)
            continue
        v = numpy_to_vtk(np.ascontiguousarray(values), deep=1)
        v.SetName(arr.GetName())
        dst.AddArray(v)


def _polydata_of(ds, parts, owners):
    """The polydata of `parts` ([(setter, offsets, connectivity)] in `ds`'s
    point ids, `vtkPolyData.SetPolys` and the like) on the points they use
    only — the mapper uploads every point it is given, the grid's million
    would cost more than the faces, and the bounds are the cut's — each
    cell carrying the data of its `owners` cell; `ds`'s field data
    passed."""
    import numpy as np
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    used = np.zeros(ds.GetNumberOfPoints(), dtype=bool)
    for _setter, _off, conn in parts:
        used[conn] = True
    new_id = np.cumsum(used) - 1
    out = vtkPolyData()
    points = vtkPoints()
    points.SetData(numpy_to_vtk(np.ascontiguousarray(vtk_to_numpy(ds.GetPoints().GetData())[used]), deep=1))
    out.SetPoints(points)
    for setter, off, conn in parts:
        cells = vtkCellArray()
        cells.SetData(numpy_to_vtkIdTypeArray(np.ascontiguousarray(off, dtype=np.int64), deep=1),
                      numpy_to_vtkIdTypeArray(np.ascontiguousarray(new_id[conn], dtype=np.int64), deep=1))
        setter(out, cells)
    _gather(ds.GetPointData(), out.GetPointData(), used)
    _gather(ds.GetCellData(), out.GetCellData(), owners)
    out.GetFieldData().PassData(ds.GetFieldData())
    _drop_scratch(out)
    return out


def _faces_polydata(ds, quads, owners):
    """The polydata of `quads`, each carrying the cell values of its
    owner."""
    import numpy as np
    from vtkmodules.vtkCommonDataModel import vtkPolyData
    m = len(quads)
    return _polydata_of(ds, [(vtkPolyData.SetPolys, np.arange(0, 4 * m + 1, 4), np.ascontiguousarray(quads).ravel())],
                        owners)


def _kept_polydata(ds, keep):
    """A polydata's kept cells, in numpy (ParaView's Threshold costs 4 ms
    on a well of 4 600 segments, as much as the grid's faces): its four
    cell arrays filtered."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from vtkmodules.vtkCommonDataModel import vtkPolyData
    ids = np.flatnonzero(keep)
    parts, start = [], 0
    for ca, setter in ((ds.GetVerts(), vtkPolyData.SetVerts), (ds.GetLines(), vtkPolyData.SetLines),
                       (ds.GetPolys(), vtkPolyData.SetPolys), (ds.GetStrips(), vtkPolyData.SetStrips)):
        m = ca.GetNumberOfCells() if ca is not None else 0
        if not m:
            continue
        mine = ids[(ids >= start) & (ids < start + m)] - start
        start += m
        if not len(mine):
            continue
        off = vtk_to_numpy(ca.GetOffsetsArray()).astype(np.int64)
        conn = vtk_to_numpy(ca.GetConnectivityArray()).astype(np.int64)
        sizes = off[mine + 1] - off[mine]
        new_off = np.concatenate([[0], np.cumsum(sizes)])
        idx = np.repeat(off[mine] - new_off[:-1], sizes) + np.arange(new_off[-1])
        parts.append((setter, new_off, conn[idx]))
    return _polydata_of(ds, parts, ids)


def _kept_quads(ds, keep):
    """A 2D structured grid's (a horizon's) kept cells as the polydata of
    their quads, in numpy; None when the grid is not a sheet."""
    import numpy as np
    from vtkmodules.vtkCommonDataModel import vtkPolyData
    nx, ny, nz = _dims(ds)
    if nz != 1 or nx < 2 or ny < 2 or ds.GetNumberOfCells() != (nx - 1) * (ny - 1):
        return None
    ids = np.flatnonzero(keep)
    p = ids % (nx - 1) + nx * (ids // (nx - 1))
    quads = np.stack([p, p + 1, p + nx + 1, p + nx], axis=1)
    return _polydata_of(ds, [(vtkPolyData.SetPolys, np.arange(0, 4 * len(ids) + 1, 4), quads.ravel())], ids)


def _kept(ds, keep):
    """`ds`'s kept cells: a shallow copy when every cell is kept; a
    polydata's and a horizon's in numpy; a Threshold on the mark otherwise,
    this leaf alone."""
    import numpy as np
    from vtkmodules.util.numpy_support import numpy_to_vtk
    out = ds.NewInstance()
    out.ShallowCopy(ds)
    _drop_scratch(out)
    if keep.all():
        return out
    if ds.IsA("vtkPolyData"):
        return _kept_polydata(ds, keep)
    if ds.IsA("vtkStructuredGrid"):
        quads = _kept_quads(ds, keep)
        if quads is not None:
            return quads
    arr = numpy_to_vtk(keep.astype(np.uint8), deep=1)
    arr.SetName(KEEP)
    out.GetCellData().AddArray(arr)
    from vtkmodules.vtkCommonDataModel import vtkDataObject
    from vtkmodules.vtkFiltersCore import vtkThreshold
    t = vtkThreshold()
    t.SetInputData(out)
    t.SetInputArrayToProcess(0, 0, 0, vtkDataObject.FIELD_ASSOCIATION_CELLS, KEEP)
    t.SetThresholdFunction(vtkThreshold.THRESHOLD_BETWEEN)
    t.SetLowerThreshold(0.5)
    t.SetUpperThreshold(1.5)
    t.Update()
    kept = t.GetOutput().NewInstance()
    kept.ShallowCopy(t.GetOutput())
    kept.GetCellData().RemoveArray(KEEP)
    return kept


def _cut_leaf(ds, boxes):
    """`ds` cut to `boxes`: an IJK grid as the polydata of its exposed
    faces, any other leaf as its kept cells; `ds` itself when it carries no
    extents."""
    keep = mask_of(ds, boxes)
    if keep is None:
        return ds
    if _field(ds, FACE_META) is not None:
        quads, owners = _exposed_faces(ds, keep)
        return _faces_polydata(ds, quads, owners)
    return _kept(ds, keep)


# the last cut's cost, leaf by leaf: [(class, cells in, cells out, ms)], then
# ("total", leaves, 0, ms) — read by the visual harness
LAST_CUT_PROFILE = []


def cut_into(src, dst, boxes):
    """`dst` made `src` cut to `boxes` ([[x0, x1], [y0, y1], [z0, z1]]
    each) (FesppSceneCut)."""
    import time
    t0 = time.perf_counter()
    rows = []
    dst.ShallowCopy(src)
    if src.IsA("vtkCompositeDataSet"):
        for it, ds in _leaves(src):
            if ds.GetNumberOfCells():
                a = time.perf_counter()
                leaf = _cut_leaf(ds, boxes)
                dst.SetDataSet(it, leaf)
                rows.append((ds.GetClassName(), ds.GetNumberOfCells(), leaf.GetNumberOfCells(),
                             (time.perf_counter() - a) * 1000))
    elif src.IsA("vtkDataSet"):
        a = time.perf_counter()
        leaf = _as_class(_cut_leaf(src, boxes), dst.GetClassName())
        dst.ShallowCopy(leaf)
        rows.append((src.GetClassName(), src.GetNumberOfCells(), leaf.GetNumberOfCells(),
                     (time.perf_counter() - a) * 1000))
    rows.append(("total", len(rows), 0, (time.perf_counter() - t0) * 1000))
    LAST_CUT_PROFILE[:] = rows


# ---------------------------------------------------------------- the boxes
def holds_whole(box, bounds):
    """Whether `box` holds the whole scene of `bounds`."""
    for n, (lo, hi) in enumerate(box):
        b0, b1 = float(bounds[2 * n]), float(bounds[2 * n + 1])
        tol = _WHOLE * max(1.0, abs(b1 - b0), abs(b0), abs(b1))
        if float(lo) > b0 + tol or float(hi) < b1 - tol:
            return False
    return True


def cutting_boxes(boxes, bounds):
    """The boxes that cut the scene of `bounds`: [] when there is none or
    when one holds the whole scene (the union then holds everything)."""
    boxes = [[[float(lo), float(hi)] for lo, hi in b] for b in boxes or ()]
    return [] if not boxes or any(holds_whole(b, bounds) for b in boxes) else boxes


# ---------------------------------------------------------------- the pipeline
_FILTERS = []    # the plugin loaded, once per process


def _load_filters():
    """FesppScenePrep and FesppSceneCut, as paraview.simple constructors."""
    from paraview import simple as pvsimple
    if not _FILTERS:
        pvsimple.LoadPlugin(os.path.join(os.path.dirname(__file__), "scene_cut_filters.py"),
                            ns={})
        _FILTERS.append(True)
    return pvsimple.FesppScenePrep, pvsimple.FesppSceneCut


class SceneCrop:
    """The cut of one view's scene, on the shared source."""

    def __init__(self, view_id):
        self.view_id = str(view_id)
        self._base = None       # the source the stages chain on
        # [FesppScenePrep, FesppSceneCut] (+ a witness when traced)
        self._stages = []
        self._boxes = []        # the boxes cutting the scene ([] = whole)
        self._stale = []        # stage lists left for drop_stale
        self._serial = 0

    @property
    def boxes(self):
        """The boxes cutting the scene, [] when it is whole."""
        return self._boxes

    @property
    def prep(self):
        """The preparation stage (`prep_into`): every cell with its extent,
        what is read of the cut (`mask_of`); None when no stage is made."""
        return self._stages[0] if self._stages else None

    def _name(self, what):
        self._serial += 1
        return f"scenecut_{self.view_id}_{what}{self._serial}"

    def _ensure_stages(self, base):
        """The stages on `base`; True when they were made again. Nothing is
        brought up to date here: a render pulls the stages."""
        if self._base is base and self._stages:
            return False
        from paraview import simple as pvsimple
        prep_filter, cut_filter = _load_filters()
        if self._stages:
            self._stale.append(list(self._stages))
        prep = prep_filter(registrationName=self._name("prep"), Input=base)
        cut = cut_filter(registrationName=self._name("cut"), Input=prep)
        cut.Boxes = json.dumps(self._boxes or [])
        stages = [prep, cut]
        if os.environ.get("FESPP_SCENE_CUT_TRACE"):
            # a scenario chasing a crash: a witness after the cut
            stages.append(pvsimple.FesppSceneTrace(registrationName=self._name("trace"), Input=cut))
        self._stages, self._base = stages, base
        return True

    def set_boxes(self, base, boxes, bounds, selectors=()):
        """The cut is `boxes` ([[x0, x1], [y0, y1], [z0, z1]] each, the
        scene's coordinates) on `base`, a scene of `bounds` (`selectors`,
        the blocks the view draws, are the representation's business). True
        when what the view draws changed — the scene cut or whole again, the
        stages made again (the representations must move to `tips()`, then
        `drop_stale()`); a step otherwise moves the cut only."""
        boxes = cutting_boxes(boxes, bounds)
        was = bool(self._boxes)
        self._boxes = boxes
        if not boxes:
            return was
        rebuilt = self._ensure_stages(base)
        text = json.dumps(boxes)
        if self._stages[1].Boxes != text:
            self._stages[1].Boxes = text
        return rebuilt or not was

    def tips(self, base=None, selectors=None):
        """What the view draws: the cut, [] when the scene is whole — on
        `base` again when the shared source changed (a connection, another
        file)."""
        if not self._boxes:
            return []
        if base is not None and base is not self._base:
            self._ensure_stages(base)
        return [self._stages[-1]] if self._stages else []

    def tip_ids(self):
        """The global ids of the tips (picking recognises them)."""
        out = set()
        for tip in self.tips():
            try:
                out.add(tip.SMProxy.GetGlobalIDAsString())
            except Exception as exc:
                print(f"[fespp] scene cut ({self.view_id}): a piece without id ({exc})", flush=True)
        return out

    def source_flat(self, flat, source_index=None):
        """The source's flat index of the cut's leaf `flat`: the same — the
        cut keeps the source's structure."""
        return flat

    def drop_stale(self):
        """Delete what the representations have left, downstream first."""
        from paraview import simple as pvsimple
        stale, self._stale = self._stale, []
        for stages in stale:
            for proxy in reversed(stages):
                try:
                    pvsimple.Delete(proxy)
                except Exception as exc:
                    print(f"[fespp] scene cut ({self.view_id}): a stage not deleted ({exc})", flush=True)

    def release(self):
        """Every proxy deleted (the cut is gone, the view closed): the
        representations must have left them."""
        self._boxes = []
        if self._stages:
            self._stale.append(list(self._stages))
        self._stages, self._base = [], None
        self.drop_stale()
