from trame_client.widgets.core import AbstractElement

from trame_fespp_camlink import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["CameraLinkPanel"]


class CameraLinkPanel(HtmlElement):
    """The Synchronize camera card of ONE render view: one tick per other render
    view, ticked when the two move together. Pure display; the host
    toggles the link symmetrically.

    Props::

        view_id   str
        views     [{id, title, globe?}]   fespp_render_panels
        links     {id: [id]}              view_links, symmetric

    Events::

        toggle(other_id)
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("camera-link-panel", children, **kwargs)
        self._attr_names += [("view_id", "viewId"), "views", "links"]
        self._event_names += ["toggle"]
