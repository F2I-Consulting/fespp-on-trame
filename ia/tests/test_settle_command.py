"""settle_command: the readings that correct the model's command from the
sentence itself, and clean_command / read_command, the shape /v1/command
returns.

Pins the readings a small model gets wrong (a fluid or facies zone shown or
hidden, a negated crossing, a well filter with nothing to filter on, cells
named without a well, a complaint, a panel or a colour table read as a
nearby gesture, a zone plainly hidden), and, as much, what no reading may
touch: the exclude and the well filter the model gives, a polarity that is
not plain (left out, the application asks), and the sentences whose
reading by the model must stay untouched -- each reading is held to the
right answers of the application's corpus (the last test, when
FESPP_IA_CORPUS names its folder)."""
import glob
import json
import os

import pytest

from fespp_ia.rag import about_the_app
from fespp_ia.server import _COMMAND_EXAMPLES, canonical_category, clean_command, read_command, settle_command


CATEGORIES = ["water", "oil", "gas", "Shale", "Sandstone", "Siltstone", "Limestone"]


def cmd(**k):
    base = {"intent": None, "category": None, "kind": None, "min": None, "max": None, "objects": [],
            "well_filter": None, "question": None}
    base.update(k)
    return base


def settle(text, given):
    return settle_command(text, given, CATEGORIES)


# ------------------------------------------------------------------ zones and wells
@pytest.mark.parametrize("text, given", [
    ("cache l'huile", cmd(intent="hide", category="oil")),
    ("montre moi le gaz", cmd(intent="show", category="gas")),
    ("je veux pas voir l'eau", cmd(intent="hide", category="water")),
    ("affiche le facies huile de la grille",
     cmd(intent="show", category="oil", kind="facies", objects=["Volve_SGrid"])),
    ("cache moi l'argile", cmd(intent="hide", category="shale", kind="lithology1", objects=["Lithology1"])),
    ("masque les argiles", cmd(intent="hide", category="argiles")),          # a French word: its usual name
])
def test_a_fluid_or_facies_zone_shown_or_hidden_is_a_threshold(text, given):
    out = settle(text, given)
    assert out["intent"] == "threshold" and canonical_category(out["category"]) == canonical_category(given["category"])


@pytest.mark.parametrize("text, given", [
    # a property, even one named after a zone, or a made-up category
    ("hide porosity", cmd(intent="hide", kind="porosity")),
    ("montre la grille", cmd(intent="show", objects=["Volve_SGrid"])),
    ("peux tu me montrer la porosité de la grille", cmd(intent="show", category="porosity", kind="porosity")),
    ("poro", cmd(intent="show", category="siltstone", kind="porosity", objects=["Porosity"])),
    ("bonjour, est ce que tu pourrais m'afficher la saturation en eau sur la grille",
     cmd(intent="show", category="water", kind="water saturation", objects=["Volve_SGrid"])),
    ("hide well F-12", cmd(intent="hide", category="well_feature_NO_15_9-F-12_ABC", kind="wellbore")),
])
def test_show_or_hide_of_a_property_or_an_object_stays(text, given):
    assert settle(text, given)["intent"] == given["intent"]


@pytest.mark.parametrize("text", [
    "tu peux enlever les puits qui n'ont pas de block dans le gaz",
    "il reste des puits hors de l'huile, vire les",
    "les wellbore qui ne rentrent pas dans le grès tu les caches",
    "les puits qui passent pas par l'huile tu les enleves",
    "remove the wells that never touch the gas",
    "dont hide the ones crossing the oil, hide the others",
    "hide the wells which are not in the oil",
    "get rid of the wells that stay out of the oil",           # "out of": the wells outside go
    "remove the wells staying outside the gas cap",
    "supprime les forages qui n'atteignent jamais la zone à gaz",
    "laisse tomber les puits qui ne traversent pas l'huile",     # "laisse tomber" drops, it keeps nothing
])
def test_a_negated_crossing_keeps_the_wells_that_cross(text):
    out = settle(text, cmd(intent="well_cells", category="oil", well_filter="hide_crossing"))
    assert out["well_filter"] == "keep_crossing"


