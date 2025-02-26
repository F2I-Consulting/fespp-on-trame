from typing import Any

import json
# need the * import for grid extractor plugin
from paraview.simple import *
from paraview import simple as pvsimple
from collections import deque
from trame_server import Server
from pathlib import Path

EPC_COLLECTOR_GUI_NAME = "EPCCollector"

def get_epc_collector() -> Any:
    return pvsimple.FindSource(EPC_COLLECTOR_GUI_NAME)

def get_render_view() -> Any:
    return pvsimple.GetActiveViewOrCreate("RenderView")

def initialize_mesh_engine(
    server: Server, *, fespp_plugin_path: Path
) -> None:
    state = server.state
    controller = server.controller

    pvsimple.LoadPlugin(str(fespp_plugin_path))

    state.setdefault("data_hierarchy_surface", [])
    state.setdefault("data_hierarchy_well", [])
    state.setdefault("data_hierarchy_reservoir", [])
    state.setdefault("fespp_data_selectors_reservoir", [])
    state.setdefault("fespp_data_selectors_surface", [])
    state.setdefault("fespp_data_selectors_well", [])
    state.setdefault("fespp_data_selectors", [])
    state.setdefault("coloring_arrays", [])
    state.setdefault("selected_coloring_array", "Solid Color")

    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str) -> None:

        # create EPC collector Source
        collector = pvsimple.EPCCollector(
            registrationName=EPC_COLLECTOR_GUI_NAME
        )
        epcCollectorSource = pvsimple.GetActiveSource()
        # add epc_file_path to EPC Collector Source
        collector.SetPropertyWithName("Files", epc_file_path)
        collector.UpdatePipelineInformation()
        
        server.controller.update_data_information()

        state.file_loaded = True

    @controller.set("define_slicing_pipeline")
    def define_slicing_pipeline() -> None:
        pass
        
    @state.change("slices_range_i", "slices_range_j", "slices_range_k")
    def update_slice(slices_range_i, slices_range_j, slices_range_k, **kwargs):
        pass

    def update_data_selectors() -> None:
        collector = get_epc_collector()

        if not collector:
            return

        print("put Fespp -> ", server.state.fespp_data_selectors)
        collector.SetPropertyWithName('Selectors',server.state.fespp_data_selectors)
        print("get Fespp -> ", collector.Selectors)
        
        server.controller.view_reset_camera()
        server.controller.view_update()
        
        pvsimple.Show(proxy=get_epc_collector(), view=get_render_view())

    @controller.set("update_data_information")
    def update_data_information() -> None:
        collector = get_epc_collector()
        data_info = collector.GetDataInformation()
        data_assembly = data_info.GetDataAssembly()
        
        # init
        w_data_hierarchy_reservoir = []
        w_data_hierarchy_well = []
        w_data_hierarchy_surface = []

        def add_subtreeview_data(parent_id: int, child_index: int, treeview_type)-> None:
            node_id = data_assembly.GetChild(parent_id, child_index)
            node_label = None
            node_label = data_assembly.GetAttributeOrDefault(node_id, "label", node_label)
            node_title = node_label[node_label.find("_") + 1 :]
            node_type = node_label[:node_label.find("_")]
            node_path = data_assembly.GetNodePath(node_id)
            
            if treeview_type == "unknown":
                if node_type in ['IjkGrid','Sub', 'UnstructuredGrid']:
                    treeview_type = "reservoir"
                elif node_type in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                    treeview_type = "well"
                elif node_type in ['Grid2d', 'PolylineSet', 'TriangulatedSet']:
                    treeview_type = "surface"

            data = {}
                     
            data["treeview"] = {}
            data["treeview"]["parent_id"] = parent_id
            data["treeview"]["id"] = node_id
            data["treeview"]["title"] = node_title
            data["treeview"]["path"] = node_path
            data["treeview"]["type"] = node_type

            data["treeview_type"] = treeview_type
            
            children_count = data_assembly.GetNumberOfChildren(node_id)
            if children_count > 0:
                data["treeview"]["children"]=[]
                for i in range(children_count):
                    subTreeview = add_subtreeview_data(node_id, i, treeview_type)
                    data["treeview"]["children"].append(subTreeview["treeview"])
                    data["treeview_type"] = subTreeview["treeview_type"]
            return data
        
        root_id = 0
        for i in range(data_assembly.GetNumberOfChildren(root_id)):
            node_id = data_assembly.GetChild(root_id, i)
            node_label = None
            node_label = data_assembly.GetAttributeOrDefault(node_id, "label", node_label)
            node_title=node_label[node_label.find("_") + 1 :]
            node_type=node_label[:node_label.find("_")]
            node_path = data_assembly.GetNodePath(node_id)
            
            treeview_type = "unknown"
            if node_type in ['IjkGrid','Sub', 'UnstructuredGrid']:
                treeview_type = "reservoir"
            elif node_type in ['Wellbore', 'Trajectory', 'Completion', 'Perfo', 'Frame', 'MarkerFrame', 'WellboreMarker', 'SeismicWellboreFrame']:
                treeview_type = "well"
            elif node_type in ['Grid2d', 'PolylineSet', 'TriangulatedSet']:
                treeview_type = "surface"

            treeview = {}
            treeview["parent_id"] = root_id
            treeview["id"] = node_id
            treeview["title"] = node_title
            treeview["path"] = node_path
            treeview["type"] = node_type

            children_count = data_assembly.GetNumberOfChildren(node_id)
            if children_count > 0:
                treeview["children"]=[]
                for i in range(children_count):
                    subTreeview = add_subtreeview_data(node_id, i, treeview_type)
                    treeview["children"].append(subTreeview["treeview"])
                    treeview_type = subTreeview["treeview_type"]
            
                    if treeview_type == "reservoir":
                        if treeview and treeview not in w_data_hierarchy_reservoir:
                            w_data_hierarchy_reservoir.append(treeview)
                    elif treeview_type == "well":
                        if treeview and treeview not in w_data_hierarchy_well:
                            w_data_hierarchy_well.append(treeview)
                    elif treeview_type == "surface":
                        if treeview and treeview not in w_data_hierarchy_surface:
                            w_data_hierarchy_surface.append(treeview)
                        
        state.data_hierarchy_reservoir = list(w_data_hierarchy_reservoir)
        state.data_hierarchy_well = list(w_data_hierarchy_well)
        state.data_hierarchy_surface = list(w_data_hierarchy_surface)
        state.dirty("data_hierarchy_reservoir")
        state.dirty("data_hierarchy_well")
        state.dirty("data_hierarchy_surface")
        state.flush()
        
                
    @state.change("fespp_data_selectors")
    def on_selected_data_changed(**kwargs) -> None:
        print("Fespp Selectors changed:", server.state.fespp_data_selectors)
        update_data_selectors()
