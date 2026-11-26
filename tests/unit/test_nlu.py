"""Tests for ia.nlu, the in-house command engine.

A sentence, in French or English, becomes one command of the catalogue with
its parameters, matched against the objects of the session. Accuracy is
measured on hand-written sentences the model never saw (data/nlu_eval.jsonl),
never on the generated sentences it is trained on; the sets are read as the
application reads them, and scored the way scripts/train_nlu.py scores them
(ia/nlu/evaluation.py)."""
import json

import pytest

from fespp_on_trame.ia.nlu import catalogue, evaluation, generate, slots
from fespp_on_trame.ia.nlu.engine import MODEL_PATH, parse
from fespp_on_trame.ia.nlu.model import IntentModel, source_signature
from fespp_on_trame.ia.nlu.text import normalize, tokens

ROWS = evaluation.rows("nlu_eval.jsonl")
OBJECTS = evaluation.OBJECTS


def test_every_command_of_the_catalogue_has_its_sentences():
    assert set(generate.PATTERNS) == set(catalogue.INTENTS)


def test_the_shipped_model_is_trained_from_the_sources_in_the_tree():
    m = IntentModel.load(MODEL_PATH)
    assert m.intents == list(catalogue.NAMES)
    assert m.signature == source_signature(), (
        "the catalogue, the lexicon or the patterns changed since the model was "
        "trained: run scripts/train_nlu.py")


def test_the_text_is_read_without_accents_capitals_or_decimal_commas():
    assert normalize("Montre la porosité au-dessus de 0,2 !") == "montre la porosite au dessus de 0.2"
    assert tokens("le puits 15/9-F-4.") == ["le", "puits", "15/9-f-4"]


def test_nine_hand_written_sentences_in_ten_give_the_right_command():
    res = evaluation.score(ROWS, OBJECTS)
    print(f"\n{res['right']}/{res['n']} right; missed:", *res["misses"], sep="\n  ")
    assert res["right"] / res["n"] >= 0.9


@pytest.mark.parametrize("row", [r for r in ROWS if set(r) - {"text", "intent"}],
                         ids=lambda r: r["text"][:40])
def test_the_parameters_are_read_from_the_sentence(row):
    got = parse(row["text"], OBJECTS)
    if got["intent"] != row["intent"]:
        pytest.skip("the command itself is missed (counted above)")
    s = got["slots"]
    for key in ("kind", "panel", "preset", "axis", "on", "factor"):
        if key in row:
            assert s[key] == row[key], (key, s)
    for key in ("min", "max"):
        if key in row:
            assert s[key] == pytest.approx(row[key]), (key, s)


def test_a_kind_on_a_named_grid_is_its_property_of_that_kind():
    got = parse("montre la porosité de Hugin au-dessus de 0,2", OBJECTS)
    assert got["intent"] == "threshold" and got["sure"]
    assert [t["title"] for t in got["targets"]] == ["PHIT"]      # a TOTAL porosity is a porosity
    assert got["slots"]["min"] == pytest.approx(0.2)


def test_a_well_is_found_by_the_end_of_its_name():
    got = parse("ouvre la vue des logs du F-4", OBJECTS)
    assert got["slots"]["panel"] == "welllog"
    assert [t["path"] for t in got["targets"]] == ["/w/f4"]


def test_a_kind_alone_is_every_property_of_that_kind():
    got = parse("quelle est la perméabilité moyenne ?", OBJECTS)
    assert got["intent"] == "value" and [t["title"] for t in got["targets"]] == ["PERMX"]


def test_percentages_become_fractions_where_the_kind_is_one():
    got = parse("je ne veux que les mailles où la porosité dépasse 15 %", OBJECTS)
    assert got["slots"]["min"] == pytest.approx(0.15)
    got = parse("filtre la perméabilité entre 100 et 500", OBJECTS)
    assert (got["slots"]["min"], got["slots"]["max"]) == (100, 500)


def test_a_command_without_what_it_needs_is_not_sure():
    got = parse("passe la couleur", OBJECTS)
    assert not got["sure"]


def test_gibberish_is_not_sure():
    assert not parse("xqzt wlorp", OBJECTS)["sure"]


def test_an_unknown_object_name_is_still_a_command_shape():
    # the generator never produced "Sleipner Vest": the classifier sees the
    # placeholder <obj>, so any object name fits the command shape
    objs = OBJECTS + [{"path": "/g/sv", "title": "Sleipner Vest", "type": "IjkGrid"}]
    got = parse("masque Sleipner Vest", objs)
    assert got["intent"] == "hide" and got["targets"][0]["path"] == "/g/sv"


def test_spans_never_overlap():
    toks = tokens("montre la porosité de Hugin entre 0,1 et 0,3 en viridis")
    found = slots.spans(toks, OBJECTS)
    ends = [e for _s, e, *_ in found]
    starts = [s for s, *_ in found]
    assert all(s >= e for s, e in zip(starts[1:], ends[:-1]))
    assert [f[2] for f in found] == ["kind", "obj", "num", "num", "preset"]


# ------------------------------------------------------------ the dev, journal and sealed sets
def _rate(name, objects):
    res = evaluation.score(evaluation.rows(name), objects)
    return res["right"] / res["n"]


# the richer session the writers' sets are read against (one list, the one
# scripts/train_nlu.py reads them against too)
DEV_OBJECTS = evaluation.EVAL_OBJECTS


@pytest.mark.parametrize("name", ["nlu_dev_fr.jsonl", "nlu_dev_en.jsonl"])
def test_the_independent_writers_sentences_give_the_right_command(name):
    # sentences by writers who never saw the patterns; the engine is tuned on
    # them (the "dev" sets)
    assert _rate(name, DEV_OBJECTS) >= 0.93


def test_the_sentences_of_real_sessions_give_the_command_that_was_meant():
    """The journal: what people typed in real sessions, read with the
    context the application held. The command and the parameters that
    mattered (the values, the hiding, the wells kept) both count."""
    res = evaluation.score(evaluation.rows("nlu_journal.jsonl"), DEV_OBJECTS)
    print(f"\n{res['right']}/{res['n']} right, {res['full']} with their parameters; missed:", *res["misses"],
          sep="\n  ")
    assert res["right"] / res["n"] >= 0.9 and res["full"] / res["n"] >= 0.88
    assert res["sure_wrong"] <= 1


@pytest.mark.parametrize("name", ["nlu_heldout_fr.jsonl", "nlu_heldout_en.jsonl"])
def test_the_sealed_sentences_give_the_right_command(name):
    # SEALED: never read while developing the engine, never tuned on. A failure
    # reports the rate only: showing a sentence would leak the set, and a
    # leaked set stops measuring anything.
    rate = _rate(name, DEV_OBJECTS)
    assert rate >= 0.88, f"{name}: {rate:.1%} right"


def test_the_parameters_of_the_corpus_held_out_tenth_are_read():
    """The tenth of the corpus held out of the training states parameters
    (kind, bounds, axis, panel…): each sentence read whole, each parameter
    is right in nearly every sentence whose command is right."""
    from fespp_on_trame.ia.nlu import corpus
    _train, held = corpus.split(corpus.load(say=None))
    res = evaluation.score(held, generate.objects(), split=False)
    print("\n" + evaluation.slot_line(res))
    assert res["right"] / res["n"] >= 0.97
    for key, (ok, n) in res["slots"].items():
        assert ok / n >= _SLOT_FLOOR.get(key, 0.9), (key, ok, n)
    assert sum(ok for ok, _n in res["slots"].values()) / sum(n for _ok, n in res["slots"].values()) >= 0.97


# per parameter, the share of the held-out tenth's statements read right at
# least — a little below what the shipped model reads, the few statements
# of a parameter (an axis, a switch) moving the share by several points
_SLOT_FLOOR = {"kind": 0.97, "category": 0.97, "min": 0.95, "max": 0.94, "axis": 0.9, "on": 0.9,
               "panel": 0.95, "preset": 0.9, "factor": 0.9}


# ------------------------------------------------------------ generator, typos, groups, bounds
def test_the_training_sentences_carry_no_pattern_syntax():
    for s, _i in generate.sentences(60, seed=1):
        assert not any(c in s for c in "()[]{}|*"), s


def test_a_several_word_option_stays_whole():
    import numpy as np
    rng = np.random.default_rng(0)
    seen = {generate._expand(rng, "(fais voir|ouvre) x") for _ in range(40)}
    assert seen == {"fais voir x", "ouvre x"}


@pytest.mark.parametrize("typed, typ, value", [
    ("porosiet > 0,2", "kind", "porosity"), ("filtre la permeabilte", "kind", "permeability"),
    ("ouvre les statistques", "panel", "stats"), ("passe en virdis", "preset", "Viridis (matplotlib)"),
    ("ouvre le crossplto", "panel", "crossplot"), ("coupe selon les couhces", "axis", "k"),
])
def test_a_slipped_letter_in_a_word_of_the_trade_is_forgiven(typed, typ, value):
    found = slots.spans(tokens(typed), [])
    assert (typ, value) in [(f[2], f[3]) for f in found]


@pytest.mark.parametrize("word", ["session", "range", "rescale", "state", "ferme", "grand", "mailles"])
def test_a_real_word_is_never_taken_for_a_slip(word):
    assert [f for f in slots.spans(tokens(f"montre {word}"), []) if f[2] != "obj"] == []


def test_a_group_is_every_object_of_that_sort():
    got = parse("cache tous les puits", OBJECTS)
    assert got["intent"] == "hide"
    assert sorted(t["path"] for t in got["targets"]) == ["/w/f11", "/w/f4"]


def test_a_hiding_verb_turns_the_bound_over():
    got = parse("cache les cellules dont la porosité est en dessous de 0,08", OBJECTS)
    assert got["intent"] == "threshold"
    assert (got["slots"]["min"], got["slots"]["max"]) == (pytest.approx(0.08), None)
    got = parse("hide cells where Sw is above 60 %", DEV_OBJECTS)
    assert (got["slots"]["min"], got["slots"]["max"]) == (None, pytest.approx(0.6))


def test_a_named_property_gives_its_kind_and_its_fractions():
    got = parse("show only cells with PHIT greater than 15%", OBJECTS)
    assert got["slots"]["kind"] == "porosity" and got["slots"]["min"] == pytest.approx(0.15)


def test_a_comparison_glued_to_its_number_is_read():
    got = parse("filter poro >0.18 on hugin", OBJECTS)
    assert got["intent"] == "threshold" and got["slots"]["min"] == pytest.approx(0.18)


def test_the_well_seven_is_an_object_not_a_bound():
    objs = OBJECTS + [{"path": "/w/7", "title": "Well 7", "type": "WellboreFeature"}]
    got = parse("montre Hugin et le puits 7", objs)
    assert got["intent"] == "show" and got["slots"]["min"] is None
    assert {t["path"] for t in got["targets"]} == {"/g/hugin", "/w/7"}


def test_a_lone_number_with_a_ceiling_word_is_a_maximum():
    got = parse("plafonne la légende à 150", OBJECTS)
    assert got["intent"] == "color_range" and got["slots"]["max"] == 150


@pytest.mark.parametrize("typed", ["montre Hugin", "show Hugin", "affiche Hugin", "cache Hugin"])
def test_the_plainest_commands_are_sure(typed):
    assert parse(typed, OBJECTS)["sure"]


# ------------------------------------------------------------ the real data (drogon, Volve)
_G = "/data/_gridfolder_g/_propsfolder_g/_g"


