"""Shared helpers for the BlockScope Probe Day scripts (TARGET_ARCHITECTURE §5).

Each probe copies this file next to itself in the container (or the runner
`docker cp`s both) and does `from _probe_common import *`. Everything here is
plain pvpython — no app imports, no trame.

Run pattern (container `fespp_leaftest`):
    docker cp tools/probes/_probe_common.py fespp_leaftest:/tmp/
    docker cp tools/probes/pN_xxx.py       fespp_leaftest:/tmp/
    docker exec fespp_leaftest /opt/paraview/bin/pvpython \
        --force-offscreen-rendering /tmp/pN_xxx.py
"""
import sys
import time

from paraview import simple as pvs
from paraview import servermanager as sm

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS - " if cond else "FAIL - ") + name
          + ((" :: " + detail) if detail else ""), flush=True)


def doc(msg):
    """Non-gating observation, printed for the PARAVIEW.md write-up."""
    print("DOC  - " + msg, flush=True)


def finish():
    bad = [n for n, ok in RESULTS if not ok]
    print("PROBE VERDICT: " + ("PASS" if not bad else "FAIL: " + "; ".join(bad)),
          flush=True)


def new_view():
    v = pvs.GetActiveViewOrCreate('RenderView')
    v.ViewSize = [400, 400]
    try:
        v.BackgroundColorMode = 'Single Color'
    except Exception:
        pass
    v.UseColorPaletteForBackground = 0
    v.Background = [0.0, 0.0, 0.0]
    v.OrientationAxesVisibility = 0
    return v


def make_esg_producer(origin=(1.0, -1.5, -1.5), n=3, name='EsgSrc'):
    """A real vtkExplicitStructuredGrid (n^3 hexes) behind a PVTrivialProducer,
    with a point 'Elevation' array in [0,1] (normalized z)."""
    from vtkmodules.vtkCommonDataModel import vtkExplicitStructuredGrid, vtkCellArray
    from vtkmodules.vtkCommonCore import vtkPoints, vtkFloatArray
    ni = nj = nk = n
    pts = vtkPoints()

    def pid(i, j, k):
        return (k * (nj + 1) + j) * (ni + 1) + i

    for k in range(nk + 1):
        for j in range(nj + 1):
            for i in range(ni + 1):
                pts.InsertNextPoint(origin[0] + i, origin[1] + j, origin[2] + k)
    ca = vtkCellArray()
    corners = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
               (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))
    for k in range(nk):
        for j in range(nj):
            for i in range(ni):
                ca.InsertNextCell(8)
                for di, dj, dk in corners:
                    ca.InsertCellPoint(pid(i + di, j + dj, k + dk))
    esg = vtkExplicitStructuredGrid()
    esg.SetDimensions(ni + 1, nj + 1, nk + 1)
    esg.SetPoints(pts)
    esg.SetCells(ca)
    esg.ComputeFacesConnectivityFlagsArray()
    arr = vtkFloatArray()
    arr.SetName('Elevation')
    for idx in range(pts.GetNumberOfPoints()):
        arr.InsertNextValue((pts.GetPoint(idx)[2] - origin[2]) / max(nk, 1))
    esg.GetPointData().SetScalars(arr)
    prod = pvs.PVTrivialProducer(registrationName=name)
    prod.GetClientSideObject().SetOutput(esg)
    prod.UpdatePipeline()
    return prod


def make_sphere(name='SphereElev', center=(-2.5, 0.0, 0.0), radius=1.2):
    """Sphere + Elevation so the block carries the same 'Elevation' point array
    (range [0,1] along y) as the ESG block."""
    sph = pvs.Sphere(registrationName=name + 'Raw')
    sph.Center = list(center)
    sph.Radius = radius
    sph.ThetaResolution = 32
    sph.PhiResolution = 32
    el = pvs.Elevation(registrationName=name, Input=sph)
    el.LowPoint = [center[0], center[1] - radius, center[2]]
    el.HighPoint = [center[0], center[1] + radius, center[2]]
    el.UpdatePipeline()
    return el


def make_group(inputs, name='Grp'):
    grp = pvs.GroupDatasets(registrationName=name, Input=list(inputs))
    try:
        grp.OutputType = 'vtkPartitionedDataSetCollection'
    except Exception:
        pass
    grp.UpdatePipeline()
    return grp


def solid_white(rep):
    rep.Representation = 'Surface'
    rep.ColorArrayName = ['POINTS', '']
    rep.DiffuseColor = [1.0, 1.0, 1.0]
    rep.UpdateVTKObjects()


def top_selectors(src):
    asm = src.GetDataInformation().GetHierarchy()
    return [asm.GetNodePath(asm.GetChild(0, i))
            for i in range(asm.GetNumberOfChildren(0))]


def hierarchy_xml(src):
    from vtkmodules.vtkCommonCore import vtkIndent
    return src.GetDataInformation().GetHierarchy().SerializeToXML(vtkIndent())


def const_lut(rgb, name):
    """A 1-point (constant colour) PVLookupTable — the solid-colour fallback."""
    lut = sm._getPyProxy(sm.ProxyManager().NewProxy('lookup_tables', 'PVLookupTable'))
    lut.RGBPoints = [0.0] + list(rgb) + [1.0] + list(rgb)
    lut.ColorSpace = 'RGB'
    try:
        sm.Register(lut, registrationName=name)
    except Exception:
        pass
    lut.UpdateVTKObjects()
    return lut


_SHOT = [0]


def shot(view, tag=""):
    """Render + screenshot + return the image as an int numpy array
    (row 0 = BOTTOM of the render window, same origin as selection regions)."""
    from vtkmodules.vtkIOImage import vtkPNGReader
    from vtkmodules.util.numpy_support import vtk_to_numpy
    pvs.Render(view)
    _SHOT[0] += 1
    path = '/tmp/probe_shot_%02d%s.png' % (_SHOT[0], ('_' + tag) if tag else '')
    pvs.SaveScreenshot(path, view, ImageResolution=[400, 400])
    r = vtkPNGReader()
    r.SetFileName(path)
    r.Update()
    img = r.GetOutput()
    dx, dy = img.GetDimensions()[0], img.GetDimensions()[1]
    a = vtk_to_numpy(img.GetPointData().GetScalars()).reshape(dy, dx, -1)
    return a.astype(int)


def nred(a):
    return int(((a[..., 0] > 60) & (a[..., 0] > 1.7 * (a[..., 1] + 1))
                & (a[..., 0] > 1.7 * (a[..., 2] + 1))).sum())


def ngreen(a):
    return int(((a[..., 1] > 60) & (a[..., 1] > 1.7 * (a[..., 0] + 1))
                & (a[..., 1] > 1.7 * (a[..., 2] + 1))).sum())


def nblue(a, floor=60):
    return int(((a[..., 2] > floor) & (a[..., 2] > 1.7 * (a[..., 0] + 1))
                & (a[..., 2] > 1.7 * (a[..., 1] + 1))).sum())


def nlit(a):
    return int(((a[..., 0] + a[..., 1] + a[..., 2]) > 45).sum())


def rss_mb():
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return -1.0
