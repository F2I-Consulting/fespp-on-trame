"""Drawer-scoped Display Options dialog.

Modal triggered from the drawer tools band's cog. Hosts:
  - **Load Mode** — `auto` (push selectors on every checkbox toggle)
    vs `manual` (batched, triggered by the band's Load button).
  - **Tree Hierarchy** — `flat` / `by_interpretation` /
    `by_feature_and_interpretation`. Changing it rebuilds the C++
    assembly and resets every selection / visibility / coloring state."""
from trame.app import get_server
from trame.widgets import html, vuetify3


class DisplayOptionsDialog:
    def __init__(self):
        self._server = get_server()
        self._state = self._server.state
        self._controller = self._server.controller

        self._state.setdefault("drawer_options_dialog_visible", False)
        # Expose the open hook so the drawer tools band can bind its cog click.
        self._controller.drawer_options_open = self.open

    def open(self):
        self._state.drawer_options_dialog_visible = True

    def close(self):
        self._state.drawer_options_dialog_visible = False

    def render(self):
        with vuetify3.VDialog(
            v_model=("drawer_options_dialog_visible", False),
            max_width="460",
        ):
            with vuetify3.VCard():
                with vuetify3.VCardTitle(classes="d-flex align-center pa-3"):
                    html.Span("Display options")
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        icon="mdi-close",
                        variant="text",
                        size="small",
                        click=self.close,
                    )
                vuetify3.VDivider()
                with vuetify3.VCardText(classes="pt-4"):
                    self._render_load_mode()
                    vuetify3.VDivider(classes="my-3")
                    self._render_tree_hierarchy()
                    self._render_hierarchy_warning()

    def _render_load_mode(self):
        """Manual mode lets the user check several nodes across tabs
        without paying the load cost on every click; the drawer band's
        Load button pushes them all at once. Visibility on/off stays
        independent — driven by the eye icons in the trees."""
        html.Div(
            "Load Mode",
            classes="text-caption text-uppercase font-weight-bold mb-2",
        )
        with vuetify3.VBtnToggle(
            v_model=("load_mode", "auto"),
            mandatory=True,
            density="comfortable",
            color="blue",
            divided=True,
            classes="mb-3 w-100",
        ):
            vuetify3.VBtn("Auto", value="auto", size="small")
            vuetify3.VBtn("Manual", value="manual", size="small")

    def _render_tree_hierarchy(self):
        """Switching mode rebuilds the C++ assembly and resets every
        selection / visibility / coloring state — see the snackbar at
        the layout bottom for user confirmation."""
        html.Div(
            "Tree Hierarchy",
            classes="text-caption text-uppercase font-weight-bold mb-2",
        )
        with vuetify3.VBtnToggle(
            v_model=("tree_hierarchy_mode", "flat"),
            mandatory=True,
            density="comfortable",
            color="blue",
            divided=True,
            classes="mb-3 w-100",
        ):
            vuetify3.VBtn("Flat", value="flat", size="small")
            vuetify3.VBtn("By Interp.", value="by_interpretation", size="small")
            vuetify3.VBtn("By Feat.+Interp.", value="by_feature_and_interpretation", size="small")

    def _render_hierarchy_warning(self):
        with html.Div(classes="d-flex align-start mb-1"):
            vuetify3.VIcon(
                "mdi-alert-circle-outline",
                size="x-small",
                color="orange-darken-2",
                classes="mr-1 mt-1",
            )
            html.Span(
                "Switching mode clears all current selections and"
                " visibility/coloring state — you'll need to re-pick"
                " what you want under the new layout.",
                classes="text-caption text-medium-emphasis",
                style="line-height: 1.2;",
            )
