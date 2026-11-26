"""A statistic on a PART of a grid: the rows of the Statistics view that read one.

A part is a sub-representation, a blocked wellbore or a selection extract of
the grid a property belongs to. Its eye in the view's tree adds one row under
each property of that grid: the property read on the part only
(engine/compare_rows).

Each part is mapped once onto its grid's cells (the grid cell each of its
cells lies in). Every property of the grid, a formula included, is then read
on the part by indexing the
grid's own values (`property_values.values_for`) and weights
(`cell_weights`): one seam, the alignment of the property's own row.

* an extract carries `vtkOriginalCellIds` (ExtractSelection): the map is
  read off it;
* the cells of a sub-representation or a blocked wellbore are copies of grid
  cells: each centre is located in the grid, once per (part, grid) until either
  changes, by the one vtkStaticCellLocator of that grid all its parts share.

A blocked wellbore counts one value per grid cell the hole crosses, as the
plugin draws it (a cell entered twice is one cell), and adds a mean weighted by
how long the hole stays in each (`LENGTH_ARRAY`).
"""
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.engine.blockscope import assembly_index

SUPPORT_KINDS = ("Sub", "SubRepresentation", "BlockedWellbore")
# the plugin's cell array on a blocked wellbore: the sum of the measured-depth
# intervals of each cell
LENGTH_ARRAY = "Interval length"
_KIND_LABELS = {"Sub": "Sub-representation", "SubRepresentation": "Sub-representation",
                "BlockedWellbore": "Blocked wellbore"}

_CACHE = {}          # (part path, grid rep path) -> (stamp, cell map, lengths)
_LOCATORS = {}       # grid rep path -> (stamp of the grid, its cell locator)
_LAST_ERROR = {"msg": ""}


def last_error():
    return _LAST_ERROR["msg"]


def _ctx():
    from trame.app import get_server
    return get_server().context


def _numpy():
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    return np, vtk_to_numpy


def extract_entry(path):
    """The selection extract a `session://<view>/<id>` path names, or None."""
    sel = getattr(_ctx(), "selection", None)
    for entries in (getattr(sel, "extracts", None) or {}).values():
        for e in entries or []:
            if e.get("path") == path:
                return e
    return None


def is_extract(path):
    """A selection extract: a part the session made, not one of the file."""
    return str(path).startswith("session://")


def session_extracts():
    """The path of every 3D view's selection extract."""
    sel = getattr(_ctx(), "selection", None)
    return [e["path"] for entries in (getattr(sel, "extracts", None) or {}).values()
            for e in entries or [] if e.get("path")]


def is_support(tree, path):
    """A part of a grid the Statistics view can read a property on."""
    if not path:
        return False
    if is_extract(path):
        return extract_entry(path) is not None
    nid = tree.find_node_id(path)
    return nid is not None and (tree.find_type(nid) or "") in SUPPORT_KINDS


def kind_label(tree, path):
    if is_extract(path):
        return "Extract"
    nid = tree.find_node_id(path)
    return _KIND_LABELS.get(tree.find_type(nid) or "", "Part") if nid is not None else "Part"


def _container_of(tree, path):
    nid = tree.find_node_id(path) if path else None
    if nid is None:
        return None
    if (tree.find_type(nid) or "") == "GridContainer":
        return nid
    return tree.find_parent_node_id_with_type(nid, "GridContainer")


def grid_rep_of(tree, path):
    """The grid representation a part belongs to: an extract's own, else
    None (a sub-representation or a blocked wellbore is matched to a
    property by their common GridContainer, see `belongs_to`)."""
    if is_extract(path):
        e = extract_entry(path)
        return e.get("rep_path") if e else None
    return None


def belongs_to(tree, part, rep_path):
    """Is `part` a part of the grid `rep_path` (a property's representation)?"""
    if is_extract(part):
        own = grid_rep_of(tree, part)
        if not own:
            return False
        if own == rep_path:
            return True
        a, b = _container_of(tree, own), _container_of(tree, rep_path)
        return a is not None and a == b
    a, b = _container_of(tree, part), _container_of(tree, rep_path)
    return a is not None and a == b


def assembly_parts(tree):
    """Every part of a grid the FILE holds, read or not: its sub-representations
    and blocked wellbores, one walk of the assembly (`Tree.iter_nodes`). A
    partial stub (a reference whose target is elsewhere) has nothing behind it
    and is left out."""
    out = []
    if tree is None:
        return out
    for nid, _children in tree.iter_nodes():
        try:
            if ((tree.find_type(nid) or "") not in SUPPORT_KINDS
                    or (tree.find_title(nid) or "").startswith(node_kinds.PARTIAL_PREFIX)):
                continue
            path = tree.find_path(nid) or ""
        except Exception as exc:
            print(f"[fespp] the parts of a grid: node {nid} not read ({exc})", flush=True)
            continue
        if path:
            out.append(path)
    return out


