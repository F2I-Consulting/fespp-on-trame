"""The door to the local AI service (fespp_on_trame/ia/llm.py): off without
FESPP_IA_URL, plain HTTP with the service's contract, None when it fails."""
import io
import json
import urllib.error

import pytest

from fespp_on_trame.ia.llm import LocalIA


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, replies, seen):
    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        body = json.loads(req.data.decode("utf-8")) if getattr(req, "data", None) else None
        seen.append((url.rsplit("/", 1)[-1], body, timeout))
        reply = replies.get(url.rsplit("/", 1)[-1])
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(json.dumps(reply).encode("utf-8"))
    monkeypatch.setattr("urllib.request.urlopen", urlopen)


def test_off_without_the_environment_variable():
    assert LocalIA.from_env({}) is None
    assert LocalIA.from_env({"FESPP_IA_URL": " http://fespp_ia:8000/ "}).url == "http://fespp_ia:8000"


def test_a_command_and_a_question_follow_the_service_s_contract(monkeypatch):
    seen = []
    _serve(monkeypatch, {"command": {"command": {"intent": "show", "kind": "porosity"}, "seconds": 3.2,
                                     "glossary": ["pillars"]},
                         "ask": {"text": "Un pilier…", "sources": [{"title": "p"}], "seconds": 9.0},
                         "health": {"status": "ok", "rag": {"count": 10}}}, seen)
    ia = LocalIA("http://x")
    cmd = ia.command("montre la poro", [{"name": "show"}], [{"title": "PHIT"}], "fr")
    assert cmd["intent"] == "show" and cmd["_seconds"] == 3.2 and cmd["_glossary"] == ["pillars"]
    assert seen[0][0] == "command" and seen[0][1]["catalogue"] == [{"name": "show"}] and seen[0][2] == 240.0
    ans = ia.ask("c'est quoi un pilier ?", "fr")
    assert ans["text"] == "Un pilier…" and ans["sources"] == [{"title": "p"}]
    assert ia.health()["rag"] == {"count": 10}


def test_a_service_down_gives_none_and_says_why(monkeypatch, capsys):
    seen = []
    _serve(monkeypatch, {"command": urllib.error.URLError("refused"),
                         "ask": urllib.error.HTTPError("u", 503, "busy", {}, None)}, seen)
    ia = LocalIA("http://x")
    assert ia.command("x", [{"name": "show"}], []) is None and "refused" in ia.last_error
    assert ia.ask("x") is None and ia.last_error == "503 busy"
    assert "local AI" in capsys.readouterr().out


def test_a_reply_without_a_command_is_none(monkeypatch):
    _serve(monkeypatch, {"command": {"seconds": 1.0}, "ask": {"text": ""}}, [])
    ia = LocalIA("http://x")
    assert ia.command("x", [{"name": "show"}], []) is None and ia.ask("x") is None
