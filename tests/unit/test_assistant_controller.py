"""trame_fespp_assistant.controller: the Assistant's conversation, against a fake host.

A sentence is answered, run and undone, or asked back when it is unclear or
lacks something, always in the language it was written in."""
import asyncio
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "assistant"))
from trame_fespp_assistant.controller import (  # noqa: E402
    AssistantController, detect_language)


class FakeState(dict):
    def __init__(self):
        super().__init__()
        self.watchers = {}
        self.flushed = []

    def __getattr__(self, k):
        return self.get(k)

    def change(self, *names):
        def deco(fn):
            for n in names:
                self.watchers.setdefault(n, []).append(fn)
            return fn
        return deco

    def set(self, k, v):
        self[k] = v
        for fn in self.watchers.get(k, []):
            fn()

    def flush(self):
        # What the reader would see at that moment.
        self.flushed.append(dict(self.get("ui_assistant") or {}))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class WslinkState(FakeState):
    """The state as trame pushes it inside an event loop.

    A flush only queues the message: wslink sends it on a later turn of the
    loop (call_later(0), then a task). Leaving `with state:` flushes.
    `sent` is what the browser has received."""

    def __init__(self):
        super().__init__()
        self.sent = []

    def flush(self):
        super().flush()
        snap = dict(self.get("ui_assistant") or {})
        loop = asyncio.get_running_loop()

        async def _send():
            self.sent.append(snap)

        loop.call_later(0, lambda: loop.create_task(_send()))

    def __exit__(self, *a):
        self.flush()
        return False


class FakeServer:
    def __init__(self, state=None):
        self.state = state if state is not None else FakeState()


def _cmd(intent, conf=0.95, sure=True, missing=(), alternatives=(), targets=()):
    return {"intent": intent, "confidence": conf, "alternatives": list(alternatives),
            "slots": {}, "targets": list(targets), "missing": list(missing), "sure": sure}


PORO = {"path": "/g/poro", "title": "poro", "type": "ContinuousProperty", "kind": "porosity"}
PHIE = {"path": "/g/phie", "title": "PHIE", "type": "ContinuousProperty", "kind": "porosity"}


class FakeHost:
    READONLY = {"value", "describe", "list", "help", "save_session"}

    def __init__(self):
        self.said = {}              # sentence -> command
        self.calls = []
        self.fail = None            # the method that raises
        self.execute_ok = True
        self.token = "tok"
        self.ambiguous = set()      # intents that need one target and get several
        self.examples_by_lang = {"fr": ["montre poro", "cache poro", "quelle est la moyenne de poro ?",
                                        "exagération verticale x 3"],
                                 "en": ["show poro", "hide poro", "what is the mean of poro?"]}

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        if self.fail == name:
            raise RuntimeError(f"{name} broke")

    def parse(self, text):
        self._call("parse", text)
        return dict(self.said.get(text) or _cmd(None, 0.0, False))

    def readonly(self, intent):
        return intent in self.READONLY

    def answer(self, cmd, lang):
        self._call("answer", cmd["intent"], lang)
        return {"ok": True, "text": f"answer {cmd['intent']} {lang}",
                "rows": [["Mean", "0.21"], ("Minimum", 0.02)]}

    def execute(self, cmd, lang):
        self._call("execute", cmd["intent"], [t["path"] for t in cmd.get("targets") or []], lang)
        if not self.execute_ok:
            return {"ok": False, "text": "no 3D view", "undo": None}
        # A None token means done with nothing to undo (a highlight removed,
        # a hide of what was not shown), as the application's adapter
        # reports it.
        token = None if self.token is None else f"{self.token}-{cmd['intent']}"
        return {"ok": True, "text": f"did {cmd['intent']} {lang}", "undo": token}

    def undo(self, token, lang):
        self._call("undo", token, lang)
        return {"ok": True, "text": f"undid {token}"}

    def label(self, intent, lang):
        return {"fr": {"show": "afficher", "threshold": "filtrer par valeur", "highlight": "surligner"},
                "en": {"show": "show", "threshold": "filter by value", "highlight": "highlight"}
                }[lang].get(intent, intent)

    def missing(self, cmd):
        self._call("missing", cmd["intent"])
        out = [m for m in cmd.get("missing") or [] if m != "object|kind"]
        if cmd["intent"] in self.ambiguous and len(cmd.get("targets") or []) > 1:
            out.append("object|kind")
        return out

    def targets(self, cmd):
        self._call("targets", cmd["intent"])
        return [PORO, PHIE]

    def ask_missing(self, cmd, lang):
        self._call("ask_missing", cmd["intent"], lang)
        return {"text": "Laquelle ?" if lang == "fr" else "Which one?",
                "choices": [{"id": "target:" + t["path"], "label": t["title"]}
                            for t in self.targets(cmd)]}

    def examples(self, lang):
        return list(self.examples_by_lang[lang])


GRID = {"path": "/g", "title": "Geogrid", "type": "IjkGrid", "kind": ""}
NTG = {"path": "/g/ntg", "title": "NTG", "type": "ContinuousProperty", "kind": "net to gross ratio"}


class LiveHost(FakeHost):
    """A host whose targets() are computed from live state, like the adapter's.

    A grid named without a kind stands for its properties, narrowed to the
    view's active one when it is among them, and objects() returns the
    current data."""

    def __init__(self):
        super().__init__()
        self.data = {o["path"]: o for o in (GRID, PORO, PHIE, NTG)}
        self.active = None

    def objects(self):
        return list(self.data.values())

    def targets(self, cmd):
        self._call("targets", cmd["intent"])
        props = [o for p, o in self.data.items() if p.startswith("/g/")]
        return [p for p in props if p["path"] == self.active] or props

    def missing(self, cmd):
        self._call("missing", cmd["intent"])
        return ["object|kind"] if len(self.targets(cmd)) > 1 else []


def _ctl(host=None, state=None):
    server, host = FakeServer(state), host or FakeHost()
    return AssistantController(server, host), server.state, host


def _data(state):
    return state["ui_assistant"]


def _last(state):
    return _data(state)["messages"][-1]


def _called(host, name):
    return [c for c in host.calls if c[0] == name]


# ------------------------------------------------------------------ the state
def test_the_state_exists_before_anything_is_said():
    ctl, state, _ = _ctl()
    d = state[ctl.data_var]
    assert ctl.data_var == "ui_assistant"
    assert d["messages"] == [] and d["busy"] is False and d["can_undo"] is False
    assert d["lang"] == "fr" and d["examples"][0] == "montre poro"


def test_an_empty_sentence_is_ignored():
    ctl, state, host = _ctl()
    ctl.ask("   ")
    ctl.ask(None)
    assert _data(state)["messages"] == [] and host.calls == []


# ------------------------------------------------------------------ sure
def test_a_sure_question_is_answered_with_its_rows():
    ctl, state, host = _ctl()
    host.said["quelle est la moyenne de poro ?"] = _cmd("value", targets=[PORO])
    ctl.ask("quelle est la moyenne de poro ?")
    user, reply = _data(state)["messages"]
    assert user == {"id": 1, "role": "user", "text": "quelle est la moyenne de poro ?"}
    assert reply["role"] == "assistant" and reply["level"] == "ok" and reply["id"] == 2
    assert reply["text"] == "answer value fr"
    assert reply["rows"] == [["Mean", "0.21"], ["Minimum", 0.02]]
    assert reply["undoable"] is False and "choices" not in reply
    assert _called(host, "execute") == [] and _data(state)["busy"] is False


