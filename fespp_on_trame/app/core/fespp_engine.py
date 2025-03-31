from typing import Any

import json
# need the * import for grid extractor plugin
from paraview.simple import *
from paraview import simple as pvsimple
from trame.app import get_server
from trame_server import Server
from pathlib import Path

from fespp_on_trame.app.core.fespp_tree import Tree
from fespp_on_trame.app.core.reservoir.fespp_ijkgrid import IjkGrid

EPC_COLLECTOR_GUI_NAME = "EPCCollector"

# extract => hide block in EPCCOLLECTOR
def epc_collector_extract(name):
    epc_collector = get_epc_collector()
    epc_collector.SetPropertyWithName('objecttoextract', name)

def get_epc_collector() -> Any:
    return pvsimple.FindSource(EPC_COLLECTOR_GUI_NAME)

def get_source(source_name) -> Any:
    return pvsimple.FindSource(source_name)

def delete_source(source) -> Any:
    pvsimple.Delete(source)

def exist_src(source_name) -> Any:
    return pvsimple.FindSource(source_name) is not None

def get_render_view() -> Any:
    return pvsimple.GetActiveViewOrCreate("RenderView")

def get_representation(source) -> Any:
    render_view = get_render_view()
    if render_view:
        return pvsimple.GetDisplayProperties(proxy=source, view=render_view)
    else:
        return None

def create_ExplicitStructuredGridCrop_source(p_name, p_input):
    pvsimple.ExplicitStructuredGridCrop(registrationName=p_name, Input=p_input)
    return get_source(p_name)
    
def initialize_fespp_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    state = server.state
    controller = server.controller

    pvsimple.LoadPlugin(str(fespp_plugin_path))
    pvsimple.LoadPlugin('/opt/paraview/lib/paraview-5.13/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.so')

# data share for selection
    state.setdefault("fespp_data_selectors", []) # node path to selector for load FESPP
    state.setdefault("fespp_selection_status", 'Empty') # Empty | Change | Apply

    state.setdefault("block_selector", []) # node path to BlockSelector for representation
    state.setdefault("object_to_extract", []) # node name list to extract in new source
    
    state.setdefault("tree", Tree(None))
    state.setdefault("ijk_grid", IjkGrid())
    state.flush()
        

    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str) -> None:
        # create EPC collector Source
        collector = pvsimple.EPCCollector(registrationName=EPC_COLLECTOR_GUI_NAME)
        # add epc_file_path to EPC Collector Source
        collector.SetPropertyWithName("Files", epc_file_path)
        collector.UpdatePipelineInformation()
        controller.update_data_information()
        state.file_loaded = True

    # create the treeview structure from the FESPP vtkdatasembly
    @controller.set("update_data_information")
    def update_data_information() -> None:
        collector = get_epc_collector()
        data_info = collector.GetDataInformation()
        #state.data_assembly = data_info.GetDataAssembly()
        state.tree = Tree(data_info.GetDataAssembly())
        
    @state.change("fespp_data_selectors")
    def on_change_fespp_data_selectors(**kwargs) -> None:
        if state.fespp_selection_status != 'Change':
            state.fespp_selection_status = 'Change'
            state.flush()

        collector = get_epc_collector()
        if not collector:
            return
        
        render_view=get_render_view()
        
        # load node path selected
        collector.SetPropertyWithName('Selectors', state.fespp_data_selectors)
        #collector.ApplyColors
        collector.UpdatePipelineInformation()
        pvsimple.Show(proxy=get_epc_collector(), view=render_view)
        pvsimple.Render(view=render_view)

        # hide in vtkPartitionedDataSet: extracted object
        representation = get_representation(collector)
        representation.Assembly='Assembly'

        state.fespp_selection_status = 'Apply'

        controller.view_reset_camera()
        controller.view_update()
        pvsimple.Show(proxy=get_epc_collector(), view=render_view)

    @state.change("fespp_selection_status")
    def on_change_fespp_selection_status(**kwargs):
        if state.fespp_selection_status == 'Apply':
            if len(state.ui_select_node_reservoir) > 0:
                state.ijk_grid.set_node_id(state.ui_select_node_reservoir[0])
        