def _prop(title, kind, typ="ContinuousProperty"):
    return {"path": f"{_G}_{title}", "title": title, "type": typ, "kind": kind, "parent": _G}


REAL = [
    {"path": _G, "title": "Geogrid", "type": "IjkGrid"},
    _prop("Total Porosity", "porosity"), _prop("Water Saturation", "saturation"),
    _prop("Water Saturation (Gas Zone)", "saturation"), _prop("Gas Saturation", "saturation"),
    _prop("Horizontal Permeability", "rock permeability"), _prop("Temperature", "thermodynamic temperature"),
    {"path": "/data/_w1", "title": "well_feature_NO_15_9-F-1_A_84B691", "type": "Wellbore"},
    {"path": "/data/_w11", "title": "well_feature_NO_15_9-F-11_B_1C2D", "type": "Wellbore"},
    {"path": "/data/_h1", "title": "TopVolantis", "type": "Grid2d"},
    {"path": "/data/_f1", "title": "F1 fault", "type": "TriangulatedSet"},
]


def test_a_generic_kind_is_told_apart_by_the_property_title():
    # drogon's properties share the generic kind "saturation", so the titles
    # tell which one is water: the French words for water saturation are the
    # name of Water Saturation (see ia.nlu.bilingual), and the Gas Zone
    # variant is a different property
    got = parse("montre la saturation en eau de Geogrid", REAL)
    assert [t["title"] for t in got["targets"]] == ["Water Saturation"]


@pytest.mark.parametrize("typed, title", [("montre la perméabilité de Geogrid", "Horizontal Permeability"),
                                          ("quelle est la température moyenne ?", "Temperature")])
def test_the_resqml_standard_kind_names_are_known(typed, title):
    assert title in [t["title"] for t in parse(typed, REAL)["targets"]]


@pytest.mark.parametrize("typed, path", [("ouvre la vue des logs du F-1 A", "/data/_w1"),
                                         ("montre le puits F-11 B", "/data/_w11"),
                                         ("décris la faille F1", "/data/_f1")])
def test_a_piece_of_a_generated_name_finds_the_object(typed, path):
    assert [t["path"] for t in parse(typed, REAL)["targets"]] == [path]


def test_a_grid2d_is_a_surface_not_a_grid():
    assert [t["path"] for t in parse("cache toutes les grilles", REAL)["targets"]] == [_G]
    assert [t["path"] for t in parse("cache toutes les surfaces", REAL)["targets"]] == ["/data/_h1"]


# ------------------------------------------------------------ highlight is not threshold
@pytest.mark.parametrize("typed", [
    "highlight les cellules qui correspondent à une porosité supérieure à 0,2",
    "surligne les mailles où la porosité dépasse 0,2", "highlight cells with porosity above 0.2",
    "mets en évidence les cellules avec une porosité > 0,2"])
def test_highlighting_cells_keeps_the_others_it_is_not_a_filter(typed):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "highlight" and got["sure"]
    assert got["slots"]["min"] == pytest.approx(0.2) and [t["title"] for t in got["targets"]] == ["PHIT"]


@pytest.mark.parametrize("typed", ["filtre la porosité au-dessus de 0,2", "garde les mailles avec une porosité > 0,2"])
def test_a_filter_is_still_a_filter(typed):
    assert parse(typed, OBJECTS)["intent"] == "threshold"


@pytest.mark.parametrize("typed", ["enlève la surbrillance", "remove the highlight"])
def test_the_highlight_can_be_put_out(typed):
    assert parse(typed, OBJECTS)["intent"] == "clear_highlight"


@pytest.mark.parametrize("typed", ["xqzt", "blablabla xyz"])
def test_a_sentence_that_names_nothing_known_is_not_understood(typed):
    got = parse(typed, OBJECTS)
    assert got["intent"] is None and not got["sure"]


@pytest.mark.parametrize("typed", ["aide", "annule", "recenter", "save session", "je veux plus voir la surface"])
def test_short_or_vague_sentences_still_give_a_command(typed):
    assert parse(typed, OBJECTS)["intent"] is not None


# ------------------------------------------------------------ the exact name wins over the lexicon
_TWO = [
    {"path": "/u", "title": "unknown", "type": "UnstructuredGrid"},
    {"path": "/u/poro", "title": "poro", "type": "ContinuousProperty", "kind": "continous propkind",
     "parent": "/u"},
    {"path": "/s", "title": "Sector", "type": "IjkGrid"},
    {"path": "/s/porosity", "title": "Porosity", "type": "ContinuousProperty", "kind": "porosity",
     "parent": "/s"},
]


@pytest.mark.parametrize("typed", ["montre poro", "quelle est la moyenne de poro ?", "cache poro"])
def test_a_word_of_the_lexicon_that_is_an_object_s_exact_title_names_that_object(typed):
    # an exact title outranks the lexicon: "poro" names the object poro only,
    # not also Sector's Porosity through the kind porosity
    assert [t["path"] for t in parse(typed, _TWO)["targets"]] == ["/u/poro"]


def test_a_kind_word_that_is_a_property_s_name_in_the_other_language_names_it():
    # the French word for porosity translates the title Porosity, so it names
    # that property
    got = parse("montre la porosité", _TWO)
    assert [t["path"] for t in got["targets"]] == ["/s/porosity"]


@pytest.mark.parametrize("typed, on", [
    ("ne masque plus les valeurs absentes", False), ("arrête de cacher les NaN", False),
    ("stop hiding the missing values", False), ("masque les NaN", True),
    ("affiche les valeurs manquantes", False), ("n'affiche plus les NaN", True)])
def test_a_negation_turns_the_missing_values_switch_over(typed, on):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "hide_nan" and got["slots"]["on"] is on


def test_isolating_a_property_is_isolate():
    assert parse("isole la porosité de Hugin", OBJECTS)["intent"] == "isolate"


# ------------------------------------------------------------------ category values, bare sorts
_VOLVE_G = "/data/_gridfolder_v/_propsfolder_v/_v"
VOLVE = [
    {"path": _VOLVE_G, "title": "Volve_SGrid", "type": "IjkGrid"},
    {"path": _VOLVE_G + "/_f", "title": "Fluids", "type": "CategoricalProperty", "parent": _VOLVE_G,
     "categories": {0: "water", 1: "oil", 2: "gas"}},
    {"path": _VOLVE_G + "/_l", "title": "Lithology1", "type": "CategoricalProperty", "parent": _VOLVE_G,
     "categories": {0: "Shale", 1: "Sandstone", 2: "Siltstone", 3: "Limestone"}},
    {"path": _VOLVE_G + "/_w", "title": "WatSat", "type": "ContinuousProperty", "kind": "saturation",
     "parent": _VOLVE_G},
    {"path": "/data/_w1", "title": "well_feature_NO_15_9-F-1_ABC", "type": "Wellbore"},
    {"path": "/data/_w2", "title": "well_feature_NO_15_9-F-2_ABC", "type": "Wellbore"},
    {"path": "/data/_w1/_fa", "title": "Facies_Wilfried", "type": "CategoricalProperty", "kind": "facies",
     "parent": "/data/_w1", "categories": {0: "Sand", 1: "Shale"}},
]


@pytest.mark.parametrize("typed, category, code", [
    ("peux-tu m'afficher les zones d'huile de la grille", "oil", 1.0),
    ("affiche les zones de gaz", "gas", 2.0), ("show the oil zones of the grid", "oil", 1.0),
    ("montre le grès", "sandstone", 1.0)])
def test_a_neutral_verb_on_a_category_value_asks_filter_or_highlight(typed, category, code):
    """A neutral verb on a category value is ambiguous, so the engine asks.

    Filter is offered first, then highlight; the range is the value's code in
    the grid's categorical property, not in a well's."""
    got = parse(typed, VOLVE)
    assert got["intent"] == "threshold" and not got["sure"]
    assert got["choose_between"] == ["threshold", "highlight"]
    assert got["slots"]["category"] == category
    assert got["slots"]["min"] == got["slots"]["max"] == code


@pytest.mark.parametrize("typed, intent", [
    ("surligne les zones d'huile", "highlight"), ("highlight the gas cells", "highlight"),
    ("garde que le calcaire", "threshold"), ("filtre les zones d'huile", "threshold")])
def test_an_explicit_verb_on_a_category_value_acts_at_once(typed, intent):
    got = parse(typed, VOLVE)
    assert got["intent"] == intent and got["sure"] and "choose_between" not in got


def test_a_slipped_letter_in_a_category_value_is_forgiven():
    assert parse("affiche le faciès huilde de la grille", VOLVE)["slots"]["category"] == "oil"


def test_a_word_is_a_category_value_only_where_the_session_lists_it():
    assert parse("affiche les zones d'huile", OBJECTS)["slots"]["category"] is None


@pytest.mark.parametrize("typed, intent", [("montre la grille", "show"), ("décris la grille", "describe")])
def test_the_grid_said_without_its_name_is_the_session_s_grid(typed, intent):
    got = parse(typed, VOLVE)
    assert got["intent"] == intent and got["sure"]
    assert [t["title"] for t in got["targets"]] == ["Volve_SGrid"]


def test_a_sort_said_in_the_singular_with_several_answers_is_a_question():
    got = parse("montre le puits", VOLVE)
    assert not got["sure"] and got["missing"] == ["object|kind"]
    assert len(got["targets"]) == 2


def test_watsat_is_the_grid_s_water_saturation():
    got = parse("montre la saturation en eau de la grille", VOLVE)
    assert [t["title"] for t in got["targets"]] == ["WatSat"]


def test_a_category_value_is_the_range_even_when_the_verb_was_read_as_show():
    """A category value sets the range even when the verb reads as show.

    The value's code is the range, so once the reader picks filter or
    highlight nothing is missing and no bound has to be asked for."""
    got = parse("affiche moi l'eau de la grille", VOLVE)
    assert got["choose_between"] == ["threshold", "highlight"]
    assert got["slots"]["min"] == got["slots"]["max"] == 0.0 and got["missing"] == []


# ------------------------------------------------------------------ French words, English names
from fespp_on_trame.ia.nlu import bilingual  # noqa: E402


@pytest.mark.parametrize("said, title", [
    ("perméabilité horizontale", "Horizontal Permeability"), ("porosité totale", "Total Porosity"),
    ("volume d'argile", "Shale Volume"), ("modèle structural", "Structural model"),
    ("toit du réservoir", "Top Reservoir"), ("fluides", "Fluids"), ("lithologie", "Lithology1"),
    ("horizontal permeability", "Perméabilité horizontale")])
def test_a_french_name_and_an_english_title_are_the_same_name(said, title):
    assert bilingual.same_name(tokens(said), title)


@pytest.mark.parametrize("said, title", [
    ("porosité", "Total Porosity"), ("perméabilité verticale", "Horizontal Permeability"),
    ("eau", "Water Saturation")])
def test_a_part_of_a_name_is_not_the_name(said, title):
    assert not bilingual.same_name(tokens(said), title)


_TWO_PERMS = [
    {"path": "/g", "title": "Geogrid", "type": "IjkGrid"},
    {"path": "/g/kh", "title": "Horizontal Permeability", "type": "ContinuousProperty",
     "kind": "rock permeability", "parent": "/g"},
    {"path": "/g/kv", "title": "Vertical Permeability", "type": "ContinuousProperty",
     "kind": "rock permeability", "parent": "/g"},
]


@pytest.mark.parametrize("typed, path", [("montre la perméabilité horizontale", "/g/kh"),
                                         ("affiche la perméabilité verticale de Geogrid", "/g/kv")])
