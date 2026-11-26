"""The vertical summation and the weighted means, derived a second time by
a method other than the code's.

The neighbouring tests assert hand-derived tables; these assert the same
figures against a numerical derivation that shares no step with the
implementation: a midpoint Riemann sum instead of a segment sum, a masked
``numpy.average`` instead of a paired dot product, a nearest-sample sweep
instead of a half-step formula. Two independent methods agreeing on a
number make it a measurement rather than a snapshot of the code.
"""
import numpy as np
import pytest

from fespp_on_trame.engine import reconcile_dispatch as rd
from fespp_on_trame.engine import stats_dispatch as sd
from fespp_on_trame.engine import welllog_dispatch as wd


# ---- the vertical thicknesses, against a Riemann integral ----------------

# A well inclined at a constant 60° from vertical: cos 60° = 0.5 exactly, so
# the true vertical depth is half the measured one over the whole interval.
_MD = [1000, 1020, 1040, 1060, 1080, 1100, 1120, 1140, 1160, 1180, 1200]
_PHI = [0.20, 0.20, 0.05, 0.05, 0.20, 0.10, 0.10, 0.02, 0.02, 0.02, 0.02]
_SW = [0.30, 0.30, 0.90, 0.90, 0.30, 0.50, 0.50, 0.95, 0.95, 0.95, 0.95]
_TVD = [m / 2.0 for m in _MD]
_CUTOFF = [{"curve": "PHI", "op": ">=", "value": 0.10}]


def _deviated_well():
    return {
        "name": "W60", "depthRef": "MD", "integrationRef": "TVD",
        "depth": {"min": 1000.0, "max": 1200.0},
        "tracks": [
            {"kind": "porosity", "unit": "v/v",
             "curves": [{"name": "PHI", "unit": "v/v"}]},
            {"kind": "water saturation", "unit": "v/v",
             "curves": [{"name": "SW", "unit": "v/v"}]},
        ],
        "tops": [{"name": "TopA", "depth": 1000.0, "tvd": 500.0},
                 {"name": "TopB", "depth": 1100.0, "tvd": 550.0},
                 {"name": "TopC", "depth": 1200.0, "tvd": 600.0}],
        "_full": {
            "PHI": [[p, float(m), float(t)]
                    for p, m, t in zip(_PHI, _MD, _TVD)],
            "SW": [[s, float(m), float(t)]
                   for s, m, t in zip(_SW, _MD, _TVD)],
        },
    }


def _riemann(top, bottom, dz=1e-3):
    """Return (net, phih, hcph) over [top, bottom) of the vertical axis.

    Sample-and-hold makes phi, Sw and the pay flag step functions of the
    vertical depth; every break sits on a whole metre, so a midpoint rule on
    a grid of whole millimetres is exact. No formula of the module is used:
    the integrand is evaluated point by point and summed."""
    zs = np.arange(_TVD[0] + dz / 2, _TVD[-1], dz)
    idx = np.searchsorted(np.asarray(_TVD), zs, side="right") - 1
    phi = np.asarray(_PHI)[idx]
    sw = np.asarray(_SW)[idx]
    pay = (phi >= 0.10) & (zs >= top) & (zs < bottom)
    return (float(pay.sum() * dz),
            float(np.sum(phi[pay]) * dz),
            float(np.sum((phi * (1.0 - sw))[pay]) * dz))


@pytest.mark.parametrize("name,top,bottom", [("TopA → TopB", 500.0, 550.0),
                                             ("TopB → TopC", 550.0, 600.0)])
def test_the_vertical_summation_matches_a_riemann_integral(name, top, bottom):
    zone = next(z for z in wd.zone_stats(_deviated_well(), _CUTOFF)
                if z["name"] == name)
    net, phih, hcph = _riemann(top, bottom)
    assert zone["thickness_tvd"] == pytest.approx(bottom - top)
    assert zone["net"] == pytest.approx(net, abs=2e-3)
    assert zone["ntg"] == pytest.approx(net / (bottom - top), abs=1e-4)
    assert zone["phih"] == pytest.approx(phih, abs=2e-3)
    assert zone["hcph"] == pytest.approx(hcph, abs=2e-3)
    # the along-hole thickness, which the panel must not report, is exactly
    # twice the vertical one, since cos 60° = 0.5
    assert zone["thickness"] == pytest.approx(2.0 * zone["thickness_tvd"])


# ---- the weighted means, against a masked numpy average -----------------

def _weighted(values, weights):
    v, w = np.asarray(values, float), np.asarray(weights, float)
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
    return float(np.average(v[ok], weights=w[ok])) if ok.any() else None


def test_the_weighted_means_match_a_masked_average_on_random_draws():
    """300 draws with NaNs in the values, NaNs in the weights and zero
    weights: a value and its weight must stay paired through every hole."""
    rng = np.random.default_rng(20260912)
    for _ in range(300):
        n = int(rng.integers(2, 40))
        v = rng.normal(size=n) * 10.0
        w = np.abs(rng.normal(size=n))
        v[rng.random(n) < 0.15] = np.nan
        w[rng.random(n) < 0.15] = np.nan
        w[rng.random(n) < 0.10] = 0.0
        got, count, why = sd.weighted_mean(v, w)
        want = _weighted(v, w)
        assert (got is None) == (want is None)
        if want is not None:
            assert got == pytest.approx(want)
        assert count == int((np.isfinite(v) & np.isfinite(w) & (w > 0)).sum())
        assert why == ("" if want is not None else "none")


