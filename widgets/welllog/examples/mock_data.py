"""Synthetic 3-well dataset mirroring src/correlation.js mockData() — feeds the
standalone trame example (examples/app.py)."""
import math

MARKERS = [
    {"name": "BB", "color": "#1b5e20"},
    {"name": "TOP A", "color": "#2e7d32"},
    {"name": "BOTTOM A", "color": "#d32f2f"},
    {"name": "FLATTEN DATUM", "color": "#795548"},
    {"name": "BOTTOM B", "color": "#1565c0"},
    {"name": "C", "color": "#7b1fa2"},
    {"name": "D", "color": "#29b6f6"},
]


def _walk(d0, d1, step, base, amp):
    """Return ``[value, depth]`` samples from d0 to d1: a bounded walk about
    ``base`` (within +/- ``amp``), deterministic so every run looks the same."""
    out, v, d = [], base, d0
    while d <= d1:
        v += (math.sin(d / 17) + (((d * 31) % 13) - 6) / 6) * amp * 0.18
        v = max(base - amp, min(base + amp, v))
        out.append([v, d])
        d += step
    return out


def _well(name, color, d0, off):
    """One well spanning 1300 depth units from ``d0``; ``off`` shifts its tops
    so the correlation lines tilt between wells."""
    return {
        "name": name, "color": color, "depthRef": "SSTVD",
        "depth": {"min": d0, "max": d0 + 1300},
        # one track per log kind, laid out as engine/welllog_dispatch
        # .build_payload does: the track carries the value scale every well
        # shares, each curve its own range for the header
        "tracks": [
            {"kind": "GR", "unit": "API", "range": [0, 150], "logScale": False,
             "curves": [
                 {"name": "GR", "color": "#1565c0", "unit": "API", "range": [0, 150],
                  "samples": _walk(d0, d0 + 1300, 4, 75, 70),
                  "missing": False, "synthetic": False}]},
            {"kind": "RES", "unit": "ohm.m", "range": [0.2, 2000], "logScale": True,
             "curves": [
                 {"name": "RES", "color": "#2e7d32", "unit": "ohm.m", "range": [0.2, 2000],
                  "samples": _walk(d0, d0 + 1300, 4, 1000, 950),
                  "missing": False, "synthetic": False}]},
        ],
        "tops": [
            {"name": "BB", "depth": d0 + 130 + off},
            {"name": "TOP A", "depth": d0 + 600 + off * 1.2},
            {"name": "BOTTOM A", "depth": d0 + 690 - off},
            {"name": "FLATTEN DATUM", "depth": d0 + 820},
            {"name": "BOTTOM B", "depth": d0 + 900 + off},
            {"name": "C", "depth": d0 + 980 + off},
            {"name": "D", "depth": d0 + 1060 + off * 1.4},
        ],
    }


def mock_data():
    """The panel payload: three wells sharing the same tops, not flattened."""
    return {
        "markers": MARKERS,
        "flattenOn": None,
        "wells": [
            _well("WELL-A", "#ffeb3b", 2100, 0),
            _well("WELL-B", "#8bc34a", 2150, 35),
            _well("WELL-C", "#26c6da", 1950, -60),
        ],
    }
