"""RealizationPicker widgets — per-view + global variant.

Shown in each render panel's top overlay when the panel has at least
one MR property active in its ColorBy. Lets the user switch which
realization is displayed for each active MR property, independently
per view, so different panels can show different realizations of the
same property side by side.

Buttons / slider / dropdown all drive `trigger('set_view_realization',
[panel_id, array_path, idx])` → boot.set_view_realization, which
updates the per-view realization map and re-applies ColorBy with the
right suffixed VTK array.

State binding:
  - `ui_panel_active_mr_specs_by_id[panel_id]` — array of
    `{array_path, title, available_indices, current_idx}` specs,
    computed server-side by `realization_dispatch.recompute_panel_mr_specs`
    on every change to the active-array / active-realization maps.

The realization domain isn't necessarily contiguous (e.g. {23, 24}
without 0..22), so the slider value is the POSITION in
spec.available_indices, not the actual idx; the actual idx is looked
up via `spec.available_indices[position]` before the trigger fires,
keeping slider movement linear regardless of index gaps. The dropdown
bypasses the position layer entirely (items are the raw indices).
"""
from trame.widgets import html, vuetify3


class PerViewRealizationPicker:
    """TimeControl-styled card with one row per active MR property in
    this view."""

    def __init__(self, panel_id: str):
        self._panel_id = panel_id

    def render(self):
        specs_var = f"ui_panel_active_mr_specs_by_id['{self._panel_id}']"
        with vuetify3.VCard(
            v_if=f"{specs_var} && {specs_var}.length > 0",
            classes="pa-1 px-2 elevation-5 rounded-lg",
            style=(
                "width: 100%; overflow: hidden;"
                " background: rgba(255, 255, 255, 0.5);"
                " pointer-events: auto; user-select: none;"
            ),
        ):
            with html.Div(
                classes="d-flex flex-column",
                style="gap: 2px;",
            ):
                with html.Div(
                    v_for=f"spec in ({specs_var} || [])",
                    key=("spec.array_path",),
                    classes="d-flex align-center",
                ):
                    # Property title — ellipsis on overflow so the
                    # controls keep their footprint.
                    html.Span(
                        "{{ spec.title }}",
                        classes="text-caption font-weight-medium mr-1",
                        style=(
                            "min-width: 60px; max-width: 120px;"
                            " overflow: hidden; text-overflow: ellipsis;"
                            " white-space: nowrap;"
                        ),
                    )
                    # Position of the current idx within the available
                    # set — drives each button's disabled state and the
                    # click handlers below.
                    pos_expr = "spec.available_indices.indexOf(spec.current_idx)"
                    n_expr = "spec.available_indices.length"
                    vuetify3.VBtn(
                        icon="mdi-skip-previous",
                        density="compact",
                        flat=True,
                        classes="mr-1",
                        disabled=(f"{pos_expr} <= 0",),
                        click=(
                            "trigger('set_view_realization',"
                            f" ['{self._panel_id}', spec.array_path,"
                            " spec.available_indices[0]])"
                        ),
                    )
                    vuetify3.VBtn(
                        icon="mdi-chevron-left",
                        density="compact",
                        flat=True,
                        classes="mr-1",
                        disabled=(f"{pos_expr} <= 0",),
                        click=(
                            "trigger('set_view_realization',"
                            f" ['{self._panel_id}', spec.array_path,"
                            f" spec.available_indices[Math.max(0, {pos_expr} - 1)]])"
                        ),
                    )
                    vuetify3.VBtn(
                        icon="mdi-chevron-right",
                        density="compact",
                        flat=True,
                        classes="mr-1",
                        disabled=(f"{pos_expr} >= {n_expr} - 1",),
                        click=(
                            "trigger('set_view_realization',"
                            f" ['{self._panel_id}', spec.array_path,"
                            f" spec.available_indices[Math.min({n_expr} - 1, {pos_expr} + 1)]])"
                        ),
                    )
                    vuetify3.VBtn(
                        icon="mdi-skip-next",
                        density="compact",
                        flat=True,
                        classes="mr-1",
                        disabled=(f"{pos_expr} >= {n_expr} - 1",),
                        click=(
                            "trigger('set_view_realization',"
                            f" ['{self._panel_id}', spec.array_path,"
                            f" spec.available_indices[{n_expr} - 1]])"
                        ),
                    )
                    # Direct-jump dropdown: lists every available
                    # realization; picking one fires the trigger
                    # directly with that idx (no stepping through).
                    vuetify3.VSelect(
                        model_value=("spec.current_idx",),
                        items=("spec.available_indices",),
                        density="compact",
                        hide_details=True,
                        variant="outlined",
                        single_line=True,
                        classes="mx-2",
                        style="width: 10rem; flex: 0 0 auto;",
                        update_modelValue=(
                            "trigger('set_view_realization',"
                            f" ['{self._panel_id}', spec.array_path, $event])"
                        ),
                    )
                    # Slider value is the POSITION in available_indices
                    # (0..N-1), so movement stays linear despite index
                    # gaps. @end fires on release; the actual idx is
                    # looked up before the trigger.
                    vuetify3.VSlider(
                        model_value=(pos_expr,),
                        min=0,
                        max=(f"{n_expr} - 1",),
                        step=1,
                        density="compact",
                        hide_details=True,
                        thumb_label=False,
                        end=(
                            "trigger('set_view_realization',"
                            f" ['{self._panel_id}', spec.array_path,"
                            " spec.available_indices[$event]])"
                        ),
                    )


