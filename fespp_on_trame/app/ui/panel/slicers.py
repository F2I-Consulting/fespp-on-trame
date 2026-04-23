from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3, html
from typing import Literal

server = get_server()
state = server.state

vuetify3.enable_lab()

class SlicerControls(html.Div):
    def __init__(self):
        super().__init__()
        
        state.setdefault("ui_range_i", [0, 0])
        state.setdefault("ui_range_j", [0, 0])
        state.setdefault("ui_range_k", [0, 0])
        state.setdefault("ui_slices_i_active", False)
        state.setdefault("ui_slices_i_list", [0])
        state.setdefault("ui_slices_j_active", False)
        state.setdefault("ui_slices_j_list", [0])
        state.setdefault("ui_slices_k_active", False)
        state.setdefault("ui_slices_k_list", [0])
        state.setdefault("ui_slices_range_active", False)
        state.setdefault("ui_slices_range_i", [0, 0])
        state.setdefault("ui_slices_range_j", [0, 0])
        state.setdefault("ui_slices_range_k", [0, 0])
        state.setdefault("ui_slices_range_mode", "range")
        state.setdefault("ui_range_real", [0, 0])
        state.setdefault("ui_slices_real", 0)

        # Per-slicer visibility lists (one bool per slicer row)
        state.setdefault("ui_slices_i_visible_list", [True])
        state.setdefault("ui_slices_j_visible_list", [True])
        state.setdefault("ui_slices_k_visible_list", [True])
        state.setdefault("ui_slices_volume_visible", True)

        # Lock state for realization
        state.setdefault("ui_slices_real_locked", True)
        state.setdefault("ui_slices_real_locked_value", None)

        self._mode_var = f"ui_slices_range_mode"
        self._slices_range_active_var = f"ui_slices_range_active"
        
        with self:
          with vuetify3.VExpansionPanels(v_model=("slc_panels", [0]), multiple=True, elevation=0):
            with vuetify3.VExpansionPanel(elevation=0, value=0):
              with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                html.Span("Slicer", classes="text-body-2 font-weight-medium")
                vuetify3.VSpacer()
                # IJK mode chip — Range or Slice
                vuetify3.VChip(
                    "{{ ui_slices_range_mode === 'slice' ? 'Slice' : 'Range' }}",
                    size="x-small",
                    variant="tonal",
                    color="blue",
                    classes="font-italic mr-1",
                    v_if="ui_active_node_reservoir_type_rep === 'IjkGrid'",
                )
                # Realization chip — current realization label (e.g. "Real 23")
                vuetify3.VChip(
                    "Real {{ realization_labels && realization_labels[ui_slices_real] }}",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="font-italic mr-2",
                    v_if="realization_labels && realization_labels.length > 0",
                )
              with vuetify3.VExpansionPanelText(classes="pa-2"):
                # IJK/Volume slicers - only for IjkGrid representations
                with html.Div(v_if="ui_active_node_reservoir_type_rep === 'IjkGrid'"):
                    vuetify3.VSwitch(
                        v_model=(self._mode_var, "range",),
                        style="margin-left: 0.5rem;",
                        label=(self._mode_var,),
                        false_value="range",
                        true_value="slice",
                    )

                    self.RangeSlider("i")
                    self.RangeSlider("j")
                    self.RangeSlider("k")

                    self.MultiSlider("i")
                    self.MultiSlider("j")
                    self.MultiSlider("k")

                # Realization slider section
                with html.Div(
                    v_if="realization_labels && realization_labels.length > 0",
                    classes="mt-2"
                ):
                    # Divider visible only if IJK sliders are shown above
                    vuetify3.VDivider(
                        v_if="ui_active_node_reservoir_type_rep === 'IjkGrid'",
                        classes="mb-2"
                    )
                    self.Slider("real")

    def RangeSlider(self, index: Literal["i", "j", "k"]):
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
            update_modelValue="console.log($event)",
            classes="mx-n4",
        ):
            # Prepend slot: Label + Visibility button + Min value field
            with html.Template(v_slot_prepend=""):
                with html.Div(style="display: flex; align-items: center; gap: 4px;"):
                    html.Div(index.upper(), classes="text-caption", style="width: 10px; text-align: center; font-size: 0.65rem;")

                    # Refresh icon for volume - reset to full range
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
                        blur=f"console.log('blur {index} min:', $event.target.value); {slices_range_var} = [parseInt($event.target.value), {slices_range_var}[1]]",
                        keydown=f"$event.key === 'Enter' && (console.log('enter {index} min:', $event.target.value), {slices_range_var} = [parseInt($event.target.value), {slices_range_var}[1]])",
                        density="compact",
                        variant="outlined",
                        hide_details=True,
                        style="width: 80px; font-size: 0.75rem;",
                        type="number",
                        single_line=True,
                    )

            # Append slot: Max value field
            with html.Template(v_slot_append=""):
                vuetify3.VTextField(
                    model_value=(f"{slices_range_var}[1]",),
                    blur=f"console.log('blur {index} max:', $event.target.value); {slices_range_var} = [{slices_range_var}[0], parseInt($event.target.value)]",
                    keydown=f"$event.key === 'Enter' && (console.log('enter {index} max:', $event.target.value), {slices_range_var} = [{slices_range_var}[0], parseInt($event.target.value)])",
                    density="compact",
                    variant="outlined",
                    hide_details=True,
                    style="width: 80px; font-size: 0.75rem;",
                    type="number",
                    single_line=True,
                )

    def MultiSlider(self, index: Literal["i", "j", "k"]):
        """Slider multi-position pour le mode slice (0 à N slices par axe)."""
        range_var = f"ui_range_{index}"
        list_var = f"ui_slices_{index}_list"
        vis_list_var = f"ui_slices_{index}_visible_list"
        label = index.upper()

        with html.Div(v_if=f"{self._mode_var} === 'slice'", classes="mb-1"):
            # En-tête : label + bouton ajout
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

            # Une ligne par position de slice (v-for côté Vue)
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
                # Oeil de visibilité par slicer
                vuetify3.VBtn(
                    icon=(f"{vis_list_var}[idx] !== false ? 'mdi-eye' : 'mdi-eye-off'",),
                    click=f"{vis_list_var} = {vis_list_var}.map(function(v, i) {{ return i === idx ? !v : v; }})",
                    variant="text", density="compact", size="x-small",
                    color=(f"{vis_list_var}[idx] !== false ? 'primary' : 'grey'",),
                    style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px; flex-shrink: 0;",
                )
                # Bouton suppression — toujours visible, autorise 0 slicers
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

    def Slider(self, index: Literal["i", "j", "k", "real"]):
        # Configure based on slider type
        range_var = f"ui_range_{index}"
        slices_var = f"ui_slices_{index}"
        label = index.upper() if index != "real" else "Real"

        # Only IJK sliders have v_if condition for mode switching
        v_if_condition = None if index == "real" else f"{self._mode_var} === 'slice'"

        # Build VSlider kwargs
        slider_kwargs = {
            "min": (f"{range_var}[0]",),
            "max": (f"{range_var}[1]",),
            "step": 1,
            "thumb_label": False,
            "model_value": (f"{slices_var}",),
            "update_modelValue": f"{slices_var} = $event",
            "hide_details": True,
            "classes": "mx-n4",
        }
        if v_if_condition:
            slider_kwargs["v_if"] = (v_if_condition,)

        with vuetify3.VSlider(**slider_kwargs):
            # Prepend slot: Label + Icon button
            with html.Template(v_slot_prepend=""):
                with html.Div(style="display: flex; align-items: center; gap: 4px;"):
                    html.Div(label, classes="text-caption", style="width: 30px; text-align: center; font-size: 0.65rem;")

                    # Icon button: lock for real, visibility for i/j/k
                    if index == "real":
                        # Lock icon for realization
                        vuetify3.VBtn(
                            icon=("ui_slices_real_locked ? 'mdi-lock' : 'mdi-lock-open'",),
                            click="ui_slices_real_locked = !ui_slices_real_locked",
                            variant="text",
                            density="compact",
                            size="x-small",
                            color=("ui_slices_real_locked ? 'success' : 'primary'",),
                            style="margin: 0; padding: 0; min-width: 28px; width: 28px; height: 28px;",
                        )
                    else:
                        # Visibility icon for i/j/k slices
                        visible_var = f"ui_slices_{index}_visible"
                        vuetify3.VBtn(
                            icon=(f"{visible_var} ? 'mdi-eye' : 'mdi-eye-off'",),
                            click=f"{visible_var} = !{visible_var}",
                            variant="text",
                            density="compact",
                            size="x-small",
                            color=(f"{visible_var} ? 'primary' : 'grey'",),
                            style="margin: 0; padding: 0; min-width: 28px; width: 28px; height: 28px;",
                        )

            # Append slot: Editable field for all sliders
            with html.Template(v_slot_append=""):
                # Special handling for realization labels
                if index == "real":
                    model_value_expr = "realization_labels[ui_slices_real]"
                    # Find index of label in array and set ui_slices_real
                    change_expr = "console.log('blur real:', $event.target.value); ui_slices_real = realization_labels.indexOf($event.target.value)"
                    enter_expr = "$event.key === 'Enter' && (console.log('enter real:', $event.target.value), ui_slices_real = realization_labels.indexOf($event.target.value))"
                else:
                    model_value_expr = slices_var
                    # Directly set state variable with parsed integer value
                    change_expr = f"console.log('blur {index}:', $event.target.value); {slices_var} = parseInt($event.target.value)"
                    enter_expr = f"$event.key === 'Enter' && (console.log('enter {index}:', $event.target.value), {slices_var} = parseInt($event.target.value))"

                vuetify3.VTextField(
                    model_value=(model_value_expr,),
                    blur=change_expr,
                    keydown=enter_expr,
                    density="compact",
                    variant="outlined",
                    hide_details=True,
                    style="width: 80px; font-size: 0.75rem;",
                    type="number",
                    single_line=True,
                )

