"""Global view settings dialog.

A modal triggered from the top tools band. Always applies across
every render view (no per-view scope here — per-view variants live
in `ViewSettingsDialog`, opened from each panel's ⚙ button). Three
sections, each commits on its own (no dialog-level Apply / Cancel):
  - **Transformation** — Z-scale via the wrapped `TransformationEditor`.
  - **Orientation** — axis triad colors / visibility.
  - **Background** — palette picker (Global preset).

The user dismisses the dialog via the ✕, click-outside, or Escape."""
from trame.widgets import html, vuetify3

from ..widget.background_editor import BackgroundEditor
from ..widget.orientation_editor import OrientationEditor
from ..widget.transformation_editor import TransformationEditor


# Sentinel value the editors read from `state.settings_scope` to
# pick their "Global" branch.
_SCOPE_VAR = "settings_scope"
_GLOBAL = "global"


class GlobalSettingsDialog:
    def __init__(self, state, controller):
        self.state = state
        self.controller = controller

        state.setdefault("global_settings_dialog_visible", False)
        # Hardcoded "global" — the editors read this state var and
        # branch on its value. Locked to "global" for this dialog.
        state.setdefault(_SCOPE_VAR, _GLOBAL)

        controller.global_settings_open = self.open

        self._transformation = TransformationEditor(scope_var=_SCOPE_VAR)
        self._orient_editor = OrientationEditor(scope_var=_SCOPE_VAR)
        self._bg_editor = BackgroundEditor(scope_var=_SCOPE_VAR)

    def open(self):
        # Re-assert the scope on every open so a stale per-view value
        # can't leak into the global dialog.
        self.state.settings_scope = _GLOBAL
        self.state.global_settings_dialog_visible = True

    def close(self):
        self.state.global_settings_dialog_visible = False

    def render(self):
        with vuetify3.VDialog(
            v_model=("global_settings_dialog_visible", False),
            max_width="560",
        ):
            with vuetify3.VCard():
                with vuetify3.VCardTitle(classes="d-flex align-center pa-3"):
                    html.Span("Global view settings")
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        icon="mdi-close",
                        variant="text",
                        size="small",
                        click=self.close,
                    )
                vuetify3.VDivider()
                with vuetify3.VCardText(classes="pt-4"):
                    self._transformation.render()
                    vuetify3.VDivider(classes="my-4")
                    self._orient_editor.render()
                    vuetify3.VDivider(classes="my-4")
                    self._bg_editor.render()
