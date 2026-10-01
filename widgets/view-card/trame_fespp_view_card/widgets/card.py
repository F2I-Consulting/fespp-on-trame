from trame_client.widgets.core import AbstractElement

from trame_fespp_view_card import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["FloatingCard"]


class FloatingCard(HtmlElement):
    """A draggable + resizable tool card, clamped to its view container.

    Decoupled from any picker — open it from a toolbar, a radial menu, anything;
    the host just shows/hides it (``v_show``) and fills its default slot.

    The parent element MUST be ``position: relative; overflow: hidden`` — the
    card is absolutely positioned inside it and BOTH its drag and its resize are
    clamped to those bounds, so a card in view 1 can never drift/grow over
    view 2. The host sets the default size per tool (``width`` / ``height``); the
    user can then resize. Clicking a card brings it to front. Default slot = the
    tool content.

    Visibility is the ``open`` prop (not ``v_show``: the card is teleported
    into a dock column when docked, where a v-show on the wrapper would not
    reach it).

    DOCKING: the title bar docks the card into the host's LEFT / RIGHT dock
    column (``dock_left`` / ``dock_right`` = CSS selectors of two flex columns
    the host renders beside the render, e.g. ``#fc-dock-left-view_1``) and
    floats it back. Cards docked in one column STACK and share its height;
    the column is as wide as its widest card. The render, a ``flex: 1``
    sibling of the columns, shrinks beside them.

    ``target`` names what the tool acts on, shown after the title
    ("Slicers · Geogrid"); the host writes it, the card only shows it.

    Props:
        title, target, open, x0, y0, width, height (0 = auto), min_width,
        min_height, resizable, dock_left, dock_right
    Events:
        close, dock(mode: 'float' | 'left' | 'right')
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("floating-card", children, **kwargs)
        self._attr_names += [
            "title", "target", "open", "x0", "y0", "width", "height",
            "min_width", "min_height", "resizable", "dock_left", "dock_right",
            "dock0",
        ]
        self._event_names += ["close", "dock", "geometry"]
