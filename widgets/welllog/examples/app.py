"""Standalone trame app showing the WellLogCorrelation widget with mock data.

    pip install trame trame-vuetify
    pip install -e .            # this package (after building vue-components)
    python examples/app.py

then open the printed URL.
"""
import os
import sys

# mock_data sits next to this script, which is not a package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trame.app import get_server
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import html

from trame_welllog.widgets.welllog import WellLogCorrelation

from mock_data import mock_data

server = get_server(client_type="vue3")
state = server.state

state.welllog_data = mock_data()

with SinglePageLayout(server) as layout:
    layout.title.set_text("Well-log correlation")
    with layout.content:
        with html.Div(style="height:100%; width:100%;"):
            WellLogCorrelation(
                data=("welllog_data",),
                style="width:100%; height:100%;",
            )

if __name__ == "__main__":
    server.start()
