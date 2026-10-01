"""Trame demo for the autonomous DataExplorerTree widget.

The widget takes ONE input — a vtkDataAssembly (serialized to XML) — owns its
own interaction state, and writes its outputs to trame state variables. The host
just *watches* those variables with ``@state.change`` — no per-event wiring.

The mock data is a real **Drogon** assembly (sample/drogon_assembly.xml): Grid2d
surfaces, an IjkGrid with ~250 properties, 12 wellbores with trajectories /
marker frames / log frames, plus Partial stubs — rich enough to exercise the
tree (tabs, filter, bulk-select, colours) on realistic data.

Run::

    python app.py
    python app.py --server --host 0.0.0.0 --port 8080 --timeout 0
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from trame.app import get_server
from trame.ui.html import DivLayout
from trame.widgets import html

from trame_fespp_tree.widgets.tree import DataExplorerTree

server = get_server(client_type="vue3")
state, ctrl = server.state, server.controller

# --- input: a real vtkDataAssembly (Drogon demo) serialized to XML ------------
SAMPLE = Path(__file__).parent / "sample"


def load_assembly():
    """Drogon (wells / surfaces / IjkGrid + properties + partials) merged with a
    small MultiRealization / TimeSeries sample injected into the IjkGrid, so one
    assembly exercises every node kind. Timestep labels live on the root."""
    drog = ET.parse(SAMPLE / "drogon_assembly.xml").getroot()
    mrts = ET.parse(SAMPLE / "mr_ts_assembly.xml").getroot()
    for k, v in mrts.attrib.items():
        if k.startswith("time"):
            drog.set(k, v)
    ijk = next((e for e in drog.iter() if e.get("kind") == "IjkGrid"), None)
    ugrid = next(e for e in mrts if e.get("kind") == "UnstructuredGrid")
    specials = [c for c in list(ugrid)
                if c.get("kind") in ("MultiRealization", "MultiRealizationTimeSeries", "TimeSeries")]
    if ijk is not None:
        for c in specials:
            ijk.append(c)
    return '<?xml version="1.0"?>\n' + ET.tostring(drog, encoding="unicode")


ASSEMBLY_XML = load_assembly()

# Tabs are pure kind filters; a matching node brings its whole subtree, so the
# IjkGrid pulls its properties and each Wellbore pulls its trajectory/markers/logs.
TABS = [
    {"name": "Reservoir", "kinds": ["IjkGrid", "UnstructuredGrid", "Sub"]},
    {"name": "Surface", "kinds": ["Grid2d", "Grid2dRepresentation", "TriangulatedSet", "PolylineSet", "Polyline", "PointSet"]},
    {"name": "Well", "kinds": ["Wellbore", "Trajectory", "Frame", "MarkerFrame"]},
]

CONTEXT_ACTIONS = [
    {"key": "display_all", "label": "Display in all views"},
    {"key": "zoom", "label": "Zoom to"},
    {"key": "properties", "label": "Properties…", "separatorBefore": True},
    {"key": "export", "label": "Export…"},
    {"key": "rename", "label": "Rename", "separatorBefore": True},
    {"key": "delete", "label": "Delete", "danger": True},
]


# --- input state -------------------------------------------------------------
state.assembly_xml = ASSEMBLY_XML
state.tabs_config = TABS
state.ctx_actions = CONTEXT_ACTIONS

# --- output state (the widget writes these; the host only watches them) -------
state.selected_paths = []
state.visible_paths = []
state.active_path = None
state.colour_request = None
state.context_action = None
state.status = "ready — interact with the tree; the widget owns its state"


@state.change("selected_paths")
def _on_selected(selected_paths, **kw):
    state.status = f"selected_paths changed -> {len(selected_paths or [])} loaded"


@state.change("visible_paths")
def _on_visible(visible_paths, **kw):
    state.status = f"visible_paths changed -> {len(visible_paths or [])} visible"


@state.change("active_path")
def _on_active(active_path, **kw):
    if active_path:
        state.status = f"active_path: {active_path}"


@state.change("colour_request")
def _on_colour(colour_request, **kw):
    if colour_request:
        state.status = f"colour_request: {colour_request}  (host opens its colour/colormap editor)"


@state.change("context_action")
def _on_context(context_action, **kw):
    if context_action:
        state.status = f"context_action: {context_action}"


# --- UI ----------------------------------------------------------------------
with DivLayout(server) as layout:
    layout.root.style = "margin:0;font-family:system-ui,sans-serif"
    with html.Div(style="display:flex;flex-direction:column;height:100vh"):
        with html.Div(style="width:340px;flex:1 1 0;border-right:1px solid #ccc;overflow:auto"):
            DataExplorerTree(
                assembly=("assembly_xml",),
                tabs=("tabs_config",),
                context_actions=("ctx_actions",),
                color_editing=True,
                # outputs default to these state-var names (shown for clarity);
                # the host just watches them with @state.change above.
                selected_paths="selected_paths",
                visible_paths="visible_paths",
                active_path="active_path",
                colour_request="colour_request",
                context_action="context_action",
            )
        html.Div(
            "event: {{ status }}\n"
            "selected: {{ selected_paths.length }}   visible: {{ visible_paths.length }}\n"
            "active:   {{ active_path }}",
            style="flex:0 0 auto;width:340px;padding:6px 8px;border-right:1px solid #ccc;"
            "border-top:1px solid #ddd;background:#fafafa;font:12px/1.4 monospace;color:#444;"
            "white-space:pre-wrap;word-break:break-all",
        )


if __name__ == "__main__":
    server.start()
