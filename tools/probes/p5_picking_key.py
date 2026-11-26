"""P5 — which field of a surface selection carries the BLOCK identity?

Question (TARGET_ARCHITECTURE §5 / R5): render a 3-block composite, run
vtkSMRenderViewProxy.SelectSurfaceCells on pixels known to belong to ONE
block, and inspect the returned selection sources — is the block identity an
assembly SELECTOR, a flat COMPOSITE_INDEX, or a hierarchy index? Prints the
selection-source proxy XML name + every property verbatim, plus the
hierarchy XML (with its cid attributes) so indices can be correlated.
Also probes the selectBlocks=True variant (block picking).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_common import *  # noqa: F401,F403
import numpy as np
from vtkmodules.vtkCommonCore import vtkCollection


def dump_sources(tag, srcs):
    n = srcs.GetNumberOfItems()
    print("%s: %d selection source(s)" % (tag, n), flush=True)
    infos = []
    for i in range(n):
        raw = srcs.GetItemAsObject(i)
        py = sm._getPyProxy(raw)
        xml = raw.GetXMLName()
        print("  source[%d] XMLName=%s class=%s" % (i, xml, raw.GetClassName()),
              flush=True)
        for p in sorted(py.ListProperties()):
            try:
                val = py.GetPropertyValue(p)
                try:
                    val = list(val)
                except Exception:
                    pass
            except Exception as exc:
                val = "<err %r>" % (exc,)
            print("    %s = %r" % (p, val), flush=True)
        infos.append((xml, py))
    return infos


view = new_view()
sph = make_sphere(center=(-4.0, 0.0, 0.0))          # left
cone = pvs.Cone(registrationName='ConeSrc')
cone.Center = [0.0, 0.0, 0.0]
cone.Radius = 1.2
cone.Height = 2.4
esg = make_esg_producer(origin=(2.5, -1.5, -1.5))   # right
grp = make_group([sph, cone, esg])
rep = pvs.Show(grp, view)
solid_white(rep)
pvs.ResetCamera(view)

sels = top_selectors(grp)
s_sph = next(s for s in sels if 'Sphere' in s)
s_cone = next(s for s in sels if 'Cone' in s)
s_esg = next(s for s in sels if 'Esg' in s)
print("selectors:", sels, flush=True)
print("hierarchy XML (correlate cid attributes with picked indices):",
      flush=True)
print(hierarchy_xml(grp), flush=True)

# Paint the sphere red so its pixels are unambiguous, then pick its centroid.
rep.BlockColors = [s_sph, '1', '0', '0']
rep.UpdateVTKObjects()
a = shot(view, 'p5_layout')
m = (a[..., 0] > 60) & (a[..., 0] > 1.7 * (a[..., 1] + 1)) \
    & (a[..., 0] > 1.7 * (a[..., 2] + 1))
check("layout: red sphere block locatable", int(m.sum()) > 400,
      "red=%d" % int(m.sum()))
rows, cols = np.nonzero(m)
cy, cx = int(rows.mean()), int(cols.mean())
region = [cx - 8, cy - 8, cx + 8, cy + 8]
doc("picking region %r (render-window coords, origin bottom-left)" % (region,))

# --- cell picking ------------------------------------------------------------
reps1, srcs1 = vtkCollection(), vtkCollection()
ok = view.SMProxy.SelectSurfaceCells(region, reps1, srcs1, False)
check("SelectSurfaceCells returns a selection", bool(ok)
      and srcs1.GetNumberOfItems() > 0,
      "ok=%r n=%d" % (ok, srcs1.GetNumberOfItems()))
infos = dump_sources("CELL PICK", srcs1)

# --- block picking variant ----------------------------------------------------
try:
    reps2, srcs2 = vtkCollection(), vtkCollection()
    ok2 = view.SMProxy.SelectSurfaceBlocks(region, reps2, srcs2, False)
    doc("SelectSurfaceBlocks ok=%r n=%d" % (ok2, srcs2.GetNumberOfItems()))
    dump_sources("BLOCK PICK", srcs2)
except AttributeError:
    # older signature: SelectSurfaceCells(..., multiselect, modifier, selectBlocks)
    try:
        reps2, srcs2 = vtkCollection(), vtkCollection()
        ok2 = view.SMProxy.SelectSurfaceCells(region, reps2, srcs2, False, 0, True)
        doc("SelectSurfaceCells(selectBlocks=True) ok=%r n=%d"
            % (ok2, srcs2.GetNumberOfItems()))
        dump_sources("BLOCK PICK", srcs2)
    except Exception as exc:
        doc("block-pick variant unavailable: %r" % (exc,))
except Exception as exc:
    doc("block-pick variant failed: %r" % (exc,))

# --- verdict helper: does any property look like a selector or an index? -----
carrier = []
for xml, py in infos:
    props = py.ListProperties()
    if 'Selectors' in props or 'BlockSelectors' in props:
        carrier.append('assembly-selectors(%s)' % xml)
    if 'IDs' in props:
        carrier.append('IDs-triplets(%s)' % xml)
    if 'Blocks' in props:
        carrier.append('flat-block-ids(%s)' % xml)
check("block identity field identified in cell-pick selection source",
      bool(carrier), "; ".join(carrier))

finish()
