"""app/core/notifier: one way to tell the reader something (slice 2b)."""
from fespp_on_trame.app.core.notifier import Notifier


class _State:
    def __init__(self):
        self.writes = []

    def __setattr__(self, name, value):
        if name != "writes":
            self.writes.append((name, value))
        object.__setattr__(self, name, value)

    def __setitem__(self, name, value):
        self.writes.append((name, value))


def test_say_pulses_the_snackbar_so_a_repeated_sentence_shows_again():
    st = _State()
    n = Notifier(st)
    n.say("Nothing is selected")
    n.say("Nothing is selected")
    pulses = [w for w in st.writes if w[0] == "empty_color_snackbar_visible"]
    assert pulses == [("empty_color_snackbar_visible", False),
                      ("empty_color_snackbar_visible", True)] * 2
    assert ("empty_color_snackbar_text", "Nothing is selected") in st.writes


def test_note_and_readout_write_the_view_s_own_line():
    st = _State()
    n = Notifier(st)
    n.note("view_2", "Rotation centre set")
    n.readout("view_1", "Geogrid  cell #12")
    # a note and a readout no longer share a line (D30)
    assert ("ui_view_note__view_2", "Rotation centre set") in st.writes
    assert ("ui_pick_info__view_1", "Geogrid  cell #12") in st.writes
    assert not any(k == "ui_pick_info__view_2" for k, _v in st.writes)