def test_a_sure_action_runs_can_be_undone_and_the_undo_clears():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    ctl.ask("montre poro")
    assert _called(host, "execute") == [("execute", "show", ["/g/poro"], "fr")]
    reply = _last(state)
    assert reply["level"] == "ok" and reply["text"] == "did show fr" and reply["undoable"] is True
    assert _data(state)["can_undo"] is True

    ctl.undo()
    assert _called(host, "undo") == [("undo", "tok-show", "fr")]
    msgs = _data(state)["messages"]
    assert msgs[-2]["role"] == "user"
    assert msgs[-1]["level"] == "ok" and msgs[-1]["text"] == "undid tok-show"
    assert not any(m.get("undoable") for m in msgs)
    assert _data(state)["can_undo"] is False


def test_the_busy_bar_is_pushed_while_the_command_runs():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    ctl.ask("montre poro")
    assert any(f.get("busy") is True for f in state.flushed)
    assert _data(state)["busy"] is False


def test_only_the_newest_action_carries_the_undo_and_undo_goes_back_in_order():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    host.said["filtre poro au-dessus de 0,2"] = _cmd("threshold", targets=[PORO])
    ctl.ask("montre poro")
    ctl.ask("filtre poro au-dessus de 0,2")
    undoable = [m for m in _data(state)["messages"] if m.get("undoable")]
    assert [m["text"] for m in undoable] == ["did threshold fr"]
    ctl.undo()
    assert _called(host, "undo")[-1][1] == "tok-threshold"
    # After that undo the show is the action on top: its message carries the
    # button again.
    undoable = [m for m in _data(state)["messages"] if m.get("undoable")]
    assert [m["text"] for m in undoable] == ["did show fr"]
    assert _data(state)["can_undo"] is True
    ctl.undo()
    assert _called(host, "undo")[-1][1] == "tok-show"
    ctl.undo()
    assert _last(state)["level"] == "info" and _last(state)["text"] == "Rien à annuler."


def test_a_typed_undo_uses_the_stack_of_the_conversation():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    host.said["annule"] = _cmd("undo")
    ctl.ask("montre poro")
    ctl.ask("annule")
    assert _called(host, "undo") == [("undo", "tok-show", "fr")]
    assert [c for c in _called(host, "execute") if c[1] == "undo"] == []
    assert _last(state)["text"] == "undid tok-show"


def test_an_action_that_failed_is_not_undoable():
    ctl, state, host = _ctl()
    host.said["show poro"] = _cmd("show", targets=[PORO])
    host.execute_ok = False
    ctl.ask("show poro")
    assert _last(state)["level"] == "error" and _last(state)["text"] == "no 3D view"
    assert _last(state)["undoable"] is False and _data(state)["can_undo"] is False


def test_an_action_done_without_a_token_is_not_undoable_and_the_one_before_stays():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    host.said["enlève la surbrillance"] = _cmd("clear_highlight")
    ctl.ask("montre poro")
    host.token = None
    ctl.ask("enlève la surbrillance")
    reply = _last(state)
    assert reply["level"] == "ok" and reply["text"] == "did clear_highlight fr"
    assert reply["undoable"] is False
    # The show is still the action on top: its reply keeps the button.
    assert [m["text"] for m in _data(state)["messages"] if m.get("undoable")] == ["did show fr"]
    assert _data(state)["can_undo"] is True
    ctl.undo()
    assert _called(host, "undo") == [("undo", "tok-show", "fr")]
    assert _data(state)["can_undo"] is False


def test_the_undo_stack_keeps_twenty():
    ctl, state, host = _ctl()
    host.said["show poro"] = _cmd("show", targets=[PORO])
    for _ in range(25):
        ctl.ask("show poro")
    for _ in range(25):
        ctl.undo()
    assert len(_called(host, "undo")) == 20
    assert _last(state)["text"] == "Nothing to undo."


def test_the_conversation_keeps_its_last_two_hundred_messages():
    ctl, state, host = _ctl()
    host.said["show poro"] = _cmd("show", targets=[PORO])
    for _ in range(120):
        ctl.ask("show poro")
    msgs = _data(state)["messages"]
    assert len(msgs) == 200
    assert msgs[-1]["id"] == 240 and [m["id"] for m in msgs] == sorted(m["id"] for m in msgs)


def test_an_action_whose_reply_left_the_conversation_is_no_longer_undoable():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    host.said["décris poro"] = _cmd("describe", targets=[PORO])
    ctl.ask("montre poro")
    for _ in range(99):
        ctl.ask("décris poro")
    # 200 messages: the action's reply is still there and carries the Undo.
    assert [m["id"] for m in _data(state)["messages"] if m.get("undoable")] == [2]
    assert _data(state)["can_undo"] is True
    ctl.ask("décris poro")
    d = _data(state)
    assert d["messages"][0]["id"] == 3
    assert d["can_undo"] is False and not any(m.get("undoable") for m in d["messages"])
    ctl.undo()
    assert _called(host, "undo") == [] and _last(state)["text"] == "Rien à annuler."


def test_the_undo_button_undoes_its_own_action_only_while_it_is_the_last_one(capsys):
    ctl, state, host = _ctl()
    host.said["filtre poro au-dessus de 0,2"] = _cmd("threshold", targets=[PORO])
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    ctl.ask("filtre poro au-dessus de 0,2")
    ctl.ask("montre poro")
    top = [m["id"] for m in _data(state)["messages"] if m.get("undoable")]
    assert top == [4]
    ctl.undo(4)
    # A double click: its action is already undone and the filter is on top.
    n = len(_data(state)["messages"])
    ctl.undo(4)
    assert _called(host, "undo") == [("undo", "tok-show", "fr")]
    assert len(_data(state)["messages"]) == n
    undoable = [m for m in _data(state)["messages"] if m.get("undoable")]
    assert [m["text"] for m in undoable] == ["did threshold fr"] and _data(state)["can_undo"] is True
    # An id that never carried an Undo (the user's own message) does nothing.
    ctl.undo(1)
    assert len(_called(host, "undo")) == 1 and len(_data(state)["messages"]) == n
    # The filter's own button still works, even with the id as a float, the
    # way JSON may deliver it.
    ctl.undo(float(undoable[0]["id"]))
    assert _called(host, "undo")[-1] == ("undo", "tok-threshold", "fr")
    # Nothing left: a stale button, or an id that is not one, is ignored,
    # not answered "nothing to undo".
    n = len(_data(state)["messages"])
    ctl.undo(undoable[0]["id"])
    ctl.undo("junk")
    assert len(_data(state)["messages"]) == n
    assert "ignored" in capsys.readouterr().out


