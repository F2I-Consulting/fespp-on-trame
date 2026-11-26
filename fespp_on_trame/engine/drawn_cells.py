"""What a 3D view draws of a grid, cell by cell: what the view's row reads.

The row of a 3D view in the Statistics view, and the histograms opened from it,
read a property on the cells the view draws and count each of them once.

* An isolate (engine/sources/ijkgrid) draws each visible cut or volume, or the
  tips of its threshold chain on it. Two cuts share the cells where they cross,
  two branches of a union the cells both keep. A crop writes which cell of the
  grid each of its cells is (`vtkOriginalCellIds`) and a threshold passes it on;
  a threshold on the grid itself has no such array, so the cells of a tip there
  come from the ranges of its branch, checked against what it holds.
* A cut scene (engine/blockscope/scene_crop) draws an IJK grid as its exposed
  faces, the cells inside it not at all. The read stops at the cut's preparation,
  which holds every cell with its extent, and keeps the cells a box meets:
  whether an isolate or the view's composite draws the grid.

`Drawn` is one thing drawn. One display with no scene cut is a plain read; anything
else goes through numpy here: AppendDatasets counts a shared cell twice and, on two
explicit structured grids, corrupts the heap.
"""
from typing import NamedTuple

from paraview import simple as pvsimple

from fespp_on_trame.engine import nan_mask
from fespp_on_trame.engine import property_values
from fespp_on_trame.engine import source_resolver
from fespp_on_trame.engine.blockscope import assembly_index
from fespp_on_trame.engine.blockscope.scene_crop import ORIGINAL_IDS, mask_of

_LAST_ERROR = {"msg": ""}

_NOTHING = "the view draws nothing of it"
_NOT_CARRIED = "what the view draws does not carry it"
_ON_NODES = "a property on the nodes cannot be read on several cuts or on a cut scene"
_NOT_TOLD_APART = "the cells its thresholds keep could not be told apart"


class Drawn(NamedTuple):
    """One thing a 3D view draws of a grid."""
    proxy: object           # what holds its cells
    boxes: object = ()      # the scene's boxes that cut them
    flats: tuple = ()       # the grid's leaves, when `proxy` holds a whole scene
    branch: object = ()     # a threshold on the grid itself: the ranges it keeps
    root: object = None     # ... and the grid they are read on


def last_error():
    """Why the last read returned None."""
    return _LAST_ERROR["msg"]


def forget_error():
    _LAST_ERROR["msg"] = ""


def of_isolate(iso, pv_view):
    """What a view's isolate draws in it: a display is shown or it is not, and
    a proxy the scene cuts is shown through its cut."""
    out = []
    root = iso.render_root()
    for proxy in source_resolver.ijk_rendered_sources(iso):
        cut = iso.scene_cut_of(proxy)
        try:
            disp = pvsimple.GetDisplayProperties(cut.tips()[0] if cut else proxy, view=pv_view)
            shown = disp is not None and int(getattr(disp, "Visibility", 0) or 0)
        except Exception as exc:
            print(f"[fespp] what a view draws ({iso.rep_path!r}): {exc}", flush=True)
            continue
        if shown:
            out.append(Drawn(cut.prep if cut else proxy, cut.boxes if cut else (), (),
                             iso.root_branch(proxy), root))
    return out


def of_scene(scene, rep_path, assembly_index):
    """What a cut scene draws of a grid its composite draws: nothing when it is
    whole, when the grid's eye is closed or when something else draws it."""
    crop = getattr(scene, "crop", None)
    if (crop is None or not crop.boxes or crop.prep is None or assembly_index is None
            or rep_path in scene.isolated or rep_path not in scene.shown_selectors()):
        return []
    flats = tuple(assembly_index.flat_indices(rep_path, subtree=False))
    return [Drawn(crop.prep, crop.boxes, flats)] if flats else []


def scene_boxes(scene):
    """The boxes that cut the whole scene of a 3D view, [] when it is whole."""
    crop = getattr(scene, "crop", None)
    return crop.boxes if crop is not None else []


def is_plain(drawn):
    """One display, as it is: the values of its output are the cells drawn."""
    return len(drawn) == 1 and not drawn[0].boxes and not drawn[0].flats