class GlobalRealizationPicker:
    """Tools-band variant — single row that dispatches to every panel
    at once for the currently-picked MR property.

    Layout (left → right):
      [property ▼]  ⏮ ◀ ▶ ⏭  [index ▼]  ━━━●━━━

    The property dropdown lists every MR currently active across the
    scene (`ui_global_mr_specs`); its value is the user pick
    `ui_global_mr_selected_path` (server-side clamped so it can't go
    stale). Items (and the selection) render in orange when panels
    disagree on the active index — `spec.mixed === true` — so the
    closed dropdown surfaces the divergence at a glance.

    The rest of the row binds to `ui_global_mr_selected_spec`, the
    server-resolved spec for the selected path. Buttons / index
    dropdown / slider fire `set_global_realization` which fans out to
    every panel that has the property active."""

    def render(self):
        with vuetify3.VCard(
            v_if="ui_global_mr_specs && ui_global_mr_specs.length > 0",
            classes="pa-1 px-2 elevation-5 rounded-lg",
            style=(
                "min-width: 480px; max-width: 720px;"
                " background: rgba(255, 255, 255, 0.5);"
                " pointer-events: auto; user-select: none;"
            ),
        ):
            with html.Div(
                classes="d-flex align-center",
            ):
                # Property selector — orange when the spec is mixed
                # (panels diverge). The mixed flag travels with each
                # item so the slot can read it.
                with vuetify3.VSelect(
                    v_model=("ui_global_mr_selected_path",),
                    items=(
                        "(ui_global_mr_specs || []).map(s => ({"
                        " title: s.title,"
                        " value: s.array_path,"
                        " mixed: !!s.mixed,"
                        "}))",
                    ),
                    item_title="title",
                    item_value="value",
                    density="compact",
                    hide_details=True,
                    variant="outlined",
                    single_line=True,
                    classes="mr-1",
                    style="width: 9rem; flex: 0 0 auto;",
                ):
                    # Closed-state display: coloured when mixed.
                    with vuetify3.Template(v_slot_selection="{ item }"):
                        html.Span(
                            "{{ item.raw.title }}",
                            style=(
                                "item.raw.mixed"
                                " ? 'color: #f57c00; font-weight: 500;'"
                                " : ''",
                            ),
                        )
                    # Open menu: same color rule per item.
                    with vuetify3.Template(v_slot_item="{ props, item }"):
                        with vuetify3.VListItem(v_bind="props", title=""):
                            with vuetify3.Template(v_slot_title=""):
                                html.Span(
                                    "{{ item.raw.title }}",
                                    style=(
                                        "item.raw.mixed"
                                        " ? 'color: #f57c00; font-weight: 500;'"
                                        " : ''",
                                    ),
                                )

                # The rest of the row reads from the resolved selected
                # spec, aliased to `spec` via a one-element v-for (the
                # lightest way to introduce a local name without a Vue
                # computed). The whole row collapses when no spec is
                # selected.
                spec_expr = "ui_global_mr_selected_spec"
                pos_expr = "spec.available_indices.indexOf(spec.current_idx)"
                n_expr = "spec.available_indices.length"
                with html.Div(
                    v_if=spec_expr,
                    classes="d-flex align-center",
                    style="flex: 1; min-width: 0;",
                ):
                    with html.Div(
                        v_for=f"spec in [{spec_expr}]",
                        key="spec.array_path",
                        classes="d-flex align-center",
                        style="flex: 1; min-width: 0;",
                    ):
                        vuetify3.VBtn(
                            icon="mdi-skip-previous",
                            density="compact",
                            flat=True,
                            classes="mr-1",
                            disabled=(f"{pos_expr} <= 0",),
                            click=(
                                "trigger('set_global_realization',"
                                " [spec.array_path,"
                                " spec.available_indices[0]])"
                            ),
                        )
                        vuetify3.VBtn(
                            icon="mdi-chevron-left",
                            density="compact",
                            flat=True,
                            classes="mr-1",
                            disabled=(f"{pos_expr} <= 0",),
                            click=(
                                "trigger('set_global_realization',"
                                " [spec.array_path,"
                                f" spec.available_indices[Math.max(0, {pos_expr} - 1)]])"
                            ),
                        )
                        vuetify3.VBtn(
                            icon="mdi-chevron-right",
                            density="compact",
                            flat=True,
                            classes="mr-1",
                            disabled=(f"{pos_expr} >= {n_expr} - 1",),
                            click=(
                                "trigger('set_global_realization',"
                                " [spec.array_path,"
                                f" spec.available_indices[Math.min({n_expr} - 1, {pos_expr} + 1)]])"
                            ),
                        )
                        vuetify3.VBtn(
                            icon="mdi-skip-next",
                            density="compact",
                            flat=True,
                            classes="mr-1",
                            disabled=(f"{pos_expr} >= {n_expr} - 1",),
                            click=(
                                "trigger('set_global_realization',"
                                " [spec.array_path,"
                                f" spec.available_indices[{n_expr} - 1]])"
                            ),
                        )
                        vuetify3.VSelect(
                            model_value=("spec.current_idx",),
                            items=("spec.available_indices",),
                            density="compact",
                            hide_details=True,
                            variant="outlined",
                            single_line=True,
                            classes="mx-2",
                            style="width: 6rem; flex: 0 0 auto;",
                            update_modelValue=(
                                "trigger('set_global_realization',"
                                " [spec.array_path, $event])"
                            ),
                        )
                        vuetify3.VSlider(
                            model_value=(pos_expr,),
                            min=0,
                            max=(f"{n_expr} - 1",),
                            step=1,
                            density="compact",
                            hide_details=True,
                            thumb_label=False,
                            end=(
                                "trigger('set_global_realization',"
                                " [spec.array_path,"
                                " spec.available_indices[$event]])"
                            ),
                        )
