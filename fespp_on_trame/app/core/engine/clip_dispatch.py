"""Clip-plane dispatch — analog of slice_dispatch.

Exposes two controller entry points:
  - `clip_publish_state(...)` — pushes the active rep's clip
    descriptor into the `ui_clip_*` trame vars so the panel binds
    to it. Called on rep activation, and whenever the clip changes.
  - `clip_set(...)` — applies a partial (enabled, axis, offset,
    inside_out) patch on the rep's `ClipPlane` and republishes.

The "active rep" is read from `state.active_representation_path` —
the rep whose properties are currently edited by the side-panels.
"""
from paraview import simple as pvsimple


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def publish_clip_state(state, source_registry):
    rep_path = getattr(state, "active_representation_path", "") or ""
    desc = source_registry.clip_state(rep_path) if rep_path else {
        "enabled": False, "axis": "X", "offset": 0.0,
        "inside_out": False,
        "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
    }
    bounds = list(desc.get("bounds") or [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    axis = desc.get("axis") or "X"
    i = _AXIS_INDEX.get(axis, 0)
    lo = float(bounds[2 * i])
    hi = float(bounds[2 * i + 1])
    step = (hi - lo) / 1000.0 if hi > lo else 0.001

    state.ui_clip_enabled = bool(desc.get("enabled"))
    state.ui_clip_axis = axis
    state.ui_clip_offset = float(desc.get("offset") or 0.0)
    state.ui_clip_inside_out = bool(desc.get("inside_out"))
    state.ui_clip_bounds = bounds
    state.ui_clip_offset_min = lo
    state.ui_clip_offset_max = hi
    state.ui_clip_offset_step = step


def clip_set(state, controller, source_registry, view,
             enabled=None, axis=None, offset=None, inside_out=None):
    """Apply a partial update to the active rep's clip plane, then
    republish + render."""
    rep_path = getattr(state, "active_representation_path", "") or ""
    if rep_path:
        source_registry.clip_set(
            rep_path,
            enabled=enabled, axis=axis, offset=offset,
            inside_out=inside_out,
        )
    publish_clip_state(state, source_registry)
    if view is not None:
        try:
            pvsimple.Render(view=view)
        except Exception:
            pass
    try:
        controller.view_update()
    except Exception:
        pass


def set_edit_mode(state, controller, source_registry, view, mode):
    """Set which filter the 3D plane widget binds to: "slice", "clip",
    or None. Re-applies both filters so their widgets get created /
    destroyed accordingly."""
    if mode not in (None, "slice", "clip"):
        return
    state.ui_plane_edit_mode = mode
    # Re-apply both filters so their `_apply` runs and checks the new
    # edit mode. Cheap when the filter is disabled (early return).
    rep_path = getattr(state, "active_representation_path", "") or ""
    if rep_path:
        # Nudge slice and clip with no state change — `set()` with all
        # None still calls `_apply` and updates widget gating.
        try:
            source_registry.slice_set(rep_path)
        except Exception:
            pass
        try:
            source_registry.clip_set(rep_path)
        except Exception:
            pass
    if view is not None:
        try:
            pvsimple.Render(view=view)
        except Exception:
            pass
    try:
        controller.view_update()
    except Exception:
        pass
