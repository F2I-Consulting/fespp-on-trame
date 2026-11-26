"""The assistant's dialogue journal (fespp_on_trame/ia/journal.py) and the
report scripts/assistant_log_report.py builds from it.

Every sentence is kept with what it was taken for and what the reader did
next, so the vocabulary can be enriched from real use."""
import json
import os
import sys
from pathlib import Path

from fespp_on_trame.ia import journal as jr
from tests.unit.test_assistant_controller import PORO, FakeHost, FakeServer, _cmd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "assistant"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from trame_fespp_assistant.controller import AssistantController  # noqa: E402
import assistant_log_report as report  # noqa: E402


def _ctl():
    events = []
    host = FakeHost()
    ctl = AssistantController(FakeServer(), host, journal=events.append)
    return ctl, host, events


def test_a_journal_writes_one_line_per_event_stamped_with_time_and_session(tmp_path):
    j = jr.DialogueJournal(str(tmp_path), session="s1")
    j.append({"event": "said", "text": "montre la grille"})
    j({"event": "reply", "level": "ok"})
    files = os.listdir(tmp_path)
    assert len(files) == 1 and files[0].startswith("assistant-") and files[0].endswith(".jsonl")
    lines = [json.loads(line) for line in open(tmp_path / files[0], encoding="utf-8")]
    assert [e["event"] for e in lines] == ["said", "reply"]
    assert all(e["session"] == "s1" and e["ts"].endswith("Z") for e in lines)
    assert jr.read(str(tmp_path)) == lines


def test_the_journal_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("FESPP_ASSISTANT_LOG", "off")
    assert jr.DialogueJournal.from_env() is None


def test_a_journal_that_cannot_write_never_breaks_the_assistant(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    j = jr.DialogueJournal(str(blocker / "sub"))       # a folder under a file
    j.append({"event": "said"})
    j.append({"event": "said"})                        # silent after the first failure
    assert j._broken


def test_a_sentence_is_kept_with_what_it_was_taken_for_and_the_reply():
    ctl, host, events = _ctl()
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    ctl.ask("montre poro")
    said = next(e for e in events if e["event"] == "said")
    assert said["text"] == "montre poro" and said["intent"] == "show" and said["targets"] == ["poro"]
    reply = next(e for e in events if e["event"] == "reply")
    assert reply["turn"] == said["turn"] and reply["level"] == "ok"


def test_a_choice_and_an_undo_are_tied_to_the_sentence_they_answer():
    ctl, host, events = _ctl()
    host.said["montre la porosité"] = _cmd("show", conf=0.4, sure=False, alternatives=[("value", 0.3)])
    ctl.ask("montre la porosité")
    turn = events[0]["turn"]
    ctl.choose("intent:show")
    choose = next(e for e in events if e["event"] == "choose")
    assert choose["turn"] == turn and choose["choice"] == "intent:show"
    ctl.undo()
    undone = next(e for e in events if e["event"] == "undone")
    assert undone["of_turn"] == turn and undone["intent"] == "show"


def test_a_sentence_not_understood_is_kept_too():
    ctl, host, events = _ctl()
    ctl.ask("xqzt")
    said = next(e for e in events if e["event"] == "said")
    assert said["intent"] is None
    assert any(e["event"] == "reply" and e["level"] == "error" for e in events)


def test_the_report_sorts_what_needs_work_and_labels_what_the_reader_chose():
    ctl, host, events = _ctl()
    host.said["montre la porosité"] = _cmd("show", conf=0.4, sure=False, alternatives=[("value", 0.3)])
    host.said["filtre poro"] = _cmd("threshold", targets=[PORO])
    host.said["cache poro"] = _cmd("hide", targets=[PORO])
    host.said["annule"] = _cmd("undo")
    ctl.ask("xqzt")                                   # not understood
    ctl.ask("montre la porosité")                     # asked back, the reader chose
    ctl.choose("intent:value")
    ctl.ask("filtre poro")                            # done, then taken back
    ctl.ask("annule")
    ctl.ask("cache poro")                             # done
    for e in events:
        e.setdefault("session", "s")
    groups = report.sort(report.exchanges(events))
    texts = {k: [x["said"]["text"] for x in v] for k, v in groups.items()}
    assert texts["not_understood"] == ["xqzt"]
    assert texts["asked"] == ["montre la porosité"]
    assert texts["undone"] == ["filtre poro"]
    assert "cache poro" in texts["done"]
    labelled = {c["text"]: c["intent"] for c in report.candidates(groups)}
    assert labelled["montre la porosité"] == "value" and labelled["xqzt"] is None


def test_a_long_reply_is_kept_whole_enough_to_diagnose_a_contested_result():
    """A reply is journaled up to 2 000 characters: the wells a filter hid,
    the cells a highlight lit, what a later complaint is checked against."""
    ctl, host, events = _ctl()
    long = "puits masqués : " + ", ".join(f"15/9-F-{i}" for i in range(150))
    assert 1500 < len(long) < 2000
    host.said["montre poro"] = _cmd("show", targets=[PORO])
    host.execute = lambda cmd, lang: {"ok": True, "text": long, "undo": None}
    ctl.ask("montre poro")
    reply = next(e for e in events if e["event"] == "reply")
    assert reply["text"] == long
    host.execute = lambda cmd, lang: {"ok": True, "text": long * 2, "undo": None}
    ctl.ask("montre poro")
    assert len([e for e in events if e["event"] == "reply"][-1]["text"]) == 2000
