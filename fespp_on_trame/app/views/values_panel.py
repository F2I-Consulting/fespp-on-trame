"""The ``values`` view kind — the values of what the 3D view in use has active:
one page of a geometry by its cells or its points, of a property on its whole
grid or on a part of it, and the Map of a K layer. ONE for the session, whatever
the number of 3D views: it reads the one last worked in
(``fespp_last_render_panel_id``), and follows it.

Mount point only: the widget is ``trame_fespp_attributes``, its figures come from
app/features/values_card and values_map, named per 3D view.
"""
from trame.widgets import html
from trame_fespp_attributes.widgets.attributes import AttributesPanel

_IN_USE = "fespp_last_render_panel_id"


class ValuesPanel:
    def __init__(self, server, view_id, pv_view=None):
        self.server = server
        self.view_id = str(view_id)
        ctrl = server.controller
        with html.Div(style="height:100%; width:100%; min-height:0; background:#fff;"
                            " display:flex; flex-direction:column; overflow:auto;"):
            AttributesPanel(
                active_node=(f"(ui_active_node_by_view && ui_active_node_by_view[{_IN_USE}]) || ''",),
                active_key=(f"(ui_values_key_by_view && ui_values_key_by_view[{_IN_USE}]) || ''",),
                values=(f"(ui_node_values_by_view && ui_node_values_by_view[{_IN_USE}]) || {{}}",),
                values_csv=(f"(ui_node_values_csv_by_view && ui_node_values_csv_by_view[{_IN_USE}]) || {{}}",),
                load_values=(ctrl.node_values, f"[$event, {_IN_USE}]"),
                export_values=(ctrl.node_values_csv, f"[$event, {_IN_USE}]"),
                highlight=(ctrl.node_highlight, f"[$event, {_IN_USE}]"),
                # a log's sample under the pointer: lit in blue in the 3D views and the log view
                hover=(ctrl.values_hover, f"[$event, {_IN_USE}]"),
                # Clear: the rows highlighted and the cells selected in 3D let go
                clear=(ctrl.selection_clear, f"[{_IN_USE}]"),
                extract=(ctrl.values_extract, f"[$event, {_IN_USE}]"),
                read_node=(ctrl.values_read, f"[$event, {_IN_USE}]"),
                # the Map: a K layer of an IJK grid, coloured (app/features/values_map)
                layer_map=(f"(ui_node_map_by_view && ui_node_map_by_view[{_IN_USE}]) || {{}}",),
                load_map=(ctrl.node_values_map, f"[$event, {_IN_USE}]"),
                map_cell=(ctrl.node_map_cell, f"[$event, {_IN_USE}]"),
            )
        self.html_view = None  # non-render kind