@pytest.mark.parametrize("text, category", [
    ("ne garde que les puits qui évitent le gaz", "gas"),
    ("only keep the wells that stay clear of the water", "water"),
    ("keep only the wells away from the gas", "gas"),
    ("isole les forages à l'écart de l'huile", "oil"),
    ("ne laisse que les puits loin de l'eau", "water"),
])
def test_keeping_only_some_wells_leaves_the_model_s_filter(text, category):
    """A verb that keeps only some wells does not say which: the wells kept
    may stay clear of the zone in words no list holds, and turning the
    model's hide_crossing into keep_crossing there hides the very wells the
    sentence keeps."""
    out = settle(text, cmd(intent="well_cells", category=category, well_filter="hide_crossing"))
    assert out["well_filter"] == "hide_crossing"


@pytest.mark.parametrize("text", [
    "show only the wells that don't cross the oil",
    "display only the boreholes that never reach the oil",
    "affiche seulement les puits qui ne traversent pas l'huile",
    "montre uniquement les forages qui ne touchent pas l'huile",
    "je veux voir uniquement les puits qui ne traversent pas l'huile",
    "laisse les puits qui ne traversent pas l'huile et vire le reste",
])
def test_a_verb_that_shows_or_leaves_wells_over_a_negated_crossing_keeps_them(text):
    """"show only", "affiche seulement", "laisse": verbs that keep the wells
    they name -- over a negated crossing, the wells kept are those outside
    the zone, and hide_crossing is right."""
    out = settle(text, cmd(intent="well_cells", category="oil", well_filter="hide_crossing"))
    assert out["well_filter"] == "hide_crossing"


@pytest.mark.parametrize("text", [
    "get the wells that cross the oil out of the way",
    "take the wells going through the oil out of the 3D view",
    "cache les puits qui traversent l'huile, si ce n'est pas trop demander",
])
def test_a_negation_that_is_not_about_the_crossing_turns_no_filter(text):
    """"out of the way" or "out of the 3D view" take the wells off the view,
    and "si ce n'est pas trop demander" is politeness: none says the wells
    stay outside the zone."""
    out = settle(text, cmd(intent="well_cells", category="oil", well_filter="hide_crossing"))
    assert out["well_filter"] == "hide_crossing"


@pytest.mark.parametrize("text", [
    "cache les puits qui traversent l'huile",
    "ne garde pas les puits qui traversent l'huile",
    "hide the wells crossing the gas",
    "garde la grille mais cache les puits qui traversent le gaz",   # a keeping word, and a hiding verb
])
def test_a_plain_crossing_hidden_stays_hidden(text):
    out = settle(text, cmd(intent="well_cells", category="oil", well_filter="hide_crossing"))
    assert out["well_filter"] == "hide_crossing"


def test_a_well_filter_with_nothing_to_filter_on_is_the_wells_themselves():
    out = settle("cache les puits", cmd(intent="well_cells", well_filter="hide_crossing", objects=["w1", "w2"]))
    assert out["intent"] == "hide" and out["well_filter"] is None and out["objects"] == ["w1", "w2"]
    out = settle("hide well F-12", cmd(intent="well_cells", well_filter="hide_crossing", objects=["F-12"]))
    assert out["intent"] == "hide"
    out = settle("montre les puits", cmd(intent="well_cells", well_filter="keep_crossing"))
    assert out["intent"] == "show"
    # a real well question keeps its computation
    out = settle("combien de puits touchent la zone à gaz ?", cmd(intent="well_cells", category="gas"))
    assert out["intent"] == "well_cells"
    # a crossing said otherwise than the usual verbs is still a crossing
    for text in ("où est-ce que le puits F-1 C rencontre le réservoir ? marque les cellules",
                 "les mailles forées par le F-1 C", "Highlight the grid cells along the 15/9-F-11 A wellbore.",
                 "tu pourrais me donner la liste des puits bloqués ?"):
        assert settle(text, cmd(intent="well_cells", well_filter="keep_crossing"))["intent"] == "well_cells", text