# ------------------------------------------------------------------ busy
def test_in_an_event_the_busy_bar_reaches_the_browser_before_the_work():
    async def main():
        ctl, state, host = _ctl(state=WslinkState())
        host.said["montre poro"] = _cmd("show", targets=[PORO])
        seen = []
        execute = host.execute

        def watched_execute(cmd, lang):
            # What the browser had received when the work began.
            seen.append([s.get("busy") for s in state.sent])
            return execute(cmd, lang)

        host.execute = watched_execute
        with state:                      # the trame event
            ctl.ask("montre poro")
        # The event returns before the work: the bar is up, no reply yet.
        assert _called(host, "execute") == []
        assert _data(state)["busy"] is True and _last(state)["role"] == "user"
        await ctl.idle()
        assert seen and True in seen[0]
        assert _last(state)["text"] == "did show fr" and _last(state)["undoable"] is True
        assert _data(state)["busy"] is False
        await asyncio.sleep(0.01)
        assert state.sent[-1]["busy"] is False and state.sent[-1]["messages"][-1]["text"] == "did show fr"

        # The Undo goes the same way: the bar reaches the browser first,
        # then the undo runs.
        seen.clear()
        undo = host.undo

        def watched_undo(token, lang):
            seen.append(state.sent[-1].get("busy"))
            return undo(token, lang)

        host.undo = watched_undo
        with state:
            ctl.undo(_last(state)["id"])
        assert _called(host, "undo") == [] and _data(state)["busy"] is True
        await ctl.idle()
        assert seen == [True] and _last(state)["text"] == "undid tok-show"
        assert _data(state)["busy"] is False

    asyncio.run(main())


def test_the_gestures_that_arrive_while_a_command_runs_are_ignored(capsys):
    async def main():
        ctl, state, host = _ctl(state=WslinkState())
        host.said["montre poro"] = _cmd("show", targets=[PORO])
        with state:
            ctl.ask("montre poro")
        n = len(_data(state)["messages"])
        with state:
            ctl.ask("montre poro")       # the example clicked twice
            ctl.undo()
            ctl.choose("cancel")
            ctl.clear()
        assert len(_data(state)["messages"]) == n
        await ctl.idle()
        assert _called(host, "execute") == [("execute", "show", ["/g/poro"], "fr")]
        assert _called(host, "undo") == [] and _data(state)["can_undo"] is True

    asyncio.run(main())
    assert "ignored: a command is running" in capsys.readouterr().out


def test_idle_returns_at_once_when_nothing_runs():
    ctl, state, host = _ctl()
    asyncio.run(asyncio.wait_for(ctl.idle(), 1.0))
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    # Without a running loop the command runs through: the reply is there.
    ctl.ask("montre poro")
    assert _last(state)["text"] == "did show fr" and _data(state)["busy"] is False
    asyncio.run(asyncio.wait_for(ctl.idle(), 1.0))


# ------------------------------------------------------------------ too long
def test_a_sentence_too_long_is_refused_without_being_parsed():
    ctl, state, host = _ctl()
    ctl.ask("montre " + "poro " * 400)
    assert _called(host, "parse") == []
    user, reply = _data(state)["messages"]
    assert len(user["text"]) <= 501 and user["text"].endswith("…")
    assert reply["level"] == "error"
    assert reply["text"] == ("Cette demande est trop longue (plus de 500 caractères) :"
                             " une commande tient en une phrase.")
    ctl.ask("show " + "poro " * 400)
    assert _last(state)["text"].startswith("That request is too long (over 500 characters)")
    # A sentence at the bound is parsed.
    ctl.ask("x" * 500)
    assert _called(host, "parse") == [("parse", "x" * 500)]


# ------------------------------------------------------------------ unclear
def test_an_unsure_command_asks_which_one_was_meant_and_the_choice_runs():
    ctl, state, host = _ctl()
    host.said["poro 0,2"] = _cmd("threshold", conf=0.41, sure=False, targets=[PORO],
                                 alternatives=[("highlight", 0.3), ("show", 0.2), ("value", 0.05)])
    ctl.ask("poro 0,2")
    ask = _last(state)
    assert ask["level"] == "ask" and ask["text"] == "Voulez-vous dire… ?"
    assert ask["choices"] == [{"id": "intent:threshold", "label": "filtrer par valeur"},
                              {"id": "intent:highlight", "label": "surligner"},
                              {"id": "intent:show", "label": "afficher"},
                              {"id": "none", "label": "Rien de tout ça — je précise"},
                              {"id": "cancel", "label": "Annuler"}]
    assert _called(host, "execute") == []

    ctl.choose("intent:highlight")
    msgs = _data(state)["messages"]
    assert msgs[-2] == {"id": msgs[-2]["id"], "role": "user", "text": "surligner"}
    assert _called(host, "execute") == [("execute", "highlight", ["/g/poro"], "fr")]
    assert msgs[-1]["level"] == "ok" and msgs[-1]["text"] == "did highlight fr"


def test_a_chosen_intent_is_read_again_by_the_host_that_can():
    """The host reads the sentence again for the gesture chosen
    (`with_intent`): what it settles there (a hiding said stays a hiding)
    is in the command that runs."""
    ctl, state, host = _ctl()
    host.said["masque des mailles de poro"] = _cmd("hide", conf=0.4, sure=False, targets=[PORO],
                                                   alternatives=[("threshold", 0.3)])
    host.with_intent = lambda cmd, intent: dict(cmd, intent=intent, slots=dict(cmd["slots"], exclude=True))
    ran = []
    execute = host.execute
    host.execute = lambda cmd, lang: ran.append(dict(cmd)) or execute(cmd, lang)
    ctl.ask("masque des mailles de poro")
    ctl.choose("intent:threshold")
    assert ran and ran[-1]["intent"] == "threshold" and ran[-1]["slots"] == {"exclude": True} and ran[-1]["sure"]


def test_a_chosen_intent_that_still_lacks_something_is_asked_again():
    ctl, state, host = _ctl()
    host.ambiguous = {"value"}
    host.said["poro ?"] = _cmd("describe", conf=0.4, sure=False, targets=[PORO, PHIE],
                               alternatives=[("value", 0.35)])
    ctl.ask("poro ?")
    ctl.choose("intent:value")
    assert _called(host, "ask_missing") == [("ask_missing", "value", "fr")]
    assert _last(state)["level"] == "ask"
    ctl.choose("target:/g/phie")
    assert _called(host, "answer") == [("answer", "value", "fr")]


def test_a_command_lacking_an_object_asks_for_it_and_the_target_runs():
    ctl, state, host = _ctl()
    host.ambiguous = {"threshold"}
    host.said["filtre la porosité au-dessus de 0,2"] = _cmd("threshold", targets=[PORO, PHIE])
    ctl.ask("filtre la porosité au-dessus de 0,2")
    ask = _last(state)
    assert _called(host, "ask_missing") == [("ask_missing", "threshold", "fr")]
    assert ask["level"] == "ask" and ask["text"] == "Laquelle ?"
    assert [c["id"] for c in ask["choices"]] == ["target:/g/poro", "target:/g/phie", "none", "cancel"]
    assert _called(host, "execute") == []

    ctl.choose("target:/g/phie")
    assert _called(host, "execute") == [("execute", "threshold", ["/g/phie"], "fr")]
    assert _last(state)["undoable"] is True


def test_a_command_the_engine_found_incomplete_but_clear_asks_what_is_missing():
    ctl, state, host = _ctl()
    host.said["filtre poro"] = _cmd("threshold", conf=0.9, sure=False, missing=["min|max"],
                                    targets=[PORO])
    ctl.ask("filtre poro")
    assert _called(host, "ask_missing") == [("ask_missing", "threshold", "fr")]
    assert _last(state)["level"] == "ask"


