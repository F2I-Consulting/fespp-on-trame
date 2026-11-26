"""The player of a slicer card (app/features/slicer_card_host, slicer_player):
the button shows the player's state as the server says it, a click asks for
the other one — a pause the server let pass left the button on "pause" for
good (the PO, 20-23/11, the Time & Realizations card after another node was
made active). A pause always pauses and says so, whatever the card holds by
then."""
from fespp_on_trame.app.features import slicer_card_host


class _State(dict):
    def __getattr__(self, k):
        return self.get(k)

    def dirty(self, *_k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Any:
    """Whatever the host calls on it answers nothing."""

    def __getattr__(self, _name):
        return lambda *a, **k: None


class _Core:
    def __init__(self):
        self.state = _State()
        self.activation = _Any()
        self.ctx = _Any()
        self.lifecycle = _Any()
        self.scheduler = _Any()


class _Task:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


def _host(context):
    core = _Core()
    host = slicer_card_host.CardHost(core, tool="timereal", card_key="card__", player_key="player__",
                                     context=context, card_of=lambda *_a: None, draw=lambda *_a: None)
    return core, host


def _playing(host, vid="v1", entry="c3"):
    task = _Task()
    host.player._runs[vid] = {"entry": entry, "kind": "Categorical", "steps": [(0, 0, "t0"), (1, 1, "t1")],
                              "index": 1, "width": 0.05}
    host.player._tasks[vid] = task
    host.player.publish(vid)
    return task


def test_a_pause_pauses_when_the_card_has_nothing_to_cut_any_more():
    # no time step while a read goes on: the card has no object, the pause still pauses
    core, host = _host(lambda vid, extra=(): ("", {}, "", []))
    task = _playing(host)
    assert core.state["player__v1"]["playing"] is True
    host.gesture({"op": "player", "id": "c3", "action": "play", "value": False}, "v1")
    assert task.cancelled
    assert core.state["player__v1"]["playing"] is False


def test_a_row_of_one_step_does_not_play():
    # the view coloured by a series of one time step: a play would show the same image for ever
    core, host = _host(lambda vid, extra=(): ("", {}, "", []))
    host.player._runs["v1"] = {"entry": "c3", "kind": "Categorical", "steps": [(12, 12, "t12")],
                               "index": 0, "width": 0.05}
    host.player.play("v1", True)
    assert "v1" not in host.player._tasks
    assert core.state["player__v1"]["playing"] is False


def test_a_pause_pauses_when_the_card_was_made_again():
    # the card made again: its row has another id, the pause of the old one still pauses
    infos = {"time": {"label": "Time step", "kind": "Categorical", "extent": [0, 1], "values": [0, 1]}}
    core, host = _host(lambda vid, extra=(): ("@view", infos, "", []))
    task = _playing(host, entry="c3")
    host.gesture({"op": "player", "id": "c9", "action": "play", "value": False}, "v1")
    assert task.cancelled and core.state["player__v1"]["playing"] is False


def test_a_play_the_card_cannot_serve_leaves_the_player_as_it_is():
    core, host = _host(lambda vid, extra=(): ("", {}, "", []))
    host.gesture({"op": "player", "id": "c3", "action": "play", "value": True}, "v1")
    assert "v1" not in host.player._tasks
    assert not (core.state.get("player__v1") or {}).get("playing")
