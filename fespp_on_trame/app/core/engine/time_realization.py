"""Time dispatch — global TimeKeeper labelling for the UI.

`change_time_label` keeps `state.ui_time_label` aligned with the
tree-attached `timeXXX.XXXXXX` label (or the formatted raw float when
no custom label was attached). `register_per_view_time_label` does the
same wiring for each panel's own slider so per-view readouts match the
global format.

Realization handling moved out of this module: the legacy global
cursor (`ui_slices_real` → collector.set_realization_index) is gone.
Per-view realization selection is owned by
`fespp_on_trame.app.core.engine.realization_dispatch` (state map
`ui_active_realization_by_array_by_view`).
"""
from paraview import simple as pvsimple


def label_for_time_value(tree, time_value):
    """Return the tree-attached label (`timeX.YYYYYY` attribute on
    root) for a given time, or the formatted time itself when no
    custom label is registered."""
    try:
        label = tree.find_attribute_value(0, f"time{time_value:.6f}")
        if label is not None:
            return label
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
    the global label format instead of showing the raw float."""
    def _on_change(**_):
        try:
            tv = float(getattr(state, time_value_var, 0) or 0)
            setattr(state, label_var, label_for_time_value(tree, tv))
        except Exception:
            setattr(state, label_var, "")
    state.change(time_value_var)(_on_change)
    # Seed once so the label is already populated when the panel
    # first renders.
    _on_change()
