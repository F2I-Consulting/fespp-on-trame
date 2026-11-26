from trame_client.widgets.core import AbstractElement

from trame_fespp_timereal import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["TimeRealPanel"]


class TimeRealPanel(HtmlElement):
    """The Time & Realizations card of ONE view (the PO, 29/10: the same
    card as the slicers): the shared slicer card (widgets/_shared/
    components/FpSlicer) on the view's time step, its realizations and its
    vector components — a cut of one value each, the player stepping it.
    The host (app/features/timereal_slicer) applies the gestures.

    Props::

        view_id
        card     ui_timereal_card__<vid> (see the Geometry slicer)
        player   ui_timereal_player__<vid>

    Events::

        edit({op, ...})   one gesture (app/features/slicer_card_host)
    """

    def __init__(self, **kwargs):
        super().__init__("time-real-panel", **kwargs)
        self._attr_names += ["view_id", "card", "player"]
        self._event_names += ["edit"]
