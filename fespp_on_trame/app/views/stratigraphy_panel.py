"""StratigraphyPanel — the stratigraphic column as a view of its own (the
session's time-depth model is a card of the 3D view since 03/11:
app/views/tools_config, key "timedepth").

Contract
--------
Input:     ``server``, ``view_id``.
Behaviour: renders ``StratigraphicColumn`` (widgets/stratigraphy) over the
           column parsed server-side by ``engine/stratigraphy`` straight from
           the loaded EPC parts.
Reads:     ``ui_strati_columns``, ``ui_strati_selected_by_view``,
           ``ui_strati_note``, ``ui_strati_titles``.
Writes:    through ``controller.strati_select`` the rank shown in this panel,
           through ``controller.strati_pick`` the marked unit.

A panel, not a card of the 3D view's toolbar: the data is session-wide (it
comes from the files, not from a scene) and the chart has nothing to do with
a render view — it neither reads the camera nor draws in it. As a panel it
can be sized, docked and put beside the well log, which is where a column is
actually read.
"""
from trame.widgets import html


class StratigraphyPanel:
    def __init__(self, server, view_id, pv_view=None):
        from trame_fespp_stratigraphy.widgets import StratigraphicColumn

        self.server = server
        self.view_id = vid = str(view_id)
        self.html_view = None
        ctrl = server.controller

        with html.Div(style="width:100%; height:100%; overflow:hidden;"):
            StratigraphicColumn(
                columns=("ui_strati_columns", []),
                # the rank and the marked unit are per panel: a panel that
                # chose none shows the first rank
                selected=(f"(ui_strati_selected_by_view && ui_strati_selected_by_view['{vid}'])"
                          f" || (ui_strati_columns && ui_strati_columns[0] && ui_strati_columns[0].uuid)"
                          f" || ''",),
                highlight=(f"(ui_strati_titles && ui_strati_titles['{vid}'])"
                           f" || ''",),
                note=("ui_strati_note", ""),
                select=(ctrl.strati_select, f"[$event, '{vid}']"),
                pick=(ctrl.strati_pick, f"[$event, '{vid}']"),
            )
