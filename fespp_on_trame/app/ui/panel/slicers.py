from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3, html
from typing import Literal

server = get_server()
state = server.state

vuetify3.enable_lab()


class SlicerControls(html.Div):
    """IJK slicer panel for the active reservoir node. Hosts:
    - one range slider per axis (Range mode);
    - a multi-position slider per axis with add/remove buttons (Slice
      mode);
    - a realization slider when a multi-realization property is active.

    The whole panel is hidden when neither IJK slicers nor a
    realization slider would render."""

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

        state.setdefault("ui_slices_i_visible_list", [True])
        state.setdefault("ui_slices_j_visible_list", [True])
        state.setdefault("ui_slices_k_visible_list", [True])
        state.setdefault("ui_slices_volume_visible", True)

        state.setdefault("ui_slices_real_locked", True)
        state.setdefault("ui_slices_real_locked_value", None)

        # Threshold chain for the active rep (refreshed by the engine
        # whenever the active grid or chain changes). Each entry is a
        # dict {name, parent_name, array, visible, low, high,
        # data_range}.
        state.setdefault("ui_threshold_chain", [])
        # Array names available on the active rep — used for the UI's
        # "no array to bind" empty-state hint.
        state.setdefault("ui_threshold_arrays_available", [])
        # Sentinel-driven controllers: writing to these triggers the
        # engine handler below, then the handler resets it. Trame
        # ignores writes that don't change the value, so we MUST reset
        # so the next event fires.
        state.setdefault("ui_threshold_pending_action", None)
        # Local UI-side range edits: per-name {name: [low, high]}.
        # Mirror of the chain entries' ranges, debounced through the
        # slider's @end event below.
        state.setdefault("ui_threshold_local_ranges", {})

        self._mode_var = f"ui_slices_range_mode"
        self._slices_range_active_var = f"ui_slices_range_active"

        _slicer_panel_v_if = (
            "ui_active_node_reservoir_type_rep === 'IjkGrid'"
            " || ui_active_node_reservoir_type_rep === 'UnstructuredGrid'"
            " || (realization_labels && realization_labels.length > 0)"
        )

        with self:
          with vuetify3.VExpansionPanels(
              v_if=_slicer_panel_v_if,
              v_model=("slc_panels", [0]),
              multiple=True,
              elevation=0,
          ):
            with vuetify3.VExpansionPanel(elevation=0, value=0):
              with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                html.Span("Slicer", classes="text-body-2 font-weight-medium")
                vuetify3.VSpacer()
                vuetify3.VChip(
                    "{{ ui_slices_range_mode === 'slice' ? 'Slice' : 'Range' }}",
                    size="x-small",
                    variant="tonal",
                    color="blue",
                    classes="font-italic mr-1",
                    v_if="ui_active_node_reservoir_type_rep === 'IjkGrid'",
                )
                vuetify3.VChip(
                    "Real {{ realization_labels && realization_labels[ui_slices_real] }}",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="font-italic mr-2",
                    v_if="realization_labels && realization_labels.length > 0",
                )
              with vuetify3.VExpansionPanelText(classes="pa-2"):
                with html.Div(v_if="ui_active_node_reservoir_type_rep === 'IjkGrid'"):
                    vuetify3.VSwitch(
                        v_model=(self._mode_var, "range",),
                        style="margin-left: 0.5rem;",
                        label=(self._mode_var,),
                        false_value="range",
                        true_value="slice",
                    )

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

                # Threshold filter — available for IjkGrid AND UnstructuredGrid
                # reservoir grids. Driven by the currently selected data
                # array; the eye toggles the threshold filter on/off.
                with html.Div(
                    v_if=(
                        "ui_active_node_reservoir_type_rep === 'IjkGrid'"
                        " || ui_active_node_reservoir_type_rep === 'UnstructuredGrid'"
                    ),
                    classes="mt-2"
                ):
                    vuetify3.VDivider(
                        v_if="ui_active_node_reservoir_type_rep === 'IjkGrid'",
                        classes="mb-2"
                    )
                    self.ThresholdControls()

                with html.Div(
                    v_if="realization_labels && realization_labels.length > 0",
                    classes="mt-2"
                ):
                    vuetify3.VDivider(
                        v_if=(
                            "ui_active_node_reservoir_type_rep === 'IjkGrid'"
                            " || ui_active_node_reservoir_type_rep === 'UnstructuredGrid'"
                        ),
                        classes="mb-2"
                    )
                    self.Slider("real")

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
                        blur=f"console.log('blur {index} min:', $event.target.value); {slices_range_var} = [parseInt($event.target.value), {slices_range_var}[1]]",
                        keydown=f"$event.key === 'Enter' && (console.log('enter {index} min:', $event.target.value), {slices_range_var} = [parseInt($event.target.value), {slices_range_var}[1]])",
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

    def Slider(self, index: Literal["i", "j", "k", "real"]):
        """Single-value slider — used for the realization slider. The
        i/j/k variants are kept here too for symmetry but the slice
        mode uses MultiSlider above."""
        range_var = f"ui_range_{index}"
        slices_var = f"ui_slices_{index}"
        label = index.upper() if index != "real" else "Real"

        v_if_condition = None if index == "real" else f"{self._mode_var} === 'slice'"

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
            with html.Template(v_slot_prepend=""):
                with html.Div(style="display: flex; align-items: center; gap: 4px;"):
                    html.Div(label, classes="text-caption", style="width: 30px; text-align: center; font-size: 0.65rem;")

                    if index == "real":
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

            with html.Template(v_slot_append=""):
                if index == "real":
                    # Realization slider: the user types a label
                    # ("23"), we look up its index in
                    # realization_labels and store that as
                    # ui_slices_real.
                    model_value_expr = "realization_labels[ui_slices_real]"
                    change_expr = "console.log('blur real:', $event.target.value); ui_slices_real = realization_labels.indexOf($event.target.value)"
                    enter_expr = "$event.key === 'Enter' && (console.log('enter real:', $event.target.value), ui_slices_real = realization_labels.indexOf($event.target.value))"
                else:
                    model_value_expr = slices_var
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

    def ThresholdControls(self):
        """Chained threshold UI for the active reservoir grid.

        Each chain entry renders as one row: array label + range badge,
        eye toggle (visibility / re-parenting), VRangeSlider (debounced
        @end commit), `+` (add child), 🗑️ (delete). Top-level `+`
        creates a new chain root. Every chain entry's array is fixed at
        creation time (the active visible property at the moment of
        the click) — no VSelect, by design (cf. user feedback: a blind
        threshold is hard to interpret).

        UI events go through a single sentinel state var
        ``ui_threshold_pending_action`` that the engine consumes and
        resets — keeps the JS-side terse and the server-side flow
        unified."""
        # Header + root-add button.
        with html.Div(style="display: flex; align-items: center; gap: 4px; margin-bottom: 4px;"):
            html.Div("Thresholds", classes="text-caption font-weight-bold",
                     style="font-size: 0.75rem;")
            # ∪ (union) icon — clicking adds a parallel threshold
            # filter at root level. Multiple root-level entries on
            # the same property render in parallel = union of their
            # ranges in 3D. Tooltip spells out the semantic for users
            # who don't recognise set-theory glyphs.
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon="mdi-set-all",
                        v_bind="props",
                        # Disabled when no active visible property — a
                        # threshold without an array to bind onto is
                        # meaningless.
                        disabled=("!active_color_array_name",),
                        click=(
                            "ui_threshold_pending_action = "
                            "{ action: 'add', parent: null }"
                        ),
                        variant="text", density="compact", size="x-small",
                        color="primary",
                        style="margin: 0; padding: 0; min-width: 28px; width: 28px; height: 28px;",
                    )
                html.Span("Add union — show cells matching this range OR any existing root range")
            html.Span(
                "(activate a property first)",
                v_if="!active_color_array_name && (!ui_threshold_chain || ui_threshold_chain.length === 0)",
                classes="text-caption text-medium-emphasis ml-1",
                style="font-size: 0.7rem;",
            )

        # Empty state when chain has nothing.
        html.Div(
            "No thresholds.",
            v_if="!ui_threshold_chain || ui_threshold_chain.length === 0",
            classes="text-caption text-medium-emphasis",
            style="font-size: 0.7rem;",
        )

        # Per-entry rows. Indentation tracks chain depth: a child sits
        # one level deeper than its parent_name's row.
        with html.Div(
            v_for="(entry, idx) in (ui_threshold_chain || [])",
            key="entry.name",
            classes="mb-2",
        ):
            # Header line: array label, eye, +child, delete.
            # Inline :style object so the per-depth indent merges with
            # the static flex layout.
            with html.Div(
                style=(
                    "{ display: 'flex', alignItems: 'center', gap: '4px',"
                    " paddingLeft: ((entry._depth || 0) * 12) + 'px' }",
                ),
            ):
                vuetify3.VBtn(
                    icon=("entry.visible ? 'mdi-eye' : 'mdi-eye-off'",),
                    click=(
                        "ui_threshold_pending_action = "
                        "{ action: 'set_visible', name: entry.name, visible: !entry.visible }"
                    ),
                    variant="text", density="compact", size="x-small",
                    color=("entry.visible ? 'primary' : 'grey'",),
                    style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px;",
                )
                html.Span(
                    "{{ entry.array }}",
                    classes="text-caption font-weight-medium",
                    style="font-size: 0.75rem;",
                )
                html.Span(
                    "[{{ entry.low.toFixed(3) }} .. {{ entry.high.toFixed(3) }}]",
                    classes="text-caption text-medium-emphasis",
                    style="font-size: 0.7rem;",
                )
                vuetify3.VSpacer()
                # ∩ (intersection) icon — clicking adds a Threshold
                # filter chained downstream of `entry`. Its output is
                # the intersection of the parent's cells and the new
                # range. Tooltip spells it out for users who don't
                # recognise the set-theory glyph.
                with vuetify3.VTooltip(location="bottom"):
                    with vuetify3.Template(v_slot_activator="{ props }"):
                        vuetify3.VBtn(
                            icon="mdi-set-center",
                            v_bind="props",
                            disabled=("!active_color_array_name",),
                            click=(
                                "ui_threshold_pending_action = "
                                "{ action: 'add', parent: entry.name }"
                            ),
                            variant="text", density="compact", size="x-small",
                            color="primary",
                            style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px;",
                        )
                    html.Span("Add intersection — narrow this entry's cells further with a chained range")
                vuetify3.VBtn(
                    icon="mdi-delete",
                    click=(
                        "ui_threshold_pending_action = "
                        "{ action: 'delete', name: entry.name }"
                    ),
                    variant="text", density="compact", size="x-small",
                    color="grey",
                    style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px;",
                )

            # Range slider, indented under the header line.
            with html.Div(
                style=(
                    "{ paddingLeft: ((entry._depth || 0) * 12 + 4) + 'px',"
                    " paddingRight: '4px' }",
                ),
            ):
                vuetify3.VRangeSlider(
                    model_value=("[entry.low, entry.high]",),
                    min=("entry.data_range[0]",),
                    max=("entry.data_range[1]",),
                    step=(
                        "(entry.data_range[1] - entry.data_range[0]) / 1000 || 1",
                    ),
                    strict=True,
                    thumb_label=False,
                    hide_details=True,
                    end=(
                        "ui_threshold_pending_action = "
                        "{ action: 'set_range', name: entry.name,"
                        " low: $event[0], high: $event[1] }"
                    ),
                )

