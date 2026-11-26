"""Image check — what a freshly built image really contains.

Run after a ParaView bump or a Dockerfile change, inside the image:

    docker run --rm --entrypoint /opt/paraview/bin/pvpython \
        -v "<repo>/tools/probes:/pp:ro" fespp_on_trame:<tag> /pp/p9_image_check.py

It prints the ParaView / VTK / Python versions, the SMP backend COMPILED as
default (read before the app switches it at startup), the plugins shipped,
whether FESPP loads from the stable path /work/ttl/install-fespp/lib/paraview,
and whether ParaView's own classes serialize (vtkObjectManager on a render
view) — the prerequisite of trame-vtklocal (VtkLocalView). On the 6.0.1 image
(2026-09-24): SMP Sequential, serialization failing on vtkPVLODActor and the
other vtkPV* classes.
"""
import json
import os
import sys

from paraview import simple as s
import vtk
from vtkmodules.vtkCommonCore import vtkSMPTools

print("VTK", vtk.vtkVersion.GetVTKVersion(), "| Python", sys.version.split()[0])
try:
    from paraview import servermanager as sm
    print("ParaView", sm.vtkSMProxyManager.GetParaViewSourceVersion())
except Exception as exc:
    print("ParaView version unreadable:", exc)
print("SMP backend (compiled default, before any switch):", vtkSMPTools.GetBackend(),
      "threads", vtkSMPTools.GetEstimatedNumberOfThreads())

plug = "/work/ttl/install-fespp/lib/paraview/plugins/Fespp/Fespp.so"
print("stable plugin path exists:", os.path.exists(plug), "->", os.path.realpath(plug))
if not os.path.exists(plug):
    plug = sorted(__import__("glob").glob("/work/ttl/install-fespp/lib/paraview-*/plugins/Fespp/Fespp.so"))[0]
s.LoadPlugin(plug)
import glob
esg = sorted(glob.glob("/opt/paraview/lib/paraview-*/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.so"))
print("ExplicitStructuredGrid plugin:", esg)
if esg:
    s.LoadPlugin(esg[0])
print("plugins shipped:", sorted(os.listdir(os.path.dirname(os.path.dirname(esg[0])))) if esg else "?")
col = s.EPCCollector()
print("EPCCollector proxy:", col.GetXMLName())
w = s.Wavelet()
crop = None
try:
    crop = s.ExplicitStructuredGridCrop(Input=s.ExplicitStructuredGridGeneratorSource() if hasattr(s, "ExplicitStructuredGridGeneratorSource") else w)
    print("ExplicitStructuredGridCrop proxy:", crop.GetXMLName())
except Exception as exc:
    print("ExplicitStructuredGridCrop:", exc)

# serialization of a ParaView render view (trame-vtklocal's prerequisite)
from vtkmodules.vtkSerializationManager import vtkObjectManager
v = s.CreateRenderView()
v.ViewSize = [400, 300]
c = s.Contour(Input=w, ContourBy=["POINTS", "RTData"], Isosurfaces=[150])
d = s.Show(c, v)
s.ColorBy(d, ("POINTS", "RTData"))
s.Render(v)
rw = v.GetClientSideObject().GetRenderWindow()
m = vtkObjectManager()
m.Initialize()
rid = m.RegisterObject(rw)
m.UpdateStatesFromObjects()
ids = m.GetAllDependencies(rid)
classes = {}
for i in ids:
    try:
        cn = json.loads(m.GetState(i)).get("ClassName", "?")
    except Exception:
        cn = "?"
    classes[cn] = classes.get(cn, 0) + 1
pv = {k: v for k, v in classes.items() if k.startswith("vtkPV")}
print(f"serialization: {len(ids)} objects; ParaView classes serialized: {pv}")
print("  vtkPVLODActor serialized:", "vtkPVLODActor" in classes,
      "| blobs:", len(m.GetBlobHashes(ids)))
