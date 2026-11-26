"""P2 — Block* corner interplay: BlockOpacities x BlockUseSeparateColorMaps x
BlockMapScalars (PV 6.0.1).

Question (TARGET_ARCHITECTURE §5 / R1): set a per-block opacity AND two
DIFFERENT block LUTs simultaneously on the same composite rep — do both apply
(pixel-verified)? Also documents the BlockUseSeparateColorMaps=0 corner and
BlockMapScalars=0 (solid colour despite a colour array entry).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_common import *  # noqa: F401,F403
import numpy as np


def blue_stats(a):
    """(count, mean B) over clearly-blue pixels, low floor so a translucent
    blue block still registers."""
    m = (a[..., 2] > 20) & (a[..., 2] > 2.0 * (a[..., 0] + 1)) \
        & (a[..., 2] > 2.0 * (a[..., 1] + 1))
    cnt = int(m.sum())
    return cnt, (float(a[..., 2][m].mean()) if cnt else 0.0)


view = new_view()
sph = make_sphere()
esg = make_esg_producer()
grp = make_group([sph, esg])
rep = pvs.Show(grp, view)
solid_white(rep)
pvs.ResetCamera(view)

sels = top_selectors(grp)
s_sph = next(s for s in sels if 'Sphere' in s)
s_esg = next(s for s in sels if 'Esg' in s)

lut_r = const_lut([1, 0, 0], 'lut_const_red')
lut_b = const_lut([0, 0, 1], 'lut_const_blue')

# ACTIVATION (see P1): block LUT entries only apply while GLOBAL scalar
# coloring is on — constant green global LUT makes any fall-through obvious.
lut_g = const_lut([0, 1, 0], 'lut_const_green')
rep.LookupTable = lut_g
rep.ColorArrayName = ['POINTS', 'Elevation']

# Two DIFFERENT per-block LUTs + per-block opacity, all at once.
rep.BlockColorArrayNames = [s_sph, '0', 'Elevation', s_esg, '0', 'Elevation']
rep.BlockLookupTables = [lut_r, lut_b]
rep.BlockMapScalars = [s_sph, '1', s_esg, '1']
try:
    rep.BlockUseSeparateColorMaps = [s_sph, '1', s_esg, '1']
except Exception as exc:
    doc("BlockUseSeparateColorMaps write failed: %r" % (exc,))
rep.BlockOpacities = [s_esg, '0.35']
rep.UpdateVTKObjects()

a = shot(view, 'p2_op035')
cnt035, mean035 = blue_stats(a)
red035 = nred(a)
check("two different block LUTs apply simultaneously (red sphere + blue ESG)",
      red035 > 400 and cnt035 > 200,
      "red=%d blue_px=%d blue_mean=%.1f" % (red035, cnt035, mean035))

rep.BlockOpacities = [s_esg, '1.0']
rep.UpdateVTKObjects()
a = shot(view, 'p2_op100')
cnt100, mean100 = blue_stats(a)
check("BlockOpacities applies WITH block LUTs active (0.35 dimmer than 1.0)",
      cnt100 > 200 and mean100 > 1.25 * max(mean035, 1.0),
      "blue_mean(0.35)=%.1f blue_mean(1.0)=%.1f" % (mean035, mean100))

# Corner: BlockUseSeparateColorMaps=0 with two explicit per-block LUTs — does
# the explicit LUT pairing still win? (property has cmd=None: GUI-side only.)
try:
    rep.BlockUseSeparateColorMaps = [s_sph, '0', s_esg, '0']
    rep.UpdateVTKObjects()
    a = shot(view, 'p2_sepmaps0')
    cnt0, _ = blue_stats(a)
    doc("BlockUseSeparateColorMaps=0 corner: red=%d blue_px=%d (explicit "
        "BlockLookupTables %s)" % (nred(a), cnt0,
        "still honoured" if (nred(a) > 400 and cnt0 > 200) else "OVERRIDDEN"))
    rep.BlockUseSeparateColorMaps = [s_sph, '1', s_esg, '1']
    rep.UpdateVTKObjects()
except Exception as exc:
    doc("BlockUseSeparateColorMaps corner skipped: %r" % (exc,))

# Corner: BlockMapScalars=0 on the ESG — array entry present but mapping off.
# Does the block go SOLID (white) or fall through to the GLOBAL (green) map?
rep.BlockMapScalars = [s_sph, '1', s_esg, '0']
rep.UpdateVTKObjects()
a = shot(view, 'p2_mapscalars0')
cntoff, _ = blue_stats(a)
doc("BlockMapScalars=0 corner: blue_px=%d green_px=%d (block went %s)"
    % (cntoff, ngreen(a),
       "solid" if ngreen(a) < 100 else "GLOBAL-mapped (green)"))
check("BlockMapScalars=0 disables that block's own LUT mapping",
      cntoff < 100 and nred(a) > 400,
      "blue_px=%d red=%d" % (cntoff, nred(a)))

finish()
