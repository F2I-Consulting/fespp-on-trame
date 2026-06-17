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

Routes through `scene_registry` for per-(rep, view) clip ownership.
The active rep is read from `state.active_representation_path`.
"""
from fespp_on_trame.app.core.engine import view_routing


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def _resolve_active_panel_id(state, scene_registry):
    """Target panel id for clip edits."""
    return view_routing.target_panel_id(state, scene_registry)


def _resolve_rep(state, scene_registry, panel_id):
    return view_routing.resolve_rep(state, scene_registry, panel_id)


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
    pv_view = view_routing.scene_pv_view(scene_registry, panel_id, fallback_view=view)
    view_routing.render_and_push(controller, pv_view, panel_id)


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
    pv_view = view_routing.scene_pv_view(scene_registry, panel_id, fallback_view=view)
    view_routing.render_and_push(controller, pv_view, panel_id)
