"""Regression probe: the Globe must survive the wheel after a selection change.

WHAT IT GUARDS
--------------
A Python observer on the camera, while a Python ProgrammableFilter sits in the
RENDERED pipeline and that pipeline is dirty, segfaults the process on the
first mouse-wheel notch. `vtkPVInteractorStyle::OnMouseWheelForward` does the
dolly AND the render inside ONE interactor callback, so the filter's Python
script re-executes while the camera's ModifiedEvent re-enters the interpreter
through vtkPythonCommand. The interpreter state is corrupted; the process dies
with SIGSEGV, which reaches the browser as "Connection closed".

Isolated on 2026-09-05 — all four ingredients are necessary, none is
sufficient. Remove the observer, OR the ProgrammableFilter, OR the Selectors
re-commit, and it survives; a native filter in place of the Python one also
survives. The observer's BODY is irrelevant: an empty lambda crashes too.

A Globe view is the only view that has a Python filter in its rendered
pipeline (GeoSource re-projects to ECEF), so this probe is what stops anyone
adding a camera observer — or any other Python VTK observer reachable from an
interactor callback — back into that view.

EXIT 0 = safe. EXIT 139 (SIGSEGV) = the pattern is back.

RUN
---
    docker run --rm --entrypoint sh \
      -v <repo>/fespp_on_trame:/tmp/pkg/fespp_on_trame:ro \
      -v <repo>/data/private:/data:ro \
      -v <repo>/tools/probes:/scr:ro \
      fespp_on_trame:local -c \
      'tr -d "\r" < /scr/p8_globe_wheel_crash.py > /tmp/p8.py; \
       /opt/paraview/bin/pvpython --force-offscreen-rendering /tmp/p8.py; \
       echo EXIT=$?'

Point EPC_DIR at any directory holding EPCs with a grid and some wellbores.
"""
import faulthandler
import os
import sys
from builtins import max as _max      # paraview.simple shadows the builtin

_fault = open("/tmp/p8_fault.txt", "w")
faulthandler.enable(file=_fault, all_threads=True)

sys.path.insert(0, "/tmp/pkg")
sys.path.append("/deploy/server/venv/lib/python3.12/site-packages")

EPC_DIR = os.environ.get("EPC_DIR", "/data")
PLUGIN = ("/work/ttl/install-fespp/lib/paraview/plugins/Fespp/Fespp.so")

from paraview import simple as pvsimple  # noqa: E402

pvsimple.LoadPlugin(PLUGIN, ns={})

from fespp_on_trame.engine import geo  # noqa: E402
from fespp_on_trame.engine.blockscope.globe_scene import GlobeScene  # noqa: E402


def rss():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS"):
            return int(line.split()[1]) // 1024
    return 0


src = pvsimple.EPCCollector()
epcs = sorted(f for f in os.listdir(EPC_DIR) if f.endswith(".epc"))
for f in epcs:
    src.SetPropertyWithName("Files", os.path.join(EPC_DIR, f))
    src.UpdatePipelineInformation()
asm = src.GetClientSideObject().GetOutputDataObject(0).GetDataAssembly()

paths, kinds = [], {}


def walk(n):
    p = asm.GetNodePath(n)
    paths.append(p)
    kinds[p] = asm.GetAttributeOrDefault(n, "kind", "")
    for i in range(asm.GetNumberOfChildren(n)):
        walk(asm.GetChild(n, i))


walk(asm.GetRootNode())
grids = [p for p in paths if kinds[p] in ("IjkGrid", "UnstructuredGrid")]
wells = [p for p in paths if kinds[p] in ("Trajectory", "WellboreTrajectory")]
if not grids or not wells:
    print("SKIP: need at least one grid and one wellbore trajectory in", EPC_DIR)
    raise SystemExit(0)
props = [p for p in paths
         if kinds[p] == "ContinuousProperty"
         and p.startswith(grids[0].rsplit("/", 1)[0])][:1]

base = grids + props
src.SetPropertyWithName("Selectors", base)
src.UpdatePipeline()
cdi = src.GetDataInformation().GetCellDataInformation()
arrays = [cdi.GetArrayInformation(i).GetName()
          for i in range(cdi.GetNumberOfArrays())]

view = pvsimple.CreateRenderView()
view.ViewSize = [900, 700]
pvsimple.SetActiveView(view)


class _Active:
    def get_source(self):
        return src


class _Sched:
    def mark_dirty(self, *_a, **_k):
        pass

    def flush(self):
        pvsimple.Render(view)


scene = GlobeScene("p8", view, _Active(), _Sched(),
                   texture=geo.earth_texture_path("4k"))
scene.set_epsg(int(os.environ.get("EPSG", "23031")))
scene.set_visible_many(base)
if arrays:
    scene.set_color(grids[0], arrays[0], "CELLS")
scene.frame("earth")
# the heaviest imagery, because that is what the report came in with
scene.set_texture(geo.earth_texture_path("16k"))
labels = {s: ("G", True) for s in grids}
scene.set_marks(labels, set(base))
pvsimple.Render(view)
print("[SETUP] grid + property + 16k imagery on the Earth, RSS %d MB" % rss())

iren = view.GetInteractor()
win_w, win_h = view.GetRenderWindow().GetSize()

for rnd in range(4):
    # the user ticks wellbore trajectories: the collector re-commits its
    # Selectors, so the projection filter downstream is dirty
    n = 1 + rnd * 2
    src.SetPropertyWithName("Selectors", base + wells[:n])
    src.UpdatePipeline()
    for s in wells[:n]:
        labels[s] = ("W", False)
    scene.set_visible_many(base + wells[:n])
    scene.set_marks(labels, set(scene.visible_selectors()))
    pvsimple.Render(view)
    # ...and then uses the wheel. THIS is what used to die, on notch one.
    for i in range(20):
        iren.SetEventPosition(win_w // 2, win_h // 2)
        iren.MouseMoveEvent()
        if i < 12:
            iren.MouseWheelForwardEvent()
        else:
            iren.MouseWheelBackwardEvent()
    print("[ROUND %d] %d trajectories, 20 wheel notches, RSS %d MB"
          % (rnd, n, rss()))

print("[PASS] the Globe survived %d selection changes and %d wheel notches"
      % (4, 80))
