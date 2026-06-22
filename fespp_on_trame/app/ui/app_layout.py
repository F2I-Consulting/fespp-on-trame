"""Top-level UI orchestrator.

The whole app layout reads like a story:
  - declare layout-wide state defaults,
  - inject global styles,
  - mount the four UI zones (toolbar / drawer / content) + the
    hierarchy snackbar,
  - inject client-side scripts.

Each zone is built by its own zone class — Toolbar, Drawer, Content
— under `app/ui/<zone>/`."""
from trame.app import get_server
from trame.assets.local import LocalFileManager
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3, html
from trame_server import Server

import fespp_on_trame.app.core.engine as engine
from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH

from fespp_on_trame.app.ui.toolbar.toolbar import Toolbar
from fespp_on_trame.app.ui.toolbar.dialog.import_dialog import ImportDialog
from fespp_on_trame.app.ui.drawer.tree_views import TreeViews
from fespp_on_trame.app.ui.drawer.drawer import Drawer
from fespp_on_trame.app.ui.drawer.dialog.display_options_dialog import DisplayOptionsDialog
from fespp_on_trame.app.ui.content.content import Content
from fespp_on_trame.app.ui.shared.styles import inject_global_styles
from fespp_on_trame.app.ui.shared.scripts import inject_client_scripts
from fespp_on_trame.app.ui.shared.widget.hierarchy_snackbar import HierarchySnackbar
from fespp_on_trame.app.ui.shared.widget.empty_color_snackbar import EmptyColorSnackbar


server = get_server()
state = server.state
controller = server.controller

# Layout-wide state defaults. The drawer width is set once; live
# resize happens client-side (see shared/scripts.py) to avoid a
# trame round-trip per drag step.
# Boot with the Import Data dialog already open so a fresh session lands
# straight on the file picker.
state.dialog_visible = True
state.execute_action = False
state.ui_time_label = ""
state.drawer_width = 500
state.init_height_dataexplorer = "50vh"
state.init_height_attribute = "600px"
# Top AppBar visibility — toggled by the chevron button in the drawer
# tools band. The whole AppBar (title + Import button) collapses to
# zero height when False, freeing vertical space for the data area.
state.toolbar_visible = True


def ui(server: Server, **kwargs) -> None:
    """Build the main UI layout: toolbar, drawer, content, snackbar."""
    local_file_manager = LocalFileManager(PUBLIC_PATH)
    local_file_manager.url("logo", "logo.png")

    with SinglePageWithDrawerLayout(
        server,
        width=("drawer_width", 500),
    ) as layout:
        layout.title.set_text(TRAME_APP_TITLE)
        inject_global_styles()

        with layout.icon:
            vuetify3.VImg(src=local_file_manager["logo"], height="35", width="35")

        # ImportDialog is owned here because the toolbar references it
        # (the trigger button lives in the toolbar). The drawer-area
        # DisplayOptionsDialog is owned here too — its cog lives in
        # the drawer tools band but the dialog is rendered at the
        # layout level so it can overlay the whole window. The five
        # content dialogs live inside Content itself.
        import_dialog = ImportDialog(state, controller)
        display_options_dialog = DisplayOptionsDialog()

        # TreeViews is created once and shared with Drawer. The engine
        # needs the same Tree instance to walk the assembly for
        # dependency expansion, so we keep tv pinned to that.
        tv = TreeViews(controller, state, engine._tree)

        with layout.toolbar:
            Toolbar(local_file_manager, import_dialog).render()
        # Bind a v-if on the AppBar so the whole component is
        # unmounted when toggled off — Vuetify then re-computes its
        # `--v-layout-top` CSS var to 0 and VMain reclaims the
        # vertical space (which a `display:none` hack would not).
        layout.toolbar.v_if = ("toolbar_visible", True)

        with layout.drawer:
            Drawer(tv).render()

        with layout.content:
            Content(server, state, controller).render()

        # Floating show-toolbar button rendered at the layout root
        # (NOT inside layout.content) so VMain / drawer / dockview
        # can't clip it. `position: fixed` anchors it to the viewport
        # — top-right corner is the only place guaranteed not to be
        # covered by the drawer (which always occupies the left
        # edge). Variant / color / size match the hide-button in
        # Toolbar for visual continuity. Visible only while the
        # AppBar is collapsed.
        with vuetify3.VTooltip(location="left", open_delay=300, close_delay=0):
            with vuetify3.Template(v_slot_activator="{ props }"):
                vuetify3.VBtn(
                    icon="mdi-chevron-double-down",
                    v_bind="props",
                    v_if="!toolbar_visible",
                    variant="tonal",
                    color="blue-grey-darken-2",
                    size="small",
                    style=(
                        "position: fixed; top: 8px; right: 8px;"
                        " z-index: 9999;"
                    ),
                    click="toolbar_visible = true",
                )
            html.Span("Show top toolbar")

        # The Display Options dialog is rendered at the layout level
        # so it overlays the whole window when the drawer-band cog
        # opens it (rendering inside the drawer would clip it to the
        # drawer's bounds).
        display_options_dialog.render()
        inject_client_scripts()
        HierarchySnackbar().render()
        EmptyColorSnackbar().render()

        return layout
