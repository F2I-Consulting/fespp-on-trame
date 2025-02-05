from typing import Any

# need the * import for grid extractor plugin
from paraview.simple import *
from paraview import simple as pvsimple
from collections import deque
from trame_server import Server
from pathlib import Path

from wish_wells_viewer.app.utils.data import (
    ColoringArrayInformation,
    DataInformation,
    DataType,
)

DEFAULT_COLOR = "Solid Color"

EPC_READER_GUI_NAME = "EPCReader"
GRID_SLICE_EXTRACTOR_REGISTRATION_NAME = "grid_slice_extractor"
EXTRACT_BLOCK_REGISTRATION_NAME = "extract_block"
PROGRAMMABLE_FILTER_REGISTRATION_NAME = "programmable_filter_registration_name"
GRIDS_EXTRACT_BLOCK = "grids_extract_block"
WELLS_EXTRACT_BLOCK = "wells_extract_block"


WELL_TYPE_TO_COLOR = {
    "OP": ("0.25", "0.66", "0"),
    "WI": ("0", "0.69", "0.94"),
    "GI": ("1", "0.65", "0.38"),
    "GP": ("0.93", "0", "0")
}


def get_pv_extent_script(extent):
    return f"""pdi = self.GetInput()
pdo = self.GetOutput()

extents = list({extent})

data = vtk.vtkIntArray()
data.SetNumberOfComponents(6)
data.SetNumberOfTuples(2)
data.SetName("Extents")
data.SetComponent(0, 0, extents[0])
data.SetComponent(0, 1, extents[1])
data.SetComponent(0, 2, extents[2])
data.SetComponent(0, 3, extents[3])
data.SetComponent(0, 4, extents[4])
data.SetComponent(0, 5, extents[5])

data.SetComponent(1, 0, extents[0])
data.SetComponent(1, 1, extents[1])
data.SetComponent(1, 2, extents[2])
data.SetComponent(1, 3, extents[3])
data.SetComponent(1, 4, extents[4])
data.SetComponent(1, 5, extents[5])

pdo.GetFieldData().AddArray(data)
"""


def get_grid_slice_extractor():
    return pvsimple.FindSource(GRID_SLICE_EXTRACTOR_REGISTRATION_NAME)


def get_extract_block():
    return pvsimple.FindSource(EXTRACT_BLOCK_REGISTRATION_NAME)


def get_programmable_filter():
    return pvsimple.FindSource(PROGRAMMABLE_FILTER_REGISTRATION_NAME)


def get_epc_reader() -> Any:
    return pvsimple.FindSource(EPC_READER_GUI_NAME)


def get_grids_extract_block() -> Any:
    return pvsimple.FindSource(GRIDS_EXTRACT_BLOCK)


def get_wells_extract_block() -> Any:
    return pvsimple.FindSource(WELLS_EXTRACT_BLOCK)


def get_render_view() -> Any:
    return pvsimple.GetActiveViewOrCreate("RenderView")


def get_wells_solid_block_colors(data_hierarchy_wells):
    queue = deque([data_hierarchy_wells])

    selectors = []

    while queue:
        node = queue.popleft()
        if node["name"] in WELL_TYPE_TO_COLOR.keys():
            selectors.append(node["path"].replace('/data', '/assembly', 1))
            selectors.extend(WELL_TYPE_TO_COLOR[node["name"]])
            continue

        for child in node["children"]:
            queue.append(child)

    return selectors