def test_the_property_named_in_french_is_the_one_meant(typed, path):
    assert [t["path"] for t in parse(typed, _TWO_PERMS)["targets"]] == [path]


# ------------------------------------------------------------------ a small memory per session
_WATER = {"category": "water", "kind": None, "targets": [_VOLVE_G + "/_f"], "intent": "highlight"}


@pytest.mark.parametrize("typed, intent", [
    ("maintenant masque moi les autres zones", "threshold"), ("cache le reste", "threshold"),
    ("filtre-les", "threshold"), ("surligne-les", "highlight")])
def test_a_sentence_that_refers_back_takes_up_the_last_command(typed, intent):
    """A sentence that refers back takes up the last command's value and targets.

    After the water is highlighted, hiding "the other zones" keeps only the
    water cells; it is not read as hiding the missing values."""
    got = parse(typed, VOLVE, context=_WATER)
    assert got["intent"] == intent and got["sure"]
    assert got["slots"]["category"] == "water" and got["slots"]["min"] == got["slots"]["max"] == 0.0
    assert [t["title"] for t in got["targets"]] == ["Fluids"]


@pytest.mark.parametrize("typed", ["montre la grille", "annule", "affiche les zones de gaz"])
def test_a_sentence_that_names_its_own_objects_ignores_the_memory(typed):
    assert not parse(typed, VOLVE, context=_WATER)["slots"].get("from_context")


# ------------------------------------------------------------------ hiding a value, complaining
@pytest.mark.parametrize("typed", ["masque la zone huile de la grille", "cache les zones d'huile"])
def test_hiding_a_value_keeps_the_others(typed):
    """Hiding a category value hides those cells and keeps the other values.

    Hiding the oil zone leaves the water and gas cells shown; it never
    switches the whole property off."""
    got = parse(typed, VOLVE)
    assert got["intent"] == "threshold" and got["sure"] and got["slots"].get("exclude")
    assert got["slots"]["category"] == "oil" and "choose_between" not in got


def test_hiding_it_after_it_was_lit_hides_that_value_and_hiding_the_others_keeps_it():
    oil = dict(_WATER, category="oil")
    assert parse("cache-les", VOLVE, context=oil)["slots"].get("exclude")
    assert not parse("masque les autres zones", VOLVE, context=oil)["slots"].get("exclude")


@pytest.mark.parametrize("typed", ["ta réponse ne me convient pas", "ce n'est pas ce que je voulais",
                                   "that's not what I wanted"])
def test_saying_the_answer_missed_is_a_complaint_not_a_gesture(typed):
    assert parse(typed, VOLVE)["intent"] == "complain"


# ------------------------------------------------------------------ several commands in one sentence
from fespp_on_trame.ia.nlu import multi  # noqa: E402


@pytest.mark.parametrize("typed, parts", [
    ("montre la porosité de Hugin et passe en viridis", ["montre la porosite de hugin", "passe en viridis"]),
    ("affiche Hugin puis ouvre les statistiques", ["affiche hugin", "ouvre les statistiques"]),
    ("filter porosity above 0.2 then highlight the gas cells",
     ["filter porosity above 0.2", "highlight the gas cells"]),
    ("ouvre les stats ; exagération x3", ["ouvre les stats", "exageration x3"]),
    ("cache Hugin, ensuite montre le puits F-4 et zoome dessus",
     ["cache hugin", "montre le puits f-4", "zoome dessus"])])
def test_a_sentence_with_several_requests_is_cut_between_them(typed, parts):
    assert multi.split(typed) == parts


@pytest.mark.parametrize("typed", ["filtre la porosité entre 0,1 et 0,3", "montre l'huile et le gaz",
                                   "montre aussi la porosité", "show porosity and permeability"])
def test_an_et_that_joins_words_not_requests_does_not_cut(typed):
    assert len(multi.split(typed)) == 1


@pytest.mark.parametrize("typed, kind, value", [
    ("filtre la perméabilité au-dessus de 100 mD", "permeability", 100.0),
    ("profondeur sous 2500 m", "depth", 2500.0), ("GR au-dessus de 80 gAPI", "gamma ray", 80.0)])
def test_a_unit_after_a_number_is_the_number_s_not_an_object(typed, kind, value):
    objs = [{"path": "/m", "title": "M", "type": "Wellbore"}, {"path": "/md", "title": "MD", "type": "Wellbore"}]
    found = slots.spans(tokens(typed), objs)
    assert [(f[2], f[3]) for f in found if f[2] != "num"] == [("kind", kind)]
    assert [f[3][0] for f in found if f[2] == "num"] == [value]


# ------------------------------------------------------------------ the corpus (people's sentences)
from fespp_on_trame.ia.nlu import corpus  # noqa: E402


