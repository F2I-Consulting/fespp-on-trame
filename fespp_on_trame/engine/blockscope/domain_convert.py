"""The scene's domain conversion stage — an object of the other vertical
domain drawn in a view with the velocity model (the PO, 30/10: a property
in time, ticked in a depth view, is either seen in the time view or
converted for display; no third "converted" view).

One stage per view between the shared source and the cut
(`FesppDomainConvert`, scene_cut_filters): the blocks named by their flat
indices get their points' z converted by the velocity model (engine/velocity_model:
the one law as a 1 × 1 cube, or the velocity model built from placed columns),
everything else is the source's own data (a shallow copy). The stage runs
in the server's own process, so the velocity model is handed to it by its key in
`CUBES` (app/features/time_depth_law registers the active model's cube),
never serialised. The data's sign is kept: in these files a depth below
the zero is a negative z, and so is a two-way time. The structure is the
source's (same blocks, same flat indices), so the cut, the picking and
the block properties see nothing new.
"""
import json

from fespp_on_trame.engine.blockscope import scene_crop

DEPTH, TIME = "depth", "time"

CUBES = {}      # key -> engine.velocity_model.Cube: the active model's


def register_cube(key, cube):
    """The velocity model the stages read from now on (the active one: the
    previous one is forgotten here); `cube` None forgets it."""
    CUBES.clear()
    if cube is not None and key:
        CUBES[key] = cube


# points converted at a time: the float64 temporaries of a large object's
# points all at once are gigabytes
CHUNK = 1 << 21


def convert_points(ds, cube, to):
    """A shallow copy of `ds` whose points' z are converted `to` DEPTH or
    TIME by `cube`; `ds` itself when it has no points or no velocity model.
    The new points keep the source's precision, written in place."""
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkPoints
    pts = ds.GetPoints() if hasattr(ds, "GetPoints") else None
    if pts is None or pts.GetNumberOfPoints() == 0 or cube is None:
        return ds
    n = pts.GetNumberOfPoints()
    new = vtkPoints()
    new.SetDataType(pts.GetDataType())
    new.SetNumberOfPoints(n)
    xyz = vtk_to_numpy(new.GetData())
    xyz[:] = vtk_to_numpy(pts.GetData())
    for a in range(0, n, CHUNK):
        part = xyz[a:a + CHUNK]
        part[:, 2] = cube.convert(part, to)
    new.Modified()
    out = ds.NewInstance()
    out.ShallowCopy(ds)
    out.SetPoints(new)
    return out


def convert_into(src, dst, flats, cube_key, to):
    """`dst` made `src` with the leaves of flat indices `flats` converted
    by the velocity model `cube_key` names (FesppDomainConvert); a lone dataset is
    converted whole; an unknown key converts nothing (said once)."""
    dst.ShallowCopy(src)
    cube = CUBES.get(cube_key) if cube_key else None
    if cube is None:
        if cube_key:
            print(f"[fespp] domain conversion: no velocity model under {cube_key!r}, nothing converted", flush=True)
        return
    if src.IsA("vtkCompositeDataSet"):
        wanted = set(int(f) for f in flats or ())
        for it, ds in scene_crop._leaves(src):
            if it.GetCurrentFlatIndex() in wanted:
                dst.SetDataSet(it, convert_points(ds, cube, to))
    elif src.IsA("vtkDataSet"):
        dst.ShallowCopy(convert_points(src, cube, to))


def _load_filter():
    from paraview import simple as pvsimple
    scene_crop._load_filters()      # the plugin holding every scene stage
    return pvsimple.FesppDomainConvert


class DomainConvert:
    """The conversion stage of one view's scene, on the shared source."""

    def __init__(self, view_id):
        self.view_id = str(view_id)
        self._base = None
        self._stage = None
        self._stale = []
        self._serial = 0

    def tip(self, base, flats, cube_key, to):
        """The stage on `base`, converting `flats` by the velocity model `cube_key`
        to `to`: what the cut and the representation draw. Made again on
        a new base (`drop_stale` deletes the old one once nothing draws
        it)."""
        if self._stage is None or self._base is not base:
            if self._stage is not None:
                self._stale.append(self._stage)
            self._serial += 1
            self._stage = _load_filter()(registrationName=f"domconv_{self.view_id}_{self._serial}", Input=base)
            self._base = base
        stage = self._stage
        for name, value in (("Flats", json.dumps(sorted(int(f) for f in flats))),
                            ("Cube", str(cube_key or "")),
                            ("To", to)):
            if getattr(stage, name) != value:
                setattr(stage, name, value)
        return stage

    def drop_stale(self):
        from paraview import simple as pvsimple
        stale, self._stale = self._stale, []
        for proxy in stale:
            try:
                pvsimple.Delete(proxy)
            except Exception as exc:
                print(f"[fespp] domain conversion ({self.view_id}): a stage not deleted ({exc})", flush=True)

    def park(self):
        """The stage set aside (nothing converted any more): deleted by
        `drop_stale` once the representation has left it."""
        if self._stage is not None:
            self._stale.append(self._stage)
        self._stage, self._base = None, None

    def release(self):
        self.park()
        self.drop_stale()
