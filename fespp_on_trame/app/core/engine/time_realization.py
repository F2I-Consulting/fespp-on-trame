"""Time / realization dispatch — extracted from
`boot.initialize_fespp_engine`.

Two unrelated but adjacent UI domains:

  - **Time** — the global TimeKeeper drives every render view's
    `ViewTime`. `change_time_label` keeps `state.ui_time_label`
    aligned with the tree-attached `timeXXX.XXXXXX` label (or the
    formatted raw float when no custom label was attached).
    `register_per_view_time_label` does the same wiring for each
    panel's own slider so per-view readouts match the global
    format.

  - **Realization** — `update_realization_slider` drives the
    collector's `RealizationIndex` from `state.ui_slices_real` (a
    slider position into `state.realization_labels`); the C++ layer
    swaps the property values under the same VTK array name, so
    ParaView's color mapping follows for free.
    `update_real_lock` stores the locked value so the lock survives
    a switch to a property whose index set differs."""
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
    # first renders (the @change handler only fires on subsequent
    # mutations).
    _on_change()


def update_realization_slider(state, controller, collector, view, ui_slices_real):
    """Realization slider → drive the collector's RealizationIndex.
    `ui_slices_real` is the slider position (0..N-1); the actual
    realization index lives in `realization_labels[ui_slices_real]`
    (e.g. "23"). The C++ layer swaps the property values under the
    same array name, so ParaView's color mapping follows."""
    labels = state.realization_labels or []
    if not labels or ui_slices_real >= len(labels):
        return
    try:
        real_index = int(labels[ui_slices_real])
    except (ValueError, TypeError):
        return
    if ui_slices_real != state.realization_selected_index:
        state.realization_selected_index = ui_slices_real
        collector.set_realization_index(real_index)
        pvsimple.Render(view=view)
        controller.view_update()
    if state.ui_slices_real_locked:
        state.ui_slices_real_locked_value = labels[ui_slices_real]


def update_real_lock(state, ui_slices_real_locked):
    """Store the locked realization *value* (e.g. "23") so the lock
    survives a switch to a property whose index set differs."""
    if ui_slices_real_locked:
        labels = state.realization_labels or []
        pos = state.ui_slices_real
        state.ui_slices_real_locked_value = (
            labels[pos] if 0 <= pos < len(labels) else None
        )
    else:
        state.ui_slices_real_locked_value = None
