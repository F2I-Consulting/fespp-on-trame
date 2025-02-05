from paraview import simple  # type: ignore
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify, paraview, html
from trame_server import Server
from typing import Literal

from wish_wells_viewer.constants import TRAME_APP_TITLE, PUBLIC_PATH
from wish_wells_viewer.app.utils.data import DataInformation
from wish_wells_viewer.app.utils.data_treeview import add_data_hierarchy_to_drawer

from trame.assets.local import LocalFileManager


class SlicerControls(html.Div):
    def __init__(self, index: Literal["i", "j", "k"]):
        super().__init__(style="display: flex; align-items: center;")

        mode_var = f"slices_range_{index}_mode"
        range_var = f"range_{index}"
        slices_range_var = f"slices_range_{index}"

        with self:
            vuetify.VRangeSlider(
                v_if=(f"{mode_var} === 'range'"),
                label=index.upper(),
                strict=True,
                min=(f"{range_var}[0]",),
                max=(f"{range_var}[1]",),
                step=1,
                v_model=(slices_range_var,),
                thumb_label="always",
                update_modelValue="console.log($event)",
            )

            vuetify.VSlider(
                v_else="",
                label=index.upper(),
                min=(f"{range_var}[0]",),
                max=(f"{range_var}[1]",),
                step=1,
                thumb_label="always",
                model_value=(f"{slices_range_var}[0]",),
                update_modelValue=f"{slices_range_var} = [$event, $event]",
            )

            vuetify.VSwitch(
                v_model=(
                    mode_var,
                    "range",
                ),
                style="margin-left: 1.5rem;",
                label=(mode_var,),
                false_value="range",
                true_value="slice",
                update_modelValue=f"{slices_range_var} = [{slices_range_var}[0], {slices_range_var}[0]]",
            )


def ui(server: Server, **kwargs) -> None:
    # Get TotalEnergies logo from public folder
    localFileManager = LocalFileManager(PUBLIC_PATH)
    localFileManager.url("logo", "logo.png")

    with SinglePageWithDrawerLayout(server, width=450) as layout:
        layout.title.set_text(TRAME_APP_TITLE)

        with layout.icon:
            vuetify.VImg(src=localFileManager["logo"], height="35", width="35")

        with layout.toolbar:
            pass

        with layout.drawer, vuetify.VCard(style="box-shodow: None;"):
            with vuetify.VTabs(v_model=("tab", None)):
                with vuetify.VTab(value="data"):
                    html.Div("Data")
                with vuetify.VTab(value="representation"):
                    html.Div("Representation")
                with vuetify.VTab(value="ijk_slicing"):
                    html.Div("IJK Slicing")
            with vuetify.VCardText(), vuetify.VWindow(v_model=("tab",)):
                with vuetify.VWindowItem(value="data"):
                    add_data_hierarchy_to_drawer(
                        server,
                        (
                            DataInformation.from_dict(server.state.data_hierarchy_grids)
                            if server.state.data_hierarchy_grids
                            else None
                        ),
                        "Grids",
                    )
                    add_data_hierarchy_to_drawer(
                        server,
                        (
                            DataInformation.from_dict(server.state.data_hierarchy_wells)
                            if server.state.data_hierarchy_wells
                            else None
                        ),
                        "Wells",
                    )
                with vuetify.VWindowItem(value="representation"):
                    vuetify.VSelect(
                        label="Color by",
                        v_model=("selected_coloring_array",),
                        items=("coloring_list",),
                    )
                with vuetify.VWindowItem(value="ijk_slicing"):
                    with vuetify.VCard(flat=True, elevation=0), vuetify.VCardText(
                        style="padding-top: 3rem;"
                    ):
                        SlicerControls("i")
                        SlicerControls("j")
                        SlicerControls("k")

        with layout.content:
            with vuetify.VContainer(
                fluid=True, classes="pa-0 fill-height", v_if="file_loaded"
            ):
                view = paraview.VtkRemoteView(
                    simple.GetActiveViewOrCreate("RenderView") if simple else None,
                    interactive_ratio=1,
                    interactive_quality=70,
                    namespace="view",
                    style="width: 100%; height: 100%;",
                )
                # Link view callbacks
                server.controller.view_replace = view.replace_view
                server.controller.view_update = view.update
                server.controller.view_reset_camera = view.reset_camera
                server.controller.on_server_ready.add(server.controller.view_update)

        layout.footer.hide()

        return layout