@pytest.mark.parametrize("text, wf", [
    ("planque les puits qui traversent l'huile", "hide_crossing"),
    ("zappe les forages qui coupent l'huile", "hide_crossing"),
    ("fais sauter les puits qui passent dans l'huile", "hide_crossing"),
    ("je ne veux voir aucun puits qui traverse l'huile", "hide_crossing"),
    ("montre les puits qui traversent l'huile", "keep_crossing"),
])
def test_the_model_s_well_filter_stands_without_a_verb_of_the_lexicon(text, wf):
    """A verb that removes or keeps wells is said in more words than any
    list holds ("planque", "zappe", "fais sauter"): the model's filter
    stands, and the application weighs it by its own words."""
    out = settle(text, cmd(intent="well_cells", category="oil", well_filter=wf))
    assert out["intent"] == "well_cells" and out["well_filter"] == wf


@pytest.mark.parametrize("text, wf", [
    ("affiche moi que les puits qui passent par l'huile", "keep_crossing"),
    ("j'ai toujours des puits qui coupent pas l'huile", "keep_crossing"),
    ("i still have wells that dont touch the oil zone", "keep_crossing"),
    ("masque moi les puits qui coupent la zone d'eau", "hide_crossing"),
    ("isolate the wells crossing the oil", "keep_crossing"),
])
def test_a_verb_that_removes_or_keeps_wells_keeps_the_filter(text, wf):
    out = settle(text, cmd(intent="well_cells", category="oil", well_filter=wf))
    assert out["well_filter"] == wf


@pytest.mark.parametrize("text, wf", [
    # the wordings the prompt itself teaches, in its examples and its rules
    *[(t, out["well_filter"]) for t, out in _COMMAND_EXAMPLES if out.get("well_filter")],
    ("isole les puits qui la traversent", "keep_crossing"),
    ("enlève les puits qui restent à l'écart de la zone, qui ne la touchent pas", "keep_crossing"),
    ("garde ceux qui traversent l'huile et vire tous les autres puits", "keep_crossing"),
    ("des puits sont encore hors de la zone", "keep_crossing"),
    ("isolate the wells that cross it", "keep_crossing"),
    ("remove the wells staying away from the zone, not touching it", "keep_crossing"),
    ("keep the wells through the oil and get rid of all the others", "keep_crossing"),
    ("some wells are still outside the zone", "keep_crossing"),
])
def test_the_well_filters_the_prompt_teaches_survive_the_readings(text, wf):
    out = settle(text, cmd(intent="well_cells", category="oil", well_filter=wf))
    assert out["intent"] == "well_cells" and out["well_filter"] == wf


def test_a_complaint_that_the_wells_vanished_hides_nothing():
    assert settle("les puits disparaissent quand je filtre", cmd(intent="unknown"))["intent"] == "unknown"


def test_cells_named_without_a_well_are_a_zone_or_a_value_on_the_grid():
    out = settle("the oil cells", cmd(intent="well_cells", category="oil", objects=["Volve_SGrid"]))
    assert out["intent"] == "threshold" and out["category"] == "oil"
    out = settle("light up the cells with perm over 200", cmd(intent="well_cells", kind="permeability", min=200))
    assert out["intent"] == "highlight" and out["min"] == 200
    out = settle("flag the oil cells", cmd(intent="well_cells", category="oil"))
    assert out["intent"] == "highlight"


@pytest.mark.parametrize("text", [
    # a well's name, "boreholes", "drilled": wells all the same
    "Where does 15/9-F-4 cross the gas cap?",
    "Which boreholes reach the shale interval?",
    "Mark the cells drilled by NO 15/9-F-5 where porosity exceeds 0.2.",
    "Highlight the cells that F-12 passes through in the limestone.",
    # a crossing verb with a mistyped well, or none at all
    "quels puis traversent la zone d'uile",
    "Les tuyaux, où est-ce qu'ils croisent le calcaire ? Montre les cases.",
    "i want the blocked welbores of the oil zone",
])
def test_a_well_computation_with_a_well_or_a_crossing_stays_one(text):
    out = settle(text, cmd(intent="well_cells", category="oil", kind="porosity", min=0.2))
    assert out["intent"] == "well_cells"