def test_a_target_clicked_after_the_active_property_changed_runs_on_the_one_clicked():
    host = LiveHost()
    ctl, state, _ = _ctl(host)
    host.said["filtre Geogrid au-dessus de 0,2"] = _cmd("threshold", targets=[GRID])
    ctl.ask("filtre Geogrid au-dessus de 0,2")
    assert [c["id"] for c in _last(state)["choices"]] == [
        "target:/g/poro", "target:/g/phie", "target:/g/ntg", "none", "cancel"]
    # The reader activates poro in the tree to check, which narrows the live
    # candidates to it, then clicks NTG.
    host.active = "/g/poro"
    ctl.choose("target:/g/ntg")
    assert _called(host, "execute") == [("execute", "threshold", ["/g/ntg"], "fr")]
    assert _last(state)["level"] == "ok"


def test_a_target_gone_from_the_data_is_refused_and_asked_again():
    host = LiveHost()
    ctl, state, _ = _ctl(host)
    host.said["surligne les mailles au-dessus de 0,2"] = _cmd("highlight", targets=[GRID])
    ctl.ask("surligne les mailles au-dessus de 0,2")
    # NTG leaves the data (a file reloaded) and poro becomes active meanwhile.
    del host.data["/g/ntg"]
    host.active = "/g/poro"
    ctl.choose("target:/g/ntg")
    assert _called(host, "execute") == []
    gone, again = _data(state)["messages"][-2:]
    assert gone["level"] == "error" and gone["text"] == "« NTG » n'est plus disponible : rien n'est fait."
    assert again["level"] == "ask" and [c["id"] for c in again["choices"]] == ["target:/g/poro", "none", "cancel"]
    # The question asked again works.
    ctl.choose("target:/g/poro")
    assert _called(host, "execute") == [("execute", "highlight", ["/g/poro"], "fr")]


def test_a_host_that_cannot_list_its_data_never_runs_a_target_on_nothing():
    host = LiveHost()
    host.objects = None                  # no objects(): the candidates alone decide
    ctl, state, _ = _ctl(host)
    host.said["cache"] = _cmd("hide", conf=0.9, sure=True, missing=["object|kind"])
    ctl.ask("cache")
    assert _last(state)["level"] == "ask"
    host.active = "/g/phie"
    ctl.choose("target:/g/ntg")
    # Never execute(hide, []): the host would hide everything.
    assert _called(host, "execute") == []
    gone, again = _data(state)["messages"][-2:]
    assert gone["level"] == "error" and again["level"] == "ask"
    # A target still among the candidates runs.
    ctl.choose("target:/g/phie")
    assert _called(host, "execute") == [("execute", "hide", ["/g/phie"], "fr")]


def test_cancel_does_nothing():
    ctl, state, host = _ctl()
    host.said["poro"] = _cmd("show", conf=0.3, sure=False, targets=[PORO])
    ctl.ask("poro")
    ctl.choose("cancel")
    assert _last(state)["level"] == "info" and _last(state)["text"] == "D'accord, rien n'est fait."
    assert _called(host, "execute") == []
    # The question is answered: the same button again does nothing.
    n = len(_data(state)["messages"])
    ctl.choose("cancel")
    assert len(_data(state)["messages"]) == n


def test_a_choice_on_an_older_message_is_ignored():
    ctl, state, host = _ctl()
    host.ambiguous = {"threshold"}
    host.said["filtre la porosité au-dessus de 0,2"] = _cmd("threshold", targets=[PORO, PHIE])
    host.said["liste ce qui est chargé"] = _cmd("list")
    ctl.ask("filtre la porosité au-dessus de 0,2")
    ctl.ask("liste ce qui est chargé")
    n = len(_data(state)["messages"])
    ctl.choose("target:/g/poro")
    assert _called(host, "execute") == [] and len(_data(state)["messages"]) == n
    # Neither is a choice that was never offered.
    host.said["poro"] = _cmd("show", conf=0.3, sure=False, targets=[PORO])
    ctl.ask("poro")
    ctl.choose("target:/g/poro")
    assert _called(host, "execute") == []


# ------------------------------------------------------------------ failures
def test_a_sentence_not_understood_says_so_with_three_examples():
    ctl, state, host = _ctl()
    ctl.ask("blablabla xyz")
    reply = _last(state)
    assert reply["level"] == "error"
    assert reply["text"].startswith("Je n'ai pas compris. Essayez par exemple : ")
    assert "« montre poro »" in reply["text"] and "« quelle est la moyenne de poro ? »" in reply["text"]
    assert "exagération" not in reply["text"]


def test_a_sentence_not_understood_in_english_is_answered_in_english():
    ctl, state, host = _ctl()
    ctl.ask("please do the thing")
    reply = _last(state)
    assert reply["text"].startswith("I did not understand. Try for instance: ")
    assert "“show poro”" in reply["text"]
    assert _data(state)["lang"] == "en" and _data(state)["examples"][0] == "show poro"


def test_a_host_that_raises_gives_an_error_message_and_the_panel_is_not_left_busy():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    host.fail = "execute"
    ctl.ask("montre poro")
    reply = _last(state)
    assert reply["level"] == "error" and reply["text"] == "Une erreur est survenue : execute broke"
    assert _data(state)["busy"] is False and _data(state)["can_undo"] is False

    host.fail = "parse"
    ctl.ask("show poro")
    assert _last(state)["text"] == "Something went wrong: parse broke"

    host.fail = None
    ctl.ask("montre poro")
    host.fail = "undo"
    ctl.undo()
    assert _last(state)["level"] == "error" and _last(state)["text"].endswith("undo broke")
    assert _data(state)["busy"] is False


def test_a_question_the_host_could_not_answer_is_an_error():
    ctl, state, host = _ctl()
    host.said["décris poro"] = _cmd("describe", targets=[PORO])
    host.answer = lambda cmd, lang: {"ok": False, "text": "rien", "rows": []}
    ctl.ask("décris poro")
    assert _last(state)["level"] == "error" and "rows" not in _last(state)


# ------------------------------------------------------------------ language
def test_the_language_of_a_sentence():
    fr = ["montre la porosité de Geogrid", "filtre la porosité au-dessus de 0,2",
          "quelle est la porosité moyenne ?", "exagération verticale x 3", "ouvre les statistiques",
          "décris Geogrid", "liste ce qui est chargé",
          "surligne les mailles où la porosité dépasse 0,2", "enlève la surbrillance",
          "montre poro", "cache poro", "remets l'ombrage", "qu'est-ce que tu sais faire ?"]
    en = ["show the porosity of Geogrid", "filter porosity above 0.2", "what is the mean porosity?",
          "vertical exaggeration x 3", "open the statistics", "describe Geogrid",
          "list what is loaded", "highlight cells where porosity exceeds 0.2",
          "remove the highlight", "show poro", "hide poro", "let's undo that", "don't show the grid"]
    assert [s for s in fr if detect_language(s) != "fr"] == []
    assert [s for s in en if detect_language(s) != "en"] == []


def test_the_english_verbs_of_the_commands_and_the_words_both_languages_write():
    for s in ("isolate Geogrid", "rescale PHIT", "drop NaN", "exclude poro",
              "enable shading", "disable shading", "cut the grid along I"):
        assert detect_language(s) == "en", s
    # "vertical" is also a French word, so the conversation's language stays.
    assert detect_language("zoom vertical x 3") == "fr"
    assert detect_language("zoom vertical x 3", "en") == "en"
    assert detect_language("exagération verticale x 3", "en") == "fr"
    assert detect_language("vertical exaggeration x 3") == "en"