def _datasets(part):
    part.proxy.UpdatePipeline()
    data = part.proxy.GetClientSideObject().GetOutputDataObject(0)
    if part.flats:
        return [ds for f, ds in assembly_index.leaves(data)
                if f in part.flats and ds.IsA("vtkDataSet")]
    inner = assembly_index.inner(data)
    return [inner] if inner is not None else []


def _branch_cells(part):
    """The cells of the grid a branch of thresholds keeps, as a threshold does:
    each in every range, a hidden cell never; None when a range is not on a cell
    array."""
    np, vtk_to_numpy = property_values._numpy()
    part.root.UpdatePipeline()
    grid = assembly_index.inner(part.root.GetClientSideObject().GetOutputDataObject(0))
    cells = grid.GetCellData()
    keep = np.ones(grid.GetNumberOfCells(), dtype=bool)
    ghost = cells.GetArray(nan_mask.GHOSTS)
    if ghost is not None:
        keep &= vtk_to_numpy(ghost).ravel() == 0
    for array, assoc, low, high in part.branch:
        arr = cells.GetArray(array) if assoc == "CELLS" else None
        if arr is None:
            return None
        # in doubles, as a threshold compares: a float array's own precision
        # would round the bounds
        values = vtk_to_numpy(arr).astype(float)
        values = values[:, 0] if values.ndim > 1 else values
        keep &= (values >= low) & (values <= high)
    return np.flatnonzero(keep)


def _grid_ids(part, ds, count):
    """Which cell of the grid each of the `count` cells of `ds` is: what they
    carry (a crop's cells, and what a threshold keeps of them), else their own
    index, into the grid or, on a threshold on the grid itself, into what its
    branch keeps; None when that cannot be said."""
    np, vtk_to_numpy = property_values._numpy()
    carried = ds.GetCellData().GetArray(ORIGINAL_IDS)
    own = vtk_to_numpy(carried).astype(np.int64) if carried is not None else np.arange(count)
    if not part.branch:
        return own
    kept = _branch_cells(part)
    return kept[own] if kept is not None and kept.size == count else None


def _cells_of(part, name, component, with_ids):
    """`(values, grid cell ids or None)` of what one drawn thing holds, the ids
    when asked; None with the reason in `last_error()`."""
    np, _vtk_to_numpy = property_values._numpy()
    values, ids = [], []
    for ds in _datasets(part):
        cells = ds.GetCellData()
        arr = cells.GetArray(name)
        if arr is None:
            _LAST_ERROR["msg"] = _ON_NODES if ds.GetPointData().GetArray(name) is not None else _NOT_CARRIED
            return None
        vals = property_values.values_of(arr, cells.GetArray(nan_mask.GHOSTS), component)
        own = _grid_ids(part, ds, vals.size) if with_ids else np.arange(vals.size)
        if own is None:
            _LAST_ERROR["msg"] = _NOT_TOLD_APART
            return None
        keep = mask_of(ds, part.boxes) if part.boxes else None
        values.append(vals if keep is None else vals[keep])
        ids.append(own if keep is None else own[keep])
    if not values:
        _LAST_ERROR["msg"] = _NOT_CARRIED
        return None
    return np.concatenate(values), np.concatenate(ids)


def values(drawn, name, component):
    """1-D float64 of the array `name` on what a view draws, one value per cell
    however many of its displays hold the cell, NaN on a blanked one; None with
    the reason in `last_error()`."""
    _LAST_ERROR["msg"] = ""
    if not drawn:
        _LAST_ERROR["msg"] = _NOTHING
        return None
    if is_plain(drawn):
        vals = property_values.named_values(drawn[0].proxy, name, component)
        if vals is None:
            _LAST_ERROR["msg"] = _NOT_CARRIED
        return vals
    np, _vtk_to_numpy = property_values._numpy()
    several = len(drawn) > 1
    try:
        read = [_cells_of(part, name, component, several) for part in drawn]
    except Exception as exc:
        print(f"[fespp] what a view draws of {name!r}: {exc}", flush=True)
        _LAST_ERROR["msg"] = str(exc)
        return None
    if any(r is None for r in read):
        return None
    vals = np.concatenate([r[0] for r in read])
    if not several:
        return vals
    _ids, first = np.unique(np.concatenate([r[1] for r in read]), return_index=True)
    return vals[first]