def test_a_value_condition_keeps_the_gesture_the_model_read():
    """A highlight said with a number keeps every cell: the verbs of
    highlighting are many ("flag", "mark", "bring out"...), and turning a
    highlight without one of a short list into a filter changed right
    answers."""
    for text in ("les mailles avec plus de 100 md de perm", "flag the cells with NTG lower than 0.3",
                 "mark cells with So greater than 0.4 on Hugin", "bring out the cells deeper than 3000 m"):
        assert settle(text, cmd(intent="highlight", kind="permeability", min=100))["intent"] == "highlight", text
    out = settle("fais ressortir la porosité supérieure à 20%", cmd(intent="highlight", kind="porosity", min=0.2))
    assert out["intent"] == "highlight"


# ------------------------------------------------------------------ the intents the model confuses
@pytest.mark.parametrize("text, category", [
    ("which cells of the gas zone go over 0.3 of porosity?", "gas"),
    ("quelles mailles d'huile passent au-dessus de 20 % de porosité ?", "oil"),
    ("garde la zone d'huile", "oil"),
])
def test_a_threshold_on_a_zone_asked_as_a_question_stays_one(text, category):
    """A question word and a verb of going ("go over", "passent") do not
    make a threshold a well computation: with no well named, turning one
    into the other changed right answers and fixed none."""
    assert settle(text, cmd(intent="threshold", category=category))["intent"] == "threshold"


@pytest.mark.parametrize("text, intent", [
    ("montre moi les blocked wellbores", "unknown"),
    ("affiche les blocks des wellbores la où la porosité est au dessus de 0,2", "show"),
    ("je veux voir les puits bloqués", "list"),
])
def test_blocked_wellbores_are_the_cells_the_wells_go_through(text, intent):
    assert settle(text, cmd(intent=intent))["intent"] == "well_cells"


@pytest.mark.parametrize("text, intent", [
    ("ça bloque, je ne peux plus rien faire", "unknown"),       # "bloque" names no well
    ("c'est bloqué ?", "ask"),
    ("show the blocks of the grid", "show"),
    # a block word beside the wells is not a blocked wellbore
    ("affiche les puits du bloc nord", "show"),
    ("show the wells of the north block", "show"),
    ("liste les puits de chaque bloc", "list"),
    ("ça bloque quand j'affiche les puits", "unknown"),
    ("la vue est bloquée sur les puits", "unknown"),
    ("the grid blocks my view of the wells", "unknown"),
    # the verb "bloque" after the wells, with its object
    ("le chargement des puits bloque l'appli", "unknown"),
    ("l'affichage des puits bloque la vue", "unknown"),
])
def test_a_block_word_without_a_well_names_no_well_cells(text, intent):
    assert settle(text, cmd(intent=intent))["intent"] == intent


def test_hiding_the_wells_read_as_nothing_hides_them():
    assert settle("hide the wells", cmd(intent="unknown"))["intent"] == "hide"
    assert settle("hide the oil", cmd(intent="unknown"))["intent"] == "unknown"      # no well named
    assert settle("cache les puits dans l'huile", cmd(intent="unknown", category="oil"))["intent"] == "unknown"


def test_bounds_for_the_colour_scale_are_a_range():
    out = settle("ne change pas la palette, juste la plage 0 a 1", cmd(intent="rescale", min=0, max=1))
    assert out["intent"] == "color_range"
    assert settle("recale les couleurs sur les valeurs", cmd(intent="rescale"))["intent"] == "rescale"


