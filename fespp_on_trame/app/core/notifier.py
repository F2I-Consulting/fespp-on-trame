"""One way to tell the reader something.

- ``say(text)`` — the session-wide snackbar: what no panel is there to
  carry (a gesture whose effect landed elsewhere, a refusal at the level of
  the application). Its visibility is pulsed, so two identical sentences in a
  row show as two.
- ``note(vid, text)`` — a note under a 3D view (navigation, refusals that
  concern that view): its own line, ``ui_view_note__<vid>``, shown whatever
  the view's mode and in its Navigation card, gone after ``NOTE_SECONDS``.
- ``readout(vid, text)`` — what a pick says about the picked cells,
  ``ui_pick_info__<vid>``. The two shared one line until slice 6: a note
  replaced the last pick's readout, and outside the selection mode it was
  shown nowhere but the Navigation card (04-verification D30).

The snackbar used to be pulsed by hand in half a dozen places, each writing
the same three lines. Slice 2b of the overhaul.
"""


NOTE_SECONDS = 8.0


class Notifier:
    def __init__(self, state):
        self._state = state

    def say(self, text):
        state = self._state
        state.empty_color_snackbar_text = text
        state.empty_color_snackbar_visible = False
        state.empty_color_snackbar_visible = True

    def note(self, vid, text):
        key = f"ui_view_note__{vid}"
        self._state[key] = text
        if text:
            # gone after a while, unless another note took its place; only
            # inside the server's loop (a gesture's handler)
            try:
                import asyncio
                asyncio.get_running_loop().call_later(
                    NOTE_SECONDS, self._expire, key, text)
            except RuntimeError:
                pass   # no loop running (a unit test): the note stays until replaced

    def _expire(self, key, text):
        state = self._state
        if getattr(state, key, None) == text:
            with state:
                state[key] = ""

    def readout(self, vid, text):
        self._state[f"ui_pick_info__{vid}"] = text
