"""How the wells are drawn in the 3D views goes with the session: each log's
way (graph, curve, tube), the graphs' width, the markers' scale and the
markers named — of the objects read only, and back only for those the data
still holds.

No trame, no ParaView (the conftest stubs): the session adapter runs on a
fake state and a fake tree."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "widgets" / "session"))

from fespp_on_trame.app.session_host import FesppSessionHost  # noqa: E402

LOG, CURVE_LOG, MARKER, GONE = "/w/frame/AI", "/w/frame/PHI", "/w/markers/Top", "/other/log"


class FakeState(dict):
    """trame's state: attributes and items alike, None for what was never set."""

    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __missing__(self, k):
        return None


class FakeTree:
    def __init__(self, paths):
        self.paths = set(paths)

    def find_node_id(self, path):
        return 1 if path in self.paths else None


def _host(paths=(LOG, CURVE_LOG, MARKER)):
    server = types.SimpleNamespace(state=FakeState(), controller=None,
                                   context=types.SimpleNamespace(multi_view=None, tree=FakeTree(paths)))
    return FesppSessionHost(server), server.state


def test_the_wells_settings_of_the_objects_read_are_saved():
    host, state = _host()
    state.ui_log_modes = {LOG: "tube", CURVE_LOG: "curve", GONE: "tube"}
    state.ui_marker_labels = [MARKER, GONE]
    state.ui_log_width, state.ui_marker_scale = 183.2, 5.0
    wells = host._collect_wells([LOG, CURVE_LOG, MARKER])
    assert wells == {"log_modes": {LOG: "tube", CURVE_LOG: "curve"}, "marker_labels": [MARKER],
                     "log_width": 183.2, "marker_scale": 5.0}


def test_nothing_set_saves_nothing():
    host, _state = _host()
    assert host._collect_wells([LOG]) == {}


def test_the_wells_settings_come_back_for_what_the_data_holds():
    host, state = _host()
    host._restore_wells({"log_modes": {LOG: "curve", GONE: "tube", CURVE_LOG: "sideways"},
                         "marker_labels": [MARKER, GONE], "log_width": 90.0, "marker_scale": 0})
    assert state.ui_log_modes == {LOG: "curve"}
    assert state.ui_marker_labels == [MARKER]
    assert state.ui_log_width == 90.0
    assert state.ui_marker_scale is None


def test_a_session_saved_and_opened_again_draws_the_wells_alike():
    host, state = _host()
    state.ui_log_modes, state.ui_marker_labels, state.ui_log_width = {LOG: "graph"}, [MARKER], 12.5
    saved = host._collect_wells([LOG, MARKER])
    again, state2 = _host()
    again._restore_wells(saved)
    assert (state2.ui_log_modes, state2.ui_marker_labels, state2.ui_log_width) == ({LOG: "graph"}, [MARKER], 12.5)
