from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3, html
from typing import Literal

from fespp_on_trame.app.ui.drawer.panel.copy_from_view_menu import (
    render_copy_menu,
)

server = get_server()
state = server.state

vuetify3.enable_lab()


# v_if expression for the IJK tab visibility — only IjkGrid qualifies.
IJK_TAB_VISIBLE = "ui_active_node_reservoir_type_rep === 'IjkGrid'"


class SlicerControls:
    """IJK slicer body — axis crop (range mode) and per-axis multi-
    position cuts (slice mode). Rendered inside the SlicersPanel's IJK
    tab. Threshold lives in `ThresholdPanel` (attributes drawer) because
    it's a per-rep value-based filter, not a cut. Realization is per-view:
    each render panel's overlay carries a `PerViewRealizationPicker`
    populated from the per-view MR specs computed by
    `realization_dispatch.recompute_panel_mr_specs`.
    """

    _mode_var = "ui_slices_range_mode"

    def render_body(self):
        with html.Div(v_if="ui_active_node_reservoir_type_rep === 'IjkGrid'"):
            # Header row hosts the Copy-from-view menu so the user can
            # snapshot another panel's IJK slicer / volume / mode state
            # onto the active panel.
            with html.Div(classes="d-flex align-center"):
                vuetify3.VSwitch(
                    v_model=(self._mode_var, "range",),
                    style="margin-left: 0.5rem;",
                    label=(self._mode_var,),
                    false_value="range",
                    true_value="slice",
                )
                vuetify3.VSpacer()
                render_copy_menu("ijk_slicers")

            # Single eye for the full volume in range mode.
            with html.Div(
                v_if=f"{self._mode_var} === 'range'",
                style="display: flex; align-items: center; gap: 4px; margin-bottom: 4px;",
            ):
                html.Div("Volume", classes="text-caption font-weight-bold",
                         style="font-size: 0.75rem;")
                vuetify3.VBtn(
                    icon=("ui_slices_volume_visible ? 'mdi-eye' : 'mdi-eye-off'",),
                    click="ui_slices_volume_visible = !ui_slices_volume_visible",
                    variant="text", density="compact", size="x-small",
                    color=("ui_slices_volume_visible ? 'primary' : 'grey'",),
                    style="margin: 0; padding: 0; min-width: 28px; width: 28px; height: 28px;",
                )

            self.RangeSlider("i")
            self.RangeSlider("j")
            self.RangeSlider("k")

            self.MultiSlider("i")
            self.MultiSlider("j")
            self.MultiSlider("k")

    def RangeSlider(self, index: Literal["i", "j", "k"]):
        """Range slider for the volume crop on the given axis."""
        range_var = f"ui_range_{index}"
        slices_range_var = f"ui_slices_range_{index}"

        with vuetify3.VRangeSlider(
            v_if=(f"{self._mode_var} === 'range'"),
            strict=True,
            min=(f"{range_var}[0]",),
            max=(f"{range_var}[1]",),
            step=1,
            v_model=(slices_range_var,),
            thumb_label=False,
            hide_details=True,
            classes="mx-n4",
        ):
            with html.Template(v_slot_prepend=""):
                with html.Div(style="display: flex; align-items: center; gap: 4px;"):
                    html.Div(index.upper(), classes="text-caption", style="width: 10px; text-align: center; font-size: 0.65rem;")

                    vuetify3.VBtn(
                        icon="mdi-refresh",
                        click=f"{slices_range_var} = [{range_var}[0], {range_var}[1]]",
                        variant="text",
                        density="compact",
                        size="x-small",
                        color="primary",
                        style="margin: 0; padding: 0; min-width: 28px; width: 28px; height: 28px;",
                    )

                    vuetify3.VTextField(
                        model_value=(f"{slices_range_var}[0]",),
                        blur=f"{slices_range_var} = [parseInt($event.target.value), {slices_range_var}[1]]",
                        keydown=f"$event.key === 'Enter' && ({slices_range_var} = [parseInt($event.target.value), {slices_range_var}[1]])",
                        density="compact",
                        variant="outlined",
                        hide_details=True,
                        style="width: 80px; font-size: 0.75rem;",
                        type="number",
                        single_line=True,
                    )

            with html.Template(v_slot_append=""):
                vuetify3.VTextField(
                    model_value=(f"{slices_range_var}[1]",),
                    blur=f"{slices_range_var} = [{slices_range_var}[0], parseInt($event.target.value)]",
                    keydown=f"$event.key === 'Enter' && ({slices_range_var} = [{slices_range_var}[0], parseInt($event.target.value)])",
                    density="compact",
                    variant="outlined",
                    hide_details=True,
                    style="width: 80px; font-size: 0.75rem;",
                    type="number",
                    single_line=True,
                )

    def MultiSlider(self, index: Literal["i", "j", "k"]):
        """Multi-position slider used in Slice mode: 0..N slicers per
        axis, each with its own position, visibility eye and delete
        button. Add button creates a new slicer at the mid-range
        position."""
        range_var = f"ui_range_{index}"
        list_var = f"ui_slices_{index}_list"
        vis_list_var = f"ui_slices_{index}_visible_list"
        label = index.upper()

        with html.Div(v_if=f"{self._mode_var} === 'slice'", classes="mb-1"):
            with html.Div(style="display: flex; align-items: center; gap: 4px; margin-bottom: 2px;"):
                html.Div(label, classes="text-caption font-weight-bold",
                         style="width: 16px; text-align: center; font-size: 0.75rem;")
                vuetify3.VBtn(
                    icon="mdi-plus",
                    click=(
                        f"{list_var} = {list_var}.concat([Math.round(({range_var}[0]+{range_var}[1])/2)]); "
                        f"{vis_list_var} = {vis_list_var}.concat([true])"
                    ),
                    variant="text", density="compact", size="x-small",
                    color="primary",
                    style="margin: 0; padding: 0; min-width: 28px; width: 28px; height: 28px;",
                )

            with html.Div(
                v_for=f"(pos, idx) in {list_var}",
                key=("idx",),
                style="display: flex; align-items: center; gap: 2px; margin-bottom: 2px;",
            ):
                vuetify3.VSlider(
                    min=(f"{range_var}[0]",),
                    max=(f"{range_var}[1]",),
                    step=1,
                    model_value=("pos",),
                    end=f"{list_var} = {list_var}.map(function(v, i) {{ return i === idx ? $event : v; }})",
                    thumb_label=False,
                    hide_details=True,
                    style="flex: 1; min-width: 0;",
                )
                vuetify3.VTextField(
                    model_value=("pos",),
                    blur=f"{list_var} = {list_var}.map(function(v, i) {{ return i === idx ? parseInt($event.target.value) : v; }})",
                    keydown=f"if ($event.key === 'Enter') {{ {list_var} = {list_var}.map(function(v, i) {{ return i === idx ? parseInt($event.target.value) : v; }}); }}",
                    density="compact",
                    variant="outlined",
                    hide_details=True,
                    style="width: 70px; font-size: 0.75rem; flex-shrink: 0;",
                    type="number",
                    single_line=True,
                )
                vuetify3.VBtn(
                    icon=(f"{vis_list_var}[idx] !== false ? 'mdi-eye' : 'mdi-eye-off'",),
                    click=f"{vis_list_var} = {vis_list_var}.map(function(v, i) {{ return i === idx ? !v : v; }})",
                    variant="text", density="compact", size="x-small",
                    color=(f"{vis_list_var}[idx] !== false ? 'primary' : 'grey'",),
                    style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px; flex-shrink: 0;",
                )
                vuetify3.VBtn(
                    icon="mdi-close",
                    click=(
                        f"{list_var} = {list_var}.filter(function(_, i) {{ return i !== idx; }}); "
                        f"{vis_list_var} = {vis_list_var}.filter(function(_, i) {{ return i !== idx; }})"
                    ),
                    variant="text", density="compact", size="x-small",
                    color="grey",
                    style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px; flex-shrink: 0;",
                )

