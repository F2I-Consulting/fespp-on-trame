from paraview import simple  # type: ignore
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify3, paraview, html
from trame_server import Server
from typing import Literal

from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH
from fespp_on_trame.app.utils.data import DataInformation
from fespp_on_trame.app.utils.data_treeview import add_data_hierarchy_to_drawer

from trame.assets.local import LocalFileManager

vuetify3.enable_lab()

class SlicerControls(html.Div):
    def __init__(self, index: Literal["i", "j", "k"]):
        super().__init__(style="display: flex; align-items: center;")

        mode_var = f"slices_range_{index}_mode"
        range_var = f"range_{index}"
        slices_range_var = f"slices_range_{index}"

        with self:
            vuetify3.VRangeSlider(
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

            vuetify3.VSlider(
                v_else="",
                label=index.upper(),
                min=(f"{range_var}[0]",),
                max=(f"{range_var}[1]",),
                step=1,
                thumb_label="always",
                model_value=(f"{slices_range_var}[0]",),
                update_modelValue=f"{slices_range_var} = [$event, $event]",
            )

            vuetify3.VSwitch(
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

# -----------------------------------------------------------------------------
# default Card
# -----------------------------------------------------------------------------
def create_card(title, icon, height=None):
    card_props = {"classes": "pa-0",
                  "elevation": 10,
                  "flat": True, 
                  "outlined": False, 
                  "tile": True,
                  "style": "border: solid; border-color: #d0d3d4;"}
    if height:  
        card_props["height"] = height

    with vuetify3.VCard(**card_props):
        vuetify3.VDivider()
        card_title_props = {"classes": "d-flex align-center py-1", "style": "background-color: #b3b6b7;"}
        with vuetify3.VCardTitle(**card_title_props):
            vuetify3.VIcon(icon)
            html.Div(title)
        vuetify3.VDivider()
        if height:
            height_value = int(height[:-2])
            max_height_value = height_value - 5
            max_height = f"{max_height_value}vh"
            return vuetify3.VCardText(style=f"overflow-y: auto; max-height: {max_height};")
        else:
            return vuetify3.VCardText(style="overflow-y: auto;")

def ui(server: Server, **kwargs) -> None:
    # Get logo from public folder
    localFileManager = LocalFileManager(PUBLIC_PATH)
    localFileManager.url("logo", "logo.png")

    with SinglePageWithDrawerLayout(server, width=450) as layout:
        layout.title.set_text(TRAME_APP_TITLE)

        with layout.icon:
            vuetify3.VImg(src=localFileManager["logo"], height="35", width="35")

        with layout.toolbar:
            pass

        with layout.drawer, vuetify3.VCard(style="box-shodow: None;"):
            with vuetify3.VTabs(v_model=("tab", None)):
                with vuetify3.VTab(value="reservoir"):
                    html.Div("Reservoir")
                with vuetify3.VTab(value="surface"):
                    html.Div("Surface")
                with vuetify3.VTab(value="well"):
                    html.Div("Well")
                with vuetify3.VTab(value="representation"):
                    html.Div("Representation")
                with vuetify3.VTab(value="ijk_slicing"):
                    html.Div("IJK Slicing")
            with vuetify3.VCardText(), vuetify3.VWindow(v_model=("tab",)):
                with vuetify3.VWindowItem(value="reservoir"):
                    # Treeview CARD
                    with create_card(
                        "Project treeview",
                        "mdi-file-tree",
                        "60vh"
                    ):
                        add_data_hierarchy_to_drawer(
                            server,
                            (
                                DataInformation.from_dict(server.state.data_hierarchy_grids)
                                if server.state.data_hierarchy_grids
                                else None
                            ),
                            "Grids",
                        )
                    # Attribut Node CARD
                    with create_card(
                        "Node Attribut",
                        "mdi-information",
                        "30vh"
                    ):
                        pass
                    
                with vuetify3.VWindowItem(value="surface"):
                    # Treeview CARD
                    with create_card(
                        "Project treeview",
                        "mdi-file-tree",
                        "60vh"
                    ):
                        pass
                    # Attribut Node CARD
                    with create_card(
                        "Node Attribut",
                        "mdi-information",
                        "30vh"
                    ):
                        pass
                
                with vuetify3.VWindowItem(value="well"):
                    # Treeview CARD
                    with create_card(
                        "Project treeview",
                        "mdi-file-tree",
                        "60vh"
                    ):
                        add_data_hierarchy_to_drawer(
                            server,
                            (
                                DataInformation.from_dict(server.state.data_hierarchy_wells)
                                if server.state.data_hierarchy_wells
                                else None
                            ),
                            "Wells",
                        )
                    # Attribut Node CARD
                    with create_card(
                        "Node Attribut",
                        "mdi-information",
                        "30vh"
                    ):
                        pass

        with layout.content:
            with vuetify3.VContainer(
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
