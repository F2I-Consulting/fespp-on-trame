"""P6 — FESPP assembly granularity for wellbore MARKERS (real plugin + EPC).

Question (TARGET_ARCHITECTURE §5, concern 9): after loading a
WellboreMarkerFrame through the EPCCollector (ExplicitSelection=1 +
Selectors), does the rendered hierarchy expose ONE node PER MARKER (=>
per-marker eye via BlockSelectors is native) or one node per FRAME (=>
categorical-LUT fallback)?

Reality check: /tmp/test.epc (testingPackageCpp) has NO WellboreMarkerFrame.
The C++ source (ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx
~3041-3057) shows markers go through the MAPPER-SET path: loadVtkObject() ->
one partition PER MARKER, each AddDataSetIndex()'d to the per-marker assembly
node ("_" + marker uuid). That EXACT code path (same loop, same
AddDataSetIndex) also serves WellboreCompletion -> Perforation children,
which DO exist in test.epc — so this probe validates the per-sub-element
granularity live on Completion/Perfos + WellboreFrame and prints both the
rendered HIERARCHY and the FESPP custom DataAssembly verbatim.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_common import *  # noqa: F401,F403

FESPP = '/work/ttl/install-fespp/lib/paraview/plugins/Fespp/Fespp.so'
EPC = '/tmp/test.epc'

pvs.LoadPlugin(FESPP, remote=False, ns=globals())
src = EPCCollector(registrationName='EPCCollector')  # noqa: F821 (from plugin)

from paraview.servermanager import vtkSMPropertyHelper
vtkSMPropertyHelper(src.SMProxy, 'ExplicitSelection').Set(1)
src.SMProxy.UpdateVTKObjects()

src.SetPropertyWithName('Files', EPC)
src.UpdatePipelineInformation()

# --- the live assembly = the full EPC tree (what the app's Tree consumes) ----
cso = src.GetClientSideObject()
asm = None
for getter in ('GetLiveAssembly', 'GetAssembly'):
    if hasattr(cso, getter):
        try:
            asm = getattr(cso, getter)()
        except Exception:
            asm = None
    if asm is not None:
        break
if asm is None:
    out = cso.GetOutputDataObject(0)
    asm = out.GetDataAssembly() if hasattr(out, 'GetDataAssembly') else None
check("live assembly reachable after UpdatePipelineInformation", asm is not None)


def walk(a, nid=0, depth=0, out=None):
    out = [] if out is None else out
    out.append((nid, depth, a.GetNodePath(nid),
                a.GetAttributeOrDefault(nid, 'label', '')))
    for i in range(a.GetNumberOfChildren(nid)):
        walk(a, a.GetChild(nid, i), depth + 1, out)
    return out


nodes = walk(asm)
print("live assembly: %d nodes total" % len(nodes), flush=True)

marker_nodes = [n for n in nodes
                if 'marker' in n[2].lower() or 'marker' in n[3].lower()]
if marker_nodes:
    doc("EPC has real marker nodes — probing them directly")
    targets = marker_nodes
else:
    doc("EPC has NO WellboreMarkerFrame — probing the SAME C++ mapper-set/"
        "AddDataSetIndex path via Completion(+Perfos) and WellboreFrame "
        "(ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx ~3041)")
    targets = [n for n in nodes
               if n[3].startswith(('Completion_', 'Perfo_', 'Frame_',
                                   'Trajectory_'))]
check("granularity targets found in the live assembly", bool(targets),
      "%d nodes" % len(targets))
print("--- live-assembly target subtree ---", flush=True)
for nid, depth, path, label in targets:
    print("  " * depth + "%s  [label=%s]" % (path, label), flush=True)

# Select the targets + all their ancestor paths (FESPP wants the geometry
# ancestors loaded too).
sel_paths = []
for nid, depth, path, label in targets:
    if path not in sel_paths:
        sel_paths.append(path)
    parts = path.strip('/').split('/')
    for k in range(2, len(parts)):
        p = '/' + '/'.join(parts[:k])
        if p not in sel_paths:
            sel_paths.append(p)
print("Selectors (%d):" % len(sel_paths), flush=True)
for p in sel_paths:
    print("   ", p, flush=True)

src.SetPropertyWithName('Selectors', sel_paths)
src.UpdatePipeline()

di = src.GetDataInformation()
hier = di.GetHierarchy()
hnodes = walk(hier)
print("--- rendered HIERARCHY after load (%d nodes) ---" % len(hnodes),
      flush=True)
for nid, depth, path, label in hnodes:
    print("  " * depth + "%s  [label=%s]" % (path, label), flush=True)

dasm = di.GetDataAssembly() if hasattr(di, 'GetDataAssembly') else None
if dasm is not None:
    danodes = walk(dasm)
    print("--- rendered custom DataAssembly after load (%d nodes) ---"
          % len(danodes), flush=True)
    for nid, depth, path, label in danodes:
        ds = dasm.GetDataSetIndices(nid, False) if hasattr(
            dasm, 'GetDataSetIndices') else []
        print("  " * depth + "%s  [label=%s] datasets=%s"
              % (path, label, list(ds)), flush=True)
else:
    doc("rendered data information exposes NO custom DataAssembly")

# Verdict: per-sub-element granularity = each Perfo (marker analogue) is its
# own top-level hierarchy node (FESPP names partitions '<title>(<uuid>)').
perfo_hier = [n for n in hnodes if 'perfo' in n[2].lower()
              or 'perfo' in n[3].lower()]
frame_hier = [n for n in hnodes if 'frame' in n[2].lower()
              or 'frame' in n[3].lower()]
doc("rendered hierarchy: %d Perfo nodes, %d Frame nodes (of %d targets "
    "loaded)" % (len(perfo_hier), len(frame_hier), len(targets)))
check("per-sub-element granularity: each Perforation is its OWN hierarchy "
      "node (same C++ path as per-marker partitions)",
      len(perfo_hier) >= 2,
      "%d perfo hierarchy nodes" % len(perfo_hier))
doc("markers verdict (source-backed): PER-MARKER partitions attached to "
    "per-marker assembly nodes — BlockSelectors per marker is native; "
    "needs a live re-run on a marker EPC when one is available")

finish()
