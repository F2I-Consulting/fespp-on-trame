"""Slice-plane dispatch — single axis-aligned plane per rep.

The engine exposes three controller entry points:
  - `slice_publish_state(rep_path)` — pushes the rep's slice
    descriptor into the `ui_slice_*` trame vars so the panel binds
    to it. Called on rep activation, and whenever the slice changes.
  - `slice_set(...)` — applies an (enabled, axis, offset) patch on
    the rep's `SlicePlane` and republishes.

The "active rep" is read from `state.active_representation_path` —
the rep whose properties are currently edited by the side-panels.
Switching the active rep republishes the new rep's slice state.
"""
from paraview import simple as pvsimple


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def publish_slice_state(state, source_registry):
    """Push the active rep's slice descriptor into `ui_slice_*` so
    the UI panel binds to it. Idempotent — called on activation, on
    user edits, and after data load.

    Also resolves the offset slider's domain (min/max/step) from the
    chosen axis + bounds and writes them to dedicated state vars,
    so the Vue template doesn't have to evaluate a ternary across
    `ui_slice_axis` / `ui_slice_bounds` (which can trip Vue's
    expression parser depending on context)."""
    rep_path = getattr(state, "active_representation_path", "") or ""
    desc = source_registry.slice_state(rep_path) if rep_path else {
        "enabled": False, "axis": "X", "offset": 0.0,
        "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
    }
    bounds = list(desc.get("bounds") or [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    axis = desc.get("axis") or "X"
    i = _AXIS_INDEX.get(axis, 0)
    lo = float(bounds[2 * i])
    hi = float(bounds[2 * i + 1])
    step = (hi - lo) / 1000.0 if hi > lo else 0.001

    # Trame is fine writing identical values — these compare equal
    # and short-circuit at the deep-equality check.
    state.ui_slice_enabled = bool(desc.get("enabled"))
    state.ui_slice_axis = axis
    state.ui_slice_offset = float(desc.get("offset") or 0.0)
    state.ui_slice_bounds = bounds
    state.ui_slice_offset_min = lo
    state.ui_slice_offset_max = hi
    state.ui_slice_offset_step = step


def slice_set(state, controller, source_registry, view,
              enabled=None, axis=None, offset=None):
    """Apply a partial update to the active rep's slice plane, then
    republish + render. Called from the UI panel via a controller
    method. Passing all three None is a no-op (still republishes —
    cheap, and useful as a forced refresh hook)."""
    rep_path = getattr(state, "active_representation_path", "") or ""
    if rep_path:
        source_registry.slice_set(rep_path, enabled=enabled, axis=axis, offset=offset)
    publish_slice_state(state, source_registry)
    if view is not None:
        try:
            pvsimple.Render(view=view)
        except Exception:
            pass
    try:
        controller.view_update()
    except Exception:
        pass
