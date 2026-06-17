from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3, html


_KIND_RENDER = "render"
_KIND_DIFF = "diff"

# Positions accepted by dockview's addPanel. We expose three of them
# in the dialog: "within" (= new tab in the active group, default),
# "right" (split group on the right) and "below" (split group at the
# bottom). The active panel is used as the reference for the split.
_POS_TAB = "within"
_POS_RIGHT = "right"
_POS_BELOW = "below"


class AddViewDialog:
    """Single-step picker triggered by the floating "+" button. Asks
    which kind of panel to add and where to place it relative to the
    current active panel — the diff view itself hosts the A/B setup
    form, so this dialog has no per-kind parameters beyond that."""

    def __init__(self):
        self.server = get_server()
        self.state = self.server.state
        self.controller = self.server.controller
        self.state.setdefault("add_view_dialog_visible", False)
        self.state.setdefault("add_view_kind", _KIND_RENDER)
        self.state.setdefault("add_view_position", _POS_TAB)

    def render(self):
        with vuetify3.VDialog(
            v_model=("add_view_dialog_visible", False),
            max_width="420",
        ):
            with vuetify3.VCard():
                vuetify3.VCardTitle("Add a view")
                with vuetify3.VCardText():
                    with vuetify3.VRadioGroup(
                        v_model=("add_view_kind", _KIND_RENDER),
                        density="comfortable",
                        hide_details=True,
                    ):
                        vuetify3.VRadio(
                            label="Render view (copy current scene)",
                            value=_KIND_RENDER,
                        )
                        vuetify3.VRadio(
                            label="Diff view (compute A − B inside the view)",
                            value=_KIND_DIFF,
                            disabled=("!diff_array_choices || diff_array_choices.length < 2",),
                        )
                    html.Div(
                        "Diff needs at least two loaded properties on the same grid.",
                        v_if="!diff_array_choices || diff_array_choices.length < 2",
                        classes="text-caption text-medium-emphasis mt-2",
                    )

                    html.Div(
                        "Position",
                        classes="text-caption text-uppercase font-weight-bold mt-4 mb-1",
                    )
                    with vuetify3.VBtnToggle(
                        v_model=("add_view_position", _POS_TAB),
                        mandatory=True,
                        density="comfortable",
                        color="blue",
                        divided=True,
                        classes="w-100",
                    ):
                        vuetify3.VBtn(
                            "Tab",
                            value=_POS_TAB,
                            size="small",
                            prepend_icon="mdi-tab",
                        )
                        vuetify3.VBtn(
                            "Right",
                            value=_POS_RIGHT,
                            size="small",
                            prepend_icon="mdi-arrow-right-bold-box-outline",
                        )
                        vuetify3.VBtn(
                            "Below",
                            value=_POS_BELOW,
                            size="small",
                            prepend_icon="mdi-arrow-down-bold-box-outline",
                        )
                    html.Div(
                        "Tab = new panel in the same group as the active view."
                        " Right / Below = new split group on that side of the active view.",
                        classes="text-caption text-medium-emphasis mt-1",
                    )

                with vuetify3.VCardActions():
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        "Cancel",
                        variant="text",
                        click="add_view_dialog_visible = false",
                    )
                    vuetify3.VBtn(
                        "Add",
                        variant="tonal",
                        color="blue",
                        click=(self._on_add,),
                    )

    def _on_add(self):
        mv = self.server.context.multi_view
        if mv is None:
            self.state.add_view_dialog_visible = False
            return
        kind = self.state.add_view_kind or _KIND_RENDER
        direction = self.state.add_view_position or _POS_TAB
        if kind == _KIND_DIFF:
            # Reset prior selection / error so the form opens clean.
            self.state.diff_array_a_path = None
            self.state.diff_array_b_path = None
            self.state.diff_compute_error = ""
            self.state.fespp_diff_ready = False
            mv.get_or_create_diff_view(direction=direction)
        else:
            mv.add_view(kind=_KIND_RENDER, direction=direction)
        self.state.add_view_dialog_visible = False
