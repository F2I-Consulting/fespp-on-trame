"""Snackbar shown when a tree eye-toggle activates a property that
resolves to NO VTK array on the rep's rendered source — a partial /
empty property, or (for a wellbore frame) a log that lives on a
partition the extractor discards. Tells the user why nothing coloured
instead of leaving them guessing."""
from trame.widgets import html, vuetify3


class EmptyColorSnackbar:
    """Bottom snackbar bound to `state.empty_color_snackbar_visible`,
    body text from the dynamic `state.empty_color_snackbar_text`."""

    def render(self):
        with vuetify3.VSnackbar(
            v_model=("empty_color_snackbar_visible", False),
            timeout=4000,
            color="blue-grey-darken-1",
            location="bottom",
        ):
            with html.Div(classes="d-flex align-center"):
                vuetify3.VIcon(
                    "mdi-information-outline",
                    size="small",
                    classes="mr-2",
                )
                html.Span("{{ empty_color_snackbar_text }}")
