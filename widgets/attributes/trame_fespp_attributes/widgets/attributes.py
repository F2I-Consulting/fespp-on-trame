from trame_client.widgets.core import AbstractElement

from trame_fespp_attributes import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["AttributesPanel"]


class AttributesPanel(HtmlElement):
    """Per-view Values card (custom Vue, no Vuetify).

    A paged table of the active node's VALUES: a geometry by its cells (id,
    I J K on an IJK grid) or its points (id, X Y Z) with its ticked
    properties, the one colouring the view marked; a property on its whole
    grid or on a part of it; every row the filter keeps copied as CSV. The
    colorBy is OWNED by the tree's property eyes; the node's XML is the
    XML explorer's, a view of its own.

    Props — bind to THIS view's state::

        active_node  : title of the active node ("" = none, the panel shows
                       its empty state); the card frame names it, the panel
                       draws no header of its own
        values       : {count, total, offset, assoc, columns, rows, min, max,
                       only, picked, picked_rows, highlight, supports, part}
                       — one page of the node's values, or {error};
                       `count` = rows matching the filter, `total` = all
                       rows, `picked` = the node's cells the 3D selection
                       holds, `picked_rows` = those on this page,
                       `highlight` = the column colouring the view,
                       `supports` = [{value, label}] the parts of its grid a
                       property can be read on ("" the whole grid), `part`
                       = the one read
        values_csv   : the answer to export_values, {n, name, text} or
                       {n, error}

    Events::

        load_values({offset, min, max, only, assoc, filter, part})
                                          compute the page starting at
                                          `offset`; min / max (null = no
                                          bound) filter the column `filter`,
                                          `only` keeps the cells selected in
                                          3D, `part` reads a property on a
                                          part of its grid
        export_values({..., n})           every row the same request keeps,
                                          as CSV, answered in values_csv
                                          under `n`
        highlight([indices])              rows selected in the table (multi)
                                          to highlight in the view; [] clears
        extract("keep" | "remove")        what is highlighted kept, or taken
                                          out, as a new object under the grid

    Every event the Vue component emits must be listed in `_event_names`:
    trame writes no binding for a name missing there, so the event reaches
    nobody.

    Example::

        AttributesPanel(
            active_node=("ui_active_node_by_view['view-1']",),
            values=("ui_node_values_by_view['view-1']",),
            values_csv=("ui_node_values_csv_by_view['view-1']",),
            load_values=(ctrl.node_values, "[$event, 'view-1']"),
            export_values=(ctrl.node_values_csv, "[$event, 'view-1']"),
            highlight=(ctrl.node_highlight, "[$event, 'view-1']"),
        )
    """

    def __init__(self, **kwargs):
        super().__init__("attributes-panel", **kwargs)
        self._attr_names += ["active_node", ("active_key", "activeKey"), "values", "values_csv",
                             ("layer_map", "layerMap")]
        self._event_names += ["load_values", "export_values", "highlight", "hover", "extract", ("read_node", "read-node"),
                              ("load_map", "load-map"), ("map_cell", "map-cell")]
