"""Plane slice panel — MVP single plane per rep.

Binds to:
  - `ui_slice_enabled` (bool) — toggle the slice on/off
  - `ui_slice_axis`    (str)  — "X" / "Y" / "Z" — axis preset
  - `ui_slice_offset`  (float) — position along the normal
  - `ui_slice_bounds`  (list[6]) — used by the offset slider's domain

Plus the "Edit" toggle controlling `ui_plane_edit_mode`: only one
plane filter (slice vs. clip) is being edited at a time, so the 3D
widget only appears on the one whose Edit toggle is on. Both filters
can still be applied (enabled) simultaneously — they just share the
single widget channel.
"""
from trame.app import get_server
from trame.widgets import html, vuetify3


_server = get_server()


class SlicePlanePanel:
    """Renders the slice controls + Edit toggle for the 3D plane
    widget. Used inside the `SlicersPanel` tabs — no outer
    VExpansionPanel of its own (the parent provides one)."""

    def render_body(self):
        # Top row: Enable switch + Edit toggle.
        with html.Div(classes="d-flex align-center mb-2"):
            vuetify3.VSwitch(
                v_model=("ui_slice_enabled", False),
                label="Enabled",
                color="primary",
                density="compact",
                hide_details=True,
                classes="me-3",
                update_modelValue="trigger('slice_set_enabled', [$event])",
            )
            vuetify3.VBtn(
                "Edit 3D",
                prepend_icon="mdi-cursor-move",
                size="small",
                density="compact",
                variant="tonal",
                color=(
                    "ui_plane_edit_mode === 'slice' ? 'primary' : 'grey'"
                ),
                click=(
                    "trigger('plane_edit_mode_set',"
                    " [ui_plane_edit_mode === 'slice' ? null : 'slice'])"
                ),
            )

        html.Div(
            "Normal axis",
            classes="text-caption text-medium-emphasis",
        )
        with vuetify3.VBtnToggle(
            v_model=("ui_slice_axis", "X"),
            mandatory=True,
            density="compact",
            color="primary",
            divided=True,
            classes="mb-2",
            update_modelValue="trigger('slice_set_axis', [$event])",
        ):
            vuetify3.VBtn("X", value="X", size="small")
            vuetify3.VBtn("Y", value="Y", size="small")
            vuetify3.VBtn("Z", value="Z", size="small")

        html.Div(
            "Offset along axis",
            classes="text-caption text-medium-emphasis",
        )
        vuetify3.VSlider(
            v_model=("ui_slice_offset", 0.0),
            min=("ui_slice_offset_min", 0.0),
            max=("ui_slice_offset_max", 1.0),
            step=("ui_slice_offset_step", 0.001),
            density="compact",
            hide_details=True,
            thumb_label=True,
            end="trigger('slice_set_offset', [$event])",
        )


def _wire_slice_set_triggers():
    """One trigger per field — easier to wire than a single trigger
    with an object payload (Vue's inline-object literal `{a: $event}`
    in a v-on handler trips its parser in some versions)."""
    controller = _server.controller

    @_server.trigger("slice_set_enabled")
    def _on_enabled(value):
        fn = getattr(controller, "slice_set", None)
        if fn is None:
            return
        fn(enabled=bool(value))
        # Enabling the slice auto-focuses edit on slice if nothing is
        # currently being edited — gives the user the widget right away
        # without an extra click.
        if bool(value) and getattr(_server.state, "ui_plane_edit_mode", None) is None:
            edit_fn = getattr(controller, "plane_edit_mode_set", None)
            if edit_fn is not None:
                edit_fn("slice")

    @_server.trigger("slice_set_axis")
    def _on_axis(value):
        fn = getattr(controller, "slice_set", None)
        if fn is not None and value in ("X", "Y", "Z"):
            fn(axis=value)

    @_server.trigger("slice_set_offset")
    def _on_offset(value):
        fn = getattr(controller, "slice_set", None)
        if fn is None:
            return
        try:
            fn(offset=float(value))
        except (TypeError, ValueError):
            pass

    @_server.trigger("plane_edit_mode_set")
    def _on_edit_mode(value):
        fn = getattr(controller, "plane_edit_mode_set", None)
        if fn is None:
            return
        # Vue's ternary may pass the string "null" or the JS null —
        # normalise both to Python None.
        if value in (None, "null", ""):
            fn(None)
        elif value in ("slice", "clip"):
            fn(value)


_wire_slice_set_triggers()
