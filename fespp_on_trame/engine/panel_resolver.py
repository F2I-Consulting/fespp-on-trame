"""Per-panel resolution helpers, shared by visibility + active-array
dispatch.

The trame multi-view exposes panel IDs via `server.context.multi_view`.
These tiny helpers translate a panel ID into the right PV view / HTML
view, falling back to the legacy "active view" when no panel context
is supplied."""


def active_panel_id(server):
    """The id of the render panel the current interaction targets, or
    None when no multi-view is mounted yet.

    `mv._active_panel_id` tracks the focused DOCKVIEW panel, which can
    be the Statistics tab; every caller here writes a colour or
    visibility bucket keyed by view, so a non-render id must be coerced
    to a render panel (view_routing.resolve_active_render_panel)."""
    mv = getattr(server.context, "multi_view", None)
    raw = getattr(mv, "_active_panel_id", None) if mv is not None else None
    if raw is None:
        return None
    from fespp_on_trame.engine.view_routing import resolve_active_render_panel
    return resolve_active_render_panel(server.state, raw)
