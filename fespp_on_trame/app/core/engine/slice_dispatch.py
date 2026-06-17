"""Slice-plane dispatch — single axis-aligned plane per (rep, view).

Three controller entry points:
  - `publish_slice_state(state, scene_registry, ...)` — pushes the
    active panel's active rep's slice descriptor into the
    `ui_slice_*` trame vars so the panel binds to it.
  - `slice_set(state, controller, scene_registry, view, ...,
    panel_id=None)` — applies an (enabled, axis, offset) patch on
    the RepInScene that owns the slice and republishes. `panel_id`
    defaults to the currently active panel.

Phase 1.b.1: the dispatcher routes through `scene_registry` so each
(rep, view) has its own slice filter. The "active rep" is read from
`state.active_representation_path` — same as the legacy flow.
Per-view state vars + UI re-enable land in Phase 1.b.2.
"""
from paraview import simple as pvsimple


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def _resolve_active_panel_id(state, scene_registry):
    """Best-effort target panel id for the slice plane edits.

    Prefers the Attributes drawer's `drawer_target_view_id` (which
    follows the active panel by default and can be pinned to a
    specific view via the picker in the Attributes toolbar), falls
    back to `fespp_active_panel_id` for the boot window before the
    drawer-pinned change handler has fired, falls back to the first
    known scene as a last resort."""
    target = getattr(state, "drawer_target_view_id", "") or ""
    if target:
        return target
    active = getattr(state, "fespp_active_panel_id", "") or ""
    if active:
        return active
    ids = scene_registry.view_ids() if scene_registry is not None else []
    return ids[0] if ids else None


def _resolve_rep(state, scene_registry, panel_id):
    """Look up the RepInScene for (panel_id, active rep_path)."""
    if scene_registry is None or not panel_id:
        return None
    rep_path = getattr(state, "active_representation_path", "") or ""
    if not rep_path:
        return None
    return scene_registry.get_rep(panel_id, rep_path)


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
    # Prefer rendering the owning view — when slice_dispatch is
    # called via a per-view UI in Phase 1.b.2 we want THIS specific
    # view to refresh, not just whatever was globally active.
    target_view = view
    scene = scene_registry.get_scene(panel_id) if scene_registry is not None else None
    if scene is not None and scene.pv_view is not None:
        target_view = scene.pv_view
    if target_view is not None:
        try:
            pvsimple.Render(view=target_view)
        except Exception:
            pass
    # Push the freshly-rendered frame to BOTH:
    #   - the target panel's vtk.js client (so pinned mode sees its
    #     edit immediately even when the focus is on another panel);
    #   - the active panel's client (the legacy view_update — safe
    #     to call too, the no-op cost is negligible and it covers
    #     follow-mode where target == active).
    try:
        controller.view_update_for(panel_id)
    except Exception:
        pass
    try:
        controller.view_update()
    except Exception:
        pass
