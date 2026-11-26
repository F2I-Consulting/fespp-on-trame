"""Which RENDER panel a gesture targets (loads, eye toggles, colour
buckets): `resolve_active_render_panel`.

The Attributes-drawer dispatchers' other primitives (the target panel,
its RepInScene and render view, render-and-push) went with the
per-representation model (engine/legacy); a view's render view is in
`engine/view_resources`."""


def resolve_active_render_panel(state, raw_id=None):
    """Coerce a panel id to a RENDER panel, the one loads, eye toggles
    and colour buckets must target. With the Statistics tab
    focused, the raw active id points at a non-render panel: colours and
    visibility written to that bucket would be silently lost.
    Fallback order: `raw_id` when it IS a render panel → the render panel
    last activated (`fespp_last_render_panel_id`, written by the view
    manager on every activation of a 3D view) → the first render panel.
    Returns `raw_id` untouched when no render panel is known yet (early
    boot)."""
    raw = raw_id if raw_id is not None else (getattr(state, "fespp_active_panel_id", "") or "")
    render_ids = [p.get("id") for p in (getattr(state, "fespp_render_panels", None) or [])
                  if isinstance(p, dict) and p.get("id")]
    if not render_ids or raw in render_ids:
        return raw
    last = getattr(state, "fespp_last_render_panel_id", "") or ""
    return last if last in render_ids else render_ids[0]


def model_view(state):
    """The 3D view the time-depth model's view works with: the one in use,
    the Globe aside — the model is a grid in time, the Earth draws none —
    then the first 3D view; "" when there is none."""
    last = getattr(state, "fespp_last_render_panel_id", "") or ""
    panels = [p for p in (getattr(state, "fespp_render_panels", None) or [])
              if isinstance(p, dict) and p.get("id")]
    if last not in [p["id"] for p in panels if p.get("globe")]:
        return last
    return next((p["id"] for p in panels if not p.get("globe")), "")
