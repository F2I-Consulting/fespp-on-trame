from trame_client.widgets.core import AbstractElement

from trame_fespp_title3dview import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["Title3dView"]


class Title3dView(HtmlElement):
    """The camera strip of ONE 3D view's TITLE BAR.

    Gestures, not a panel: framing the data, looking down an axis, a zoom
    notch and the interaction mode are things you reach for mid-drag, so they
    live open in the chrome rather than behind a toolbar icon.

    Props:
        cursor: True = the MOUSE (show position: the scene held still, the
                pointer reads what is under it), False = the HAND (the
                scene moves)
        mode  : "3D" | "2D" — this view's interaction mode (2D locks the
                rotation, for a map-like read)
        globe : this view draws on the Earth — the framings below are
                computed on local-CRS bounds and would aim at the other side
                of the planet, so they are drawn DEAD with the reason in
                their tooltip (the Globe card carries its own framings)
        rep_style / rep_styles : how every block of this view is drawn, and
                the choices on offer (the select is hidden without choices)
        flat  : False (default) = lit, True = exact colours, no shading —
                a lit surface reads a different colour than its legend says.
                Offered on the Earth too.
    Events:
        set-cursor(bool) — the wanted pointer: True = mouse, False = hand
        set-mode(mode) / reset() / axis("+x"|"+y"|"+z") / zoom(factor)
        set-style(name) / frame("earth") (on the Earth only)
        set-flat(bool) — the wanted mode: True = exact colours, False = lit;
                bound in Python as ``set_flat=(ctrl.x, "[$event, vid]")``

    Stateless: every gesture is computed by the host (boot's nav_* +
    view_interaction_mode controllers), so the strip and the Navigation card
    drive the very same camera code.
    """

    def __init__(self, **kwargs):
        super().__init__("title3d-view", **kwargs)
        self._attr_names += ["cursor", "mode", "globe", "flat",
                             # NOT "style": a reserved DOM attribute, which
                             # Vue takes for CSS -- the prop never arrives and
                             # the element's whole attribute serialisation
                             # goes with it
                             ("rep_style", "repStyle"),
                             ("rep_styles", "repStyles")]
        self._event_names += [("set_cursor", "set-cursor"),
                              ("set_mode", "set-mode"), "reset", "axis", "zoom",
                              ("set_style", "set-style"),
                              ("set_flat", "set-flat"), "frame"]
