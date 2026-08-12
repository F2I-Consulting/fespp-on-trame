"""Snackbar surfacing `state.load_error` — import / load failures.

`load_error` had WRITERS but no UI consumer: a corrupt EPC (fesapi
parse failure caught by `Collector.add_file`) or an unsupported upload
(the endpoint's extension filter) set the state var and the user saw…
nothing. This binds the var to a red bottom snackbar; writing a new
message re-opens it, an empty write is ignored.
"""
from trame.app import get_server
from trame.widgets import html, vuetify3


class LoadErrorSnackbar:
    """Bottom ERROR snackbar driven by `state.load_error` (text)."""

    def __init__(self):
        server = get_server()
        state = server.state
        state.setdefault("load_error", "")
        state.setdefault("load_error_visible", False)

        @state.change("load_error")
        def _on_load_error(load_error, **_):
            if load_error:
                state.load_error_visible = True

    def render(self):
        with vuetify3.VSnackbar(
            v_model=("load_error_visible", False),
            timeout=8000,
            color="error",
            location="bottom",
        ):
            with html.Div(
                classes="d-flex align-center",
                style="font-size: 1.05rem; font-weight: 600;",
            ):
                vuetify3.VIcon(
                    "mdi-alert-octagon",
                    size="large",
                    classes="mr-3",
                )
                html.Span("{{ load_error }}")
