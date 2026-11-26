"""P3 — do Block* lists survive an upstream composite-structure change?

Question (TARGET_ARCHITECTURE §5 / R1, block_state/reconcile design): set
BlockSelectors + BlockColors, then CHANGE the composite structure upstream
(add a third dataset to the GroupDatasets, then remove the selected one) and
re-render. Do the Block* lists survive, and do they still APPLY to the right
blocks — or must reconcile() re-assert them?

Findings encoded below (pixel-verified):
- The Block* PROPERTY lists always survive (they are plain rep state).
- Selector matching is re-evaluated against the CURRENT hierarchy by NAME:
  a pure ADD keeps working with zero re-assertion (new block obeys current
  selectors, i.e. hidden unless matched).
- BUT if a structure change re-assigns an existing node NAME to a different
  dataset (GroupDatasets names blocks positionally, so removing block #2
  hands its name to the next input), the old selector silently applies to the
  WRONG data — no error, no crash. => reconcile() must re-assert after every
  structure commit AND the FESPP assembly names must be UUID-stable (the C++
  contract in TARGET_ARCHITECTURE §5 C++ TRACK).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_common import *  # noqa: F401,F403


def nwhite(a):
    return int(((a[..., 0] > 60) & (a[..., 1] > 60) & (a[..., 2] > 60)).sum())


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

# Show ONLY the ESG, painted blue (sphere would be white if leaked).
rep.BlockSelectors = [s_esg]
rep.BlockColors = [s_esg, '0', '0', '1']
rep.UpdateVTKObjects()
a = shot(view, 'p3_before')
check("setup: only ESG visible, blue (no white sphere pixels)",
      nblue(a) > 400 and nwhite(a) < 200,
      "blue=%d white=%d lit=%d" % (nblue(a), nwhite(a), nlit(a)))
before_sel = list(rep.BlockSelectors)
before_col = list(rep.BlockColors)

# --- structure change 1: ADD a third dataset upstream -----------------------
cone = pvs.Cone(registrationName='ConeSrc')
cone.Center = [6.0, 0.0, 0.0]
cone.Radius = 1.2
cone.Height = 2.4
grp.Input = [sph, esg, cone]
grp.UpdatePipeline()
pvs.ResetCamera(view)

after_sel = list(rep.BlockSelectors)
after_col = list(rep.BlockColors)
check("BlockSelectors survives structure change (property value intact)",
      after_sel == before_sel, "%r -> %r" % (before_sel, after_sel))
check("BlockColors survives structure change (property value intact)",
      after_col == before_col, "%r -> %r" % (before_col, after_col))

a = shot(view, 'p3_added')
new_sels = top_selectors(grp)
doc("hierarchy after add: %r (new block got a NEW name)" % (new_sels,))
check("Block* lists still APPLY after a pure ADD (ESG still blue; cone and "
      "sphere hidden — no reconcile needed for an add)",
      nblue(a) > 400 and nwhite(a) < 200,
      "blue=%d white=%d lit=%d" % (nblue(a), nwhite(a), nlit(a)))

# --- structure change 2: REMOVE the selected block ---------------------------
# GroupDatasets names blocks positionally: after removing the ESG, the CONE
# inherits the node name '/Root/EsgSrc' — the perfect trap for name-based
# selector matching.
grp.Input = [sph, cone]
grp.UpdatePipeline()
removed_sels = top_selectors(grp)
doc("hierarchy after remove: %r" % (removed_sels,))
a = shot(view, 'p3_removed')
name_reused = s_esg in removed_sels
doc("node name %r reused by a DIFFERENT dataset: %r" % (s_esg, name_reused))
if name_reused:
    # The old selector now matches the cone -> the cone shows up BLUE.
    doc("stale selector now paints the WRONG dataset: blue=%d lit=%d "
        "(silently misapplied, no error)" % (nblue(a, floor=25), nlit(a)))
    check("no crash; stale-name misapply demonstrated (=> reconcile() + "
          "UUID-stable assembly names are REQUIRED, not optional)",
          nlit(a) > 0, "blue=%d lit=%d" % (nblue(a, floor=25), nlit(a)))
else:
    check("dangling selector (name gone) shows nothing and does not crash",
          nlit(a) < 400, "lit=%d" % nlit(a))

# --- re-assert (what reconcile() would do) ----------------------------------
grp.Input = [sph, esg, cone]
grp.UpdatePipeline()
rep.BlockSelectors = [s_esg]
rep.BlockColors = [s_esg, '0', '0', '1']
rep.UpdateVTKObjects()
a = shot(view, 'p3_reasserted')
check("re-asserting the same lists after re-add restores the exact display",
      nblue(a) > 400 and nwhite(a) < 200,
      "blue=%d white=%d" % (nblue(a), nwhite(a)))

finish()
