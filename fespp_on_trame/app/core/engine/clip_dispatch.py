"""Clip-plane dispatch — analog of slice_dispatch.

Three controller entry points:
  - `publish_clip_state(state, scene_registry, ...)` — pushes the
    active rep's clip descriptor into the `ui_clip_*` trame vars so
    the panel binds to it.
  - `clip_set(state, controller, scene_registry, view, ..., panel_id=None)`
    — applies a partial patch on the RepInScene's clip and republishes.
  - `set_edit_mode(...)` — sets `state.ui_plane_edit_mode` to
    "slice" / "clip" / None and nudges both filters so the 3D
    widget rebinds.

Phase 1.b.1: routes through `scene_registry` for per-(rep, view)
clip ownership. The active rep stays read from
`state.active_representation_path`.
"""
from paraview import simple as pvsimple


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def _resolve_active_panel_id(state, scene_registry):
    """Best-effort target panel id for the clip plane edits.

    See `slice_dispatch._resolve_active_panel_id` for the resolution
    order — `drawer_target_view_id` first (Attributes drawer picker),
    `fespp_active_panel_id` next (active focus), first scene last."""
    target = getattr(state, "drawer_target_view_id", "") or ""
    if target:
        return target
    active = getattr(state, "fespp_active_panel_id", "") or ""
    if active:
        return active
    ids = scene_registry.view_ids() if scene_registry is not None else []
    return ids[0] if ids else None


def _resolve_rep(state, scene_registry, panel_id):
    if scene_registry is None or not panel_id:
        return None
    rep_path = getattr(state, "active_representation_path", "") or ""
    if not rep_path:
        return None
    return scene_registry.get_rep(panel_id, rep_path)


def publish_clip_state(state, scene_registry, panel_id=None):
    panel_id = panel_id or _resolve_active_panel_id(state, scene_registry)
    rep = _resolve_rep(state, scene_registry, panel_id)
    desc = rep.clip_state() if rep is not None else {
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


def clip_set(state, controller, scene_registry, view,
             enabled=None, axis=None, offset=None, inside_out=None,
             panel_id=None):
    """Apply a partial update to the (panel_id, active_rep) clip
    plane, then republish + render. `panel_id` defaults to the
    currently active panel."""
    panel_id = panel_id or _resolve_active_panel_id(state, scene_registry)
    rep = _resolve_rep(state, scene_registry, panel_id)
    if rep is not None:
        rep.clip_set(
            enabled=enabled, axis=axis, offset=offset,
            inside_out=inside_out,
        )
    publish_clip_state(state, scene_registry, panel_id=panel_id)
    target_view = view
    scene = scene_registry.get_scene(panel_id) if scene_registry is not None else None
    if scene is not None and scene.pv_view is not None:
        target_view = scene.pv_view
    if target_view is not None:
        try:
            pvsimple.Render(view=target_view)
        except Exception:
            pass
    # Push the freshly-rendered frame to BOTH the target panel
    # (pinned-mode safe) and the active panel (legacy). See the
    # equivalent block in slice_dispatch.slice_set for context.
    try:
        controller.view_update_for(panel_id)
    except Exception:
        pass
    try:
        controller.view_update()
    except Exception:
        pass


def set_edit_mode(state, controller, scene_registry, view, mode):
    """Set which filter the 3D plane widget binds to: "slice",
    "clip", or None. Re-applies both filters on the active rep's
    RepInScene so the widget is created / destroyed accordingly."""
    if mode not in (None, "slice", "clip"):
        return
    state.ui_plane_edit_mode = mode
    panel_id = _resolve_active_panel_id(state, scene_registry)
    rep = _resolve_rep(state, scene_registry, panel_id)
    if rep is not None:
        # No-state-change patch — `set()` with all-None still calls
        # `_apply` which re-evaluates widget gating.
        try:
            rep.slice_set()
        except Exception:
            pass
        try:
            rep.clip_set()
        except Exception:
            pass
    target_view = view
    scene = scene_registry.get_scene(panel_id) if scene_registry is not None else None
    if scene is not None and scene.pv_view is not None:
        target_view = scene.pv_view
    if target_view is not None:
        try:
            pvsimple.Render(view=target_view)
        except Exception:
            pass
    # Push the freshly-rendered frame to BOTH the target panel
    # (pinned-mode safe) and the active panel (legacy). See the
    # equivalent block in slice_dispatch.slice_set for context.
    try:
        controller.view_update_for(panel_id)
    except Exception:
        pass
    try:
        controller.view_update()
    except Exception:
        pass