def test_a_sentence_that_says_neither_keeps_the_language_given():
    assert detect_language("xqzt") == "fr"
    assert detect_language("xqzt", "en") == "en"
    assert detect_language("Geogrid PHIT", "en") == "en"
    assert detect_language("", "fr") == "fr"


def test_the_reply_follows_the_language_of_each_sentence():
    ctl, state, host = _ctl()
    host.said["show poro"] = _cmd("show", targets=[PORO])
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    ctl.ask("show poro")
    assert _last(state)["text"] == "did show en" and _data(state)["lang"] == "en"
    ctl.ask("montre poro")
    assert _last(state)["text"] == "did show fr" and _data(state)["lang"] == "fr"
    # A sentence of neither language keeps the conversation's language.
    host.said["poro"] = _cmd("show", conf=0.3, sure=False, targets=[PORO])
    ctl.ask("poro")
    assert _last(state)["text"] == "Voulez-vous dire… ?"


# ------------------------------------------------------------------ clear
def test_clear_empties_the_conversation_and_forgets_what_was_pending():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    host.said["poro"] = _cmd("show", conf=0.3, sure=False, targets=[PORO])
    ctl.ask("montre poro")
    ctl.ask("poro")
    ctl.clear()
    d = _data(state)
    assert d["messages"] == [] and d["can_undo"] is False and d["examples"]
    ctl.choose("intent:show")
    ctl.undo()
    assert len(_called(host, "execute")) == 1 and _called(host, "undo") == []
    assert _last(state)["text"] == "Rien à annuler."
    # The ids keep increasing across a clear.
    assert _last(state)["id"] > 4


def test_the_examples_are_asked_again_when_the_host_says_the_data_changed():
    host = FakeHost()
    host.examples_watch = ("assembly_rev",)
    ctl, state, _ = _ctl(host)
    host.examples_by_lang["fr"] = ["montre la porosité de Geogrid"]
    state.set("assembly_rev", 2)
    assert _data(state)["examples"] == ["montre la porosité de Geogrid"]


def test_an_undo_the_host_refuses_keeps_the_action_to_undo():
    """An undo the host refuses leaves the action on the stack.

    When the host refuses to undo (for instance on a Globe view), nothing
    is undone, so the action stays on the stack and a later undo reaches
    it, not the action before it."""
    ctl, state, host = _ctl()
    host.said["filtre poro"] = _cmd("threshold", targets=[PORO])
    host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
    ctl.ask("filtre poro")
    ctl.ask("passe en viridis")
    real_undo = host.undo
    host.undo = lambda token, lang: (host.calls.append(("undo", token, lang))
                                     or {"ok": False, "text": "Pas sur un globe."})
    ctl.undo()
    assert _last(state)["level"] == "error" and _data(state)["can_undo"] is True
    assert _last(state)["undoable"] is False
    host.undo = real_undo
    ctl.undo()
    # The colour table again (refused the first time), not the filter
    # before it.
    assert [c[1] for c in _called(host, "undo")] == ["tok-colormap", "tok-colormap"]


def test_clear_undo_forgets_the_actions_even_while_a_command_runs():
    ctl, state, host = _ctl()
    host.said["filtre poro"] = _cmd("threshold", targets=[PORO])
    ctl.ask("filtre poro")
    ctl._busy = True                                  # a command is running
    ctl.clear_undo()
    ctl._busy = False
    data = _data(state)
    assert data["can_undo"] is False and not any(m.get("undoable") for m in data["messages"])
    assert data["messages"]                           # the conversation stays


def test_a_choice_between_gestures_is_asked_with_the_host_s_words_filter_first():
    """A choice between two gestures is offered in the host's words.

    For a sentence such as "affiche les zones d'huile" (show the oil zones),
    the host says the sentence leaves a choice between two gestures, and
    the buttons word them for this very command, the filter first."""
    ctl, state, host = _ctl()
    host.choice_label = lambda cmd, intent, lang: {"threshold": "Ne garder que les mailles « oil »",
                                                   "highlight": "Surligner les mailles « oil »"}[intent]
    cmd = _cmd("threshold", conf=0.9, sure=False, targets=[PORO])
    cmd["choose_between"] = ["threshold", "highlight"]
    host.said["affiche les zones d'huile"] = cmd
    ctl.ask("affiche les zones d'huile")
    reply = _last(state)
    assert reply["level"] == "ask" and reply["text"] == "Que voulez-vous faire ?"
    assert [c["label"] for c in reply["choices"]] == [
        "Ne garder que les mailles « oil »", "Surligner les mailles « oil »", "Rien de tout ça — je précise", "Annuler"]
    ctl.choose("intent:highlight")
    assert _called(host, "execute")[-1][1] == "highlight"


# ------------------------------------------------------------------ "none of these": learning from the reader
def _journaled():
    events = []
    server, host = FakeServer(), FakeHost()
    return AssistantController(server, host, journal=events.append), server.state, host, events


def test_none_of_these_asks_to_rephrase_and_a_rephrasing_that_works_is_learned():
    """"None of these" asks for a rephrasing, and a working rephrasing is learned.

    Rather than a slow learning loop, "none of these" opens the free field;
    the request said again in other words and carried out becomes a
    labelled example: the first words, and what they meant."""
    ctl, state, host, events = _journaled()
    host.said["masque les autres zones"] = _cmd("hide_nan", conf=0.4, sure=False,
                                                alternatives=[("hide", 0.2)])
    host.said["ne garde que l'eau"] = _cmd("threshold", targets=[PORO])
    ctl.ask("masque les autres zones")
    assert "none" in [c["id"] for c in _last(state)["choices"]]
    ctl.choose("none")
    assert _last(state)["level"] == "ask" and _last(state)["text"].startswith("Dites-le autrement")
    ctl.ask("ne garde que l'eau")
    assert _called(host, "execute")[-1][1] == "threshold"
    learned = [e for e in events if e["event"] == "learned"]
    assert learned and learned[0]["original"] == "masque les autres zones"
    assert learned[0]["text"] == "ne garde que l'eau" and learned[0]["intent"] == "threshold"


def test_a_rephrasing_still_not_understood_asks_for_the_result_expected_and_notes_it():
    ctl, state, host, events = _journaled()
    host.said["montre le truc"] = _cmd("show", conf=0.3, sure=False, alternatives=[("hide", 0.2)])
    ctl.ask("montre le truc")
    ctl.choose("none")
    ctl.ask("le machin là")                           # not understood either
    assert _last(state)["text"].startswith("Toujours pas")
    ctl.ask("je voulais voir la grille coloriée par les fluides")
    assert _last(state)["text"] == "Merci, c'est noté pour l'apprentissage."
    expected = [e for e in events if e["event"] == "expected"]
    assert expected and expected[0]["original"] == "montre le truc"
    assert expected[0]["text"] == "je voulais voir la grille coloriée par les fluides"
    assert _called(host, "execute") == []             # a description is noted, never run


