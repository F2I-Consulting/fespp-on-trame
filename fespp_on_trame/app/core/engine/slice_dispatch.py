"""Slice-plane dispatch — single axis-aligned plane per (rep, view).

Three controller entry points:
  - `publish_slice_state(state, scene_registry, ...)` — pushes the
    active panel's active rep's slice descriptor into the
    `ui_slice_*` trame vars so the panel binds to it.
  - `slice_set(state, controller, scene_registry, view, ...,
    panel_id=None)` — applies an (enabled, axis, offset) patch on
    the RepInScene that owns the slice and republishes. `panel_id`
    defaults to the currently active panel.

The dispatcher routes through `scene_registry` so each (rep, view)
has its own slice filter. The active rep is read from
`state.active_representation_path`.
"""
from fespp_on_trame.app.core.engine import view_routing


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def _resolve_active_panel_id(state, scene_registry):
    """Target panel id for slice edits."""
    return view_routing.target_panel_id(state, scene_registry)


def _resolve_rep(state, scene_registry, panel_id):
    """Look up the RepInScene for (panel_id, active rep_path)."""
    return view_routing.resolve_rep(state, scene_registry, panel_id)


def publish_slice_state(state, scene_registry, panel_id=None):
    """Push the active rep's slice descriptor (from the active panel's
    RepInScene) into `ui_slice_*` so the UI panel binds to it.
    Idempotent."""
    panel_id = panel_id or _resolve_active_panel_id(state, scene_registry)
    rep = _resolve_rep(state, scene_registry, panel_id)
    desc = rep.slice_state() if rep is not None else {
        "enabled": False, "axis": "X", "offset": 0.0,
        "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
    }
    bounds = list(desc.get("bounds") or [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    axis = desc.get("axis") or "X"
    i = _AXIS_INDEX.get(axis, 0)
    lo = float(bounds[2 * i])
    hi = float(bounds[2 * i + 1])
    step = (hi - lo) / 1000.0 if hi > lo else 0.001

    state.ui_slice_enabled = bool(desc.get("enabled"))
    state.ui_slice_axis = axis
    state.ui_slice_offset = float(desc.get("offset") or 0.0)
    state.ui_slice_bounds = bounds
    state.ui_slice_offset_min = lo
    state.ui_slice_offset_max = hi
    state.ui_slice_offset_step = step


def slice_set(state, controller, scene_registry, view,
              enabled=None, axis=None, offset=None, panel_id=None):
    """Apply a partial update to the (panel_id, active_rep) slice
    plane, then republish + render. `panel_id` defaults to the active
    panel. Calling with all three (enabled/axis/offset) None is a
    no-op pipeline-wise but still republishes — useful as a forced
    refresh hook on rep activation."""
    panel_id = panel_id or _resolve_active_panel_id(state, scene_registry)
    rep = _resolve_rep(state, scene_registry, panel_id)
    if rep is not None:
        rep.slice_set(enabled=enabled, axis=axis, offset=offset)
    publish_slice_state(state, scene_registry, panel_id=panel_id)
    # Render the OWNING view (a per-view edit must refresh THAT panel, not
    # just whatever is globally active), then dual-push to clients (pinned +
    # follow modes).
    pv_view = view_routing.scene_pv_view(scene_registry, panel_id, fallback_view=view)
    view_routing.render_and_push(controller, pv_view, panel_id)
