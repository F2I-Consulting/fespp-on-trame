from typing import Any

# need the * import for grid extractor plugin
from paraview.simple import *
from paraview import simple as pvsimple
from collections import deque
from trame_server import Server
from pathlib import Path

from fespp_on_trame.app.utils.data import (
    ColoringArrayInformation,
    DataInformation,
    DataType,
)

DEFAULT_COLOR = "Solid Color"

EPC_COLLECTOR_GUI_NAME = "EPCCollector"

def get_epc_collector() -> Any:
    return pvsimple.FindSource(EPC_COLLECTOR_GUI_NAME)

def get_render_view() -> Any:
    return pvsimple.GetActiveViewOrCreate("RenderView")

def initialize_mesh_engine(
    server: Server, *, fespp_plugin_path: Path, slicing_plugin_path: Path
) -> None:
    state = server.state
    controller = server.controller

    pvsimple.LoadPlugin(str(fespp_plugin_path))

    state.setdefault("data_hierarchy_grids", {})
    state.setdefault("data_hierarchy_wells", {})
    state.setdefault("grids_selectors", [])
    state.setdefault("wells_selectors", [])
    state.setdefault("selected_data_selectors", [])
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
        print("def define_slicing_pipeline")
        
    @state.change("slices_range_i", "slices_range_j", "slices_range_k")
    def update_slice(slices_range_i, slices_range_j, slices_range_k, **kwargs):
        print("def update_slice")


    def update_data_selectors() -> None:
        collector = get_epc_collector()

        if not collector:
            return

        collector.SetPropertyWithName('Selectors',server.state.selected_data_selectors)
        
        server.controller.view_reset_camera()
        server.controller.view_update()
        
        pvsimple.Show(proxy=get_epc_collector(), view=get_render_view())

    @controller.set("update_data_information")
    def update_data_information() -> None:
        collector = get_epc_collector()
        data_info = collector.GetDataInformation().DataInformation
        data_assembly = data_info.GetDataAssembly()

        def append_data_hierarchy(element_id: int, selectors: list[str]) -> None:
            element_name = None
            element_name = data_assembly.GetAttributeOrDefault(
                element_id, "label", element_name
            )
            # Remove first part of the name (keep everything after "_" char)
            element_name = element_name[element_name.find("_") + 1 :]

            element_type = None
            element_type = data_assembly.GetAttributeOrDefault(
                element_id, "type", element_type
            )


            data_path = data_assembly.GetNodePath(element_id)
            selectors.append(data_path)

            parent_item = DataInformation(
                identifier=element_id,
                path=data_path,
                name=element_name,
                data_type=int(element_type),
            )

            for i in range(data_assembly.GetNumberOfChildren(element_id)):
                child_id = data_assembly.GetChild(element_id, i)
                parent_item.children.append(append_data_hierarchy(child_id, selectors))

            return parent_item.to_dict()

        main_data_id = 0
        for i in range(data_assembly.GetNumberOfChildren(main_data_id)):
            child_id = data_assembly.GetChild(main_data_id, i)
            child_type = None
            child_type = data_assembly.GetAttributeOrDefault(
                child_id, "type", child_type
            )

            if int(child_type) == DataType.REPRESENTATION.value:
                hierarchy = state.data_hierarchy_grids
                selectors = state.grids_selectors
            else:
                hierarchy = state.data_hierarchy_wells
                selectors = state.wells_selectors

            hierarchy.update(append_data_hierarchy(child_id, selectors))

        print(state.data_hierarchy_wells)
        
    @state.change("selected_data_selectors")
    def on_selected_data_changed(**kwargs) -> None:
        print("def on_selected_data_changed")
        update_data_selectors()