def test_a_complaint_offers_to_undo_and_learns_the_rephrasing_for_the_sentence_that_went_wrong():
    """A complaint offers the undo and learns the next sentence for the earlier one.

    After a complaint such as "ta réponse ne me convient pas" (that answer
    does not suit me), the undo is offered, and what the reader says next
    is learned for the sentence that went wrong, not for the complaint."""
    ctl, state, host, events = _journaled()
    host.said["montre moi les zones d'huile"] = _cmd("highlight", targets=[PORO])
    host.said["ta réponse ne me convient pas"] = _cmd("complain")
    host.said["masque la zone huile"] = _cmd("threshold", targets=[PORO])
    ctl.ask("montre moi les zones d'huile")
    ctl.ask("ta réponse ne me convient pas")
    sorry = _last(state)
    assert sorry["level"] == "ask" and sorry["text"].startswith("Désolé")
    assert [c["id"] for c in sorry["choices"]] == ["undo", "intent:reset_camera", "cancel"]
    ctl.choose("undo")
    assert _called(host, "undo")
    ctl.ask("masque la zone huile")
    learned = [e for e in events if e["event"] == "learned"]
    assert learned[-1]["original"] == "montre moi les zones d'huile"
    assert learned[-1]["intent"] == "threshold"


def test_a_learned_rephrasing_that_is_undone_is_unlearned():
    ctl, state, host, events = _journaled()
    host.said["le truc"] = _cmd("show", conf=0.3, sure=False, alternatives=[("hide", 0.2)])
    host.said["cache poro"] = _cmd("hide", targets=[PORO])
    ctl.ask("le truc")
    ctl.choose("none")
    ctl.ask("cache poro")
    assert any(e["event"] == "learned" for e in events)
    ctl.undo()
    assert any(e["event"] == "unlearned" for e in events)


# ------------------------------------------------------------------ several commands in one sentence
def test_the_commands_of_a_sentence_run_in_order_each_with_its_reply_and_undo():
    ctl, state, host = _ctl()
    first = _cmd("show", targets=[PORO])
    first["then"] = [_cmd("colormap", targets=[PORO]), _cmd("z_scale")]
    host.said["montre poro et passe en viridis puis exagération x3"] = first
    ctl.ask("montre poro et passe en viridis puis exagération x3")
    assert [c[1] for c in _called(host, "execute")] == ["show", "colormap", "z_scale"]
    replies = [m for m in _data(state)["messages"] if m["role"] == "assistant"]
    assert [m["level"] for m in replies] == ["ok", "ok", "ok"]
    assert [t for t, _c, _m in ctl._undo] == ["tok-show", "tok-colormap", "tok-z_scale"]


def test_the_chain_stops_to_ask_when_a_later_command_is_unsure():
    ctl, state, host = _ctl()
    first = _cmd("show", targets=[PORO])
    first["then"] = [_cmd("hide", conf=0.4, sure=False, alternatives=[("isolate", 0.3)])]
    host.said["montre poro et enlève le reste"] = first
    ctl.ask("montre poro et enlève le reste")
    assert [c[1] for c in _called(host, "execute")] == ["show"]
    assert _last(state)["level"] == "ask" and ctl._pending is not None
    ctl.choose("intent:isolate")
    assert [c[1] for c in _called(host, "execute")] == ["show", "isolate"]


def test_the_rest_of_a_sentence_is_dropped_after_a_failure():
    ctl, state, host = _ctl()
    first = _cmd("show", targets=[PORO])
    first["then"] = [_cmd("colormap", targets=[PORO])]
    host.said["montre poro et passe en viridis"] = first
    host.execute_ok = False
    ctl.ask("montre poro et passe en viridis")
    assert [c[1] for c in _called(host, "execute")] == ["show"]
    assert _last(state)["text"] == "Le reste de la phrase n'a pas été fait."


# ------------------------------------------------------------------ a value's button answers "which cells?"
def test_a_category_button_puts_the_value_in_the_command_and_runs_it():
    """A category button fills the command's value and runs the command.

    For "surligne Fluids" (highlight Fluids), the host asks which cells of
    Fluids are meant, with the values as buttons; the one clicked becomes
    the command's value."""
    ctl, state, host = _ctl()
    host.said["surligne Fluids"] = _cmd("highlight", missing=["min|max"], targets=[PORO])
    host.ask_missing = lambda cmd, lang: {"text": "Quelles mailles de Fluids ?",
                                          "choices": [{"id": "category:oil", "label": "oil"}]}
    host.missing = lambda cmd: [] if (cmd.get("slots") or {}).get("category") else ["min|max"]
    ran = []
    execute = host.execute
    host.execute = lambda cmd, lang: ran.append(dict(cmd)) or execute(cmd, lang)
    ctl.ask("surligne Fluids")
    reply = _last(state)
    assert reply["level"] == "ask" and [c["id"] for c in reply["choices"]] == ["category:oil", "none", "cancel"]
    ctl.choose("category:oil")
    assert ran and ran[-1]["slots"]["category"] == "oil" and ran[-1]["intent"] == "highlight"
    assert _last(state)["text"] == "did highlight fr"


# ------------------------------------------------------------------ the local AI: a question, and a sentence the engine did not read
class AIHost(FakeHost):
    """A host with the local AI behind it.

    Questions are slow, and a sentence the engine did not read is passed
    to the AI."""

    def __init__(self):
        super().__init__()
        self.llm = {}                # text -> command the AI returns
        self.asked = []

    def slow(self, intent):
        return intent == "ask"

    def llm_available(self):
        return True

    def llm_command(self, text, lang):
        self._call("llm_command", text, lang)
        return self.llm.get(text)

    def answer(self, cmd, lang):
        if cmd["intent"] == "ask":
            self.asked.append(cmd["slots"]["question"])
            return {"ok": True, "text": "Un pilier est une ligne selon K.", "rows": [["pillars", "fesapi"]]}
        return super().answer(cmd, lang)


def test_a_sentence_the_engine_did_not_read_goes_to_the_local_ai_then_runs():
    server, host = FakeServer(), AIHost()
    events = []
    ctl = AssistantController(server, host, journal=events.append)
    state = server.state
    host.said["enlève les puits qui ne passent pas par les chenaux"] = _cmd(None, 0.1, False)
    host.llm["enlève les puits qui ne passent pas par les chenaux"] = _cmd("well_cells", targets=[PORO])
    ctl.ask("enlève les puits qui ne passent pas par les chenaux")
    texts = [m["text"] for m in _data(state)["messages"] if m["role"] == "assistant"]
    assert texts[-2].startswith("Je demande à l'IA locale") and texts[-1] == "did well_cells fr"
    assert _called(host, "llm_command") == [("llm_command", "enlève les puits qui ne passent pas par les chenaux", "fr")]
    assert [e["event"] for e in events if e["event"] in ("llm", "reply")].count("llm") == 1
    assert not ctl._busy


def test_when_the_local_ai_reads_nothing_either_the_sentence_is_not_understood():
    server, host = FakeServer(), AIHost()
    ctl = AssistantController(server, host)
    host.said["xqzt"] = _cmd(None, 0.1, False)
    ctl.ask("xqzt")
    assert _last(server.state)["level"] == "error" and "pas compris" in _last(server.state)["text"]


def test_a_question_is_answered_by_the_local_ai_with_its_sources():
    server, host = FakeServer(), AIHost()
    ctl = AssistantController(server, host)
    cmd = _cmd("ask")
    cmd["slots"] = {"question": "c'est quoi un pilier ?"}
    host.said["c'est quoi un pilier ?"] = cmd
    ctl.ask("c'est quoi un pilier ?")
    last = _last(server.state)
    assert last["level"] == "ok" and last["text"].startswith("Un pilier") and last["rows"] == [["pillars", "fesapi"]]
    assert host.asked == ["c'est quoi un pilier ?"] and not ctl._busy


