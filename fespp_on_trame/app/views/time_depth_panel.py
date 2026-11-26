"""The ``timedepth`` view kind — the session's time-depth model: its velocity
model, its laws side by side and their tracks. ONE for the session, anchored along
the whole bottom of the layout, whatever the number of 3D views.

Mount point only: the widget is ``trame_fespp_stratigraphy``'s ``TimeDepthModel``,
its figures come from app/features/time_depth_law. The colours of its tracks are
those of the 3D view in use (app/features/time_depth_pins). What the tracks' zoom
reads goes in the tab row, as a 3D view's strip does (app/views/render_panel).
"""
from trame.widgets import html

from fespp_on_trame.app.views.widgets.view_chrome import chrome_tools

_CHROME = chrome_tools(180)


class TimeDepthPanel:
    def __init__(self, server, view_id, pv_view=None):
        from trame_fespp_stratigraphy.widgets import TimeDepthModel

        self.server = server
        self.view_id = str(view_id)
        with html.Div(classes="tdp",
                      style="position:relative; height:100%; width:100%; min-height:0;"
                            " background:#fff; display:flex; flex-direction:column;"):
            html.Div(classes="tdp-chrome", style=_CHROME,
                     mousedown="$event.stopPropagation()", click="$event.stopPropagation()")
            TimeDepthModel(
                law=("ui_time_depth_law", {}),
                colors=("ui_time_depth_colors", {}),
                tab=True,
                edit=(server.controller.time_depth_law_edit, "[$event]"),
            )
        self.html_view = None  # non-render kind