def test_a_colour_table_named_among_the_colour_gestures_is_a_colormap():
    assert settle("en noir et blanc", cmd(intent="flat_colors"))["intent"] == "colormap"
    assert settle("passe en viridis", cmd(intent="rescale"))["intent"] == "colormap"
    # with bounds it is a range; outside the colour gestures nothing moves
    assert settle("viridis de 0 a 1", cmd(intent="color_range", min=0, max=1))["intent"] == "color_range"
    assert settle("je vois que du gris", cmd(intent="show"))["intent"] != "colormap"


@pytest.mark.parametrize("text", [
    "rescale the jet colormap to fit the data",
    "ajuste la palette viridis aux valeurs affichées",
    "recale l'échelle turbo sur les données visibles",
    "adapte l'échelle de la palette jet aux données",
])
def test_a_colour_table_fitted_to_the_data_stays_a_rescale(text):
    assert settle(text, cmd(intent="rescale"))["intent"] == "rescale"


@pytest.mark.parametrize("text, intent, want", [
    ("montre-moi les stats de la porosité", "value", "open_panel"),
    ("tu peux comparer le log et la grille ?", "ask", "open_panel"),
    ("ouvre l'histogramme de la perm stp", "ask", "open_panel"),
    # a statistic, or a question on how a panel works, stays what it is
    ("donne moi la moyenne des stats de porosité", "value", "value"),
    ("comment marche le crossplot ?", "ask", "ask"),
    # a value read in a panel, with no verb that opens it
    ("how high is the porosity in the well log of F-12?", "value", "value"),
    ("donne la porosité au toit du réservoir dans le log du puits", "value", "value"),
    # a question on a panel, wherever its question word stands
    ("est-ce que tu peux me dire pourquoi l'histogramme montre deux pics ?", "ask", "ask"),
    ("can you tell me why the histogram doesn't show the median?", "ask", "ask"),
    ("peux-tu me montrer comment lire le crossplot ?", "ask", "ask"),
    ("can you show me how the histogram is computed?", "ask", "ask"),
    ("tu peux m'expliquer pourquoi le crossplot affiche des points isolés ?", "ask", "ask"),
])
def test_a_panel_asked_for_is_open_panel(text, intent, want):
    assert settle(text, cmd(intent=intent, kind="porosity"))["intent"] == want


@pytest.mark.parametrize("text, intent", [
    ("ta réponse ne me convient pas, je voulais les puits dans l'huile", "well_cells"),
    ("non c'est pas ça", "show"),
    ("that's not what i asked", "list"),
    ("je vois que du gris", "threshold"),
    ("je ne vois rien", "show"),
])
def test_a_complaint_is_complain_even_when_it_repeats_the_request(text, intent):
    assert settle(text, cmd(intent=intent, category="oil"))["intent"] == "complain"


@pytest.mark.parametrize("text, intent", [
    ("I'd like to have a look at PHIT_final on the main model if that's not too much trouble.", "show"),
    ("can i see only cells with Sg above 0.3", "threshold"),
    ("recadre moi la vue je vois plus rien", "reset_camera"),
    ("je vois plus rien, recentre la vue", "reset_camera"),
    ("non annule ça, c'est pas ça", "undo"),
    # a judgement said not praises: no complaint
    ("ta réponse n'est pas mal du tout", "unknown"),
    ("ta réponse n'était pas mauvaise, merci", "unknown"),
    ("ta réponse n'est pas fausse, mais montre aussi la perméabilité", "show"),
    ("ta réponse n'a pas de souci, passe à la porosité", "show"),
    ("your answer isn't wrong, now show the permeability", "show"),
    ("the answer is not bad, now hide the wells", "hide"),
    ("your reply isn't bad at all", "unknown"),
    # a view said fine, or a question on what it shows: no complaint
    ("je ne vois rien d'anormal, merci", "unknown"),
    ("je ne vois que l'huile, parfait", "unknown"),
    ("on ne voit que les puits qui traversent le gaz, nickel", "unknown"),
    ("I can't see anything wrong, thanks", "unknown"),
    ("I don't see anything missing", "unknown"),
    ("je vois que des puits traversent l'huile, combien y en a-t-il ?", "well_cells"),
])
def test_a_request_that_only_sounds_like_a_complaint_stays(text, intent):
    assert settle(text, cmd(intent=intent))["intent"] == intent


