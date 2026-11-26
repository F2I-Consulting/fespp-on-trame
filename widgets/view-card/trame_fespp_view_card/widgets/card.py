from trame_client.widgets.core import AbstractElement

from trame_fespp_view_card import module


class HtmlElement(AbstractElement):
    """Base element that registers this package's Vue module with the server."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["FloatingCard"]


class FloatingCard(HtmlElement):
    """A draggable, resizable tool card, kept within its view container.

    Decoupled from any picker: open it from a toolbar, a radial menu, anything;
    the host opens and closes it through ``open`` and fills its default slot
    with the tool content.

    The parent element MUST be ``position: relative; overflow: hidden``: the
    card is absolutely positioned inside it. A drag keeps the title bar inside
    those bounds and the parent clips the rest; a resize is clamped to them.
    A card in one view therefore never spills over another view. The host sets
    the default size per tool (``width`` / ``height``); the user can then
    resize. Clicking a card brings it to the front.

    Visibility is the ``open`` prop, not ``v_show``: the card is teleported
    into a dock column when docked, where a v-show on the wrapper would not
    reach it.

    Docking: the title bar docks the card into the host's left / right / bottom dock
    column (``dock_left`` / ``dock_right`` are CSS selectors of two flex
    columns the host renders beside the render, e.g. ``#fc-dock-left-view_1``)
    and floats it back. Cards docked in one column stack and share its height;
    the column is as wide as its widest card. The render, a ``flex: 1``
    sibling of the columns, shrinks beside them. ``dock0`` is the dock the
    card starts in, so a host that saves ``geometry`` restores the layout.

    ``target`` names what the tool acts on, shown after the title
    ("Slicers · Geogrid"); the host writes it, the card only shows it.

    Panel mode (``in_panel``): the card is shown in a panel of the view's
    dock, whose tab carries the title (with the target) and the close. The
    card renders only its body: no header, drag, resize, geometry event or
    z-order. The dock registers each open panel in
    ``window.__fpCardSlots`` under ``panel_slot`` (e.g. ``"view_1:tree"``);
    while it is there the body is teleported into the panel, otherwise it
    stays inside the card element, which the host keeps in a hidden
    reservoir. The body is never unmounted: a closed card keeps its client
    state (scroll, typed fields, expanded folders). ``open`` still says
    whether it shows.

    Props:
        title, target, open, x0, y0, width, height (0 = auto), min_width,
        min_height, resizable, dock_left, dock_right, dock_bottom,
        dock0 ('float' | 'left' | 'right' | 'bottom'),
        in_panel (bool, default False), panel_slot (the dock panel's key)
    Events:
        close, dock(mode: 'float' | 'left' | 'right' | 'bottom'),
        geometry({x, y, w, h, dock}) after a drag, a resize or a dock change;
        none in panel mode
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("floating-card", children, **kwargs)
        self._attr_names += [
            "title", "target", "open", "x0", "y0", "width", "height",
            "min_width", "min_height", "resizable", "dock_left", "dock_right", "dock_bottom",
            "dock0", "in_panel", "panel_slot",
        ]
        self._event_names += ["close", "dock", "geometry"]