def parts_of(tree, rep_path, loaded):
    """The parts of the grid `rep_path` a property can be read on: its
    sub-representations and blocked wellbores among `loaded` (the
    representations ticked in the tree), then every view's extracts of it."""
    out = [p for p in loaded or () if not is_extract(p)
           and is_support(tree, p) and belongs_to(tree, p, rep_path)]
    sel = getattr(_ctx(), "selection", None)
    for entries in (getattr(sel, "extracts", None) or {}).values():
        for e in entries or []:
            p = e.get("path")
            if p and belongs_to(tree, p, rep_path):
                out.append(p)
    return out


def title_of(tree, path):
    if is_extract(path):
        e = extract_entry(path)
        if not e:
            return path
        mv = getattr(_ctx(), "multi_view", None)
        view = mv.title_of(e.get("vid")) if mv is not None and hasattr(mv, "title_of") else e.get("vid")
        return f"{e.get('title') or e.get('id')} — {view}"
    nid = tree.find_node_id(path)
    return (tree.find_title(nid) if nid is not None and hasattr(tree, "find_title") else None) \
        or path.rsplit("/", 1)[-1]


def part_label(tree, path):
    """What a part is called on a row: `Blocked wellbore · W1`."""
    return f"{kind_label(tree, path)} · {title_of(tree, path)}"


def leaf_titles(tree, parts):
    """{part: what its leaf is called in the view's tree}: its title, and its
    grid's when the parts span several grids: a well blocked on two gives two
    leaves of the same name."""
    grids = {p: _container_of(tree, p) for p in parts if not is_extract(p)}
    several = len(set(grids.values()) - {None}) > 1
    out = {}
    for part, grid in grids.items():
        title = title_of(tree, part)
        out[part] = f"{title} — {tree.find_title(grid)}" if several and grid is not None else title
    return out


# ----------------------------------------------------------------------------
# the part's datasets, the grid's dataset

def _leaves(obj):
    """The vtkDataSet leaves of a data object (composite or not)."""
    if obj is None:
        return []
    if obj.IsA("vtkCompositeDataSet"):
        out = []
        it = obj.NewIterator()
        it.UnRegister(None)
        it.InitTraversal()
        while not it.IsDoneWithTraversal():
            d = it.GetCurrentDataObject()
            if d is not None and d.IsA("vtkDataSet"):
                out.append(d)
            it.GoToNextItem()
        return out
    return [obj] if obj.IsA("vtkDataSet") else []


def _part_datasets(path):
    if is_extract(path):
        e = extract_entry(path)
        ex = e.get("ex") if e else None
        if ex is None:
            return []
        ex.UpdatePipeline()
        client = ex.GetClientSideObject()
        return _leaves(client.GetOutputDataObject(0) if client else None)
    idx = getattr(_ctx(), "assembly_index", None)
    # [(dataset, flat index)]: the datasets alone
    return [d for d, _flat in (idx.datasets(path) or [])] if idx is not None else []


def _grid_dataset(source_registry, rep_path):
    """The grid's dataset in the index space of `values_for` (the source the
    property's own row reads)."""
    src = source_registry.get(rep_path) if source_registry is not None else None
    if src is None:
        return None
    src.UpdatePipeline()
    client = src.GetClientSideObject()
    return assembly_index.inner(client.GetOutputDataObject(0) if client else None)


def _stamp(datasets):
    """A dataset is its C++ object: nothing keeps the Python wrapper of a read
    alive until the next one."""
    return tuple((d.GetAddressAsString(""), d.GetMTime(), d.GetNumberOfCells()) for d in datasets)


def part_stamp(part):
    """What a part's cells are now: a row read on another state is read again."""
    return _stamp(_part_datasets(part))


def clear_caches():
    _CACHE.clear()
    _LOCATORS.clear()


def keep_locators(reps):
    """A locator holds its grid's dataset: it goes when the grid leaves."""
    for rep in set(_LOCATORS) - set(reps):
        del _LOCATORS[rep]


# ----------------------------------------------------------------------------
# the map onto the grid's cells

