"""Per-panel settings dialog.

A shared `VDialog` opened by each panel's ⚙ button via
`controller.open_view_settings(panel_id)`. Pre-fills the rename field
from the current panel title, and exposes the per-view variants of
the settings that GlobalSettingsDialog applies in global mode:

  - **Rename** — a single VTextField. Apply / Enter commits via
    `multi_view.set_panel_title(...)`. Cancel / ✕ / outside-click
    discards.
  - **Transformation** — per-view Z-scale (uses TransformationEditor
    scoped to the target panel).
  - **Orientation** — per-view axis triad (OrientationEditor scoped
    to the target panel).
  - **Background** — per-view background (BackgroundEditor scoped to
    the target panel).

The per-view editors read `state.view_settings_target_id` as their
scope, which is set to the panel id on open_for(...)."""
from trame.app import get_server
from trame.widgets import html, vuetify3

from ..widget.background_editor import BackgroundEditor
from ..widget.orientation_editor import OrientationEditor
from ..widget.transformation_editor import TransformationEditor


# State var that holds the currently-targeted panel id. The three
# editors below read this directly so they stay scoped to the
# panel the user opened the dialog for.
_SCOPE_VAR = "view_settings_target_id"


class ViewSettingsDialog:
    def __init__(self):
        self._server = get_server()
        self._state = self._server.state
        self._controller = self._server.controller

        self._state.setdefault("view_settings_dialog_visible", False)
        self._state.setdefault(_SCOPE_VAR, "")
        self._state.setdefault("view_settings_rename_value", "")
        # Snapshot of the targeted panel's current title at open time.
        # Used in the dialog header so the user sees "View settings —
        # View 1" instead of the internal "ptc_view_1" id.
        self._state.setdefault("view_settings_target_title", "")

        # Public hook the panel ⚙ button uses to open this dialog
        # targeted on a specific panel.
        self._controller.open_view_settings = self.open_for

        self._transformation = TransformationEditor(scope_var=_SCOPE_VAR)
        # Distinct mode_var: the global dialog uses "orientation_mode"
        # (the default), so the per-view instance must use a different
        # state var — otherwise both editors react to the same change
        # and the global one broadcasts to every view.
        self._orient_editor = OrientationEditor(
            scope_var=_SCOPE_VAR,
            mode_var="orientation_mode_view",
        )
        self._bg_editor = BackgroundEditor(scope_var=_SCOPE_VAR)

    def open_for(self, panel_id: str):
        """Pre-fill the rename field with this panel's current title
        and show the dialog. Looking up the title via the multi-view's
        public _panel_titles dict (set by add_view)."""
        mv = getattr(self._server.context, "multi_view", None)
        current_title = ""
        if mv is not None:
            current_title = (getattr(mv, "_panel_titles", {}) or {}).get(panel_id, "")
        self._state.view_settings_target_id = panel_id
        self._state.view_settings_target_title = current_title
        self._state.view_settings_rename_value = current_title
        self._state.view_settings_dialog_visible = True

    def close(self):
        self._state.view_settings_dialog_visible = False

    def apply_rename(self):
        """Commit the rename. Empty value = no-op (dialog stays open
        so the user can fix it)."""
        target = self._state.view_settings_target_id
        new_title = (self._state.view_settings_rename_value or "").strip()
        if not target or not new_title:
            return
        mv = getattr(self._server.context, "multi_view", None)
        if mv is not None and hasattr(mv, "set_panel_title"):
            try:
                mv.set_panel_title(target, new_title)
                # Keep the internal _panel_titles map in sync (used
                # by _publish_panels_state to populate
                # fespp_render_panels).
                if hasattr(mv, "_panel_titles") and target in mv._panel_titles:
                    mv._panel_titles[target] = new_title
                    if hasattr(mv, "_publish_panels_state"):
                        mv._publish_panels_state()
                # Reflect the new title in the dialog header live.
                self._state.view_settings_target_title = new_title
            except Exception:
                pass

    def render(self):
        with vuetify3.VDialog(
            v_model=("view_settings_dialog_visible", False),
            max_width="560",
        ):
            with vuetify3.VCard():
                with vuetify3.VCardTitle(classes="d-flex align-center pa-3"):
                    html.Span(
                        "View settings — {{ view_settings_target_title || view_settings_target_id }}",
                        classes="text-body-1",
                    )
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        icon="mdi-close",
                        variant="text",
                        size="small",
                        click=self.close,
                    )
                vuetify3.VDivider()
                with vuetify3.VCardText(classes="pt-4"):
                    self._render_rename()
                    vuetify3.VDivider(classes="my-4")
                    self._transformation.render()
                    vuetify3.VDivider(classes="my-4")
                    self._orient_editor.render()
                    vuetify3.VDivider(classes="my-4")
                    self._bg_editor.render()
                    vuetify3.VDivider(classes="my-4")
                    self._render_marker_display()

    def _render_marker_display(self):
        """Marker display (orientation + size) — GLOBAL settings, moved
        here from the Attributes drawer: everything in Attributes acts
        on ONE element, and these act on every marker in every view
        (user feedback: the explicit "global" chip wasn't enough)."""
        html.Div(
            "Markers",
            classes="text-caption text-uppercase font-weight-bold mb-2",
        )
        html.Div(
            "Applies to ALL markers (in every view).",
            classes="text-caption text-medium-emphasis mb-2",
        )
        vuetify3.VSwitch(
            v_model=("marker_orientation",),
            label="Orientation (disc oriented by dip/azimuth, otherwise sphere)",
            density="compact",
            hide_details=True,
            color="deep-orange",
            classes="mb-2",
        )
        vuetify3.VSlider(
            v_model=("marker_size",),
            label="Size",
            min=1, max=200, step=1,
            thumb_label=True,
            density="compact",
            hide_details=True,
            color="deep-orange",
            # Apply on RELEASE only (rebuilding markers re-runs the
            # collector over the whole selection).
            end=(self._server.controller.apply_marker_options,),
        )

    def _render_rename(self):
        """Rename field — Enter and the Apply button commit the
        rename without closing the dialog (so the user can keep
        editing other sections after renaming)."""
        html.Div(
            "Rename",
            classes="text-caption text-uppercase font-weight-bold mb-2",
        )
        with html.Div(classes="d-flex align-center", style="gap: 8px;"):
            vuetify3.VTextField(
                v_model=("view_settings_rename_value", ""),
                density="comfortable",
                variant="outlined",
                hide_details=True,
                autofocus=True,
                keydown_enter=self.apply_rename,
            )
            vuetify3.VBtn(
                "Apply",
                variant="tonal",
                color="blue",
                density="comfortable",
                click=self.apply_rename,
            )
