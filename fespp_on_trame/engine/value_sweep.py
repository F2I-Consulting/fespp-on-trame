"""The steps a threshold entry goes through when it is swept — pure.

The PO, 27/10: "a player that shows only the current value and hides
everything else, a threshold of one single value moved by the player's
slider", and the movement must be fluid. The sweep drives ONE entry of a
view's threshold chain (`engine/sources/ijkgrid`): each step is the range
that entry keeps.

- Discrete and Categorical entries: one step per distinct value of the
  data (`unique_values`, the NullValue sentinel already out), the range
  `[v, v]`; a categorical step is named by its category.
- Continuous entries: a window `width` (a fraction of the data range)
  sliding over the range by small steps, its centre from the low end to the
  high end in `POSITIONS` steps, clamped at both ends. Small steps and an
  overlapping window are what makes the movement fluid: one cell set
  differs from the next by a thin slice of values.

Since 28/10 every row of the Geometry and the Property slicers has a player
(`window_steps`): in value mode it steps one value at a time as above (an
I, J or K index is a whole number like a discrete value); in range mode it
slides the WHOLE kept range, low and high together, its width kept — the
"step range" of the PO's manager.
"""
from fespp_on_trame.engine.utils import numfmt

# the window of a continuous sweep, as a fraction of the data range
WIDTHS = (0.01, 0.02, 0.05, 0.1, 0.2)
DEFAULT_WIDTH = 0.05
# the positions of a continuous window's centre, both ends included
POSITIONS = 101
# the player's speeds, in steps per second
RATES = (1, 2, 5, 10, 20)
DEFAULT_RATE = 5


def _integer_kind(kind):
    return kind in ("Discrete", "Categorical", "Index")


def _label(v, labels):
    key = str(int(v)) if float(v).is_integer() else str(v)
    name = labels.get(key)
    return f"{name} ({key})" if name is not None else key


def window_steps(kind, extent=None, values=None, labels=None, low=None, high=None,
                 mode="value", width=DEFAULT_WIDTH, positions=POSITIONS):
    """``[(low, high, label)]`` — the ranges a row's player goes through.

    - Integer kinds (Discrete, Categorical, Index): `values` the distinct
      values (an Index's: every whole number of `extent` when not given).
      Value mode: one step per value. Range mode: the values [low, high]
      holds, as a window slid one value a step.
    - Continuous: value mode, a window `width` (a fraction of the extent)
      whose centre goes from one end to the other in `positions` steps,
      clamped; range mode, the window [low, high] itself, its start from the
      low end to the high end in `positions` steps.
    Empty when there is nothing to step through."""
    labels = {str(k): v for k, v in (labels or {}).items()}
    lo_ext, hi_ext = (list(extent or ()) + [None, None])[:2]
    if _integer_kind(kind):
        if values is None and kind == "Index" and lo_ext is not None and hi_ext is not None:
            values = range(int(lo_ext), int(hi_ext) + 1)
        vals = sorted({float(v) for v in values or ()})
        if not vals:
            return []
        if mode != "range" or low is None or high is None:
            return [(v, v, _label(v, labels)) for v in vals]
        held = [v for v in vals if float(low) <= v <= float(high)] or vals[:1]
        m = len(held)
        return [(vals[i], vals[i + m - 1],
                 f"{_label(vals[i], labels)} – {_label(vals[i + m - 1], labels)}" if m > 1
                 else _label(vals[i], labels))
                for i in range(len(vals) - m + 1)]
    if lo_ext is None or hi_ext is None:
        return []
    lo, hi = float(lo_ext), float(hi_ext)
    span = hi - lo
    if not span > 0:
        return [(lo, hi, numfmt.fmt(lo))]
    n = max(2, int(positions))
    out = []
    if mode == "range" and low is not None and high is not None:
        w = min(max(float(high) - float(low), 0.0), span)
        for i in range(n):
            a = lo + (span - w) * i / (n - 1)
            out.append((a, a + w, f"{numfmt.fmt(a)} – {numfmt.fmt(a + w)}"))
        return out
    w = float(width) if isinstance(width, (int, float)) else DEFAULT_WIDTH
    half = max(min(w, 1.0), 1e-6) * span / 2.0
    for i in range(n):
        c = lo + span * i / (n - 1)
        a, b = max(lo, c - half), min(hi, c + half)
        out.append((a, b, f"{numfmt.fmt(a)} – {numfmt.fmt(b)}"))
    return out


def steps(entry, width=DEFAULT_WIDTH, positions=POSITIONS):
    """``[(low, high, label)]`` — the ranges the entry keeps, in order.

    `entry` is a chain entry as the isolate gives it (`get_chain()`):
    ``kind``, ``unique_values``, ``labels``, ``data_range``. Empty when there
    is nothing to step through (no value, an empty range)."""
    kind = entry.get("kind") or "Continuous"
    if kind == "Index":
        kind = "Discrete"
    return window_steps(kind, extent=entry.get("data_range"),
                        values=entry.get("unique_values") or (),
                        labels=entry.get("labels"), mode="value",
                        width=width, positions=positions)


def start_index(entry, sweep_steps):
    """The step a sweep starts on: the first one inside the range the entry
    keeps now (a reader who narrowed it starts there), else the first."""
    low = entry.get("low")
    if not isinstance(low, (int, float)):
        return 0
    for i, (a, _b, _t) in enumerate(sweep_steps):
        if a >= low:
            return i
    return 0


def nearest_index(sweep_steps, low):
    """The step whose low end is nearest `low` — where a row's player
    picks up from what the row keeps now."""
    if not sweep_steps or not isinstance(low, (int, float)):
        return 0
    return min(range(len(sweep_steps)), key=lambda i: abs(sweep_steps[i][0] - float(low)))
