"""HealthPanel — the ``health`` view kind: what is wrong with the loaded
data, in one table (partial objects, unreadable datasets, fesapi's
messages, kinds and units, the CRS, duplicates).

Mount point only: the table and its filters are the decoupled
``trame_fespp_health`` widget (``widgets/health``); every finding is read
by ``engine/health_dispatch`` and pushed as ``ui_health`` by the
controllers ``boot`` wires (``health_refresh``, ``health_activate``,
``health_focus`` — "Show in Data health", right-clicked in a panel tree,
which names the object in the table's text filter).

Singleton: one table for the session, re-read on every load.
"""
from trame.widgets import html
from trame_fespp_health.widgets import HealthPanel as _HealthWidget


class HealthPanel:
    def __init__(self, server, view_id):
        self.server = server
        self.view_id = str(view_id)
        ctrl = server.controller
        with html.Div(style="height:100%; width:100%; background:#fff;"
                            " display:flex; flex-direction:column;"):
            _HealthWidget(
                data=("ui_health", {}),
                # "Show in Data health", right-clicked in a panel's tree:
                # the object's name lands in the text filter
                focus_on=("ui_health_focus", {}),
                refresh=(ctrl.health_refresh, "[]"),
                activate=(ctrl.health_activate, "[$event]"),
            )
        self.html_view = None  # non-render kind