def test_the_pore_volume_weight_is_volume_times_ntg_times_porosity():
    # two cells, volumes 1 and 9, net-to-gross 1.0 and 0.5, porosity the
    # property being averaged: three genuinely different means
    vol = np.array([1.0, 9.0])
    phi = np.array([0.10, 0.30])
    pore = vol * np.array([1.0, 0.5]) * phi
    row = sd._row_stats_from_values(phi, "PHI", volume=vol, pore_volume=pore)
    assert row["Mean"] == pytest.approx(float(np.mean(phi)))
    assert row["Mean (V)"] == pytest.approx(_weighted(phi, vol))
    assert row["Mean (PV)"] == pytest.approx(_weighted(phi, pore))
    assert len({round(row[k], 12)
                for k in ("Mean", "Mean (V)", "Mean (PV)")}) == 3


# ---- the traversed length, against a nearest-sample sweep ----------------

def _ownership(depths, top, bottom, dz=1e-4):
    """Sweep the zone at dz and give each step to the sample nearest it,
    within half a step of the two ends — the length of hole a sample stands
    for, counted rather than computed."""
    d = np.asarray(depths, float)
    lo, hi = d[0] - (d[1] - d[0]) / 2, d[-1] + (d[-1] - d[-2]) / 2
    zs = np.arange(max(top, lo) + dz / 2, min(bottom, hi), dz)
    owner = np.abs(zs[:, None] - d[None, :]).argmin(axis=1)
    return [float((owner == i).sum() * dz) for i in range(len(d))]


@pytest.mark.parametrize("depths,top,bottom", [
    ([1.0, 3.0, 5.0, 7.0, 9.0, 11.0], 0.0, 10.0),     # the last one outside
    ([1.0, 3.0, 5.0, 7.0, 9.0, 11.0], 0.0, 11.0),     # astride the base
    ([1.0, 3.0, 5.0, 7.0, 9.0, 10.0], 0.0, 10.5),     # uneven last step
    ([0.0, 1.0, 4.0, 10.0], 2.0, 8.0),                # uneven throughout
])
def test_the_traversed_length_matches_a_nearest_sample_sweep(depths, top,
                                                             bottom):
    got = rd.traversed_lengths(depths, top, bottom)
    for a, b in zip(got, _ownership(depths, top, bottom)):
        assert a == pytest.approx(b, abs=2e-4)
    assert sum(got) == pytest.approx(min(bottom, depths[-1] + 0.5
                                         * (depths[-1] - depths[-2]))
                                     - max(top, depths[0] - 0.5
                                           * (depths[1] - depths[0])),
                                     abs=2e-4)


@pytest.mark.parametrize("depths,values,top,bottom", [
    ([1.0, 3.0, 5.0, 7.0, 9.0, 11.0], [1, 1, 1, 1, 1, 100], 0.0, 11.0),
    ([1.0, 3.0, 5.0, 7.0, 9.0, 10.0], [1, 1, 1, 1, 1, 100], 0.0, 10.5),
    ([0.0, 1.0, 4.0, 10.0], [2.0, 8.0, 3.0, 5.0], 2.0, 8.0),
])
def test_the_length_weighted_grid_mean_matches_a_swept_average(depths, values,
                                                               top, bottom):
    """`mean_grid_len` derived a second way: sweep the zone at 0.1 mm, read
    the value of the sample nearest each step, and average the steps. No
    half-step formula, no weights — the mean of the rock the hole passed
    through, counted. A sample whose station falls outside the zone still
    owns the part of its stretch that reaches in, and the sweep counts it,
    so the two methods only agree if the code weighs it too."""
    well = {
        "name": "W", "depth": {"min": min(depths) - 1, "max": max(depths) + 1},
        "tops": [{"name": "Z", "depth": top, "tvd": top},
                 {"name": "end", "depth": bottom, "tvd": bottom}],
        "_full": {
            "PHI": [[1.0, d, d] for d in depths],
            "PORO (grid)": [[v, d, d] for d, v in zip(depths, values)],
        },
    }
    row = rd.rows_for_well(
        well, [{"log": "PHI", "prop": "/p", "basis": "kind"}],
        {"PHI": {"kind": "porosity", "unit": "v/v"}},
        {"/p": {"path": "/p", "title": "PORO", "kind": "porosity",
                "unit": "v/v"}})[0]
    d = np.asarray(depths, float)
    lo = d[0] - (d[1] - d[0]) / 2
    hi = d[-1] + (d[-1] - d[-2]) / 2
    dz = 1e-4
    zs = np.arange(max(top, lo) + dz / 2, min(bottom, hi), dz)
    owner = np.abs(zs[:, None] - d[None, :]).argmin(axis=1)
    swept = float(np.asarray(values, float)[owner].mean())
    assert row["mean_grid_len"] == pytest.approx(swept, rel=1e-4)
    assert row["len_grid"] == pytest.approx(len(zs) * dz, abs=2e-4)
