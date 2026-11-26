"""app/scene/cards: one writer for the open cards of the 3D views."""
from fespp_on_trame.app.scene.cards import Cards, VAR


class _State(dict):
    def __getattr__(self, k):
        return self.get(k)


MODES = [{"key": "pick", "var": "ui_pick_mode__"},
         {"key": "frustum", "var": "ui_frustum_mode__"}]


def test_open_close_keep_the_order_and_say_when_nothing_changed():
    state = _State()
    cards = Cards(state, MODES)
    assert cards.open("v1", "tree") and cards.open("v1", "colormap")
    assert not cards.open("v1", "tree")
    assert cards.keys("v1") == ["tree", "colormap"]
    assert cards.open("v1", "tree", last=True)
    assert cards.keys("v1") == ["colormap", "tree"]
    assert cards.close("v1", "colormap") and not cards.close("v1", "colormap")
    assert state[VAR] == {"v1": ["tree"]}


def test_set_many_writes_once_and_keeps_the_other_views():
    state = _State()
    cards = Cards(state, MODES)
    cards.set("v1", ["tree"])
    assert cards.set_many({"v2": ["globe"], "v3": []})
    assert state[VAR] == {"v1": ["tree"], "v2": ["globe"], "v3": []}
    assert not cards.set_many({"v2": ["globe"]})


def test_a_mode_variable_follows_its_key():
    # D29: a restored session lit "pick" and left its mode off
    state = _State()
    cards = Cards(state, MODES)
    cards.set("v1", ["tree", "pick"])
    cards.sync_modes("v1")
    assert state["ui_pick_mode__v1"] is True and state["ui_frustum_mode__v1"] is False
