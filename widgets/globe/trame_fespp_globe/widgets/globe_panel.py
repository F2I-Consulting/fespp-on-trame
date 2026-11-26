from trame_client.widgets.core import AbstractElement

from trame_fespp_globe import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["GlobePanel"]


class GlobePanel(HtmlElement):
    """The card of the Globe view.

    Pure display: the host pushes the card's state
    (``boot._push_globe_state``) and routes every event to its ``globe_*``
    controllers.

    Props::

        globe         {crs, epsg, from_data, axes, where, extent,
                      geo_extent, hint, mode, opacity}
        busy          bool     the view's scene is being built (seconds):
                               the card is drawn first and says so
        textures      [name]   the Earth imagery on offer (session-wide)
        texture       str      the imagery in use
        texture_note  str      what the imagery has to say

    Events::

        epsg(text)         the typed EPSG code
        frame('earth')     frame the whole Earth
        set_texture(name)  the imagery
        opacity(number)    the Earth's opacity, 0 to 1
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("globe-panel", children, **kwargs)
        self._attr_names += ["globe", "busy", "textures", "texture",
                             ("texture_note", "textureNote")]
        self._event_names += ["epsg", "frame",
                              ("set_texture", "set-texture"), "opacity"]