def test_a_host_without_the_local_ai_says_not_understood_as_before():
    ctl, state, host = _ctl()
    host.said["xqzt"] = _cmd(None, 0.1, False)
    ctl.ask("xqzt")
    assert _last(state)["level"] == "error"


# ------------------------------------------------------------------ the requests of a sentence, read in turn
def test_a_later_request_is_parsed_when_its_turn_comes():
    """The host gives the words of a later request; the panel parses them
    once the request before has run (its zone, its active property are then
    the session's), not when the sentence comes in."""
    ctl, state, host = _ctl()
    first = _cmd("show", targets=[PORO])
    first["then"] = ["passe en viridis", "exagération x3"]
    host.said["montre poro et passe en viridis puis exagération x3"] = first
    host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
    host.said["exagération x3"] = _cmd("z_scale")
    ctl.ask("montre poro et passe en viridis puis exagération x3")
    steps = [(c[0], c[1]) for c in host.calls if c[0] in ("parse", "execute")]
    assert steps == [("parse", "montre poro et passe en viridis puis exagération x3"), ("execute", "show"),
                     ("parse", "passe en viridis"), ("execute", "colormap"),
                     ("parse", "exagération x3"), ("execute", "z_scale")]
    assert [t for t, _c, _m in ctl._undo] == ["tok-show", "tok-colormap", "tok-z_scale"]


def test_a_later_request_not_read_goes_to_the_local_ai_and_the_rest_follows():
    server, host = FakeServer(), AIHost()
    ctl = AssistantController(server, host)
    first = _cmd("show", targets=[PORO])
    first["then"] = ["vire les chenaux", "passe en viridis"]
    host.said["montre poro puis vire les chenaux puis passe en viridis"] = first
    host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
    host.llm["vire les chenaux"] = _cmd("threshold", targets=[PORO])
    ctl.ask("montre poro puis vire les chenaux puis passe en viridis")
    assert _called(host, "llm_command") == [("llm_command", "vire les chenaux", "fr")]
    assert [c[1] for c in _called(host, "execute")] == ["show", "threshold", "colormap"]
    assert not ctl._busy


def test_a_later_request_not_read_without_a_local_ai_stops_the_sentence_and_says_which():
    ctl, state, host = _ctl()
    first = _cmd("show", targets=[PORO])
    first["then"] = ["xqzt blorp", "passe en viridis"]
    host.said["montre poro puis xqzt blorp puis passe en viridis"] = first
    host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
    ctl.ask("montre poro puis xqzt blorp puis passe en viridis")
    assert [c[1] for c in _called(host, "execute")] == ["show"]
    assert _last(state)["level"] == "error"
    assert _last(state)["text"] == "Je n'ai pas compris « xqzt blorp » : le reste de la phrase n'a pas été fait."


def test_a_first_request_not_read_sends_that_request_alone_to_the_local_ai_and_keeps_the_rest():
    """Only the request the parser did not read goes to the local AI: the
    sentence's other requests are not lost, they follow its command."""
    server, host = FakeServer(), AIHost()
    ctl = AssistantController(server, host)
    first = _cmd(None, 0.1, False)
    first["text"] = "vire les chenaux"
    first["then"] = ["recadre la vue"]
    host.said["vire les chenaux puis recadre la vue"] = first
    host.said["recadre la vue"] = _cmd("reset_camera")
    host.llm["vire les chenaux"] = _cmd("threshold", targets=[PORO])
    ctl.ask("vire les chenaux puis recadre la vue")
    assert _called(host, "llm_command") == [("llm_command", "vire les chenaux", "fr")]
    assert [c[1] for c in _called(host, "execute")] == ["threshold", "reset_camera"]


def test_a_first_request_not_read_without_a_local_ai_says_the_rest_was_not_done():
    ctl, state, host = _ctl()
    first = _cmd(None, 0.1, False)
    first["then"] = ["recadre la vue"]
    host.said["xqzt puis recadre la vue"] = first
    host.said["recadre la vue"] = _cmd("reset_camera")
    ctl.ask("xqzt puis recadre la vue")
    texts = [m["text"] for m in _data(state)["messages"] if m["role"] == "assistant"]
    assert texts[-2].startswith("Je n'ai pas compris.") and texts[-1] == "Le reste de la phrase n'a pas été fait."
    assert _called(host, "execute") == []


def test_an_undo_in_a_sentence_lets_the_rest_follow():
    ctl, state, host = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    ctl.ask("montre poro")
    first = _cmd("undo")
    first["then"] = ["passe en viridis"]
    host.said["annule puis passe en viridis"] = first
    host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
    ctl.ask("annule puis passe en viridis")
    assert _called(host, "undo") == [("undo", "tok-show", "fr")]
    assert [c[1] for c in _called(host, "execute")] == ["show", "colormap"]


# ------------------------------------------------------------------ the local AI: what it costs, when it fails
def test_the_waiting_message_says_the_host_s_longest_wait_and_never_a_few_seconds():
    """The waiting message tells the longest the host waits for the local
    AI (its own timeout, `llm_wait_s`), never "a few seconds"; a host that
    does not say it gets an open-ended wait."""
    server, host = FakeServer(), AIHost()
    host.llm_wait_s = 90.0
    ctl = AssistantController(server, host)
    ctl.ask("blabla")
    ctl.ask("blabla in english please")
    waiting = [m["text"] for m in _data(server.state)["messages"] if m.get("level") == "info"]
    assert waiting == ["Je demande à l'IA locale : sa réponse peut prendre jusqu'à 90 secondes…",
                       "Asking the local AI: its answer may take up to 90 seconds…"]
    assert not any("quelques secondes" in m["text"] for m in _data(server.state)["messages"])
    server, host = FakeServer(), AIHost()
    ctl = AssistantController(server, host)
    ctl.ask("blabla")
    waiting = [m["text"] for m in _data(server.state)["messages"] if m.get("level") == "info"]
    assert waiting == ["Je demande à l'IA locale : sa réponse peut prendre une minute ou plus…"]


def test_a_local_ai_that_failed_says_so_with_its_reason():
    """A call that failed is not "not understood": the reply says the local
    AI did not answer, and why (a timeout, a full queue)."""
    server, host = FakeServer(), AIHost()
    events = []
    ctl = AssistantController(server, host, journal=events.append)
    host.llm["blabla"] = {"intent": None, "error": "timed out"}
    ctl.ask("blabla")
    last = _last(server.state)
    assert last["level"] == "error"
    assert last["text"].startswith("L'IA locale n'a pas répondu (timed out) : je n'ai pas compris la phrase.")
    assert "« montre poro »" in last["text"]
    assert [e.get("error") for e in events if e["event"] == "llm"] == ["timed out"]


def test_not_understood_says_when_the_local_ai_is_down():
    server, host = FakeServer(), AIHost()
    host.llm_available = lambda: False
    host.llm_problem = lambda: "connection refused"
    ctl = AssistantController(server, host)
    ctl.ask("blabla")
    assert _last(server.state)["text"].startswith(
        "Je n'ai pas compris. (L'IA locale ne répond pas : connection refused.) Essayez par exemple : ")
    assert _called(host, "llm_command") == []


