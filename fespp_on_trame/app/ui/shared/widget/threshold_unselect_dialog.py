"""Confirm dialog for unchecking a property that feeds threshold entries.

Opened by the selection guard in `tree_views._expand_selection_with_deps`:
the uncheck is vetoed first, then this dialog asks.
"Delete & unselect" → `controller.confirm_unselect_property()` deletes the
matching entries in every view then re-applies the uncheck (which then
passes, the references being gone). "Cancel" → nothing to undo, the veto
already kept the selection as it was."""
from trame.app import get_server
from trame.widgets import vuetify3


class ThresholdUnselectDialog:
    """Modal bound to `state.thr_unselect_dialog_visible`; the node info
    (title, entry count) travels in `state.thr_unselect_dialog`."""

    def render(self):
        controller = get_server().controller
        with vuetify3.VDialog(
            v_model=("thr_unselect_dialog_visible", False),
            width=520,
        ):
            with vuetify3.VCard():
                vuetify3.VCardTitle("Property used by thresholds")
                vuetify3.VCardText(
                    "“{{ (thr_unselect_dialog || {}).title }}” feeds "
                    "{{ (thr_unselect_dialog || {}).count }} threshold "
                    "entr{{ (thr_unselect_dialog || {}).count > 1 ? 'ies' : 'y' }} "
                    "on its grid. Delete them and unselect the property?"
                )
                with vuetify3.VCardActions():
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        "Cancel",
                        variant="text",
                        click="thr_unselect_dialog_visible = false",
                    )
                    vuetify3.VBtn(
                        "Delete & unselect",
                        color="warning",
                        variant="flat",
                        click=controller.confirm_unselect_property,
                    )