# ------------------------------------------------------------------ the slots the final intent reads
@pytest.mark.parametrize("text, given", [
    ("cache l'huile", cmd(intent="hide", category="oil")),
    ("dont show the water", cmd(intent="show", category="water")),
    ("je veux pas voir l'eau", cmd(intent="show", category="water")),
    ("masque les argiles", cmd(intent="threshold", category="shale")),
    ("hide the shale", cmd(intent="threshold", category="shale", kind="facies")),
    ("vire-moi l'eau de là", cmd(intent="threshold", category="water")),
    ("garde la grille et vire l'eau", cmd(intent="hide", category="water")),
    ("n'affiche plus le grès", cmd(intent="show", category="sandstone")),
    ("je ne veux pas garder l'huile", cmd(intent="hide", category="oil")),
])
def test_a_zone_plainly_hidden_is_excluded_and_the_rest_kept(text, given):
    """The model left exclude out, and a verb that hides governs the zone
    in its clause, or a verb that shows or keeps is said not as an order or
    a wish."""
    out = settle(text, given)
    assert out["intent"] == "threshold" and out["exclude"] is True


@pytest.mark.parametrize("text, category, exclude", [
    # an exception under a hiding verb: the zone excepted stays
    ("cache toutes les zones sauf l'eau", "water", False),
    ("hide all the zones except the oil", "oil", False),
    ("cache-moi tout, sauf le gaz", "gas", False),
    # a negation on another verb than the zone's
    ("je ne vois pas l'eau, affiche-la", "water", False),
    ("ne cache surtout pas le gaz", "gas", False),
    # "nothing but" or "only" said of the hiding: the zone named goes
    ("ne cache rien d'autre que l'eau", "water", True),
    ("ne cache pas tout, juste le gaz", "gas", True),
    ("planque seulement le gaz", "gas", True),
])
def test_the_exclude_the_model_gives_stands(text, category, exclude):
    """A word pattern reads "sauf", "pas" or "seulement" without the clause
    they hold in: the model's own exclude is never overridden."""
    out = settle(text, cmd(intent="threshold", category=category, exclude=exclude))
    assert out["intent"] == "threshold" and out["exclude"] is exclude


@pytest.mark.parametrize("text, given", [
    # a hiding verb said done, or negated in so many words
    ("tu as caché l'huile, remets-la", cmd(intent="threshold", category="oil")),
    ("il ne faut pas cacher l'eau", cmd(intent="threshold", category="water")),
    ("évite de masquer l'eau", cmd(intent="show", category="water")),
    ("I don't want you to hide the gas", cmd(intent="threshold", category="gas")),
    ("make sure not to hide the oil", cmd(intent="show", category="oil")),
    # what the view does, not an order; a going not to be seen; the zone
    # said to stay
    ("the view doesn't show the oil, fix it", cmd(intent="show", category="oil")),
    ("je ne veux pas voir l'eau disparaître", cmd(intent="show", category="water")),
    ("remove the gas and the oil stays", cmd(intent="threshold", category="oil")),
    # an exception, a restriction, the rest
    ("cache toutes les zones sauf l'eau", cmd(intent="threshold", category="water")),
    ("masque tout à part l'huile", cmd(intent="threshold", category="oil")),
    ("planque seulement le gaz", cmd(intent="hide", category="gas")),
    ("show everything except the water", cmd(intent="threshold", category="water")),
    ("surligne l'argile et masque le reste", cmd(intent="threshold", category="shale")),
    ("ne garde que le calcaire", cmd(intent="threshold", category="limestone")),
    # no verb that hides: a zone shown or kept is no exclude the service sets
    ("montre moi le gaz", cmd(intent="show", category="gas")),
    ("vire tout ce qui n'est pas du grès", cmd(intent="threshold", category="sandstone")),
    ("hide everything but the oil", cmd(intent="threshold", category="oil")),
    ("keep the sand only, drop the rest", cmd(intent="threshold", category="sandstone")),
])
def test_a_polarity_that_is_not_plain_is_left_to_the_reader(text, given):
    """Where the model left exclude out and no verb plainly hides the zone,
    the service sets none: the application asks whether to hide the zone or
    keep it alone, rather than act on a guess."""
    out = settle(text, given)
    assert out["intent"] == "threshold" and out.get("exclude") is None


