from trame_client.widgets.core import AbstractElement

from trame_fespp_stratigraphy import module


class HtmlElement(AbstractElement):
    """Base element: the first use enables the module, so the server serves
    the widget bundle."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["StratigraphicColumn"]


class StratigraphicColumn(HtmlElement):
    """The stratigraphic column of the loaded data set.

    Pure display: `engine/stratigraphy.py` parses the column from the EPC
    XML parts and hands it over already ordered and coloured. The widget
    draws the entities of one rank, time units and rock units side by side.

    Props:
        columns   [{uuid, title, ordering, index, units, entities}], one per
                  rank. Each entity is {name, kind, top, base, color,
                  color_source, ics, parent}: `kind` is group, formation,
                  member, chrono, zone, surface or other; `top` and `base`
                  are unit indices; `ics` is the matched ICS chart interval
                  {name, rank, top_ma, base_ma, chart} or None.
        selected  uuid of the rank shown (empty = the first)
        highlight name of the entity to mark (the host sets it from `pick`)
        note      why there is no column, when there is none: a parse
                  failure and a genuine absence must not read the same
    Events:
        select    a rank was chosen (its uuid)
        pick      an entity was clicked (its name)
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("stratigraphic-column", children, **kwargs)
        self._attr_names += ["columns", "selected", "highlight", "note"]
        self._event_names += ["select", "pick"]
