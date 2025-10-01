import logging
from typing import Any

import json
# need the * import for grid extractor plugin
from paraview.simple import *
from paraview import simple as pvsimple
from trame_server import Server
from pathlib import Path

from fespp_on_trame.app.core.fespp_tree import Tree
from fespp_on_trame.app.core.reservoir.fespp_ijkgrid import IjkGrid
from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.fespp_selection import Selector
import fespp_on_trame.app.core.fespp_active as fespp_active

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def initialize_fespp_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    state = server.state
    controller = server.controller

    pvsimple.LoadPlugin(str(fespp_plugin_path))
    # load slicer vtkExplicitStructuredGrid plugin 
    pvsimple.LoadPlugin('/opt/paraview/lib/paraview-5.13/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.so')

    _view = pvsimple.GetActiveViewOrCreate("RenderView")

    _tree = Tree(None)

    _collector = Collector()            # SOURCE
    _ijkGrid = IjkGrid(_collector, _tree)      # SOURCE
    
    # FESPP engine
    _selector = Selector(_ijkGrid, _tree)
    fespp_active.Activator(_tree)
    
    #=> initialize ui variable <=
    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])
    #state.setdefault("ui_representation", "Surface")
    
    state.setdefault("isLoading", False)
    state.setdefault("download_progress", 0)
    state.setdefault("download_message", "Préparation du téléchargement...")
    
    state.setdefault("fespp_data_selectors", []) # node path to selector for load FESPP

    state.setdefault("view_update", False)
    state.setdefault("view_reset_camera", False)
    state.setdefault("representation_update", False)
    state.setdefault("object_to_extract", []) # node name list to extract in new source

    state.flush()

    @controller.add("on_data_change")
    def update():
        server.controller.view_update()
        
    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str):
        state.file_loaded = _collector.add_file(epc_file_path)

    # create the treeview structure from the FESPP vtkdatasembly
    @controller.set("update_data_information")
    def update_data_information():
        collector = _collector.get_source() #get_epc_collector()
        client_side_object = collector.GetClientSideObject()
        if hasattr(client_side_object, "GetOutput"):
            output = client_side_object.GetOutput()
            if hasattr(output, "GetDataAssembly"):
                assembly = output.GetDataAssembly()
        _tree.set_tree(assembly)
        
    @state.change("fespp_data_selectors")
    def on_change_fespp_data_selectors( **kwargs):
        if _collector is None:
            return
        # load node path selected
        _collector.get_source().SetPropertyWithName('Selectors', state.fespp_data_selectors)
        _collector.get_source().UpdatePipelineInformation()
        
        pvsimple.Render(view=_view)

        # hide in vtkPartitionedDataSet: extracted object
        representation = _collector.get_representation()
        representation.Assembly='Assembly'

        if len(state.ui_select_node_reservoir) > 0:
            _ijkGrid.set_node_id(state.ui_select_node_reservoir[0])
        _ijkGrid.update_block_visibility()
        
        controller.view_replace
        state.view_update = True

        _collector.show()
        pvsimple.SetActiveSource(_collector.get_source())
        server.controller.on_data_loaded() # for ptc.TimeControl()
        server.controller.on_active_proxy_change() # for ptc.RepresentBy() / ptc.ColorBy
        pvsimple.Render(view=_view)

    #======================= Main Properties
    @state.change("ui_scale_z")
    def ui_scale_z_update(ui_scale_z, **kwargs):
        scale = [1.0,1.0, float(ui_scale_z)]
        if _collector is not None:
            _collector.scale_z = scale
            _collector.show()
        if _ijkGrid is not None:
            _ijkGrid.scale = scale
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()
        
    @state.change("representation_active")
    def update_ui_representation(representation_active, **kwargs):
        if _collector is not None:
            _collector.representationType = representation_active
            _collector.show()
        if _ijkGrid is not None:
            _ijkGrid.representationType = representation_active
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    #======================= UI: change Slicer
    @state.change("ui_slices_i", "ui_slices_j", "ui_slices_k")
    def update_slice(ui_slices_i, ui_slices_j, ui_slices_k, **kwargs):
        if _ijkGrid is not None:
            _ijkGrid.update_slices(ui_slices_i, ui_slices_j, ui_slices_k)
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()
        
    @state.change("ui_slices_range_i", "ui_slices_range_j", "ui_slices_range_k")
    def update_range_slicer(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k, **kwargs):
        if _ijkGrid is not None:
            _ijkGrid.update_volume(ui_slices_range_i, ui_slices_range_j, ui_slices_range_k)
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()
        
    @state.change("ui_slices_range_mode")
    def update_mode_slicer(**kwargs):
        if _ijkGrid is not None:
            _ijkGrid.show()
        pvsimple.Render(view=_view)
        controller.view_update()

    #======================= UI: change time
    @state.change("time_index")
    def changeTimeLabel( **kwargs):
        try:
            index = state.time_index
            if index is not None:
                label = _tree.find_attribute_value(0, f"time{pvsimple.GetTimeKeeper().TimestepValues[index]:.6f}")
                if label is not None:
                    state.ui_time_label = label
                else:
                    state.ui_time_label = f"time{pvsimple.GetTimeKeeper().TimestepValues[index]:.6f}"
        except:
            state.ui_time_label = ""

    #======================= TreeView: change selection
    @state.change("ui_select_node_surface")
    def on_change_ui_select_node_surface(**kwargs):
        if _selector is not None:
            _selector.select_node_surface()
        
    @state.change("ui_select_node_well")
    def on_change_ui_select_node_well(**kwargs):
        if _selector is not None:
            _selector.select_node_well()
    
    @state.change("ui_select_node_reservoir")
    def on_change_ui_select_node_reservoir(**kwargs):
        if _selector is not None:
            _selector.select_node_reservoir()
        
    #======================= 
    @state.change("view_reset_camera")
    def view_reset_camera(view_reset_camera, **kwargs):
        if view_reset_camera == True:
            _ijkGrid.update_block_visibility()
            controller.view_reset_camera()
            controller.view_update()
            state.view_reset_camera = False
            state.flush()
            
    @state.change("view_update")
    def view_update(view_update, **kwargs):
        if view_update == True:
            controller.view_update()
            state.view_update = False
            state.flush()
            

