"""P4 — semantics of an EMPTY BlockSelectors list + the sentinel selector.

Question (TARGET_ARCHITECTURE §5, Layer V "empty-visible-set = never-matching
sentinel"): does BlockSelectors=[] mean show-ALL or show-NONE on PV 6.0.1?
And does a never-matching sentinel selector reliably show nothing?
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_common import *  # noqa: F401,F403


SENTINEL = '/__fespp_none__'

view = new_view()
sph = make_sphere()
esg = make_esg_producer()
grp = make_group([sph, esg])
rep = pvs.Show(grp, view)
solid_white(rep)
pvs.ResetCamera(view)

doc("default BlockSelectors value: %r" % (list(rep.BlockSelectors),))

a = shot(view, 'p4_default')
base_lit = nlit(a)
check("setup: default selectors show everything", base_lit > 3000,
      "lit=%d" % base_lit)

# --- empty list --------------------------------------------------------------
rep.BlockSelectors = []
rep.UpdateVTKObjects()
a = shot(view, 'p4_empty')
empty_lit = nlit(a)
if empty_lit > 0.8 * base_lit:
    doc("EMPTY BlockSelectors = SHOW ALL (lit=%d vs base %d) -> the app can "
        "NEVER encode 'hide everything' as []" % (empty_lit, base_lit))
    empty_means = 'show-all'
elif empty_lit < 100:
    doc("EMPTY BlockSelectors = SHOW NONE (lit=%d)" % empty_lit)
    empty_means = 'show-none'
else:
    doc("EMPTY BlockSelectors = AMBIGUOUS (lit=%d vs base %d)"
        % (empty_lit, base_lit))
    empty_means = 'ambiguous'
check("empty-list semantics determined (not ambiguous)",
      empty_means != 'ambiguous', empty_means)

# --- sentinel ----------------------------------------------------------------
rep.BlockSelectors = [SENTINEL]
rep.UpdateVTKObjects()
a = shot(view, 'p4_sentinel')
check("never-matching sentinel selector %r shows NOTHING" % SENTINEL,
      nlit(a) < 100, "lit=%d" % nlit(a))

# --- restore ------------------------------------------------------------------
rep.BlockSelectors = ['/']
rep.UpdateVTKObjects()
a = shot(view, 'p4_restore')
check("restoring '/' shows everything again", nlit(a) > 0.8 * base_lit,
      "lit=%d" % nlit(a))

finish()
