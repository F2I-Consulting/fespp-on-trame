"""A closed view or panel takes its change handlers with it.

trame registers a `@state.change` handler for the life of the server and
offers no way to unregister it. Every render view wires five handlers on
its own suffixed vars, every analysis panel a few more. Left alone, a
session that opens and closes views all day accumulates them, each called
on every change of a var nothing writes any more. `per_view_state.teardown`
drops the view's keys from trame's table, and boot's panel-closed hook
drops the panel's.
"""
from fespp_on_trame.app.views import per_view_state


class FakeState:
    """A trame state as far as these helpers read it: the private
    `_change_callbacks` table (key -> [(func, translator)]) and the
    per-view vars written as attributes."""

    def __init__(self):
        self._change_callbacks = {}

    def __setitem__(self, name, value):
        setattr(self, name, value)

    def change(self, *keys):
        def register(func):
            for k in keys:
                self._change_callbacks.setdefault(k, []).append((func, None))
            return func
        return register


def _handler(**_):
    return None


def test_dropping_a_key_forgets_every_handler_on_it_and_no_other():
    state = FakeState()
    state.change("active_path__view_1")(_handler)
    state.change("active_path__view_1")(_handler)
    state.change("active_path__view_2")(_handler)
    state.change("selected_paths")(_handler)
    gone = per_view_state.drop_listeners(state, ["active_path__view_1", "never_registered"])
    assert gone == 2
    assert "active_path__view_1" not in state._change_callbacks
    assert len(state._change_callbacks["active_path__view_2"]) == 1
    assert len(state._change_callbacks["selected_paths"]) == 1


def test_a_state_without_the_table_is_left_alone():
    class Bare:
        pass
    assert per_view_state.drop_listeners(Bare(), ["x"]) == 0


def test_the_teardown_of_a_view_drops_its_own_handlers():
    state = FakeState()
    vid = "view_7"
    for prefix in ("pos_ev__", "ui_cmap_colors__", "ui_cmap_opacities__",
                   "active_path__", "colour_request__"):
        state.change(prefix + vid)(_handler)
    state.change("active_path__view_8")(_handler)
    state.change("ui_loaded_rep_paths")(_handler)
    per_view_state.seed(state, vid)
    per_view_state.teardown(state, vid)
    assert not any(k.endswith("__" + vid) for k in state._change_callbacks), \
        "the closed view's handlers are gone"
    assert "active_path__view_8" in state._change_callbacks, "another view keeps its own"
    assert "ui_loaded_rep_paths" in state._change_callbacks, "session-wide handlers stay"
