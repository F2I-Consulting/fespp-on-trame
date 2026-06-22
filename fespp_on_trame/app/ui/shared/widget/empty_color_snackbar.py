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
        # A WARNING (amber) snackbar, deliberately prominent — the previous
        # muted blue-grey info toast was easy to miss. Bigger alert icon +
        # bolder/larger text + a longer timeout so the user sees WHY the
        # property didn't paint (and why the eye flipped back to SolidColor).
        with vuetify3.VSnackbar(
            v_model=("empty_color_snackbar_visible", False),
            timeout=6000,
            color="warning",
            location="bottom",
        ):
            with html.Div(
                classes="d-flex align-center",
                style="font-size: 1.05rem; font-weight: 600;",
            ):
                vuetify3.VIcon(
                    "mdi-alert",
                    size="large",
                    classes="mr-3",
                )
                html.Span("{{ empty_color_snackbar_text }}")
