"""Content picker for a newly-spawned view.

Opened by the per-panel `+Right` / `+Below` buttons via the
controller hook `open_new_view_dialog(direction, reference_panel_id)`.
The dialog asks the user what content the new view should hold:

  - **Copy "{parent}" scene** — replicate the visibility / coloring
    state of the panel that spawned this dialog (`reference_panel_id`).
  - **Empty scene** — a render panel with no replicate (no source
    shown); the user picks via the tree afterwards.
  - **Diff scene** — the special diff panel (A − B). If a diff panel
    already exists, it's reused (and positioning is ignored in that
    case, by design of `get_or_create_diff_view`).

The dialog commits on a single click (each button is the action — no
separate Apply needed) so the flow stays "1 click on +Right → 1 click
on content type → done".
"""
from trame.app import get_server
from trame.widgets import html, vuetify3


class NewViewContentDialog:
    def __init__(self):
        self._server = get_server()
        self._state = self._server.state
        self._controller = self._server.controller

        self._state.setdefault("new_view_dialog_visible", False)
        self._state.setdefault("new_view_dialog_direction", "right")
        self._state.setdefault("new_view_dialog_reference_id", "")
        self._state.setdefault("new_view_dialog_reference_title", "")

        # Public hook the per-panel buttons use to open this dialog
        # with pre-set context (direction + which panel asked).
        self._controller.open_new_view_dialog = self.open_for

    # ----- lifecycle -----

    def open_for(self, direction: str, reference_panel_id: str):
        """Pre-fill the dialog state (direction + reference panel
        title for the 'Copy' label) and show it."""
        mv = getattr(self._server.context, "multi_view", None)
        ref_title = reference_panel_id
        if mv is not None:
            ref_title = (getattr(mv, "_panel_titles", {}) or {}).get(
                reference_panel_id, reference_panel_id
            )
        self._state.new_view_dialog_direction = direction or "right"
        self._state.new_view_dialog_reference_id = reference_panel_id or ""
        self._state.new_view_dialog_reference_title = ref_title or ""
        self._state.new_view_dialog_visible = True

    def close(self):
        self._state.new_view_dialog_visible = False

    # ----- actions (each closes the dialog) -----

    def _multi_view(self):
        return getattr(self._server.context, "multi_view", None)

    def _add_copy(self):
        mv = self._multi_view()
        if mv is not None:
            mv.add_view(
                kind="render",
                replicate=True,
                direction=self._state.new_view_dialog_direction,
                reference_panel_id=self._state.new_view_dialog_reference_id or None,
            )
        self.close()

    def _add_empty(self):
        mv = self._multi_view()
        if mv is not None:
            mv.add_view(
                kind="render",
                replicate=False,
                direction=self._state.new_view_dialog_direction,
                reference_panel_id=self._state.new_view_dialog_reference_id or None,
            )
        self.close()

    def _add_diff(self):
        mv = self._multi_view()
        if mv is not None:
            # Reset prior selection / error so the diff form opens
            # clean on the new view.
            self._state.diff_array_a_path = None
            self._state.diff_array_b_path = None
            self._state.diff_compute_error = ""
            self._state.fespp_diff_ready = False
            mv.get_or_create_diff_view(
                direction=self._state.new_view_dialog_direction,
                reference_panel_id=self._state.new_view_dialog_reference_id or None,
            )
        self.close()

    # ----- render -----

    def render(self):
        with vuetify3.VDialog(
            v_model=("new_view_dialog_visible", False),
            max_width="500",
        ):
            with vuetify3.VCard():
                with vuetify3.VCardTitle(classes="d-flex align-center pa-3"):
                    html.Span(
                        "Add view "
                        "{{ new_view_dialog_direction === 'below' ? 'below' : 'to the right of' }}"
                        " \"{{ new_view_dialog_reference_title || new_view_dialog_reference_id }}\"",
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
                with vuetify3.VCardText(classes="pt-3"):
                    html.Div(
                        "Pick the content for the new view:",
                        classes="text-caption text-medium-emphasis mb-3",
                    )
                    # 1. Copy from parent — replicates visibility +
                    # coloring of the source panel. Label is dynamic
                    # (shows the reference panel's title) so the slot
                    # carries an interpolated Span instead of static
                    # text.
                    with vuetify3.VBtn(
                        block=True,
                        variant="tonal",
                        color="blue",
                        prepend_icon="mdi-content-copy",
                        click=self._add_copy,
                        classes="mb-2 text-none justify-start",
                    ):
                        html.Span(
                            'Copy "{{ new_view_dialog_reference_title || new_view_dialog_reference_id }}" scene'
                        )
                    # 2. Empty render view — no replicate, blank
                    # scene that the user fills via the tree.
                    with vuetify3.VBtn(
                        block=True,
                        variant="tonal",
                        color="grey",
                        prepend_icon="mdi-square-outline",
                        click=self._add_empty,
                        classes="mb-2 text-none justify-start",
                    ):
                        html.Span("Empty scene")
                    # 3. Diff scene — reuses the singleton diff panel
                    # when present, otherwise creates it. Disabled when
                    # fewer than two props are loaded (no meaningful
                    # A/B pick).
                    with vuetify3.VBtn(
                        block=True,
                        variant="tonal",
                        color="purple",
                        prepend_icon="mdi-vector-difference",
                        click=self._add_diff,
                        classes="text-none justify-start",
                        disabled=("!diff_array_choices || diff_array_choices.length < 2",),
                    ):
                        html.Span("Diff scene (A − B)")
                    html.Div(
                        "Diff needs at least two loaded properties on the same grid.",
                        v_if="!diff_array_choices || diff_array_choices.length < 2",
                        classes="text-caption text-medium-emphasis mt-1",
                    )
