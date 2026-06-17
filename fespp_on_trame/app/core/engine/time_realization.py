"""Time dispatch — global TimeKeeper labelling for the UI.

`change_time_label` keeps `state.ui_time_label` aligned with the
tree-attached `timeXXX.XXXXXX` label (or the formatted raw float when
no custom label was attached). `register_per_view_time_label` does the
same wiring for each panel's own slider so per-view readouts match the
global format.

Per-view realization selection is owned by
`fespp_on_trame.app.core.engine.realization_dispatch` (state map
`ui_active_realization_by_array_by_view`), not this module.
"""
import re

from paraview import simple as pvsimple


# `2019-12-31T23:00:00Z` / `2019-12-31 23:00:00` → keep `2019-12-31`.
# Reservoir timeseries labels are dated to the day in practice, so the
# time-of-day is noise that crowds the TC chip + every stats table
# column. Anything that doesn't match the ISO date prefix (e.g. the
# fallback `timeX.YYYYYY`, custom non-date labels) passes through
# unchanged.
_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]\d{2}:\d{2}")


def _shorten_time_label(label):
    if not isinstance(label, str):
        return label
    m = _ISO_DATE_RE.match(label)
    if m:
        return m.group(1)
    return label


def label_for_time_value(tree, time_value):
    """Return the tree-attached label (`timeX.YYYYYY` attribute on
    root) for a given time, or the formatted time itself when no
    custom label is registered. ISO datetime labels are trimmed to
    their date part (`YYYY-MM-DD`)."""
    try:
        label = tree.find_attribute_value(0, f"time{time_value:.6f}")
        if label is not None:
            return _shorten_time_label(label)
    except Exception:
        pass
    return f"time{time_value:.6f}"


def change_time_label(state, tree):
    """Update `state.ui_time_label` from the current time step's
    label attribute on the assembly root, falling back to the
    formatted time value."""
    try:
        index = state.time_index
        if index is not None:
            time_value = pvsimple.GetTimeKeeper().TimestepValues[index]
            state.ui_time_label = label_for_time_value(tree, time_value)
    except Exception:
        state.ui_time_label = ""


def register_per_view_time_label(state, tree, time_value_var, label_var):
    """Wire a `state.change` handler that recomputes `label_var`
    from `time_value_var` using the same tree-driven lookup as the
    global TC label. Called by `FesppMultiView` when it creates a
    per-view TimeControl, so each panel's slider readout matches
    the global label format instead of showing the raw float.

    Also bumps `ui_per_view_time_pulse` — a shared monotonic
    counter the stats dispatcher watches to recompute View rows
    when any per-view TC moves. `time_value_<panel_id>` is
    dynamic per view so the stats trigger list can't watch it
    directly; the pulse gives every per-view TC a single, fixed
    state var it can poke."""
    def _on_change(**_):
        try:
            tv = float(getattr(state, time_value_var, 0) or 0)
            setattr(state, label_var, label_for_time_value(tree, tv))
        except Exception:
            setattr(state, label_var, "")
        try:
            current = int(getattr(state, "ui_per_view_time_pulse", 0) or 0)
            state.ui_per_view_time_pulse = current + 1
        except Exception:
            pass
    state.change(time_value_var)(_on_change)
    # Seed once so the label is already populated when the panel
    # first renders.
    _on_change()
