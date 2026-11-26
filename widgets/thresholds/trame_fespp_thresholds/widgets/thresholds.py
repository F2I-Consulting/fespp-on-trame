from trame_client.widgets.core import AbstractElement

from trame_fespp_thresholds import module


class HtmlElement(AbstractElement):
    """Base element: the first use enables the module, so the server serves
    the widget bundle."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["ThresholdsPanel"]


class ThresholdsPanel(HtmlElement):
    """The Property slicer of one view (the Thresholds card; the PO's
    manager, 28/10): the shared slicer card (widgets/_shared/components/
    FpSlicer) on the properties added to it — the Geometry slicer is the
    same card on I, J, K. The host (app/features/property_slicer) applies
    the gestures to the view's threshold chain.

    Props::

        view_id
        card     ui_property_card__<vid> (see the Geometry slicer)
        player   ui_property_player__<vid>

    Events::

        edit({op, ...})   one gesture (app/features/slicer_card_host)
    """

    def __init__(self, **kwargs):
        super().__init__("thresholds-panel", **kwargs)
        self._attr_names += ["view_id", "card", "player"]
        self._event_names += ["edit"]