def test_exclude_is_left_to_the_model_when_the_sentence_says_neither():
    assert settle("filtre sur l'huile", cmd(intent="threshold", category="oil")).get("exclude") is None
    assert settle("le gaz, pas l'eau", cmd(intent="threshold", category="water", exclude=True))["exclude"] is True
    # a threshold on a value has no zone to exclude
    assert settle("cache la poro sous 0.1", cmd(intent="threshold", kind="porosity", max=0.1)).get("exclude") is None


def test_a_category_that_is_a_word_of_the_kind_is_the_property_not_a_zone():
    out = settle("garde les mailles dont la saturation en eau est inferieure à 30 %",
                 cmd(intent="threshold", category="water", kind="water saturation", max=0.3))
    assert out["category"] is None and out["kind"] == "water saturation"
    # a kind the model made of the zone itself keeps the zone
    out = settle("wells crossing oil zone", cmd(intent="well_cells", category="oil", kind="oil"))
    assert out["category"] == "oil"


def test_the_model_s_answer_is_kept_when_no_reading_applies():
    given = cmd(intent="open_panel", kind="porosity")
    assert settle("ouvre l'histogramme de la porosité", given) == given
    assert settle("", cmd(intent="unknown"))["intent"] == "unknown"


# ------------------------------------------------------------------ the shape returned
NAMES = ["show", "hide", "threshold", "well_cells", "open_panel", "colormap", "slice", "value"]
VOCAB = {"kinds": ["porosity", "water saturation"], "panels": ["stats", "welllog"],
         "presets": ["Viridis (matplotlib)", "Grayscale"]}


def test_clean_command_gives_every_key_and_only_known_names():
    out = clean_command({"intent": "dance", "kind": "Water_Saturation"}, NAMES)
    assert out["intent"] == "unknown" and out["kind"] == "water saturation"
    assert set(out) == {"intent", "kind", "category", "exclude", "min", "max", "objects", "well_filter", "panel",
                        "preset", "axis", "factor", "on", "question"}
    assert out["objects"] == [] and out["exclude"] is None and out["question"] is None
    out = clean_command({"intent": "colormap", "kind": "wellbore", "preset": "grayscale", "panel": "histogram",
                         "axis": "K", "factor": True, "on": "yes", "min": "0.2", "question": "why?"}, NAMES, VOCAB)
    assert (out["kind"], out["preset"], out["panel"]) == (None, "Grayscale", None)
    assert (out["axis"], out["factor"], out["on"], out["min"], out["question"]) == ("k", None, None, None, None)
    assert clean_command({"intent": "ask", "question": "c'est quoi un pilier ?"}, NAMES)["question"] == \
        "c'est quoi un pilier ?"


def test_clean_command_reads_the_category_as_its_usual_name_and_within_the_session():
    out = clean_command({"intent": "threshold", "category": "Huile"}, NAMES, None, ["Huile", "Eau"])
    assert out["category"] == "oil"
    assert clean_command({"intent": "threshold", "category": "argiles"}, NAMES)["category"] == "shale"
    assert clean_command({"intent": "threshold", "category": "porosity"}, NAMES, None, CATEGORIES)["category"] is None
    assert clean_command({"intent": "threshold", "category": "Reservoir Sand"}, NAMES, None,
                         ["Reservoir Sand"])["category"] == "reservoir sand"
    assert canonical_category("") is None and canonical_category("Gaz") == "gas"