class PrepHost(AIHost):
    """A host that prepares the local AI's call on the event loop and reads
    its answer there: only the HTTP call runs in a thread."""

    def __init__(self):
        super().__init__()
        self.threads = {}

    def llm_prepare(self, text, lang):
        self.threads["prepare"] = threading.current_thread()

        def call():
            self.threads["call"] = threading.current_thread()
            return {"intent": "show"}
        return call

    def llm_finish(self, text, got, lang):
        self.threads["finish"] = threading.current_thread()
        return dict(_cmd(got["intent"], targets=[PORO]), text=text)


def test_only_the_local_ai_s_call_runs_in_a_thread():
    async def main():
        ctl, state, host = _ctl(PrepHost(), state=WslinkState())
        with state:
            ctl.ask("blabla")
        await ctl.idle()
        assert _last(state)["text"] == "did show fr" and not ctl._busy
        return host.threads

    threads = asyncio.run(main())
    main_thread = threading.main_thread()
    assert threads["prepare"] is main_thread and threads["finish"] is main_thread
    assert threads["call"] is not main_thread


class RaisingAIHost(AIHost):
    """A local AI client that raises in its thread (a bug, an answer of a
    shape it does not expect)."""

    def llm_command(self, text, lang):
        self._call("llm_command", text, lang)
        raise AttributeError("'list' object has no attribute 'get'")


class RaisingPrepHost(PrepHost):
    def llm_prepare(self, text, lang):
        def call():
            raise AttributeError("'list' object has no attribute 'get'")
        return call


def _for_the_ai(host):
    """A sentence whose first request the parser did not read, the rest
    waiting for the local AI's command."""
    first = _cmd(None, 0.1, False)
    first["text"] = "zou le 33-1"
    first["then"] = ["recadre la vue"]
    host.said["zou le 33-1 puis recadre la vue"] = first
    host.said["recadre la vue"] = _cmd("reset_camera")


@pytest.mark.parametrize("host_class", [RaisingAIHost, RaisingPrepHost])
def test_a_local_ai_call_that_raises_frees_the_panel_and_drops_the_rest(host_class):
    """The local AI's call raising in its thread: the error reaches the
    browser with the busy bar down, and the rest of the sentence, which
    waited for that request, is dropped and said so."""
    async def main():
        ctl, state, host = _ctl(host_class(), state=WslinkState())
        _for_the_ai(host)
        with state:
            ctl.ask("zou le 33-1 puis recadre la vue")
        await ctl.idle()
        await asyncio.sleep(0.01)
        return ctl, state, host

    ctl, state, host = asyncio.run(main())
    texts = [m["text"] for m in _data(state)["messages"] if m["role"] == "assistant"]
    assert texts[-2:] == ["Une erreur est survenue : 'list' object has no attribute 'get'",
                          "Le reste de la phrase n'a pas été fait."]
    assert _data(state)["busy"] is False and not ctl._busy and ctl._chain == []
    assert state.sent[-1]["busy"] is False and state.sent[-1]["messages"][-1]["text"] == texts[-1]
    assert _called(host, "execute") == []


def test_without_a_loop_a_local_ai_call_that_raises_drops_the_rest_too():
    ctl, state, host = _ctl(RaisingAIHost())
    _for_the_ai(host)
    ctl.ask("zou le 33-1 puis recadre la vue")
    assert _last(state)["text"] == "Le reste de la phrase n'a pas été fait."
    assert ctl._chain == [] and _data(state)["busy"] is False and _called(host, "execute") == []


def test_a_command_that_raises_stops_the_sentence_and_says_the_rest_was_not_done():
    ctl, state, host = _ctl()
    first = _cmd("show", targets=[PORO])
    first["then"] = ["passe en viridis"]
    host.said["montre poro et passe en viridis"] = first
    host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
    host.fail = "execute"
    ctl.ask("montre poro et passe en viridis")
    texts = [m["text"] for m in _data(state)["messages"] if m["role"] == "assistant"]
    assert texts[-2:] == ["Une erreur est survenue : execute broke", "Le reste de la phrase n'a pas été fait."]
    assert ctl._chain == [] and [c[1] for c in _called(host, "execute")] == ["show"]


def test_a_later_request_is_read_by_the_host_s_parse_next_when_it_has_one():
    """A host may read a later request of a sentence as such ("…then the
    gas" adds a value to the request before): the panel hands it there."""
    class NextHost(FakeHost):
        def parse_next(self, text):
            self._call("parse_next", text)
            return dict(self.said.get(text) or _cmd(None, 0.0, False))

    ctl, state, host = _ctl(NextHost())
    first = _cmd("show", targets=[PORO])
    first["then"] = ["passe en viridis"]
    host.said["montre poro et passe en viridis"] = first
    host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
    ctl.ask("montre poro et passe en viridis")
    assert [c[:2] for c in host.calls if c[0] in ("parse", "parse_next")] == [
        ("parse", "montre poro et passe en viridis"), ("parse_next", "passe en viridis")]
    assert [c[1] for c in _called(host, "execute")] == ["show", "colormap"]


def test_hide_or_keep_is_asked_with_the_host_s_buttons_and_the_choice_runs():
    """A host may ask whether the values a command names are hidden or
    kept: "exclude:true" / "exclude:false" set the command's polarity, and
    it runs."""
    class PolarityHost(FakeHost):
        def missing(self, cmd):
            self._call("missing", cmd["intent"])
            return ["exclude"] if (cmd.get("slots") or {}).get("exclude") is None else []

        def ask_missing(self, cmd, lang):
            return {"text": "Masquer les mailles « gas », ou ne garder qu'elles ?",
                    "choices": [{"id": "exclude:true", "label": "Masquer"},
                                {"id": "exclude:false", "label": "Ne garder qu'elles"}]}

        def execute(self, cmd, lang):
            self.polarity = cmd["slots"]["exclude"]
            return super().execute(cmd, lang)

    for choice, polarity in (("exclude:true", True), ("exclude:false", False)):
        ctl, state, host = _ctl(PolarityHost())
        cmd = _cmd("threshold", conf=0.9, sure=False, missing=["exclude"])
        cmd["slots"] = {"category": "gas", "exclude": None}
        host.said["planque le gaz"] = cmd
        ctl.ask("planque le gaz")
        assert [c["id"] for c in _last(state)["choices"]] == ["exclude:true", "exclude:false", "none", "cancel"]
        ctl.choose(choice)
        assert host.polarity is polarity and _last(state)["text"] == "did threshold fr"


def test_the_busy_bar_stays_up_until_the_last_request_of_the_sentence_has_run():
    async def main():
        ctl, state, host = _ctl(state=WslinkState())
        first = _cmd("show", targets=[PORO])
        first["then"] = ["passe en viridis"]
        host.said["montre poro et passe en viridis"] = first
        host.said["passe en viridis"] = _cmd("colormap", targets=[PORO])
        seen = []
        execute = host.execute

        def watched(cmd, lang):
            seen.append(ctl._busy)
            return execute(cmd, lang)
        host.execute = watched
        with state:
            ctl.ask("montre poro et passe en viridis")
        await ctl.idle()
        assert [c[1] for c in _called(host, "execute")] == ["show", "colormap"]
        assert seen == [True, True] and not ctl._busy and _data(state)["busy"] is False

    asyncio.run(main())