def _locator_of(rep_path, grid, stamp):
    """The cell locator of the grid, built once per state of the grid."""
    hit = _LOCATORS.get(rep_path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator
    loc = vtkStaticCellLocator()
    loc.SetDataSet(grid)
    loc.BuildLocator()
    _LOCATORS[rep_path] = (stamp, loc)
    return loc


def _locate(np, loc, datasets):
    from vtkmodules.vtkFiltersCore import vtkCellCenters
    out = []
    for d in datasets:
        cc = vtkCellCenters()
        cc.SetInputData(d)
        cc.VertexCellsOff()
        cc.Update()
        pts = cc.GetOutput().GetPoints()
        n = pts.GetNumberOfPoints() if pts is not None else 0
        ids = np.full(n, -1, dtype=np.int64)
        for i in range(n):
            ids[i] = loc.FindCell(pts.GetPoint(i))
        out.append(ids)
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int64)


def _lengths(np, vtk_to_numpy, datasets):
    """How long the hole stays in each cell of a blocked wellbore, NaN on the
    cells of a plugin that does not say."""
    out = []
    for d in datasets:
        arr = d.GetCellData().GetArray(LENGTH_ARRAY)
        out.append(vtk_to_numpy(arr).astype(float) if arr is not None
                   else np.full(d.GetNumberOfCells(), np.nan))
    return np.concatenate(out) if out else np.zeros(0)


def cell_map(source_registry, part, rep_path, tree):
    """`(grid cell ids, interval lengths or None, grid cell count)` of the
    part — -1 where a cell lies in no grid cell — or None with the reason in
    `last_error()`."""
    _LAST_ERROR["msg"] = ""
    np, vtk_to_numpy = _numpy()
    datasets = _part_datasets(part)
    if not datasets:
        _LAST_ERROR["msg"] = "not loaded — tick it in the tree"
        return None
    grid = _grid_dataset(source_registry, rep_path)
    if grid is None or grid.GetNumberOfCells() == 0:
        _LAST_ERROR["msg"] = "its grid has no cells loaded"
        return None
    key = (part, rep_path)
    grid_stamp = _stamp([grid])
    stamp = (_stamp(datasets), grid_stamp)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    ids = None
    if is_extract(part):
        arrays = [d.GetCellData().GetArray("vtkOriginalCellIds") for d in datasets]
        if all(a is not None for a in arrays):
            ids = np.concatenate([vtk_to_numpy(a).astype(np.int64) for a in arrays])
    if ids is None:
        ids = _locate(np, _locator_of(rep_path, grid, grid_stamp), datasets)
    lengths = None
    nid = tree.find_node_id(part) if not is_extract(part) else None
    if nid is not None and (tree.find_type(nid) or "") == "BlockedWellbore":
        lengths = _lengths(np, vtk_to_numpy, datasets)
    ncell = int(grid.GetNumberOfCells())
    ids[(ids < 0) | (ids >= ncell)] = -1
    result = (ids, lengths, ncell)
    _CACHE[key] = (stamp, result)
    return result


def part_values(state, tree, source_registry, part, array_path, rep_path,
                real_idx=None, ts_idx=None, weights=None):
    """`{"values", "volume", "pore", "length", "missing"}` — the property
    read on the part, with its weights, every array one entry per cell (or
    interval) of the part, NaN where it lies in no grid cell — or None with
    the reason in `last_error()`."""
    from fespp_on_trame.engine import property_values
    m = cell_map(source_registry, part, rep_path, tree)
    if m is None:
        return None
    ids, lengths, ncell = m
    np, _v = _numpy()
    vals_all = property_values.values_for(state, tree, source_registry, array_path,
                                          rep_path, real_idx=real_idx, ts_idx=ts_idx)
    if vals_all is None:
        _LAST_ERROR["msg"] = property_values.last_error() or "its values could not be read"
        return None
    vals_all = np.asarray(vals_all, dtype=float).ravel()
    if vals_all.size != ncell:
        _LAST_ERROR["msg"] = "the property is not one value per cell of the grid"
        return None
    ok = ids >= 0

    def take(arr):
        if arr is None:
            return None
        arr = np.asarray(arr, dtype=float).ravel()
        if arr.size != ncell:
            return None
        out = np.full(ids.size, np.nan)
        out[ok] = arr[ids[ok]]
        return out

    weights = weights or {}
    blocked = lengths is not None
    return {
        "values": take(vals_all),
        # a blocked wellbore is weighted along the hole, not by the volume
        # of the cells it crosses
        "volume": None if blocked else take(weights.get("volume")),
        "pore": None if blocked else take(weights.get("pore")),
        "length": lengths,
        "missing": int((~ok).sum()),
    }
