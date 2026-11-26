"""The bench's judge: notions with their wordings in both languages, the
re-judging of a stored run, the GOOD grade of a retrieved chunk and the
retrieval summary (hit@k, MRR); for the commands, the intent (one name or
several accepted), the category and well filter that make a command pass,
and the other slots judged apart."""
from fespp_ia.bench import (bench_name, command_items, command_summary, expected_of, fold, judge, judge_command,
                            notions, rescore, rescore_commands)
from fespp_ia.bench_retrieval import first_good, share, summary

PILLAR = ["k", ["colonne", "column"], ["coin", "corner"], "ligne"]


def test_a_notion_counts_once_whichever_wording_and_the_missing_ones_are_named():
    r = judge("Une colonne de mailles, une column: le même mot deux fois.", PILLAR)
    assert (r["hits"], r["of"]) == (1, 4)
    assert r["missing"] == ["k", "coin/corner", "ligne"]


def test_the_french_wording_counts_as_much_as_the_english_one():
    assert judge("the corner of a column", PILLAR)["hits"] == 2
    assert judge("le coin d'une colonne", PILLAR)["hits"] == 2


def test_a_flat_list_of_strings_is_one_notion_per_string():
    r = judge("colonne et column", ["colonne", "column", "ligne"])
    assert (r["hits"], r["of"], r["missing"]) == (2, 3, ["ligne"])


def test_a_wording_matches_the_start_of_a_word_not_its_middle():
    assert judge("la porosité des grès", ["porosit"])["hits"] == 1
    assert judge("un log de puits", ["log"])["hits"] == 1
    assert judge("la géologie du réservoir", ["log"])["hits"] == 0
    assert judge("une grille IJK", ["k"])["hits"] == 0
    assert judge("l'indice K des couches", ["k"])["hits"] == 1
    assert judge("sous-représentation", ["sous", "representation"])["hits"] == 2


def test_case_and_accents_are_folded_on_both_sides():
    assert fold("Résistivité Œ") == "resistivite œ"
    assert judge("RÉSISTIVITÉ mesurée", ["resistivit"])["hits"] == 1
    assert judge("resistivity log", ["résistivit"])["hits"] == 1
    assert notions([["Coin", "Corner"], "Épaisseur"]) == [["coin", "corner"], ["epaisseur"]]


def test_a_multi_word_wording_is_read_as_written():
    assert judge("the free water level sits below the oil-water contact", [["free water", "eau libre"]])["hits"] == 1
    assert judge("le niveau d'eau libre", [["free water", "eau libre"]])["hits"] == 1


def test_rescore_rejudges_the_stored_answers_and_keeps_the_stored_figures():
    """A stored run is re-judged against new notions without a model call
    and without touching the input; the stored figures stay beside the new
    ones, and a question absent from the notions counts as unknown."""
    report = {"model": "m", "commands": [],
              "questions": [{"q": "q1", "seconds": 1.0, "hits": 1, "of": 2, "answer": "une colonne de mailles"},
                            {"q": "q2", "seconds": 1.0, "hits": 0, "of": 1, "answer": "rien"},
                            {"q": "q3", "error": "boom"},
                            {"q": "q4", "seconds": 1.0, "hits": 1, "of": 1, "answer": "inconnue du jeu"}],
              "summary": {"questions": {"n": 3, "hit_rate": 0.5, "median_seconds": 1.0}, "commands": {"n": 0}}}
    before = repr(report)
    out = rescore(report, {"q1": [["colonne", "column"]], "q2": ["seal"]})
    assert repr(report) == before
    q1, q2 = out["questions"][0], out["questions"][1]
    assert (q1["hits_stored"], q1["of_stored"], q1["hits"], q1["of"], q1["missing"]) == (1, 2, 1, 1, [])
    assert (q1["hits_words"], q1["of_words"]) == (1, 2)
    assert (q2["hits"], q2["of"], q2["missing"]) == (0, 1, ["seal"])
    assert out["questions"][2] == {"q": "q3", "error": "boom"}
    assert "hits_stored" not in out["questions"][3]
    s = out["summary"]["questions"]
    assert (s["n"], s["hit_rate_stored"], s["hit_rate_words"], s["hit_rate"], s["unknown"]) == (2, 0.25, 0.25, 0.5, 1)
    assert s["median_seconds"] == 1.0 and out["summary"]["commands"] == {"n": 0}


def test_bench_name_strips_the_file_prefix():
    assert bench_name("/repo/ia/bench-questions-metier.json") == "metier"
    assert bench_name("mine.json") == "mine"


def test_a_chunk_is_good_when_it_holds_half_the_notions():
    expected = notions(PILLAR)
    pillar = fold("Pilier (pillar)\n\nla ligne qui joint les coins d'une colonne de mailles")
    assert share(pillar, expected) == 0.75
    assert share(fold("nothing here"), expected) == 0.0
    assert share(fold("x"), []) == 0.0
    assert first_good([0.25, 0.5, 1.0]) == 2
    assert first_good([0.25, 0.0]) is None