def test_read_command_settles_then_drops_what_the_new_intent_does_not_read():
    out = read_command("tu peux comparer le log et la grille ?",
                       {"intent": "ask", "question": "Comment comparer les logs ?"}, NAMES, VOCAB, CATEGORIES)
    assert out["intent"] == "open_panel" and out["question"] is None
    out = read_command("cache l'huile", {"intent": "hide", "category": "oil"}, NAMES, VOCAB, CATEGORIES)
    assert (out["intent"], out["category"], out["exclude"]) == ("threshold", "oil", True)
    # a settled intent the caller does not offer: the model's own reading stays
    out = read_command("ta réponse ne me convient pas", {"intent": "show"}, NAMES, None, CATEGORIES)
    assert out["intent"] == "show"


# ------------------------------------------------------------------ the corpus
CORPUS = os.environ.get("FESPP_IA_CORPUS", "")


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="FESPP_IA_CORPUS does not name the corpus folder")
@pytest.mark.parametrize("extra", [{}, {"well_filter": "hide_crossing"}, {"well_filter": "keep_crossing"},
                                   {"exclude": True}, {"exclude": False}])
def test_no_reading_turns_a_right_answer_of_the_corpus_into_a_wrong_one(extra):
    """Every labelled sentence of the application's corpus (the files of the
    test sentences, *-po, left out), given as the model's exact answer:
    no reading may change its intent or drop its category. The corpus
    labels neither a well filter nor an exclude, so each well computation
    is also given with either filter, and each threshold on a zone with
    either exclude -- the readings of those slots must not spoil the rest of
    a right answer, never add a well filter, never drop or change the one
    given save a negated crossing turned to keep_crossing, and never change
    an exclude given. Run with the folder mounted: -v
    <repo>/fespp_on_trame/ia/nlu/data:/corpus:ro -e FESPP_IA_CORPUS=/corpus."""
    rows = []
    for path in sorted(glob.glob(os.path.join(CORPUS, "corpus_*.jsonl"))):
        if not path.endswith("-po.jsonl"):
            rows += [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    assert len(rows) > 1000
    if "well_filter" in extra:
        rows = [r for r in rows if r["intent"] == "well_cells"]
    elif "exclude" in extra:
        rows = [r for r in rows if r["intent"] == "threshold" and r.get("category")]
    assert len(rows) > 100
    spoiled = []
    for r in rows:
        given = cmd(intent=r["intent"], category=canonical_category(r.get("category")), kind=r.get("kind"),
                    min=r.get("min"), max=r.get("max"), **extra)
        out = settle_command(r["text"], dict(given), CATEGORIES + ["coal"])
        well_filter = (given["well_filter"], out.get("well_filter"))
        if out["intent"] != r["intent"] or (given["category"] and not out.get("category")) \
                or (out.get("well_filter") and not given["well_filter"]) \
                or (given["well_filter"] and well_filter[1] != well_filter[0]
                    and well_filter != ("hide_crossing", "keep_crossing")) \
                or ("exclude" in extra and out.get("exclude") is not extra["exclude"]):
            spoiled.append(f"{r['intent']} -> {out['intent']} ({out.get('category')}, {out.get('well_filter')}, "
                           f"{out.get('exclude')}): {r['text']}")
    assert not spoiled, "\n".join(spoiled)


def test_the_service_holds_in_the_project_s_line_length():
    """server.py within the 120 characters of the project's flake8 (setup.cfg)."""
    import fespp_ia.server
    with open(fespp_ia.server.__file__, encoding="utf-8") as f:
        long_lines = [i for i, line in enumerate(f, 1) if len(line.rstrip("\r\n")) > 120]
    assert not long_lines


def test_a_question_about_the_application_is_recognised():
    assert about_the_app("what does the Volumetrics tool compute?")
    assert about_the_app("comment fonctionne un seuil dans fespp_on_trame ?")
    assert about_the_app("où est le panneau des statistiques ?")
    assert not about_the_app("qu'est-ce que la diagenèse ?")
    assert not about_the_app("What is a turbidite reservoir?")
