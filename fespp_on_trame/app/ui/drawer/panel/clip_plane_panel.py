"""Plane clip panel — analog of SlicePlanePanel.

Binds to:
  - `ui_clip_enabled`    (bool)   — toggle the clip on/off
  - `ui_clip_axis`       (str)    — "X" / "Y" / "Z" — axis preset
  - `ui_clip_offset`     (float)  — position along the normal
  - `ui_clip_inside_out` (bool)   — flip which half is kept
  - `ui_clip_offset_min/max/step` (float) — slider domain

Shares the `ui_plane_edit_mode` channel with the slice panel — only
one filter can have its 3D widget visible at a time. Activating the
clip auto-focuses edit if nothing else is being edited.
"""
from trame.app import get_server
from trame.widgets import html, vuetify3


_server = get_server()


class ClipPlanePanel:
    """Renders the clip controls + Edit toggle. Body only — meant to
    be hosted inside `SlicersPanel`'s VTabs."""

    def render_body(self):
        with html.Div(classes="d-flex align-center mb-2"):
            vuetify3.VSwitch(
                v_model=("ui_clip_enabled", False),
                label="Enabled",
                color="primary",
                density="compact",
                hide_details=True,
                classes="me-3",
                update_modelValue="trigger('clip_set_enabled', [$event])",
            )
            vuetify3.VBtn(
                "Edit 3D",
                prepend_icon="mdi-cursor-move",
                size="small",
                density="compact",
                variant="tonal",
                color=(
                    "ui_plane_edit_mode === 'clip' ? 'primary' : 'grey'"
                ),
                click=(
                    "trigger('plane_edit_mode_set',"
                    " [ui_plane_edit_mode === 'clip' ? null : 'clip'])"
                ),
            )

        html.Div(
            "Normal axis",
            classes="text-caption text-medium-emphasis",
        )
        with vuetify3.VBtnToggle(
            v_model=("ui_clip_axis", "X"),
            mandatory=True,
            density="compact",
            color="primary",
            divided=True,
            classes="mb-2",
            update_modelValue="trigger('clip_set_axis', [$event])",
        ):
            vuetify3.VBtn("X", value="X", size="small")
            vuetify3.VBtn("Y", value="Y", size="small")
            vuetify3.VBtn("Z", value="Z", size="small")

        html.Div(
            "Offset along axis",
            classes="text-caption text-medium-emphasis",
        )
        vuetify3.VSlider(
            v_model=("ui_clip_offset", 0.0),
            min=("ui_clip_offset_min", 0.0),
            max=("ui_clip_offset_max", 1.0),
            step=("ui_clip_offset_step", 0.001),
            density="compact",
            hide_details=True,
            thumb_label=True,
            end="trigger('clip_set_offset', [$event])",
        )

        vuetify3.VSwitch(
            v_model=("ui_clip_inside_out", False),
            label="Invert side",
            color="primary",
            density="compact",
            hide_details=True,
            classes="mt-2",
            update_modelValue="trigger('clip_set_inside_out', [$event])",
        )


def _wire_clip_triggers():
    controller = _server.controller

    @_server.trigger("clip_set_enabled")
    def _on_enabled(value):
        fn = getattr(controller, "clip_set", None)
        if fn is None:
            return
        fn(enabled=bool(value))
        if bool(value) and getattr(_server.state, "ui_plane_edit_mode", None) is None:
            edit_fn = getattr(controller, "plane_edit_mode_set", None)
            if edit_fn is not None:
                edit_fn("clip")

    @_server.trigger("clip_set_axis")
    def _on_axis(value):
        fn = getattr(controller, "clip_set", None)
        if fn is not None and value in ("X", "Y", "Z"):
            fn(axis=value)

    @_server.trigger("clip_set_offset")
    def _on_offset(value):
        fn = getattr(controller, "clip_set", None)
        if fn is None:
            return
        try:
            fn(offset=float(value))
        except (TypeError, ValueError):
            pass

    @_server.trigger("clip_set_inside_out")
    def _on_inside_out(value):
        fn = getattr(controller, "clip_set", None)
        if fn is None:
            return
        fn(inside_out=bool(value))


_wire_clip_triggers()
