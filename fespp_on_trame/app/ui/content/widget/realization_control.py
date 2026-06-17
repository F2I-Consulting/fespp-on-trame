"""Realization control — scene-wide slider.

Realization is global by design: `collector.set_realization_index()`
swaps the property values under the same VTK array name across every
rep loaded from the collector. There's no per-rep / per-view variant
because the collector is shared. Lives in the top tools band next to
the global TimeControl rather than in the per-rep attributes drawer
where it was confusingly grouped with the IJK slicer.

State vars (legacy names, preserved):
  - `ui_slices_real` (int) — slider index into `realization_labels`
  - `ui_slices_real_locked` (bool) — keep the same realization value
    across property switches
  - `realization_labels` (list[str]) — populated by data_load
"""
from trame.widgets import html, vuetify3


class RealizationControl:
    """Compact realization slider styled to fit alongside the global
    TimeControl in the tools band."""

    def render(self):
        # Outer v_if collapses the slot entirely when no
        # multi-realization property is in play, so the surrounding
        # spacers in the tools band don't reserve dead space.
        with vuetify3.VCard(
            v_if="realization_labels && realization_labels.length > 0",
            classes="pa-1 px-2 elevation-5 rounded-lg",
            style=(
                "min-width: 280px; max-width: 480px; flex: 0 0 auto;"
                " background: rgba(255, 255, 255, 0.5);"
            ),
        ):
            with html.Div(
                classes="d-flex align-center",
                style="pointer-events: auto; user-select: none;",
            ):
                # Lock toggle — preserves the current realization value
                # across property switches with a different index set.
                vuetify3.VBtn(
                    icon=("ui_slices_real_locked ? 'mdi-lock' : 'mdi-lock-open'",),
                    click="ui_slices_real_locked = !ui_slices_real_locked",
                    density="compact",
                    flat=True,
                    size="small",
                    color=("ui_slices_real_locked ? 'success' : 'primary'",),
                    classes="mr-1",
                )
                html.Div(
                    "Real",
                    classes="text-caption mr-2",
                    style="width: 28px;",
                )
                vuetify3.VSlider(
                    v_model=("ui_slices_real", 0),
                    min=("ui_range_real[0]",),
                    max=("ui_range_real[1]",),
                    step=1,
                    density="compact",
                    hide_details=True,
                    thumb_label=False,
                    classes="mr-2",
                    style="flex: 1; min-width: 0;",
                )
                # Direct-entry label — type a realization name (e.g.
                # "23") and we lookup its index in `realization_labels`.
                vuetify3.VTextField(
                    model_value=("realization_labels[ui_slices_real]",),
                    blur=(
                        "ui_slices_real = realization_labels.indexOf($event.target.value)"
                    ),
                    keydown=(
                        "$event.key === 'Enter'"
                        " && (ui_slices_real = realization_labels.indexOf($event.target.value))"
                    ),
                    density="compact",
                    variant="outlined",
                    hide_details=True,
                    style="width: 70px; font-size: 0.75rem; flex-shrink: 0;",
                    single_line=True,
                )
