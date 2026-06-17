"""Shared per-view routing for the Attributes-drawer feature dispatchers
(slicer / slice / clip / threshold).

The single home for the three primitives those dispatchers share:
  1. which panel does this edit target? (drawer picker → active → …)
  2. what is that panel's RepInScene / pv_view?
  3. render it and push the frame to the right vtk.js client(s).

Each caller keeps only its own nuance (slice/clip resolve the panel
3-tier and pass an explicit fallback view; slicer/threshold resolve it
2-tier and read the scene registry off the server context)."""
from paraview import simple as pvsimple


def target_panel_id(state, scene_registry=None):
    """The panel an Attributes-drawer edit targets:
    `drawer_target_view_id` (the drawer picker, follows the active panel
    unless pinned) → `fespp_active_panel_id` (active focus) → the first
    known scene (ONLY when `scene_registry` is given).

    Pass a `scene_registry` for the 3-tier form (slice/clip), which returns
    a panel id or None. Omit it for the 2-tier form (slicer/threshold),
    which returns "" when nothing resolves (boot window)."""
    target = getattr(state, "drawer_target_view_id", "") or ""
    if target:
        return target
    active = getattr(state, "fespp_active_panel_id", "") or ""
    if active:
        return active
    if scene_registry is not None:
        ids = scene_registry.view_ids()
        return ids[0] if ids else None
    return ""


def resolve_rep(state, scene_registry, panel_id):
    """The RepInScene for (`panel_id`, the active `rep_path`), or None."""
    if scene_registry is None or not panel_id:
        return None
    rep_path = getattr(state, "active_representation_path", "") or ""
    if not rep_path:
        return None
    return scene_registry.get_rep(panel_id, rep_path)


def scene_pv_view(scene_registry, panel_id, fallback_view=None):
    """The panel's `pv_view` via `scene_registry`, else `fallback_view`
    (the engine's legacy single view, used during early boot)."""
    if scene_registry is not None and panel_id:
        try:
            scene = scene_registry.get_scene(panel_id)
            if scene is not None and getattr(scene, "pv_view", None) is not None:
                return scene.pv_view
        except Exception:
            pass
    return fallback_view


def push_to_clients(controller, panel_id):
    """Dual push: the target panel's vtk.js client (`view_update_for`) AND
    the active panel's (`view_update`). Covers follow mode (target == active,
    one effective update) and pinned mode (target != active, both refreshed)."""
    try:
        controller.view_update_for(panel_id)
    except Exception:
        pass
    try:
        controller.view_update()
    except Exception:
        pass


def render_and_push(controller, pv_view, panel_id):
    """Server-render `pv_view` (if any), then dual-push to clients."""
    if pv_view is not None:
        try:
            pvsimple.Render(view=pv_view)
        except Exception:
            pass
    push_to_clients(controller, panel_id)
