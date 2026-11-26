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
        globe : this view draws on the Earth — the reset framing and the
                Navigation card are computed on local-CRS bounds and would
                aim at the other side of the planet, so they are disabled
                with the reason in their tooltip (the Globe card carries its
                own framings)
        nav_open : this view's Navigation card is open (its button is here)
        rep_style / rep_styles : how every block of this view is drawn, and
                the choices on offer (the select is hidden without choices)
        empty : the view shows nothing yet — the mouse that reads, the
                framings and the zoom are greyed with the reason (the
                hand and the settings — mode, style, shading — stay)
        bare  : the view draws one thing on its own (the velocity model in
                the Stratigraphy panel): the style and the shading are
                greyed with the reason, the Depth / Time switch is offered
                whatever the data holds
        linkable / linked : the camera link offered in the strip (a
                view without cards), and the titles of the views this
                one moves with ("" = none)
        flat  : False (default) = lit, True = exact colours, no shading —
                a lit surface reads a different colour than its legend says.
                Offered on the Earth too.
        vdomain / domains : "depth" | "time", the vertical domain the view
                draws, and the domains the loaded data holds — the switch
                is offered when there are two (the PO, 28/10)
        z_scale : the view's vertical exaggeration, slid or typed
    Events:
        set_cursor(bool) — the wanted pointer: True = mouse, False = hand
        set_mode(mode) / reset() / navigation() — the Navigation card
        set_style(name) / frame("earth") (on the Earth only)
        set_flat(bool) — the wanted mode: True = exact colours, False = lit
        set_domain("depth" | "time") — the wanted vertical domain
        set_zscale(number) — the wanted vertical exaggeration
        toggle_link() — link the camera, or unlink it (linkable only)

    Stateless: every gesture is computed by the host controllers (boot's
    nav_* camera controllers, view_interaction_mode, view_cursor_mode,
    set_rep_style, set_flat_colors, globe_frame), so the strip and the
    Navigation card drive the very same camera code.
    """

    def __init__(self, **kwargs):
        super().__init__("title3d-view", **kwargs)
        self._attr_names += ["cursor", "mode", "globe", "flat", "empty", "bare",
                             "linkable", "linked", ("nav_open", "navOpen"),
                             "vdomain", "domains", ("z_scale", "zScale"),
                             # NOT "style": a reserved DOM attribute that Vue
                             # applies as CSS, so the prop never arrives and
                             # the element's whole attribute serialisation
                             # breaks with it
                             ("rep_style", "repStyle"),
                             ("rep_styles", "repStyles")]
        self._event_names += [("set_cursor", "set-cursor"),
                              ("set_mode", "set-mode"), "reset", "navigation",
                              ("set_style", "set-style"),
                              ("set_flat", "set-flat"), "frame",
                              ("set_domain", "set-domain"),
                              ("set_zscale", "set-zscale"),
                              ("toggle_link", "toggle-link")]
