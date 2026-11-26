"""P1 — per-block SOLID colour on the composite rep (PV 6.0.1).

Question (TARGET_ARCHITECTURE §5 / R1): does the composite representation of a
vtkPartitionedDataSetCollection expose per-block solid colour (`BlockColors`),
and does setting it actually change pixels? Independently validate the
1-point-LUT fallback (BlockColorArrayNames + per-block constant LUT).

Discovered activation gotcha (pixel-verified below): BlockColorArrayNames /
BlockLookupTables / BlockMapScalars are silently IGNORED while the rep's
GLOBAL ColorArrayName is solid (''); they only take effect when global scalar
coloring names a real array at render time. BlockColors (solid) works in any
global state. Per-block precedence: block LUT entry > BlockColors > global.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_common import *  # noqa: F401,F403


view = new_view()
sph = make_sphere()
esg = make_esg_producer()
grp = make_group([sph, esg])
print("composite output class:",
      grp.GetClientSideObject().GetOutputDataObject(0).GetClassName(), flush=True)

rep = pvs.Show(grp, view)
solid_white(rep)
pvs.ResetCamera(view)

sels = top_selectors(grp)
print("hierarchy selectors:", sels, flush=True)
s_sph = next(s for s in sels if 'Sphere' in s)
s_esg = next(s for s in sels if 'Esg' in s)

props = rep.ListProperties()
has_bc = 'BlockColors' in props
check("BlockColors property exists on the composite rep", has_bc)

a = shot(view, 'p1_base')
check("baseline solid white (no red/blue)",
      nred(a) < 50 and nblue(a) < 50 and nlit(a) > 3000,
      "red=%d blue=%d lit=%d" % (nred(a), nblue(a), nlit(a)))

# ---- main path: BlockColors (works with global solid) -----------------------
if has_bc:
    rep.BlockColors = [s_sph, '1', '0', '0', s_esg, '0', '0', '1']
    rep.UpdateVTKObjects()
    a = shot(view, 'p1_blockcolors')
    check("BlockColors pixel-verifies with global SOLID (sphere red, ESG blue)",
          nred(a) > 400 and nblue(a) > 400,
          "red=%d blue=%d" % (nred(a), nblue(a)))
    rep.BlockColors = []
    rep.UpdateVTKObjects()
    a = shot(view, 'p1_cleared')
    check("clearing BlockColors restores solid white",
          nred(a) < 50 and nblue(a) < 50,
          "red=%d blue=%d" % (nred(a), nblue(a)))

# ---- fallback path: per-block constant (1-point) LUTs -----------------------
# BlockColorArrayNames: (selector, int association [0=POINTS], array name);
# BlockLookupTables: ProxyProperty paired INDEX-WISE with the entries above.
lut_r = const_lut([1, 0, 0], 'lut_const_red')
lut_b = const_lut([0, 0, 1], 'lut_const_blue')
rep.BlockColorArrayNames = [s_sph, '0', 'Elevation', s_esg, '0', 'Elevation']
rep.BlockLookupTables = [lut_r, lut_b]
rep.BlockMapScalars = [s_sph, '1', s_esg, '1']
rep.UpdateVTKObjects()
a = shot(view, 'p1_lut_global_solid')
check("ACTIVATION GOTCHA: block LUT entries are ignored while the global "
      "ColorArrayName is solid ''",
      nred(a) < 50 and nblue(a) < 50,
      "red=%d blue=%d (stays white)" % (nred(a), nblue(a)))

# Activate global scalar coloring (constant GREEN global LUT so any block
# falling through to the global mapping is unambiguous in pixels).
lut_g = const_lut([0, 1, 0], 'lut_const_green')
rep.LookupTable = lut_g
rep.ColorArrayName = ['POINTS', 'Elevation']
rep.UpdateVTKObjects()
a = shot(view, 'p1_lut_fallback')
check("1-point-LUT fallback pixel-verifies once global coloring is ON "
      "(sphere red, ESG blue, nothing green)",
      nred(a) > 400 and nblue(a) > 400 and ngreen(a) < 50,
      "red=%d blue=%d green=%d" % (nred(a), nblue(a), ngreen(a)))

# ---- per-block SOLID while global coloring is ON ----------------------------
# Drop the ESG's block-LUT entry, give it BlockColors + BlockMapScalars=0.
rep.BlockColorArrayNames = [s_sph, '0', 'Elevation']
rep.BlockLookupTables = [lut_r]
rep.BlockMapScalars = [s_sph, '1', s_esg, '0']
rep.BlockColors = [s_esg, '1', '0', '1']  # magenta
rep.UpdateVTKObjects()
a = shot(view, 'p1_block_solid_under_global')
nmag = int(((a[..., 0] > 60) & (a[..., 2] > 60)
            & (a[..., 0] > 1.7 * (a[..., 1] + 1))
            & (a[..., 2] > 1.7 * (a[..., 1] + 1))).sum())
doc("per-block solid while global coloring ON (BlockColors+BlockMapScalars=0):"
    " magenta=%d green=%d red=%d -> %s" % (
        nmag, ngreen(a), nred(a),
        "BlockColors wins over global mapping" if nmag > 400 else
        "block falls back to GLOBAL mapping (use a 1-point block LUT for "
        "per-block solid when global coloring is on)"))

finish()
