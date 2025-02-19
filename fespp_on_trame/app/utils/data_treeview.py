from typing import Optional
from trame.widgets import vuetify3 as vuetify
from trame_server import Server
from fespp_on_trame.app.utils.data import DataInformation, DataType

def get_icon_from_item(item: DataInformation):
    if item.data_type == DataType.COLLECTION.value:
        return "mdi-folder"
    if item.data_type == DataType.REPRESENTATION.value:
        return "mdi-file"
    
    return "mdi-help"

def unselect_item(server: Server, item: DataInformation):
    """
    Unselect an item and all its children if it has some
    """
    if item.path in server.state.selected_data_selectors:
        server.state.selected_data_selectors.remove(item.path)
    for child in item.children:
        unselect_item(server, DataInformation.from_dict(child))

def select_item(server: Server, item: DataInformation):
    """
    Select an item and all its children if it has some
    """
    if item.path not in server.state.selected_data_selectors:
        server.state.selected_data_selectors.append(item.path)
    for child in item.children:
        select_item(server, DataInformation.from_dict(child))

def add_item_to_treeview(server: Server, item: DataInformation) -> None:
    """
    Add a new line in the data treeview panel.
    """
    def on_click() -> None:
        if item.path in server.state.selected_data_selectors:
            unselect_item(server, item)
        else:
            select_item(server, item)
        server.state.dirty("selected_data_selectors")

    def define_list_item_content():
        with vuetify.Template(v_slot_prepend=""):
            vuetify.VIcon(get_icon_from_item(item))
            vuetify.VCheckboxBtn(
                density="compact",
                v_model=("selected_data_selectors",),
                value=item.path,
                click=(
                    on_click,
                    "$event.stopPropagation()",
                ),
            )

    if len(item.children) == 0:
        with vuetify.VListItem(
            density="compact",
            title=item.name,
        ):
            define_list_item_content()
    else:
        # Define an itemGroup with a set of items
        with vuetify.VListGroup(
            style="--prepend-width: 8px;"
        ):
            with vuetify.Template(v_slot_activator="{ props }"), vuetify.VListItem(
                v_bind="props",
                density="compact",
                title=item.name,
            ):
                define_list_item_content()

            # Handle item's children
            for child in item.children:
                add_item_to_treeview(server, DataInformation.from_dict(child))

def add_data_hierarchy_to_drawer(server: Server, data_hierarchy: Optional[DataInformation], data_type: str) -> None:
    """
    Add a selectable data treeview based on a VListGroup as VTreeView is not yet implemented/stable in vuetify3.
    data_type should either be "Grids" or "Wells".
    """
    if not data_hierarchy:
        return

    with vuetify.VList(density="compact"):
        with vuetify.VListGroup(
                style="--prepend-width: 8px;"
            ):
            with vuetify.Template(v_slot_activator="{ props }"):
                vuetify.VListItem(
                    v_bind="props",
                    density="compact",
                    title=data_type,
                )
            
            add_item_to_treeview(server, data_hierarchy)