def test_summary_counts_hits_at_k_and_the_ceilings():
    rows = [{"rank": 1, "good_in_corpus": 3, "seconds": 0.5}, {"rank": 5, "good_in_corpus": 1, "seconds": 0.7},
            {"rank": None, "good_in_corpus": 2, "seconds": 0.6}, {"rank": None, "good_in_corpus": 0, "seconds": 0.8}]
    s = summary(rows)
    assert (s["hit@1"], s["hit@3"], s["hit@4"], s["hit@6"]) == (1, 1, 1, 2)
    assert (s["good_in_pool"], s["good_in_corpus"], s["n"]) == (2, 3, 4)
    assert s["mrr"] == round((1 + 0.2) / 4, 3) and s["median_seconds"] == 0.65
    assert summary([])["mrr"] is None


# ------------------------------------------------------------------ commands
def test_the_items_of_a_commands_file_keep_their_group_s_language_and_drop_the_context_ones():
    doc = {"result": [{"lang": "fr", "items": [{"text": "cache l'huile", "intent": "threshold"},
                                               {"text": "et le gaz ?", "intent": "threshold", "context": ["x"]}]},
                      {"lang": "en", "items": [{"text": "hide the oil", "intent": "threshold", "lang": "fr"}]}]}
    assert [(it["text"], it["lang"]) for it in command_items(doc)] == [("cache l'huile", "fr"), ("hide the oil", "fr")]
    assert command_items([{"text": "a", "intent": "show"}]) == [{"text": "a", "intent": "show"}]


def test_a_command_passes_on_its_intent_category_and_well_filter_the_other_slots_judged_apart():
    item = {"text": "cache l'huile", "intent": "threshold", "category": "oil", "exclude": True, "kind": None}
    expected = expected_of(item)
    assert expected == {"intent": "threshold", "category": "oil", "exclude": True}
    assert judge_command({"intent": "threshold", "category": "oil", "exclude": True}, expected) == \
        {"ok": True, "slots": {"exclude": True}}
    # the slot missed does not fail the command: earlier reports stay comparable
    assert judge_command({"intent": "threshold", "category": "oil"}, expected) == \
        {"ok": True, "slots": {"exclude": False}}
    assert judge_command({"intent": "threshold", "category": "gas", "exclude": True}, expected)["ok"] is False


def test_an_item_may_accept_several_intents():
    expected = expected_of({"text": "les puits", "intent": ["show", "list"]})
    assert judge_command({"intent": "list"}, expected)["ok"] and judge_command({"intent": "show"}, expected)["ok"]
    assert not judge_command({"intent": "hide"}, expected)["ok"]


def test_a_slot_is_judged_to_rounding_case_and_accents_aside_a_switch_null_as_false():
    expected = expected_of({"text": "x", "intent": "threshold", "kind": "Water Saturation", "min": 0, "max": 0.3,
                            "exclude": False, "preset": "Viridis (matplotlib)"})
    assert set(expected) == {"intent", "kind", "min", "max", "exclude", "preset"}      # 0 and false are labels
    got = {"intent": "threshold", "kind": "water saturation", "min": 0.0, "max": 0.30000001, "exclude": None,
           "preset": "viridis (matplotlib)"}
    assert judge_command(got, expected)["slots"] == {"kind": True, "min": True, "max": True, "exclude": True,
                                                     "preset": True}
    got = {"intent": "threshold", "kind": "water_saturation", "min": None, "max": 30, "exclude": True,
           "preset": "viridis"}
    assert judge_command(got, expected)["slots"] == {"kind": False, "min": False, "max": False, "exclude": False,
                                                     "preset": False}


def test_rescore_commands_rejudges_the_stored_commands_and_keeps_the_stored_verdict():
    report = {"model": "m", "questions": [],
              "commands": [{"text": "les puits", "ok": False, "seconds": 2.0, "tokens": 12,
                            "command": {"intent": "list"}},
                           {"text": "cache l'huile", "ok": True, "seconds": 4.0, "tokens": 30,
                            "command": {"intent": "threshold", "category": "oil"}},
                           {"text": "inconnue", "ok": True, "seconds": 1.0, "command": {"intent": "show"}},
                           {"text": "en panne", "error": "boom"}],
              "summary": {"commands": {"n": 3, "accuracy": 0.67}}}
    before = repr(report)
    items = [{"text": "les puits", "intent": ["show", "list"]},
             {"text": "cache l'huile", "intent": "threshold", "category": "oil", "exclude": True}]
    out = rescore_commands(report, items)
    assert repr(report) == before
    first, second = out["commands"][0], out["commands"][1]
    assert (first["ok_stored"], first["ok"]) == (False, True)
    assert (second["ok_stored"], second["ok"], second["slots"]) == (True, True, {"exclude": False})
    s = out["summary"]["commands"]
    assert (s["n"], s["accuracy"], s["unknown"], s["slots"]) == (2, 1.0, 2, {"exclude": {"n": 1, "ok": 0}})
    assert (s["median_seconds"], s["median_tokens"]) == (3.0, 21.0)


def test_the_command_summary_leaves_the_failed_calls_out():
    rows = [{"text": "a", "ok": True, "seconds": 1.0, "command": {}, "slots": {"kind": True}},
            {"text": "b", "ok": False, "seconds": 3.0, "command": {}, "slots": {"kind": False, "min": True}},
            {"text": "c", "error": "boom"}]
    s = command_summary(rows)
    assert (s["n"], s["accuracy"], s["median_seconds"], s["median_tokens"]) == (2, 0.5, 2.0, None)
    assert s["slots"] == {"kind": {"n": 2, "ok": 1}, "min": {"n": 1, "ok": 1}}