def _write(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_the_corpus_keeps_clean_unique_sentences_and_none_of_the_evaluation_sets(tmp_path):
    data, evald = tmp_path / "data", tmp_path / "eval"
    data.mkdir(), evald.mkdir()
    _write(evald / "nlu_heldout_fr.jsonl", [{"text": "Montre la porosité de Hugin", "intent": "show"}])
    _write(data / "corpus_fr-geol.jsonl", [
        {"text": "affiche la porosité de Hugin", "intent": "show", "kind": "porosity"},
        {"text": "Affiche la porosité de Hugin", "intent": "show"},          # a duplicate, case apart
        {"text": "montre la porosité de hugin", "intent": "show"},           # sits in a sealed set
        {"text": "fais un truc", "intent": "not_a_command"},                # not of the catalogue
        {"text": "", "intent": "show"}])
    with open(data / "corpus_en-eng.jsonl", "a", encoding="utf-8") as f:
        f.write('{"text": "keep the oil cells", "intent": "threshold", "category": "oil"}\nnot json\n')
    said = []
    items = corpus.load(str(data), str(evald), say=said.append)
    assert [(i["text"], i["intent"], i["lang"]) for i in items] == [
        ("keep the oil cells", "threshold", "en"), ("affiche la porosité de Hugin", "show", "fr")]
    assert items[1]["kind"] == "porosity" and items[0]["category"] == "oil"
    assert "2 not of the catalogue, 1 duplicates, 1 also in an evaluation set" in said[0]


def test_the_tenth_held_out_is_the_same_whatever_the_order():
    items = [{"text": f"phrase numéro {i} sur la porosité", "intent": "show"} for i in range(400)]
    train, held = corpus.split(items)
    train2, held2 = corpus.split(list(reversed(items)))
    assert 20 <= len(held) <= 60 and len(train) + len(held) == 400
    assert {h["text"] for h in held} == {h["text"] for h in held2}


def test_this_zone_refers_back_and_a_lone_letter_is_not_a_request():
    got = parse("peux-tu masquer cette zone", VOLVE, context=dict(_WATER, category="oil"))
    assert got["slots"].get("from_context") and got["slots"]["category"] == "oil"
    assert parse("k", VOLVE)["intent"] is None and parse("l", VOLVE)["intent"] is None


# ------------------------------------------------------------------ the cells the wells go through
@pytest.mark.parametrize("typed, category, kind", [
    ("surligne les mailles traversées par les puits", None, None),
    ("je veux les block wellbore de la zone huile", "oil", None),
    ("quels puits traversent la zone d'huile", "oil", None),
    ("which wells cross the oil zone", "oil", None),
    ("show the blocked wellbores of Volve_SGrid", None, None),
    ("montre où les trajectoires intersectent la grille", None, None),
    ("highlight the cells where WatSat is above 0.6 penetrated by the wells", None, "water saturation")])
def test_the_cells_the_wells_go_through_whatever_the_verb(typed, category, kind):
    """A crossing word next to a well word is the well-cells command, whatever the verb.

    Highlight, show or a "which wells" question all give it; the plural
    "wells" means every well, never a "which one?" question; a zone's
    category value gives the code range."""
    got = parse(typed, VOLVE)
    assert got["intent"] == "well_cells" and got["sure"], got
    assert got["slots"]["category"] == category
    if kind:
        assert got["slots"]["kind"] == kind
    if category:
        assert got["slots"]["min"] == got["slots"]["max"] == 1.0


def test_the_wells_on_these_zones_take_the_zone_from_the_last_command():
    ctx = dict(_WATER, category="oil", intent="threshold")
    got = parse("peux-tu me surligner où il existe des puits sur ces zones ?", VOLVE, context=ctx)
    assert got["slots"]["category"] == "oil" and got["slots"].get("from_context")
    got = parse("oui mais je veux que tu surligne les endroits où les wellbores les intersectent", VOLVE, context=ctx)
    assert got["intent"] == "well_cells" and got["slots"]["category"] == "oil"
    # a bare singular sort still asks which one; hiding "the other wells" is
    # not a cell filter
    assert "object|kind" in parse("montre le puits", VOLVE)["missing"]
    assert parse("cache les autres puits", VOLVE, context=ctx)["intent"] != "threshold"


@pytest.mark.parametrize("typed, category, well_filter", [
    ("enlève les puits qui ne passent pas par la zone d'huile", "oil", "keep_crossing"),
    ("les trajectoires de puits qui ne passent pas par une zone d'huile tu peux les enlever ?", "oil", "keep_crossing"),
    ("ne garde que les puits qui traversent la zone d'huile", "oil", "keep_crossing"),
    ("remove the wells that don't go through the oil zone", "oil", "keep_crossing"),
    ("cache les puits qui traversent la zone de gaz", "gas", "hide_crossing"),
    ("surligne les mailles traversées par les puits", None, None)])
def test_the_wells_out_of_the_zone_go_when_the_sentence_says_so(typed, category, well_filter):
    """A hiding verb sets which wells go, and a negation turns it over.

    With a negation ("the wells that do not cross"), only the crossing wells
    stay (keep_crossing); without one, the crossing wells are hidden
    (hide_crossing); with no hiding verb, no well is filtered."""
    got = parse(typed, VOLVE)
    assert got["intent"] == "well_cells" and got["sure"], got
    assert got["slots"]["category"] == category
    assert got["slots"].get("well_filter") == well_filter


def test_the_blocks_of_the_wellbores_through_this_zone_take_the_zone_from_the_last_command():
    """Words that only resemble session objects do not capture the sentence.

    "blocks" and "zone" look like fault_blocks and the OilZone representation,
    yet "this zone" is the zone of the last command."""
    objs = VOLVE + [{"path": _VOLVE_G + "/_fb", "title": "fault_blocks", "type": "DiscreteProperty",
                     "parent": _VOLVE_G},
                    {"path": "/data/_oz", "title": "Volve_SGrid_OilZone", "type": "Sub"}]
    ctx = dict(_WATER, category="oil", intent="threshold")
    got = parse("peux tu me montrer tous les blocks des wellbores qui traversent uniquement cette zone", objs,
                context=ctx)
    assert got["intent"] == "well_cells" and got["slots"]["category"] == "oil"
    assert got["slots"]["min"] == 1.0 and [t["title"] for t in got["targets"]] == ["Fluids"]


# ------------------------------------------------------------------ phrasings from the corpus's held-out tenth
@pytest.mark.parametrize("typed, intent", [
    ("arrête de faire ressortir les cellules", "clear_highlight"),
    ("stop highlighting the cells", "clear_highlight"),
    ("coupe tout ce qui a une densité sous 2.2", "threshold"),
    ("surligne les mailles d'huile mais garde tout visible", "highlight"),
    ("make the sandstone stand out", "highlight"),
    ("signale-moi les mailles de gaz", "highlight"),
    ("show the gas cells in a bright colour without hiding anything", "highlight")])
def test_the_sentences_the_corpus_held_out_taught(typed, intent):
    got = parse(typed, VOLVE)
    assert got["intent"] == intent and got["sure"], got


# ------------------------------------------------------------------ terse, conversational sentences
_OIL_KEPT = dict(_WATER, category="oil", intent="threshold")
_OIL_WELLS = dict(_WATER, category="oil", intent="well_cells")


@pytest.mark.parametrize("typed, ctx, intent, category, extra", [
    ("hide the shale", None, "threshold", "shale", {"exclude": True}),
    ("je veux pas voir l'eau", None, "threshold", "water", {"exclude": True}),
    ("non pas le gaz, l'huile", _OIL_KEPT, "threshold", "oil", {}),
    ("poro", None, "show", None, {}),
    ("surlingne le gaz", None, "highlight", "gas", {}),
    ("et pour le gaz ?", dict(_WATER, category="oil", intent="highlight"), "highlight", "gas", {}),
    ("surligne moi les mailles de ces puits", _OIL_WELLS, "well_cells", "oil", {}),
    ("et maintenant masque moi les autres puits", _OIL_WELLS, "well_cells", "oil", {"well_filter": "keep_crossing"}),
    ("cache tout sauf cette zone", _OIL_KEPT, "threshold", "oil", {}),
    ("non je voulais surligner pas filtrer", _OIL_KEPT, "highlight", "oil", {}),
    ("mask the wells that are not in the oil", None, "well_cells", "oil", {"well_filter": "keep_crossing"}),
    ("enleve ceux qui traversent pas cette zone", _OIL_WELLS, "well_cells", "oil", {"well_filter": "keep_crossing"}),
    ("whats the mean porosity along the wells", None, "value", None, {})])
def test_the_sentences_the_po_style_writers_found(typed, ctx, intent, category, extra):
    """Terse, conversational phrasings are read as the command they mean.

    Covered: a French negation without "ne", a value named to be excluded, a
    bare property name, a typo in a verb, the last command repeated with
    another value, the wells of the last command, and a correction of the
    last command."""
    got = parse(typed, VOLVE, context=ctx)
    assert got["intent"] == intent, got
    assert got["slots"].get("category") == category, got["slots"]
    for k, v in extra.items():
        assert got["slots"].get(k) == v, (k, got["slots"].get(k))


# ------------------------------------------------------------------ a common word is not a name
# titles that end like everyday words: PHIT (it), WatSat (at), Draupne fine
# (ne), Top Reservoir (voir), RHOB_WIL (il), GM09_FACIES (es), DT_EDIT
# (dit), a horizon called J, fault_blocks, the zone sub-representations
_SESSION = OBJECTS + [
    {"path": "/s/topres", "title": "Top Reservoir", "type": "Grid2dRepresentation"},
    {"path": "/g/draupne", "title": "Draupne fine", "type": "IjkGrid"},
    {"path": "/g/hugin/watsat", "title": "WatSat", "type": "ContinuousProperty", "kind": "water saturation",
     "parent": "/g/hugin"},
    {"path": "/w/f4/rhob", "title": "RHOB_WIL", "type": "ContinuousProperty", "kind": "bulk density",
     "parent": "/w/f4"},
    {"path": "/w/f4/dt", "title": "DT_EDIT", "type": "ContinuousProperty", "parent": "/w/f4"},
    {"path": "/w/f4/fac", "title": "GM09_FACIES", "type": "CategoricalProperty", "kind": "facies",
     "parent": "/w/f4"},
    {"path": "/g/hugin/fb", "title": "fault_blocks", "type": "DiscreteProperty", "parent": "/g/hugin"},
    {"path": "/z/oil", "title": "Volve_SGrid_OilZone", "type": "Sub"},
    {"path": "/s/j", "title": "J", "type": "Grid2dRepresentation"},
    {"path": "/z/3", "title": "Zone 3"},
    {"path": "/w/7", "title": "Well 7", "type": "WellboreFeature"},
]


@pytest.mark.parametrize("typed", [
    "make it viridis", "undo it", "cap the colorbar at 150", "je ne veux plus voir la porosité",
    "je veux voir la porosité", "non il n'y a rien sur la vue", "j'ai dit la porosité", "tu t'es trompé",
    "montre les blocks des puits de cette zone", "show the cells at the top", "so show me the porosity",
    "hide the zones and the wells", "show the model"])
def test_a_common_word_never_names_an_object(typed):
    """"it" is no end of PHIT, "at" none of WatSat, "ne" none of Draupne
    fine, "voir" none of Top Reservoir; a lone letter (j') names J only after
    the name of its sort; a sort ("zone", "blocks", "model") alone names no
    object whose title merely holds it (the sort said without a name, "les
    puits", is every object of that sort: not a name, a group)."""
    toks = tokens(typed)
    found = slots.spans(toks, _SESSION)
    assert [(" ".join(toks[a:b]), [o["title"] for o in v]) for a, b, t, v, _s in found
            if t == "obj" and not any(o.get("by_sort") for o in v)] == []


@pytest.mark.parametrize("typed, objects, title", [
    ("ouvre la vue des logs du F-4", _SESSION, "15/9-F-4"), ("cache 15/9-F-11 A", _SESSION, "15/9-F-11 A"),
    ("remove F-11 A from the view", _SESSION, "15/9-F-11 A"), ("montre l'horizon J", _SESSION, "J"),
    ("montre la zone 3", _SESSION, "Zone 3"), ("montre le puits 7", _SESSION, "Well 7"),
    ("cache Draupne fine", _SESSION, "Draupne fine"), ("montre le toit du réservoir", _SESSION, "Top Reservoir"),
    ("cache Hugin", [OBJECTS[-1]], "Top Hugin")])
def test_a_name_is_still_found_by_its_end_or_its_pieces(typed, objects, title):
    """The end of a name from one of its pieces on ("F-4", "Hugin" of Top
    Hugin), a lone letter after its sort, a sort and its number."""
    assert [t["title"] for t in parse(typed, objects)["targets"]] == [title]


@pytest.mark.parametrize("said, title", [("zone", "Zone 3"), ("les puits", "Well 7"), ("modèle", "Sw_model"),
                                          ("faille", "Fault F1"), ("grids", "Grid 1")])
def test_a_sort_said_alone_is_not_the_name_of_one_object(said, title):
    assert not bilingual.same_name(tokens(said), title)


def test_a_title_said_whole_with_its_number_is_the_object_not_a_kind_and_a_bound():
    got = parse("seuil sur NTG_2024 à 0.5", VOLVE + [
        {"path": _VOLVE_G + "/_ntg", "title": "NTG_2024", "type": "ContinuousProperty", "kind": "net to gross ratio",
         "parent": _VOLVE_G}])
    assert got["intent"] == "threshold" and [t["title"] for t in got["targets"]] == ["NTG_2024"]
    assert (got["slots"]["min"], got["slots"]["max"]) == (pytest.approx(0.5), None)


# ------------------------------------------------------------------ the rules defer to a sure reading
@pytest.mark.parametrize("typed", ["annule le surlignage des zones d'huile",
                                   "Désactivez le surlignage des zones à pétrole", "cancel the highlight on the gas"])
def test_cancelling_a_highlight_clears_it(typed):
    assert parse(typed, VOLVE)["intent"] == "clear_highlight"


@pytest.mark.parametrize("typed, intent", [
    ("montre le GR le long du puits F-4", "show"), ("quelle profondeur max atteint le puits F-4 ?", "value"),
    ("render the bulk density along the well", "show")])
def test_a_crossing_word_without_the_grid_s_cells_is_not_the_well_cells(typed, intent):
    """"Along the well" with a log, "reaches" with a maximum: the cells the
    wells go through are about the grid's cells, a zone or a value."""
    objs = OBJECTS + [{"path": "/w/f4/rhob", "title": "RHOB", "type": "WellboreFrameRepresentation",
                       "kind": "bulk density", "parent": "/w/f4"}]
    assert parse(typed, objs)["intent"] == intent


@pytest.mark.parametrize("typed", ["marque le grès en rouge", "make the sandstone glow",
                                   "colour the shale cells in red"])
def test_a_value_the_model_is_sure_is_to_be_lit_is_lit_without_a_question(typed):
    got = parse(typed, VOLVE)
    assert got["intent"] == "highlight" and got["sure"] and "choose_between" not in got


@pytest.mark.parametrize("typed, intent", [("hey", "help"), ("good morning", "help"), ("ctrl+z", "undo"),
                                           ("thats false", "complain")])
def test_a_sentence_of_words_the_model_was_trained_on_is_understood(typed, intent):
    assert parse(typed, OBJECTS)["intent"] == intent


def test_the_model_keeps_the_words_it_was_trained_on():
    m = IntentModel.load(MODEL_PATH)
    assert {"hey", "porosite", "surligne", "wells"} <= m.vocab


@pytest.mark.parametrize("typed", ["what's PHIT", "what is PHIT", "c'est quoi PHIT"])
def test_a_name_asked_about_is_described(typed):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "describe" and [t["title"] for t in got["targets"]] == ["PHIT"]


# ------------------------------------------------------------------ what the real sessions taught
_FLUIDS = _VOLVE_G + "/_f"
_OIL_WELLS_CTX = {"intent": "well_cells", "category": "oil", "kind": None, "targets": [_FLUIDS]}


@pytest.mark.parametrize("typed, ctx, intent, wanted", [
    # after the wells through the oil zone, the zones and the grid are the
    # grid's values again
    ("enlèves les zones autre que huile", _OIL_WELLS_CTX, "threshold", {"category": "oil", "exclude": None}),
    ("ok maintenant cache les autres zones", _OIL_WELLS_CTX, "threshold", {"category": "oil", "exclude": None}),
    # several values, hidden together
    ("enleves sur la grille les zones eau et gaz", _OIL_WELLS_CTX, "threshold",
     {"categories": ["water", "gas"], "exclude": True}),
    # a correction redoes the last command as it was, with the values said
    ("J'avais dit eau et gaz", {"intent": "threshold", "category": "water", "targets": [_FLUIDS], "exclude": True},
     "threshold", {"categories": ["water", "gas"], "exclude": True}),
    # … and takes its gesture from the main clause, not from "what I had
    # asked you to highlight"
    ("ta réponse précédente ne me convenait pas je voulais que tu masque la zone huile que je t'avais demandé"
     " de surligner", {"intent": "hide", "category": None, "targets": []}, "threshold",
     {"category": "oil", "exclude": True}),
    # "que l'huile" is only the oil: a filter, no question
    ("montre moi que l'huile sur la grille", _OIL_WELLS_CTX, "threshold", {"category": "oil", "exclude": None}),
    ("don't show the gas", None, "threshold", {"category": "gas", "exclude": True}),
    ("ne montre pas l'eau", None, "threshold", {"category": "water", "exclude": True}),
    ("cache tout sauf l'huile", None, "threshold", {"category": "oil", "exclude": None}),
    ("masque l'eau et garde le reste", None, "threshold", {"category": "water", "exclude": True})])
def test_the_real_sessions_values_are_kept_or_hidden_as_said(typed, ctx, intent, wanted):
    got = parse(typed, VOLVE, context=ctx)
    assert got["intent"] == intent and got["sure"], got
    for k, v in wanted.items():
        assert got["slots"].get(k) == v, (k, got["slots"].get(k))


def test_several_values_are_all_read_the_first_one_leading():
    s = parse("masque les zones eau et gaz", VOLVE)["slots"]
    assert s["categories"] == ["water", "gas"] and s["category"] == "water" and s["exclude"]
    assert parse("non pas le gaz, l'huile", VOLVE)["slots"]["categories"] == ["oil"]


# ------------------------------------------------------------------ numbers and bounds as people type them
def test_numbers_are_read_as_people_type_them():
    assert normalize("entre 1 000 et 2 500 m") == "entre 1000 et 2500 m"
    assert normalize("slice at k=10") == "slice at k = 10"
    assert normalize("poro ≤ 0,2 ou ≥ 0,4") == "poro <= 0.2 ou >= 0.4"
    # "≠" and "!=" say a value NOT, never an equal sign
    assert normalize("porosité ≠ 0") == normalize("porosité != 0") == "porosite neq 0"
    # well names keep their hyphens and slashes, and so do two numbers joined
    # by a hyphen: slots.py reads them as a range unless they name an object
    assert tokens("le puits 15/9-F-4 et le 25/11-15") == ["le", "puits", "15/9-f-4", "et", "le", "25/11-15"]
    toks = tokens("la porosité 0,1-0,3")
    assert toks == ["la", "porosite", "0.1-0.3"]
    assert [f[2] for f in slots.spans(toks, OBJECTS)] == ["kind", "range"]
    assert slots.delex(toks, slots.spans(toks, OBJECTS)) == ["la", "<kind>", "<num>", "-", "<num>"]


@pytest.mark.parametrize("typed, lo, hi", [
    ("filtre la perméabilité entre 1 000 et 2 500", 1000, 2500), ("filtre la porosité 0,1-0,3", 0.1, 0.3),
    ("porosité inférieure ou égale à 0,2", None, 0.2), ("porosité supérieure ou égale à 0,2", 0.2, None),
    ("porosité ≤ 0,2", None, 0.2), ("porosity less than or equal to 0.2", None, 0.2),
    ("porosity at or below 0.2", None, 0.2), ("porosity no more than 0.2", None, 0.2),
    ("porosité pas plus de 0,2", None, 0.2), ("porosité en deçà de 0,2", None, 0.2),
    ("keep porosity beyond 0.2", 0.2, None), ("porosity exceeding 0.2 only", 0.2, None),
    ("filtre la porosité supérieure à 20", 0.2, None), ("garde le facies égal à 2", 2, 2),
    ("i'd like to keep the cells with NTG over 0.55 and drop the rest", 0.55, None),
    ("filter out the cells whose Sw is above 0.8", None, 0.8), ("cells deeper than 2500 m", 2500, None),
    ("Peut-on plafonner la légende à 500 mD ?", None, 500)])
def test_the_bounds_are_read_as_people_say_them(typed, lo, hi):
    """Thousands, ranges with a hyphen, "or equal", "no more than", "beyond",
    an equal value, a bare percentage of a fraction, a ceiling verb; "…and
    drop the rest" hides the rest, not the cells said."""
    s = parse(typed, DEV_OBJECTS)["slots"]
    assert (s["min"], s["max"]) == (pytest.approx(lo) if lo is not None else None,
                                    pytest.approx(hi) if hi is not None else None), s


@pytest.mark.parametrize("typed, axis, lo, hi", [
    ("garde les couches 10-20", "k", 10, 20), ("slice at k=10", "k", 10, 10), ("montre la couche 12", "k", 12, 12),
    ("rows 1 to 30 of Hugin", "j", 1, 30), ("make an I cut from 20 to 40", "i", 20, 40)])
def test_a_slice_reads_its_axis_and_its_layers(typed, axis, lo, hi):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "slice" and got["slots"]["axis"] == axis
    assert (got["slots"]["min"], got["slots"]["max"]) == (lo, hi)


def test_two_filters_said_at_once_are_two_commands_or_a_question():
    assert multi.split("filtre la porosité au-dessus de 0,2 et la perméabilité au-dessus de 100") == [
        "filtre la porosite au dessus de 0.2", "filtre la permeabilite au dessus de 100"]
    got = parse("porosité > 0,2 et perméabilité > 100", OBJECTS)
    assert got["slots"]["min"] == pytest.approx(0.2) and not got["sure"]


# ------------------------------------------------------------------ the two switches
@pytest.mark.parametrize("typed, on", [
    ("je veux plus voir les mailles sans valeur", True), ("je ne veux pas voir les NaN", True),
    ("I don't want to see the missing values", True), ("can you drop the undefined values from the display?", True),
    ("I want to see the empty cells too", False), ("remets les valeurs absentes", False),
    ("show the missing values again", False), ("bring back the empty cells", False)])
def test_seeing_said_not_hides_the_missing_values_and_showing_them_shows_them(typed, on):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "hide_nan" and got["slots"]["on"] is on


@pytest.mark.parametrize("typed, on", [
    ("Désactive les couleurs plates", False), ("remets les ombres", False), ("turn on the shading", False),
    ("enlève les ombres", True), ("couleurs exactes", True), ("sans ombrage", True),
    ("je veux pas de dégradé, des couleurs franches", True)])
def test_the_exact_colours_switch_follows_the_words_said_of_it(typed, on):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "flat_colors" and got["slots"]["on"] is on


# ------------------------------------------------------------------ the words of the trade, English included
@pytest.mark.parametrize("typed, intent, key, value", [
    ("make it viridis", "colormap", "preset", "Viridis (matplotlib)"),
    ("cap the colorbar at 150", "color_range", "max", 150),
    ("so show me the porosity", "show", "kind", "porosity"),
    ("cut the grid on J", "slice", "axis", "j"), ("show columns 5 to 9", "slice", "axis", "i"),
    ("can I cut the grid along k", "slice", "axis", "k"), ("I want to see Hugin", "show", "axis", None),
    ("black and white for the GR", "colormap", "preset", "Grayscale"),
    ("can we have blue to red colours instead?", "colormap", "preset", "Cool to Warm"),
    ("show the water sat of Hugin", "show", "kind", "water saturation"),
    ("how deep does Hugin go?", "value", "kind", "depth"),
    ("open the quality check", "open_panel", "panel", "health"),
    ("compare logs versus grid", "open_panel", "panel", "reconcile"),
    ("je voudrais calculer une nouvelle propriété à partir de la porosité", "open_panel", "panel", "calculator"),
    ("fais un graphique croisé porosité perméabilité", "open_panel", "panel", "crossplot"),
    ("calcule la moyenne de la porosité", "value", "panel", None),
    ("zoome près du puits F-4", "reset_camera", "kind", None),
    ("c'est quoi une propriété catégorielle ?", "ask", "preset", None)])
def test_the_words_of_the_trade_are_read(typed, intent, key, value):
    """Axes said "rows", "columns", "on J" (not the English "I"), palettes
    said in words, "water sat", depth said "deep", the panels by what they
    do; "so", "près" and "à côté" are no kinds, "calcule" no panel."""
    got = parse(typed, OBJECTS)
    assert got["intent"] == intent and got["slots"][key] == value, got["slots"]


@pytest.mark.parametrize("typed, category", [("garde les mailles gréseuses", "sandstone"),
                                             ("surligne les zones argileuses", "shale")])
def test_a_value_said_as_an_adjective_is_the_value(typed, category):
    assert parse(typed, VOLVE)["slots"]["category"] == category


@pytest.mark.parametrize("typed, key, value", [
    ("keep cells where So is above 0.4", "kind", "oil saturation"), ("set z = 2", "factor", 2),
    ("vertical exaggeration back to true scale", "factor", 1),
    ("check the well logs against the grid", "panel", "reconcile"),
    ("show the volume of the cells of Hugin", "kind", "cell volume"),
    ("highlight the layers thinner than 2 m thick", "kind", "thickness")])
def test_a_parameter_said_in_passing_is_read(typed, key, value):
    """A mnemonic before its bound ("So is above"), an equal sign or "true
    scale" for the vertical factor, the logs set against the grid."""
    assert parse(typed, OBJECTS)["slots"][key] == value


def test_the_engine_s_cue_words_are_never_taken_for_a_slip():
    """A word the engine reads as a cue ("perce", "calcule", "deep") is said
    on purpose: never a mistyped kind, panel, palette, axis or value."""
    from fespp_on_trame.ia.nlu import engine, lexicon
    tables = [slots._GROUP_PHRASES, slots._PANEL_PHRASES, slots._PRESET_PHRASES, slots._KIND_PHRASES,
              slots._AXIS_PHRASES, slots._phrases(lexicon.CATEGORIES)]
    slipped = {w: c for w in engine.cue_words() for tb in tables
               for n, c in [slots._match_at([w], 0, tb, fuzzy=True)] if n}
    assert slipped == {}, "add them to slots._CUE_WORDS"


# ------------------------------------------------------------------ several requests, said tersely
@pytest.mark.parametrize("typed, parts", [
    ("quels puis traversent la zone d'uile", ["quels puits traversent la zone d uile"]),
    ("cache-les puis montre Hugin", ["cache les", "montre hugin"]),
    ("enleve le surlignage et le filtre", ["enleve le surlignage", "enleve le filtre"]),
    ("remove the highlight and the filter", ["remove the highlight", "remove the filter"]),
    ("passe en viridis et recentre", ["passe en viridis", "recentre"]),
    ("montre la porosité puis la perméabilité", ["montre la porosite", "montre la permeabilite"]),
    ("show the porosity then the permeability", ["show the porosity", "show the permeability"]),
    ("sauvegarde puis nouvelle vue", ["sauvegarde", "nouvelle vue"]),
    ("enlèves les zones autre que huile et surligne le gaz", ["enleves les zones autre que huile", "surligne le gaz"])])
def test_a_verb_said_once_or_a_slipped_well_is_read_as_meant(typed, parts):
    """"puis" after a determiner is a slipped "puits"; a verb said for two
    things is said again for the second; a request without a verb takes
    the verb before; a new request keeps its own."""
    assert multi.split(typed) == parts


def test_a_slipped_well_is_read_whole_by_the_engine_too():
    got = parse("quels puis traversent la zone d'uile", VOLVE)
    assert got["intent"] == "well_cells" and got["slots"]["category"] == "oil"


# ------------------------------------------------------------------ questions, out of the domain
@pytest.mark.parametrize("typed, ctx, intent", [
    ("pourquoi ce puit surligné est afficher il n'y avait pas de blockwellbore dans l'huile à priori",
     _OIL_WELLS_CTX, "ask"),
    ("est-ce que tu vois des chenaux dans la grille", None, "ask"),
    ("les piliers ca veut dire quoi ?", None, "ask"),
    ("pourquoi je ne vois rien ?", None, "complain"), ("je ne vois rien", None, "complain"),
    ("est-ce qu'il y a des puits qui passent par la zone d'eau de la grille ?", None, "well_cells")])
def test_a_question_is_answered_a_complaint_heard(typed, ctx, intent):
    """"Why…", "do you see…": an answer, not a gesture nor a complaint —
    unless nothing is seen; a question on the wells through a zone is the
    wells' cells."""
    assert parse(typed, VOLVE, context=ctx)["intent"] == intent


@pytest.mark.parametrize("typed", ["donne moi la recette de la tarte au pomme",
                                   "tu connais une recette de tarte aux pommes ?"])
def test_a_request_out_of_the_domain_is_not_understood(typed):
    got = parse(typed, VOLVE)
    assert got["intent"] is None and not got["sure"]


# ------------------------------------------------------------------ sentences once read wrong, pinned
@pytest.mark.parametrize("name", ["nlu_regress_fr.jsonl", "nlu_regress_en.jsonl"])
def test_the_sentences_once_read_wrong_are_read_right(name):
    """Sentences an earlier engine read wrong, each with its right reading
    — the command, the parameters, the objects acted on, whether the
    application acts without asking, the next requests' readings — read as
    the application reads them (cut by multi.split, with the context the
    row carries, in the session it names)."""
    rows = evaluation.rows(name)
    assert rows, name
    bad = [(r["text"], w) for r in rows for w in [evaluation.wrong(r, DEV_OBJECTS)] if w]
    assert bad == []


def test_a_row_naming_a_session_no_one_has_is_an_error():
    with pytest.raises(ValueError, match="unknown session"):
        evaluation.objects_of({"text": "montre Hugin", "session": "nowhere"}, OBJECTS)
    # the second sealed sets are read against their own session, which
    # lists category values (Fluids, Lithology1)
    sealed = dict(evaluation.SEALED_SETS)
    assert sealed["nlu_heldout2_fr.jsonl"] is sealed["nlu_heldout2_en.jsonl"] is evaluation.HELDOUT2_OBJECTS
    assert any(o.get("categories") for o in evaluation.HELDOUT2_OBJECTS)


# ------------------------------------------------------------------ bounds: layers, equal signs, titles
_TRAPS = evaluation.SESSIONS["traps"]


@pytest.mark.parametrize("typed, axis, lo, hi", [
    ("slice PHIT along k from 10 to 40", "k", 10, 40), ("coupe la porosité à la couche 12", "k", 12, 12),
    ("coupe k de 10 à 20 sur le NTG", "k", 10, 20), ("keep the top 10 layers of porosity", "k", 1, 10),
    ("show layers 10-20 of PHIT", "k", 10, 20)])
def test_the_layers_of_a_slice_are_never_made_fractions(typed, axis, lo, hi):
    """A fraction kind named in a slice (porosity, NTG) leaves its layers as
    said: only a filter's, a highlight's or a colour range's bounds are
    percents of a fraction."""
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "slice" and got["slots"]["axis"] == axis
    assert (got["slots"]["min"], got["slots"]["max"]) == (lo, hi) and "raw" not in got["slots"]


def test_a_bare_percent_of_a_fraction_keeps_the_number_said():
    """"…dépasse 50" on a saturation is 0.5 — and "raw" keeps the 50 said,
    for the adapter to take back on a property stored in % or p.u."""
    s = parse("filtre les mailles où la saturation en eau dépasse 50", DEV_OBJECTS)["slots"]
    assert s["min"] == pytest.approx(0.5) and s["raw"] == {"min": 50.0} and not s["percent"]


@pytest.mark.parametrize("typed, intent, lo, hi", [
    ("palette min = 0.1 max = 0.3", "color_range", 0.1, 0.3), ("légende max = 300", "color_range", None, 300),
    ("palette de la perméabilité : min = 10, max = 1000", "color_range", 10, 1000),
    ("mets le max de la légende = 0.25", "color_range", None, 0.25),
    ("porosity cutoff = 0.08", "threshold", 0.08, None), ("le seuil de porosité vaut 0.1", "threshold", 0.1, None),
    ("NTG cutoff equals 0.5", "threshold", 0.5, None),
    ("keep the cells where porosity equals 0.2", "threshold", 0.2, None),
    ("garde le faciès égal à 2", "threshold", 2, 2), ("coupe en k = 15 sur la porosité", "slice", 15, 15)])
def test_an_equal_sign_gives_the_bound_of_the_word_before_it(typed, intent, lo, hi):
    """After min / max that bound, after a cutoff a minimum; one value only
    after an axis or on a property of codes — a continuous property said
    equal to a number is filtered from it."""
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == intent, got
    assert (got["slots"]["min"], got["slots"]["max"]) == (pytest.approx(lo) if lo is not None else None,
                                                          pytest.approx(hi) if hi is not None else None)


def test_a_value_said_not_is_no_bound_and_the_engine_asks():
    got = parse("filtre la porosité ≠ 0", DEV_OBJECTS)
    assert got["slots"]["neq"] and got["slots"]["max"] is None and not got["sure"]


@pytest.mark.parametrize("typed, objects, lo, hi", [
    ("filtre Top Hugin à 2500", DEV_OBJECTS, 2500, None),
    ("highlight cells on Top Hugin with porosity 0.25", DEV_OBJECTS, 0.25, None),
    ("seuil à 0.2 sur la porosité de Top Hugin", _TRAPS, 0.2, None),
    ("plafonne la légende à 150", DEV_OBJECTS, None, 150)])
def test_a_ceiling_word_inside_a_title_is_no_maximum(typed, objects, lo, hi):
    """The "Top" of Top Hugin is a name, not a ceiling."""
    s = parse(typed, objects)["slots"]
    assert (s["min"], s["max"]) == (pytest.approx(lo) if lo is not None else None,
                                    pytest.approx(hi) if hi is not None else None)


# ------------------------------------------------------------------ names: numbers, camel case, sorts, little words
_VOLVE_J = evaluation.SESSIONS["volve"]
_DROGON = evaluation.SESSIONS["drogon"]
_LITTLE = evaluation.SESSIONS["little"]


@pytest.mark.parametrize("typed, objects, intent, title", [
    ("zoome sur 9-19 A", _VOLVE_J, "reset_camera", "well_feature_NO_15_9-19_A_B5088C"),
    ("cache le puits 9-19 SR", _VOLVE_J, "hide", "well_feature_NO_15_9-19_SR_EBECD2"),
    ("montre le puits 19 A", _VOLVE_J, "show", "well_feature_NO_15_9-19_A_B5088C"),
    ("montre le puits 11-15", _TRAPS, "show", "25/11-15"), ("montre le puits 33-1", _DROGON, "show", "55/33-1")])
def test_numbers_joined_by_a_hyphen_that_name_a_well_are_no_range(typed, objects, intent, title):
    got = parse(typed, objects)
    assert got["intent"] == intent and [t["title"] for t in got["targets"]] == [title]
    assert got["slots"]["min"] is None and got["slots"]["max"] is None


@pytest.mark.parametrize("typed, titles", [("montre Volantis", ["TopVolantis", "BaseVolantis"]),
                                           ("isole Volantis", ["TopVolantis", "BaseVolantis"]),
                                           ("show the top of Volantis", ["TopVolantis"])])
def test_a_name_written_in_camel_case_is_found_by_its_words(typed, titles):
    assert sorted(t["title"] for t in parse(typed, _DROGON)["targets"]) == sorted(titles)


def test_a_title_made_of_sorts_is_named_in_the_other_language():
    assert bilingual.same_name(tokens("blocs de faille"), "fault_blocks")
    got = parse("affiche les blocs de faille", _VOLVE_J)
    assert got["intent"] == "show" and got["sure"] and [t["title"] for t in got["targets"]] == ["fault_blocks"]


@pytest.mark.parametrize("typed, intent, title", [("montre SO", "show", "SO"), ("show me SO", "show", "SO"),
                                                  ("cache J", "hide", "J"), ("montre K1", "show", "K1")])
def test_a_title_that_is_a_little_word_is_named_in_capitals(typed, intent, title):
    """"SO", "J" written as names (in capitals) are the session's SO and J;
    the English "so", the "j'" of "j'aime" and a capital starting a
    sentence are not (a lone letter in small letters names an object only
    after the name of its sort: "l'horizon J")."""
    got = parse(typed, _LITTLE)
    assert got["intent"] == intent and got["sure"] and [t["title"] for t in got["targets"]] == [title]


@pytest.mark.parametrize("typed", ["so show me the porosity", "J'aimerais voir la porosité",
                                   "slice the grid so I can see"])
def test_a_little_word_said_as_a_word_names_no_title(typed):
    toks = tokens(typed)
    found = slots.spans(toks, _LITTLE, caps=slots.capitals(typed))
    assert not [v for _a, _b, t, v, _s in found if t == "obj" and any(o["title"] in ("SO", "J") for o in v)]


@pytest.mark.parametrize("typed", ["slice at k 1", "coupe en k 1"])
def test_an_axis_and_its_layer_are_no_title_where_a_slice_is_spoken_of(typed):
    got = parse(typed, _LITTLE)
    assert got["intent"] == "slice" and got["slots"]["axis"] == "k" and got["slots"]["min"] == got["slots"]["max"] == 1


@pytest.mark.parametrize("typed", ["hide the wells I think", "I think the porosity looks wrong",
                                   "Thanks, now on I think we should hide the wells"])
def test_think_is_no_slip_of_thick(typed):
    assert "thickness" not in parse(typed, DEV_OBJECTS)["slots"]["kinds"]


@pytest.mark.parametrize("typed", ["in I want a slice", "show PHIT by I mean the porosity", "now on I think so"])
def test_the_english_i_before_its_verb_is_no_axis(typed):
    assert parse(typed, OBJECTS)["slots"]["axis"] is None


@pytest.mark.parametrize("typed", ["porosité", "perméabilité", "NTG", "water saturation", "GR"])
def test_a_property_said_alone_is_a_sure_show(typed):
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "show" and got["sure"]


# ------------------------------------------------------------------ gestures said around, corrected, asked
@pytest.mark.parametrize("typed, intent", [
    ("j'ai dit cache les puits", "hide"), ("I told you to hide the wells", "hide"),
    ("je t'avais dit de masquer Hugin", "hide"), ("je t'ai dit d'isoler la porosité", "isolate"),
    ("j'ai dit de passer en viridis", "colormap"), ("I told you to zoom on F-4", "reset_camera"),
    ("non je voulais dire la perméabilité", "show")])
def test_a_correction_that_says_a_gesture_is_that_gesture(typed, intent):
    """"j'ai dit cache les puits" is the hiding said, not the last command
    again — which is redone only when nothing else is asked ("I meant the
    permeability")."""
    ctx = {"intent": "show", "category": None, "kind": "porosity", "targets": ["/g/hugin/phit"]}
    got = parse(typed, DEV_OBJECTS, context=ctx)
    assert got["intent"] == intent and got["sure"], got


@pytest.mark.parametrize("typed, on", [
    ("masque les NaN, je ne veux plus les voir", True),
    ("enlève les valeurs absentes, on ne doit plus les voir", True),
    ("hide the missing values, I don't want to see them", True), ("je ne veux plus les NaN", True),
    ("ne cache pas les NaN", False), ("les valeurs absentes, ne les masque plus", False)])
def test_a_negation_turns_over_the_verb_it_bears_on_only(typed, on):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "hide_nan" and got["slots"]["on"] is on


@pytest.mark.parametrize("typed, lo", [
    ("masque les mailles de porosité inférieure à 0,1 et garde les autres", 0.1),
    ("enlève les mailles de perméabilité inférieure à 5 et laisse les autres", 5),
    ("masque les mailles dont la perméabilité est inférieure à 10, pas les autres", 10),
    ("masque la porosité sous 0.05", 0.05), ("cache les mailles de porosité sous 0,1 mais pas les autres", 0.1)])
def test_keeping_the_others_confirms_the_bound_turned_over(typed, lo):
    """Hiding the cells below a bound keeps the others: "…et garde les
    autres", "…pas les autres" say it again; "…and drop the rest" alone
    hides the rest (test_the_bounds_are_read_as_people_say_them)."""
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "threshold" and got["sure"]
    assert (got["slots"]["min"], got["slots"]["max"]) == (pytest.approx(lo), None)
    assert len(multi.split(typed)) == 1


@pytest.mark.parametrize("typed, intent", [
    ("je ne veux pas voir les puits", "hide"), ("n'affiche pas Top Hugin", "hide"), ("don't show the wells", "hide"),
    ("do not show Draupne fine", "hide"), ("ne surligne pas l'huile", "clear_highlight")])
def test_seeing_or_lighting_said_not_is_its_contrary(typed, intent):
    assert parse(typed, VOLVE if "huile" in typed else DEV_OBJECTS)["intent"] == intent


@pytest.mark.parametrize("typed, intent", [
    ("why don't you hide the wells", "hide"), ("why not show the porosity?", "show"),
    ("pourquoi ne pas filtrer la porosité au-dessus de 0.2 ?", "threshold"),
    ("pourquoi tu ne masques pas les puits ?", "hide"), ("pourquoi la porosité est si basse ?", "ask"),
    ("why is the grid empty?", "complain")])
def test_a_request_said_as_a_question_is_the_request(typed, intent):
    assert parse(typed, DEV_OBJECTS)["intent"] == intent
    assert len(multi.split("masque la grille et pourquoi pas les puits")) == 1


@pytest.mark.parametrize("typed", ["merci", "vas-y", "c'est bon", "stop", "tell me a joke", "raconte moi une blague",
                                   "what's the weather like"])
def test_thanks_a_go_ahead_or_small_talk_give_no_command(typed):
    assert parse(typed, DEV_OBJECTS)["intent"] is None


@pytest.mark.parametrize("typed", ["show them on the grid", "highlight them in the grid", "montre-les sur la grille",
                                   "affiche leurs mailles dans la grille"])
def test_the_wells_of_the_last_command_shown_on_the_grid_are_their_cells(typed):
    got = parse(typed, VOLVE, context=_OIL_WELLS_CTX)
    assert got["intent"] == "well_cells" and got["slots"]["category"] == "oil"


@pytest.mark.parametrize("typed, intent", [
    ("je voudrais que l'huile ressorte en rouge", "highlight"), ("fais ressortir que l'eau", "highlight"),
    ("j'aimerais que le gaz ressorte", "highlight"), ("montre moi que l'huile", "threshold"),
    ("je ne veux que l'huile", "threshold"), ("rien que le gaz", "threshold")])
def test_que_restricts_only_where_it_keeps_a_value_alone(typed, intent):
    got = parse(typed, VOLVE)
    assert got["intent"] == intent and got["sure"] and "choose_between" not in got


@pytest.mark.parametrize("typed, category, extra", [
    ("garde tout sauf le gaz", "gas", {"exclude": True}), ("montre tout sauf l'eau", "water", {"exclude": True}),
    ("surligne tout sauf l'eau", "oil", {"categories": ["oil", "gas"]})])
def test_everything_but_a_value_is_every_other_value(typed, category, extra):
    got = parse(typed, VOLVE)
    assert got["sure"] and got["slots"]["category"] == category
    for k, v in extra.items():
        assert got["slots"][k] == v


@pytest.mark.parametrize("typed, objects, spared", [
    ("hide the wells other than F-12", _VOLVE_J, "well_feature_NO_15_9-F-12_DC912C"),
    ("cache tous les puits sauf A-1", _DROGON, "55/33-A-1"), ("cache tous les puits sauf F-4", OBJECTS, "15/9-F-4"),
    ("cache les puits sauf F-12", DEV_OBJECTS, "15/9-F-12"), ("hide every well but F-11 A", OBJECTS, "15/9-F-11 A"),
    ("hide all wells but F-4", OBJECTS, "15/9-F-4"), ("masque tous les puits à part F-4", DEV_OBJECTS, "15/9-F-4"),
    ("hide wells except OP6", _DROGON, "OP6"), ("hide the wells but not F-4", DEV_OBJECTS, "15/9-F-4"),
    ("cache les puits mais pas F-4", DEV_OBJECTS, "15/9-F-4"), ("cache les puits, pas F-4", DEV_OBJECTS, "15/9-F-4")])
def test_hiding_all_the_wells_but_one_hides_the_other_wells(typed, objects, spared):
    """The group said, but the well named: the other wells are hidden —
    never an isolation, which would hide the grid and the surfaces too."""
    from fespp_on_trame.ia.nlu import engine
    got = parse(typed, objects)
    wells = {o["title"] for o in objects if engine.in_group("well", o) and not o.get("parent")}
    assert got["intent"] == "hide" and got["sure"], got
    assert {t["title"] for t in got["targets"]} == wells - {spared}


@pytest.mark.parametrize("typed, intent", [("show all wells except F-4", "show"),
                                           ("n'affiche que les puits sauf F-4", "isolate"),
                                           ("isole les puits sauf F-4", "isolate")])
def test_showing_or_isolating_all_the_wells_but_one_is_about_the_other_wells(typed, intent):
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == intent and got["sure"]
    assert sorted(t["title"] for t in got["targets"]) == ["15/9-F-11 A", "15/9-F-12"]


def test_the_others_of_a_kind_with_nothing_lit_before_is_a_question():
    """"masque les autres fluides" with no value lit before: which value to
    keep is not said — the assistant asks, it isolates nothing."""
    got = parse("masque les autres fluides", VOLVE)
    assert not got["sure"] and got["intent"] != "isolate"


def test_hiding_the_other_wells_spares_the_wells_of_the_last_command():
    ctx = {"intent": "show", "category": None, "kind": None, "targets": ["/w/f4"]}
    got = parse("cache tous les autres puits", DEV_OBJECTS, context=ctx)
    assert got["intent"] == "hide" and got["sure"]
    assert sorted(t["title"] for t in got["targets"]) == ["15/9-F-11 A", "15/9-F-12"]


@pytest.mark.parametrize("typed, titles", [
    ("cache tout sauf Hugin", ["Hugin"]), ("hide everything but Hugin", ["Hugin"]),
    ("show nothing but Hugin", ["Hugin"]), ("i want to see just the Hugin grid, hide the rest", ["Hugin"]),
    ("show the wells and Hugin, hide the rest", ["15/9-F-11 A", "15/9-F-12", "15/9-F-4", "Hugin"])])
def test_hiding_everything_but_what_is_named_is_isolating_it(typed, titles):
    """No group between the hiding verb and what is spared ("the Hugin
    grid" names Hugin, "the wells" are said before "hide"): everything
    else goes."""
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "isolate" and sorted(t["title"] for t in got["targets"]) == titles


@pytest.mark.parametrize("typed", ["calcule une nouvelle propriété", "calcule une propriété à partir de la porosité",
                                   "crée une nouvelle propriété"])
def test_the_calculator_is_asked_in_the_imperative_too(typed):
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "open_panel" and got["slots"]["panel"] == "calculator"


# ------------------------------------------------------------------ several requests: pronouns, ellipses, the rest
@pytest.mark.parametrize("typed, parts", [
    ("masque-les puis la grille", ["masque les", "masque la grille"]),
    ("affiche-les puis la porosité", ["affiche les", "affiche la porosite"]),
    ("les puis qui traversent la zone d'huile", ["les puits qui traversent la zone d huile"]),
    ("enlève le filtre et les puits", ["enleve le filtre", "enleve les puits"]),
    ("cache les failles et les horizons", ["cache les failles", "cache les horizons"]),
    ("colore la porosité en viridis et la perméabilité en jet",
     ["colore la porosite en viridis", "colore la permeabilite en jet"]),
    ("montre Hugin et le puits 7", ["montre hugin et le puits 7"]),
    ("hide the cells below 0.1 and keep the others", ["hide the cells below 0.1 and keep the others"])])
def test_a_pronoun_is_no_well_and_a_verb_said_once_acts_on_each_thing(typed, parts):
    """"-les puis" is a pronoun and "then"; the verb said once for a gesture
    and a sort of object, two sorts, two kinds with their own colour table,
    acts on each; what is said of the rest is no request of its own."""
    assert multi.split(typed) == parts


def test_the_generator_repeats_no_sentence_of_the_journal_nor_a_pinned_one():
    """nlu_journal measures the engine on real sentences and the pinned
    sets on sentences once read wrong: the generator never draws one of
    them for the questions it teaches."""
    said = {normalize(r["text"]) for name in ("nlu_journal.jsonl", "nlu_regress_fr.jsonl", "nlu_regress_en.jsonl")
            for r in evaluation.rows(name)}
    drawn = {normalize(s) for s, intent in generate.sentences(400, seed=7) if intent == "ask"}
    assert not drawn & said


# ------------------------------------------------------------------ bounds: a place, a limit's side, the layers
@pytest.mark.parametrize("typed, lo, hi", [
    ("filtre la porosité à 0,2 au top du réservoir", 0.2, None),
    ("highlight NTG 0.5 near the top of the model", 0.5, None),
    ("règle la limite inférieure de la légende à 10", 10, None),
    ("palette avec une limite basse de 0,05", 0.05, None),
    ("set the lower limit of the porosity colour scale to 0.02", 0.02, None),
    ("filter permeability with a lower limit of 50", 50, None),
    ("fixe la limite haute de la légende à 0,3", None, 0.3),
    ("set the upper limit of the colour scale to 0.4", None, 0.4), ("limit the legend to 0.3", None, 0.3),
    ("limite la palette à 250", None, 250), ("le top de la palette à 0,3", None, 0.3),
    ("set the bottom of the colour scale to 0.1", 0.1, None)])
def test_a_place_or_the_side_of_a_limit_decides_the_bound(typed, lo, hi):
    """"top" is a place ("au top du réservoir"), a ceiling only as the top
    of the colour scale; a limit is the side it is said of ("la limite
    basse", "the upper limit"), and a cap where it is the request's verb
    ("limit the legend to 0.3")."""
    s = parse(typed, DEV_OBJECTS)["slots"]
    assert (s["min"], s["max"]) == (pytest.approx(lo) if lo is not None else None,
                                    pytest.approx(hi) if hi is not None else None)


def test_the_side_of_the_colour_scale_and_its_number_set_the_colour_range_at_once():
    """"le minimum de … la porosité" asks a statistic — not with the scale
    said and its number given."""
    got = parse("le minimum de l'échelle vaut 0,05 pour la porosité", DEV_OBJECTS)
    assert got["intent"] == "color_range" and got["sure"] and got["slots"]["min"] == pytest.approx(0.05)
    assert parse("quel est le minimum de la porosité ?", DEV_OBJECTS)["intent"] == "value"


@pytest.mark.parametrize("typed, lo, hi", [
    ("show layer 12 counting from the top", 12, 12), ("coupe la couche 8 en partant du top", 8, 8),
    ("montre la couche 3 sous Top Hugin", 3, 3), ("slice k 5 just below Top Hugin", 5, 5),
    ("show the top 5 layers of the porosity", 1, 5), ("les 8 premières couches de la porosité", 1, 8),
    ("coupe la grille 10-20 en k", 10, 20), ("slice the grid 5-15 along k", 5, 15)])
def test_a_layer_counted_from_the_top_is_that_layer_and_a_grid_s_numbers_are_its_layers(typed, lo, hi):
    """The first layers only where "top" or "premières" touches the number;
    numbers joined after "la grille" are a range of layers (after a well,
    "le puits 11-15", a name)."""
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "slice" and (got["slots"]["min"], got["slots"]["max"]) == (lo, hi)


# ------------------------------------------------------------------ switches: negations without "ne", participles
@pytest.mark.parametrize("typed, on", [
    ("cache pas les NaN, je veux les voir", False), ("masque pas les valeurs manquantes, je veux les voir", False),
    ("je veux voir les NaN, pas les cacher", False), ("the NaN, I don't want them hidden anymore", False),
    ("montre à nouveau les NaN, je ne veux plus qu'ils soient masqués", False),
    ("NaN cells shouldn't be hidden anymore", False), ("pas question de les cacher, je veux voir les NaN", False),
    ("ne cache pas les NaN, je veux les voir", False), ("masque plus les NaN", False),
    ("les NaN ne doivent plus être cachés", False), ("masque les NaN, je ne veux plus les voir", True),
    ("cache les NaN, pas la grille", True), ("rends les NaN invisibles, pas la grille", True),
    ("les NaN doivent rester cachés", True)])
def test_a_hiding_said_not_without_ne_or_as_a_participle_shows_the_missing_values(typed, on):
    """"cache pas", "pas les cacher", "don't want them hidden", "qu'ils
    soient masqués" after a wish said not: the hiding is said not; a seeing
    verb said as such wins over a hiding said with "pas" — not the "pas" of
    a contrast ("…, pas la grille")."""
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "hide_nan" and got["slots"]["on"] is on and got["sure"]


def test_a_switch_is_about_no_object():
    got = parse("cache les NaN mais je veux encore voir la grille", DEV_OBJECTS)
    assert got["intent"] == "hide_nan" and got["slots"]["on"] is True and got["sure"] and not got["missing"]


@pytest.mark.parametrize("typed, on", [
    ("désactive les couleurs plates, je veux l'ombrage", False), ("couleurs plates, je ne veux pas d'ombrage", True),
    ("I don't want flat colours anymore", False), ("pas de couleurs plates", False),
    ("je veux l'ombrage, pas les couleurs plates", False), ("mets les couleurs plates, pas l'ombrage", True),
    ("je ne veux plus d'ombrage", True), ("mets plus d'ombrage", False)])
def test_the_exact_colours_said_off_win_over_the_lighting_and_a_negation_is_read(typed, on):
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "flat_colors" and got["slots"]["on"] is on


@pytest.mark.parametrize("typed, preset", [
    ("je ne veux pas voir la porosité en jet, mets-la en viridis", "Viridis (matplotlib)"),
    ("don't show the permeability in grey, use jet instead", "Jet")])
def test_a_palette_said_not_is_set_aside_for_the_other(typed, preset):
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "colormap" and got["slots"]["preset"] == preset


@pytest.mark.parametrize("typed, sure", [("pas en jet", False), ("pourquoi pas en jet ?", True),
                                         ("mets la porosité en jet", True)])
def test_a_palette_said_not_alone_is_a_question(typed, sure):
    """"pas en jet" sets no palette — the "pas" of "pourquoi pas en jet ?"
    suggests it."""
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "colormap" and got["slots"]["preset"] == "Jet" and got["sure"] is sure


# ------------------------------------------------------------------ suggestions, the calculator, complaints
@pytest.mark.parametrize("typed, intent, key, value", [
    ("pourquoi pas la palette jet ?", "colormap", "preset", "Jet"),
    ("why not the viridis colour map?", "colormap", "preset", "Viridis (matplotlib)"),
    ("pourquoi pas en viridis ?", "colormap", "preset", "Viridis (matplotlib)"),
    ("why not a slice along i?", "slice", "axis", "i"), ("pourquoi pas une coupe en j à 15 ?", "slice", "axis", "j"),
    ("why not a vertical exaggeration of 3?", "z_scale", "factor", 3),
    ("pourquoi pas les statistiques de la porosité ?", "open_panel", "panel", "stats"),
    ("why not the porosity of Hugin?", "show", "kind", "porosity")])
def test_a_thing_suggested_after_why_not_is_the_request(typed, intent, key, value):
    got = parse(typed, OBJECTS)
    assert got["intent"] == intent and got["slots"][key] == value, got


def test_why_no_wells_is_no_suggestion():
    assert parse("pourquoi pas de puits ?", DEV_OBJECTS)["intent"] in ("ask", "complain")


@pytest.mark.parametrize("typed", [
    "calcule PHIT * NTG", "calcule NTG*PHIT", "calcule PHIT fois NTG", "calcule le volume de pores PHIT x NTG",
    "compute PHIT times NTG", "calcule une porosité effective à partir de PHIT et du NTG",
    "calculer le produit de la porosité et du NTG", "la calculette", "create a new property from porosity and NTG",
    "build a new property", "derive a new property: NTG times porosity", "make a property from PHIT and SW"])
def test_a_property_computed_from_others_opens_the_calculator(typed):
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == "open_panel" and got["slots"]["panel"] == "calculator", got


@pytest.mark.parametrize("typed, intent, panel", [
    ("calcule la moyenne de la porosité et du NTG", "value", None),
    ("compute the statistics of porosity and NTG", "open_panel", "stats")])
def test_a_statistic_computed_is_no_new_property(typed, intent, panel):
    got = parse(typed, DEV_OBJECTS)
    assert got["intent"] == intent and got["slots"]["panel"] == panel


@pytest.mark.parametrize("typed", ["show me what I asked for", "montre-moi ce que je t'ai demandé"])
def test_an_order_to_do_what_was_asked_is_a_complaint(typed):
    """It names no command: the previous answer missed (the classifier
    hesitates there between a complaint, a list and help)."""
    assert parse(typed, OBJECTS)["intent"] == "complain"


@pytest.mark.parametrize("typed, sure", [
    ("c'est faux, garde la porosité au-dessus de 0,2", True), ("wrong, filter porosity above 0.25 instead", True),
    ("erreur : seuil de perméabilité à 50", True), ("that's wrong, set the colour range to 0 - 0.3", True),
    ("c'est faux, la porosité est encore au-dessus de 0,3", False),
    ("la porosité affichée dépasse 0.3, c'est une erreur", False)])
def test_a_complaint_that_goes_on_with_its_own_order_is_carried_out(typed, sure):
    """A complaint that states a bound asks — unless it gives its order
    right after ("c'est faux, garde…")."""
    assert parse(typed, DEV_OBJECTS)["sure"] is sure


# ------------------------------------------------------------------ values, names, things said together
@pytest.mark.parametrize("typed, objects, ctx, category, title", [
    ("et masque les autres lithologies", VOLVE, {"intent": "highlight", "category": "sandstone", "kind": None,
                                                 "targets": [_VOLVE_G + "/_l"]}, "sandstone", "Lithology1"),
    ("hide the other lithologies", VOLVE, {"intent": "highlight", "category": "shale", "kind": None,
                                           "targets": [_VOLVE_G + "/_l"]}, "shale", "Lithology1"),
    ("cache les autres fluides", VOLVE, {"intent": "highlight", "category": "oil", "kind": None,
                                         "targets": [_VOLVE_G + "/_f"]}, "oil", "Fluids"),
    ("masque les autres faciès", _DROGON, {"intent": "highlight", "category": "channel", "kind": None,
                                           "targets": ["/data/_g/Facies"]}, "channel", "Facies")])
def test_hiding_the_others_of_the_lit_property_keeps_its_value(typed, objects, ctx, category, title):
    """The kind said is the lit property's own: its other values go, the
    filter keeps the value — never an isolation of the property."""
    got = parse(typed, objects, context=ctx)
    assert got["intent"] == "threshold" and got["sure"] and got["slots"]["category"] == category
    assert not got["slots"].get("exclude") and [t["title"] for t in got["targets"]] == [title]


@pytest.mark.parametrize("typed, category", [("ne surligne que l'huile", "oil"),
                                             ("ne mets en évidence que le gaz", "gas")])
def test_lighting_a_value_alone_is_a_highlight_not_a_filter(typed, category):
    got = parse(typed, VOLVE)
    assert got["intent"] == "highlight" and got["slots"]["category"] == category and "choose_between" not in got


def test_a_word_of_lighting_said_of_a_value_lights_it_at_once():
    got = parse("il faudrait que l'huile ressorte", VOLVE)
    assert got["intent"] == "highlight" and got["slots"]["category"] == "oil" and got["sure"]


@pytest.mark.parametrize("typed, objects, intent, titles", [
    ("affiche SW et SO", _LITTLE, "show", ["SO", "SW"]), ("show SO and SW", _LITTLE, "show", ["SO", "SW"]),
    ("cache SO et SW", _LITTLE, "hide", ["SO", "SW"]),
    ("montre le puits F-4 et la porosité", DEV_OBJECTS, "show", ["15/9-F-4", "PHIT", "Poro"]),
    ("montre PHIT et Hugin", DEV_OBJECTS, "show", ["Hugin", "PHIT"]),
    ("show NTG and porosity", DEV_OBJECTS, "show", ["NTG", "PHIT", "Poro"]),
    ("zoome sur 19 A", _TRAPS, "reset_camera", ["15/9-19 A"]), ("logs du 19 A", _TRAPS, "open_panel", ["15/9-19 A"])])
def test_names_said_side_by_side_or_short_are_each_found(typed, objects, intent, titles):
    """A name and a kind joined by "et" are each a target (SW read as the
    water saturation beside SO named in capitals); a number and a capital
    letter of one well's name are that well."""
    got = parse(typed, objects)
    assert got["intent"] == intent and sorted(t["title"] for t in got["targets"]) == titles


@pytest.mark.parametrize("typed, axis, layer", [("coupe où k vaut 12", "k", 12), ("slice where k equals 12", "k", 12),
                                                ("coupe à i égal à 30", "i", 30)])
def test_the_letter_before_its_value_is_the_axis(typed, axis, layer):
    got = parse(typed, OBJECTS)
    assert got["intent"] == "slice" and got["slots"]["axis"] == axis
    assert got["slots"]["min"] == got["slots"]["max"] == layer


@pytest.mark.parametrize("typed, objects, intent, titles", [
    ("isole la grille et les puits", OBJECTS, "isolate", ["15/9-F-11 A", "15/9-F-4", "Hugin"]),
    ("isole la grille Hugin et les horizons", DEV_OBJECTS, "isolate", ["Base Hugin", "Hugin", "Top Hugin"]),
    ("isolate the porosity and the wells", DEV_OBJECTS, "isolate",
     ["15/9-F-11 A", "15/9-F-12", "15/9-F-4", "PHIT", "Poro"]),
    ("isolate the wells and the horizons", DEV_OBJECTS, "isolate",
     ["15/9-F-11 A", "15/9-F-12", "15/9-F-4", "Base Hugin", "Top Hugin"]),
    ("ne montre pas que la grille, affiche aussi les puits", OBJECTS, "show", ["15/9-F-11 A", "15/9-F-4", "Hugin"]),
    ("n'affiche pas que les puits, montre aussi la grille", OBJECTS, "show", ["15/9-F-11 A", "15/9-F-4", "Hugin"])])
def test_things_isolated_together_all_stay_and_a_restriction_said_not_shows_more(typed, objects, intent, titles):
    """"isole A et B" is ONE isolation of both (the verb is not said again
    for B, which would leave B alone); "ne montre pas QUE la grille" shows
    more and isolates nothing."""
    assert len(multi.split(typed)) == 1
    got = parse(typed, objects)
    assert got["intent"] == intent and sorted(t["title"] for t in got["targets"]) == titles


def test_a_hiding_verb_on_a_kind_and_its_bound_is_a_filter_whatever_leaving_the_rest_suggests():
    got = parse("masque les mailles de porosité au-dessus de 0,3, laisse le reste", DEV_OBJECTS)
    assert got["intent"] == "threshold" and (got["slots"]["min"], got["slots"]["max"]) == (None, pytest.approx(0.3))
