from trame_client.widgets.core import AbstractElement

from trame_fespp_navigation import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["ViewContextMenu"]


class ViewContextMenu(HtmlElement):
    """Right-click menu of a 3D view.

    The server picks what is under the pointer and publishes the menu
    (position, the object's title, and the entries that apply to it), so the
    widget never has to know which actions suit a grid vs a wellbore.

    Props:
        menu    {open, x, y, w, h, title, path, items:[{key,label}]}; x/y are
                coordinates inside the view container and w/h its size, so a
                click near the edge flips the menu back inside instead of
                overflowing the panel
    Events:
        pick    the chosen entry's key
        close   dismissed (outside click, second right-click, Escape)
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("view-context-menu", children, **kwargs)
        self._attr_names += ["menu"]
        self._event_names += ["pick", "close"]
