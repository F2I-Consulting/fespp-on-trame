"""Snackbar shown after a tree-hierarchy mode change wipes a non-empty
selection — extra confirmation that the user's previous picks have
been discarded."""
from trame.widgets import html, vuetify3


class HierarchySnackbar:
    """Bottom snackbar bound to `state.tree_hierarchy_snackbar_visible`."""

    def render(self):
        with vuetify3.VSnackbar(
            v_model=("tree_hierarchy_snackbar_visible", False),
            timeout=4500,
            color="orange-darken-2",
            location="bottom",
        ):
            with html.Div(classes="d-flex align-center"):
                vuetify3.VIcon(
                    "mdi-alert-circle-outline",
                    size="small",
                    classes="mr-2",
                )
                html.Span(
                    "Tree hierarchy changed — your previous selection has"
                    " been cleared. Re-pick what you want to load under the"
                    " new layout."
                )
