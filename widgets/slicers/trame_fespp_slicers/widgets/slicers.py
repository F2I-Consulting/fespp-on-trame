from trame_client.widgets.core import AbstractElement

from trame_fespp_slicers import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["SlicersPanel"]


class SlicersPanel(HtmlElement):
    """The Geometry slicer of one view (the Slicers card; the PO's manager,
    28/10): the shared slicer card (widgets/_shared/components/FpSlicer) on
    the I, J, K of the view's grid — the Property slicer is the same card on
    properties. Range: boxes shown together, in a box each axis's ranges
    joined by ∪ or ∩, a range dragged whole; Slice: cuts of one index each;
    a player bar under every slider. The widget knows nothing about the
    engine; the host (app/features/geometry_slicer) applies the gestures.

    Props::

        view_id  the view this panel slices
        card     ui_geometry_card__<vid>: {card {mode, subjects, boxes, cuts},
                 subjects, addable, fixed, target, targets, all_visible, note}
        player   ui_geometry_player__<vid>: {} or {entry, index, count,
                 label, playing, speed, rates}
        views    the render views, sources of the copy menu

    Events::

        edit({op, ...})     one gesture (app/features/slicer_card_host)
        copy_from(view_id)  copy that view's slicing onto this one
    """

    def __init__(self, **kwargs):
        super().__init__("slicers-panel", **kwargs)
        self._attr_names += ["view_id", "card", "player", "views"]
        self._event_names += ["edit", "copy_from"]
