"""Per-panel resolution helpers — shared by visibility + active-array
dispatch. Extracted from `boot.initialize_fespp_engine`.

The trame multi-view exposes panel IDs via `server.context.multi_view`.
These tiny helpers translate a panel ID into the right PV view / HTML
view, falling back to the legacy "active view" when no panel context
is supplied."""
from paraview import simple as pvsimple


def resolve_view_and_html_view(server, panel_id):
    """Resolve `(pv_view, html_view)` for a given `panel_id` by asking
    the multi_view context. Returns `(active_view, None)` when
    panel_id is empty / unknown — keeps the legacy single-view code
    paths working when no per-view click context is supplied."""
    if not panel_id:
        return pvsimple.GetActiveView(), None
    mv = getattr(server.context, "multi_view", None)
    if mv is None:
        return pvsimple.GetActiveView(), None
    pv_view = mv.get_pv_view(panel_id) if hasattr(mv, "get_pv_view") else None
    html_view = mv.get_html_view(panel_id) if hasattr(mv, "get_html_view") else None
    if pv_view is None:
        pv_view = pvsimple.GetActiveView()
    return pv_view, html_view


def active_panel_id(server):
    """The id of the render panel the current interaction targets, or
    None when no multi-view is mounted yet.

    `mv._active_panel_id` tracks the focused DOCKVIEW panel, which can
    be a stats / distribution tab — every caller here writes a colour or
    visibility bucket keyed by view, so a non-render id must be coerced
    to a render panel (view_routing.resolve_active_render_panel)."""
    mv = getattr(server.context, "multi_view", None)
    raw = getattr(mv, "_active_panel_id", None) if mv is not None else None
    if raw is None:
        return None
    from fespp_on_trame.app.core.engine.view_routing import resolve_active_render_panel
    return resolve_active_render_panel(server.state, raw)