def initialize_mesh_engine(
    server: Server, *, fespp_plugin_path: Path, slicing_plugin_path: Path
) -> None:
    state = server.state
    controller = server.controller

    def update_ijk_ranges_state():
        programmable_filter = get_programmable_filter()
        arr = programmable_filter.CellData.GetArray("ijk")

        if not arr:
            return

        state.range_i = arr.GetRange(0)
        state.range_j = arr.GetRange(1)
        state.range_k = arr.GetRange(2)
        state.slices_range_i = arr.GetRange(0)
        state.slices_range_j = arr.GetRange(1)
        state.slices_range_k = arr.GetRange(2)
        state.flush()

    pvsimple.LoadPlugin(str(fespp_plugin_path))
    pvsimple.LoadPlugin(str(slicing_plugin_path), ns=globals())

    state.setdefault("data_hierarchy_grids", {})
    state.setdefault("data_hierarchy_wells", {})
    state.setdefault("grids_selectors", [])
    state.setdefault("wells_selectors", [])
    state.setdefault("selected_data_selectors", [])
    state.setdefault("coloring_arrays", [])
    state.setdefault("selected_coloring_array", "Solid Color")
    state.range_i = [0, 0]
    state.range_j = [0, 0]
    state.range_k = [0, 0]
    state.slices_range_i = [0, 0]
    state.slices_range_j = [0, 0]
    state.slices_range_k = [0, 0]

    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path: str) -> None:
        reader = pvsimple.EnergisticsPackagingConventionsEPCReader(
            registrationName=EPC_READER_GUI_NAME
        )
        reader.addfile = [epc_file_path]
        reader.Selectors = ["/data"]  # Load the full data

        server.controller.update_data_information()

        grids_extract = pvsimple.ExtractBlock(
            registrationName=GRIDS_EXTRACT_BLOCK, Input=reader
        )
        print(server.state.data_hierarchy_grids)
        di_grids: DataInformation = DataInformation.from_dict(
            server.state.data_hierarchy_grids
        )
        grids_extract.Selectors = [di_grids.path]

        wells_extract = pvsimple.ExtractBlock(
            registrationName=WELLS_EXTRACT_BLOCK, Input=reader
        )
        di_wells: DataInformation = DataInformation.from_dict(
            server.state.data_hierarchy_wells
        )
        wells_extract.Selectors = [di_wells.path]

        state.file_loaded = True

    @controller.set("define_slicing_pipeline")
    def define_slicing_pipeline() -> None:
        grids_extract = get_grids_extract_block()

        merge_blocks = pvsimple.MergeBlocks(
            registrationName="MERGE_BLOCKS", Input=grids_extract
        )

        merge_vector_components = pvsimple.MergeVectorComponents(registrationName="merge_vector_components", Input=merge_blocks)
        merge_vector_components.AttributeType = "Cell Data"
        merge_vector_components.XArray = "I_index"
        merge_vector_components.YArray = "J_index"
        merge_vector_components.ZArray = "K_index"
        merge_vector_components.OutputVectorName = "ijk"

        pvsimple.UpdatePipeline(proxy=merge_vector_components)

        programmable_filter = pvsimple.ProgrammableFilter(
            registrationName=PROGRAMMABLE_FILTER_REGISTRATION_NAME,
            Input=merge_vector_components,
        )
        grids_extract = get_grids_extract_block()
        programmable_filter.CopyArrays = True
        programmable_filter.Script = get_pv_extent_script(grids_extract.GetDataInformation().DataInformation.GetExtent())

        update_ijk_ranges_state()

        grid_slice_extractor = GridSliceandCellsExtractor(
            registrationName=GRID_SLICE_EXTRACTOR_REGISTRATION_NAME,
            Input=programmable_filter,
        )
        grid_slice_extractor.UsePython = False
        grid_slice_extractor.Expression = "i=0 | j=0 | k=0"

        render_scene()

    @state.change("slices_range_i", "slices_range_j", "slices_range_k")
    def update_slice(slices_range_i, slices_range_j, slices_range_k, **kwargs):
        grid_slice_extractor = get_grid_slice_extractor()

        expr = f"(i>={slices_range_i[0]} & i<={slices_range_i[1]})| (j>={slices_range_j[0]} & j<={slices_range_j[1]}) | (k>={slices_range_k[0]} & k<={slices_range_k[1]})"
        grid_slice_extractor.Expression = expr
        pvsimple.UpdatePipeline(proxy=grid_slice_extractor)

        server.controller.view_update()

    def update_data_selectors() -> None:
        reader = get_epc_reader()
        wells_extract = get_wells_extract_block()
        grids_extract = get_grids_extract_block()

        if not reader:
            return

        wells_extract.Selectors = [
            data_path
            for data_path in server.state.selected_data_selectors
            if data_path in server.state.wells_selectors
        ]
        grids_extract.Selectors = [
            data_path
            for data_path in server.state.selected_data_selectors
            if data_path in server.state.grids_selectors
        ]
        render_scene()

    def get_display_properties() -> Any:
        """get display properties of the mesh reprensetation"""
        if not get_grid_slice_extractor() or not get_render_view():
            return None
        return pvsimple.GetDisplayProperties(
            get_grid_slice_extractor(), view=get_render_view()
        )

    def render_scene() -> None:
        """
        Re-render the scene
        """
        grid_slice_extractor = get_grid_slice_extractor()
        wells_extract = get_wells_extract_block()
        render_view = get_render_view()

        pvsimple.Show(proxy=grid_slice_extractor, view=render_view)
        wells_extract_display = pvsimple.Show(proxy=wells_extract, view=render_view)

        selectors = get_wells_solid_block_colors(server.state.data_hierarchy_wells)
        wells_extract_display.BlockColors = selectors
        pvsimple.ResetCamera(view=render_view)
        # Reset Center of Rotation
        render_view.CenterOfRotation = pvsimple.GetActiveCamera().GetFocalPoint()
        pvsimple.Render(view=render_view)

        server.controller.view_reset_camera()
        server.controller.view_update()

    def update_coloring_arrays() -> None:
        active_source = get_grid_slice_extractor()

        coloring_arrays = [
            ColoringArrayInformation(field=None, array_name=DEFAULT_COLOR).to_dict()
        ]

        # Get Points Arrays
        nb_point_arrays = active_source.PointData.GetNumberOfArrays()
        if nb_point_arrays:
            coloring_arrays += [
                ColoringArrayInformation(
                    "POINTS", active_source.PointData.GetArray(i).Name
                ).to_dict()
                for i in range(nb_point_arrays)
            ]

        # Get Cell Arrays
        nb_cell_arrays = active_source.CellData.GetNumberOfArrays()
        if nb_cell_arrays:
            coloring_arrays += [
                ColoringArrayInformation(
                    "CELLS", active_source.CellData.GetArray(i).Name
                ).to_dict()
                for i in range(nb_cell_arrays)
            ]

        # Get Field Arrays
        nb_field_arrays = active_source.FieldData.GetNumberOfArrays()
        if nb_field_arrays:
            coloring_arrays += [
                ColoringArrayInformation(
                    "FIELD", active_source.FieldData.GetArray(i).Name
                ).to_dict()
                for i in range(nb_field_arrays)
            ]
            coloring_arrays += [
                ColoringArrayInformation("FIELD", "vtkBlockColors").to_dict()
            ]

        state.coloring_arrays = coloring_arrays
        state.coloring_list = [
            coloring_info["array_name"] for coloring_info in state.coloring_arrays
        ]

        if state.selected_coloring_array not in state.coloring_list:
            state.selected_coloring_array = DEFAULT_COLOR
            state.dirty("selected_coloring_array")

    def color_by(coloring_information: ColoringArrayInformation) -> None:
        data_display_properties = get_display_properties()
        render_view = get_render_view()

        if not data_display_properties:
            return
        if coloring_information.field is None:
            pvsimple.ColorBy(data_display_properties, None)
        else:
            pvsimple.ColorBy(
                data_display_properties,
                (coloring_information.field, coloring_information.array_name),
            )
            lut = pvsimple.GetColorTransferFunction(
                coloring_information.array_name, representation=data_display_properties
            )
            data_display_properties.RescaleTransferFunctionToDataRange(True, False)

            scalar_bar = pvsimple.GetScalarBar(ctf=lut, view=render_view)
            scalar_bar.Visibility = True

        pvsimple.UpdateScalarBars(render_view)

    @controller.set("update_data_information")
    def update_data_information() -> None:
        reader = get_epc_reader()
        data_info = reader.GetDataInformation().DataInformation
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

    @state.change("selected_data_selectors")
    def on_selected_data_changed(**kwargs) -> None:
        update_data_selectors()
        update_coloring_arrays()

    @state.change("selected_coloring_array")
    def on_selected_coloring_array_changed(**kwargs) -> None:
        for element in state.coloring_arrays:
            converted_element: ColoringArrayInformation = (
                ColoringArrayInformation.from_dict(element)
            )
            if converted_element.array_name == state.selected_coloring_array:
                if converted_element.field is not None:
                    color_by(converted_element)
                    render_scene()
