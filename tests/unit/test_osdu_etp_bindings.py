"""app/features/osdu_etp.widget_bindings: the attributes the upload door's two
ETP / OSDU forms share, written once — each binds the state key or the
controller of its own name."""
from types import SimpleNamespace

from fespp_on_trame.app.features.osdu_etp import widget_bindings

TRIGGERS = ("etp_connect", "etp_select", "etp_disconnect",
            "osdu_scan", "osdu_search", "osdu_find", "osdu_kinds")
STATES = ("etp_connected", "etp_connecting", "etp_step", "etp_dataspaces",
          "etp_status", "osdu_explorer")


def _controller():
    return SimpleNamespace(**{name: object() for name in TRIGGERS})


def test_every_attribute_binds_the_state_key_or_controller_of_its_name():
    ctrl = _controller()
    bound = widget_bindings(ctrl)
    assert set(bound) == set(TRIGGERS) | set(STATES)
    for name in STATES:
        key, _default = bound[name]
        assert key == name
    for name in TRIGGERS:
        value = bound[name]
        target = value[0] if isinstance(value, tuple) else value
        assert target is getattr(ctrl, name)


def test_a_trigger_with_an_argument_passes_the_event():
    bound = widget_bindings(_controller())
    assert bound["etp_disconnect"] is not None and not isinstance(bound["etp_disconnect"], tuple)
    assert bound["osdu_scan"] is not None and not isinstance(bound["osdu_scan"], tuple)
    for name in ("etp_connect", "etp_select", "osdu_search", "osdu_find", "osdu_kinds"):
        assert bound[name][1] == "[$event]"
