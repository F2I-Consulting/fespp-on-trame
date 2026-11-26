from trame_fespp_stratigraphy.widgets.stratigraphic_column import HtmlElement

__all__ = ["TimeDepthModel"]


class TimeDepthModel(HtmlElement):
    """The session's time-depth model, as a card of a 3D view (the PO,
    03/11: a widget of the 3D view, docked at its bottom): Pre-fill, the
    zone, the time range, the cells and the K layers, the TDLaws' tracks
    side by side on one depth scale.

    Pure display, like the column: `app/features/time_depth_law` publishes
    the model and applies the gestures.

    Props:
        law   the model (app/features/time_depth_law's ``ui_time_depth_law``)
        tab   true: always open, no fold (the card is its whole host)
        colors the view's colours of the velocity ({lo, hi, stops, log},
              app/features/time_depth_pins), the tracks' too
    Events:
        edit  a gesture on the model (its dict)
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("time-depth-law", children, **kwargs)
        self._attr_names += ["law", "tab", "colors"]
        self._event_names += ["edit"]
