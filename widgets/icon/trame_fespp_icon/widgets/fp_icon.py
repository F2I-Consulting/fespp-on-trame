from trame_client.widgets.core import AbstractElement

from trame_fespp_icon import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["FpIcon"]


class FpIcon(HtmlElement):
    """One icon of the application's own set, for the layout the application
    builds itself — a Vuetify button takes its icon as a PROP, which can
    only be a name, so a button that must draw an object of the model nests
    this instead.

    Props::

        icon       "fespp-<name>" | an SVG path      the drawing
        size       int                               px, 20 in a bar
        mono       bool                              one ink, as a bar wants
        declared   str                               the colour the data declares
        disabled   bool                              greyed by a filter
        title      str

    A name the set does not hold draws the "unknown" mark, says so in the
    tooltip and raises ``data-fp-incomplete``, which the browser harness
    fails on: an icon never silently draws nothing.
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("fp-icon", children, **kwargs)
        self._attr_names += ["icon", "size", "mono", "declared", "disabled", "title"]
