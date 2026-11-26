"""P7 — incremental cost of an EPCCollector Selectors commit (real FESPP).

Question (TARGET_ARCHITECTURE §5 / R2): time Selectors-write + UpdatePipeline
for 1 path, then +5, then ALL leaf paths of the test EPC — and then a
one-path DELTA at full base (remove one / re-add it). If the delta commit
costs ~= the full commit, every commit re-reads wholesale (=> batch writes +
overlay); if it costs ~= the single-path commit, the collector is
incremental. Also logs RSS (VmRSS current + ru_maxrss peak) per step and a
same-list no-op rewrite.

Requires (in the container): Fespp.so + /tmp/test.epc (+ .h5).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_common import *  # noqa: F401,F403
import resource
import time

FESPP = '/work/ttl/install-fespp/lib/paraview/plugins/Fespp/Fespp.so'
EPC = '/tmp/test.epc'

pvs.LoadPlugin(FESPP, remote=False, ns=globals())
src = EPCCollector(registrationName='EPCCollector')  # noqa: F821

from paraview.servermanager import vtkSMPropertyHelper
vtkSMPropertyHelper(src.SMProxy, 'ExplicitSelection').Set(1)
src.SMProxy.UpdateVTKObjects()
src.SetPropertyWithName('Files', EPC)
src.UpdatePipelineInformation()

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
check("live assembly reachable", asm is not None)


def leaves(a, nid=0, out=None):
    out = [] if out is None else out
    n = a.GetNumberOfChildren(nid)
    if n == 0:
        if nid != 0:
            out.append(a.GetNodePath(nid))
    else:
        for i in range(n):
            leaves(a, a.GetChild(nid, i), out)
    return out


all_paths = leaves(asm)
N = len(all_paths)
print("EPC leaf paths: %d" % N, flush=True)
for p in all_paths:
    print("   ", p, flush=True)
check("enough paths for a meaningful timing (N >= 8)", N >= 8, "N=%d" % N)

TIMINGS = []


def commit(tag, paths):
    print("commit '%s' (%d paths)..." % (tag, len(paths)), flush=True)
    t0 = time.perf_counter()
    src.SetPropertyWithName('Selectors', list(paths))
    src.UpdatePipeline()
    dt = time.perf_counter() - t0
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    cur = rss_mb()
    TIMINGS.append((tag, len(paths), dt, cur, peak))
    print("  -> %.3fs  RSS=%.1fMB  peak=%.1fMB" % (dt, cur, peak), flush=True)
    return dt


t_1 = commit("first 1", all_paths[:1])
t_6 = commit("first 6 (+5)", all_paths[:min(6, N)])
t_all = commit("ALL %d" % N, all_paths)
t_noop = commit("same list rewrite (no-op?)", all_paths)
t_minus = commit("all minus 1", all_paths[:-1])
t_readd = commit("re-add 1 at full base (DELTA)", all_paths)

print("--- timing table (tag, n, seconds, RSS MB, peak MB) ---", flush=True)
for row in TIMINGS:
    print("  %-32s n=%-4d %8.3fs  rss=%7.1f  peak=%7.1f" % row, flush=True)

# Verdict: incremental iff the 1-path delta at full base is much cheaper than
# the full commit AND in the ballpark of the first single-path commit.
ratio_full = t_readd / max(t_all, 1e-9)
doc("delta/full ratio = %.2f (delta=%.3fs, full=%.3fs, single=%.3fs, "
    "noop=%.3fs)" % (ratio_full, t_readd, t_all, t_1, t_noop))
if ratio_full < 0.4:
    doc("verdict: INCREMENTAL — a Selectors commit costs ~ the delta")
elif ratio_full > 0.7:
    doc("verdict: WHOLESALE — every Selectors commit re-reads ~everything; "
        "batch writes per transaction + busy overlay (R2 mitigation) required")
else:
    doc("verdict: MIXED — partial re-read; still batch writes per transaction")
check("timing collected for 1/+5/all/delta", len(TIMINGS) == 6)

finish()
