"""The readings of settle_command held to sentences written apart from the
application's corpus and from the bench: each paraphrase is labelled with
its right command (intent, and category, well_filter and exclude where the
sentence states them), followed by the wrong answers a model gives on it
that a reading fixes.

Given the right answer, the readings keep it right: a reading that fires on
a sentence it was not written for turns a right answer into a wrong one (a
zone the sentence keeps hidden, a definition question run as a computation,
an order read as a complaint). Given a wrong answer, the reading written
for that mistake still fixes it. The set holds near misses on purpose -- a
negated verb, a verb that falls on another object, a question on what a
thing is -- since a rule is only as good as the sentences it leaves alone.

The wrong answers no reading fixes are kept apart, for what the service
does with them: a zone whose polarity is not plain comes back without an
exclude (ASKED: the application asks), and an exclude or a well filter the
model gives -- or an intent no narrow reading covers -- comes back as given
(STANDS). The set was written along with the readings: it pins them, it
does not measure their precision. When FESPP_IA_CORPUS names the corpus
folder, the set is checked to share no sentence with it (the bench
sentences are its -po files)."""
import glob
import json
import os

import pytest

from fespp_ia.rag import _fold
from fespp_ia.server import canonical_category, read_command

# the application's catalogue and the bench session's zones
NAMES = ["show", "hide", "isolate", "threshold", "clear_threshold", "highlight", "clear_highlight", "well_cells",
         "slice", "hide_nan", "colormap", "color_range", "rescale", "flat_colors", "reset_camera", "z_scale",
         "new_view", "open_panel", "describe", "list", "value", "undo", "save_session", "complain", "help"]
CATEGORIES = ["water", "oil", "gas", "Shale", "Sandstone", "Siltstone", "Limestone"]

TH, WC = "threshold", "well_cells"
KEEP, HIDE = "keep_crossing", "hide_crossing"

PARAPHRASES = [
    # (sentence, the right command, *the wrong commands a reading fixes)
    # ---- a zone kept or hidden: exclude
    ("I don't want to see anything but the oil", {"intent": TH, "category": "oil", "exclude": False}),
    ("don't show anything except the gas", {"intent": TH, "category": "gas", "exclude": False}),
    ("je ne veux plus voir que l'huile", {"intent": TH, "category": "oil", "exclude": False}),
    ("je veux pas voir autre chose que le grès", {"intent": TH, "category": "sandstone", "exclude": False}),
    ("affiche la grille sans l'eau", {"intent": TH, "category": "water", "exclude": True},
     {"intent": "show", "category": "water", "exclude": True}),
    ("cache les puits et ne montre que l'huile", {"intent": TH, "category": "oil", "exclude": False}),
    ("remove the filter and show only the gas", {"intent": TH, "category": "gas", "exclude": False}),
    ("efface le seuil puis garde seulement le grès", {"intent": TH, "category": "sandstone", "exclude": False}),
    ("garde l'huile et enlève l'eau", {"intent": TH, "category": "oil", "exclude": False}),
    ("ne cache pas l'huile", {"intent": TH, "category": "oil", "exclude": False}),
    ("don't hide the gas", {"intent": TH, "category": "gas", "exclude": False}),
    ("arrête de masquer l'eau", {"intent": TH, "category": "water", "exclude": False}),
    ("stop hiding the oil zone", {"intent": TH, "category": "oil", "exclude": False}),
    ("n'enlève pas le calcaire", {"intent": TH, "category": "limestone", "exclude": False}),
    ("fais-moi disparaître la zone à eau", {"intent": TH, "category": "water", "exclude": True},
     {"intent": "hide", "category": "water"}),
    ("planque le gaz", {"intent": TH, "category": "gas", "exclude": True}),
    ("hide only the gas", {"intent": TH, "category": "gas", "exclude": True}),
    ("cache seulement l'eau", {"intent": TH, "category": "water", "exclude": True}),
    ("masque tout sauf le calcaire", {"intent": TH, "category": "limestone", "exclude": False}),
    ("show everything but the shale", {"intent": TH, "category": "shale", "exclude": True}),
    ("montre la grille sans le gaz", {"intent": TH, "category": "gas", "exclude": True}),
    ("je ne veux voir que le siltstone", {"intent": TH, "category": "siltstone", "exclude": False}),
    ("rien d'autre que l'huile, merci", {"intent": TH, "category": "oil", "exclude": False}),
    ("I only want to see the water", {"intent": TH, "category": "water", "exclude": False}),
    ("keep the limestone, remove everything else", {"intent": TH, "category": "limestone", "exclude": False}),
    ("ne garde pas l'argile", {"intent": TH, "category": "shale", "exclude": True},
     {"intent": "show", "category": "shale"}),
    ("vire-moi l'eau de là", {"intent": TH, "category": "water", "exclude": True},
     {"intent": "hide", "category": "water"}),
    ("n'affiche plus le grès", {"intent": TH, "category": "sandstone", "exclude": True},
     {"intent": "show", "category": "sandstone"}),
    ("do not display the sandstone", {"intent": TH, "category": "sandstone", "exclude": True},
     {"intent": "show", "category": "sandstone"}),
    ("show the oil and the gas but not the water", {"intent": TH, "category": "water", "exclude": True}),
    ("montre-moi la zone à eau", {"intent": TH, "category": "water", "exclude": False}),
    ("cache-moi tout le reste sauf le gaz", {"intent": TH, "category": "gas", "exclude": False}),
    # a hiding verb on another object: the verb that governs the zone tells
    ("montre l'huile et cache le gaz", {"intent": TH, "category": "oil", "exclude": False}),
    ("affiche le grès mais masque l'argile", {"intent": TH, "category": "shale", "exclude": True},
     {"intent": "hide", "category": "shale"}),
    ("garde la grille et vire l'eau", {"intent": TH, "category": "water", "exclude": True},
     {"intent": "hide", "category": "water"}),
    ("l'huile, cache-la", {"intent": TH, "category": "oil", "exclude": True}),
    ("just the sandstone, nothing else", {"intent": TH, "category": "sandstone", "exclude": False}),
    # a zone said in words the lexicon lacks, or in an adjective of its own
    ("masque les mailles schisteuses", {"intent": TH, "category": "shale", "exclude": True}),
    ("enlève les cellules argileuses", {"intent": TH, "category": "shale", "exclude": True},
     {"intent": "hide", "category": "shale"}),
    # ---- the wells crossing a zone: well_filter
    ("take the wells that cross the gas out of the view", {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("get the wells going through the oil out of my sight", {"intent": WC, "category": "oil", "well_filter": HIDE}),
    ("remove the wells crossing the oil and keep the ones outside",
     {"intent": WC, "category": "oil", "well_filter": HIDE}),
    ("ne garde que les puits qui ne touchent jamais le gaz", {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("only keep the wells that never reach the water", {"intent": WC, "category": "water", "well_filter": HIDE}),
    ("masque les puits qui traversent le gaz, je ne veux voir que ceux pas dans le gaz",
     {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("vire les forages qui ne passent pas dans l'eau", {"intent": WC, "category": "water", "well_filter": KEEP},
     {"intent": WC, "category": "water", "well_filter": HIDE}),
    ("garde seulement les trajectoires qui traversent le calcaire",
     {"intent": WC, "category": "limestone", "well_filter": KEEP}),
    ("isole les puits qui ne coupent pas le grès", {"intent": WC, "category": "sandstone", "well_filter": HIDE}),
    ("drop the boreholes that stay outside the gas", {"intent": WC, "category": "gas", "well_filter": KEEP},
     {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("cache les puits qui ne touchent pas l'huile", {"intent": WC, "category": "oil", "well_filter": KEEP},
     {"intent": WC, "category": "oil", "well_filter": HIDE}),
    ("keep the wells that don't go through the shale", {"intent": WC, "category": "shale", "well_filter": HIDE}),
    ("les puits qui ne traversent pas le gaz, garde-les", {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("hide the wells that pass through the water", {"intent": WC, "category": "water", "well_filter": HIDE}),
    ("ne laisse que les forages qui touchent le gaz", {"intent": WC, "category": "gas", "well_filter": KEEP}),
    ("est-ce que des puits traversent l'huile ?", {"intent": WC, "category": "oil"}),
    ("combien de forages recoupent le grès ?", {"intent": WC, "category": "sandstone"}),
    ("garde la grille mais vire les puits qui ne traversent pas le gaz",
     {"intent": WC, "category": "gas", "well_filter": KEEP}, {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("put the wells crossing the oil out of the picture", {"intent": WC, "category": "oil", "well_filter": HIDE}),
    ("n'affiche que les trajectoires passant dans le gaz", {"intent": WC, "category": "gas", "well_filter": KEEP}),
    ("the wells that stay out of the water, remove them", {"intent": WC, "category": "water", "well_filter": KEEP},
     {"intent": WC, "category": "water", "well_filter": HIDE}),
    # ---- the wells themselves
    ("masque-moi l'ensemble des forages", {"intent": "hide"}, {"intent": WC, "well_filter": HIDE},
     {"intent": "unknown"}),
    ("ne cache pas les puits", {"intent": "show"}, {"intent": WC, "well_filter": HIDE}),
    ("remets les forages", {"intent": "show"}, {"intent": WC, "well_filter": KEEP}),
    ("surligne les mailles traversées par les puits", {"intent": WC}),
    ("dis-moi où les puits percent le réservoir", {"intent": WC}),
    ("indique les couches recoupées par les sondages", {"intent": WC}),
    # ---- blocked wellbores, and what is not one
    ("c'est quoi un blocked wellbore ?", {"intent": "ask"}),
    ("what is a blocked wellbore?", {"intent": "ask"}),
    ("à quoi sert une blocked wellbore representation ?", {"intent": "ask"}),
    ("kesako un blocked welbore", {"intent": "ask"}),
    ("qu'est-ce qu'un puits bloqué dans RESQML ?", {"intent": "ask"}),
    ("explique moi à quoi sert une blocked wellbore representation", {"intent": "ask"}),
    ("what are blocked wellbores used for?", {"intent": "ask"}),
    ("show the fault blocks around the wells", {"intent": "show"}),
    ("montre-moi les blocs faillés autour des puits", {"intent": "show"}),
    ("affiche les blocs des puits", {"intent": WC}),
    ("list the blocked wellbores of F-12", {"intent": WC}, {"intent": "list"}),
    # ---- complaints, and what only sounds like one
    ("merci, ta réponse est parfaite ; maintenant cache les puits", {"intent": "hide"}),
    ("ta réponse est top", {"intent": "unknown"}),
    ("ta réponse nickel, merci", {"intent": "unknown"}),
    ("ta réponse est pas mal, merci", {"intent": "unknown"}),
    ("j'ai lu ta réponse, maintenant montre la porosité", {"intent": "show"}),
    ("ta réponse est complètement fausse", {"intent": "complain"}, {"intent": "show"}),
    ("ta réponse n'a rien à voir avec ce que j'ai demandé", {"intent": "complain"}),
    ("your answer is wrong, I asked for the porosity", {"intent": "complain"}, {"intent": "show"}),
    ("je vois que les puits sont encore là, enlève-les", {"intent": "hide"}),
    ("on voit que le gaz est en haut, surligne-le", {"intent": "highlight", "category": "gas"}),
    ("je vois que c'est parfait, merci !", {"intent": "unknown"}),
    ("on voit que ça marche nickel", {"intent": "unknown"}),
    ("je ne vois rien, affiche la porosité", {"intent": "show"}),
    ("je ne vois que du noir dans la vue", {"intent": "complain"}, {"intent": "colormap"}),
    ("on ne voit plus rien du tout", {"intent": "complain"}, {"intent": "show"}),
    ("je vois que de la grille grise", {"intent": "complain"}, {"intent": "show"}),
    ("I can't see anything in the view", {"intent": "complain"}),
    # ---- a panel asked for, or a question on one
    ("what does the crossplot show?", {"intent": "ask"}),
    ("que montre l'histogramme exactement ?", {"intent": "ask"}),
    ("what does the scatter show", {"intent": "ask"}),
    ("est-ce que l'histogramme montre la médiane ?", {"intent": "ask"}),
    ("à quoi sert le nuage de points ?", {"intent": "ask"}),
    ("peux-tu ouvrir le crossplot de la poro et de la perm ?", {"intent": "open_panel"}, {"intent": "ask"}),
    ("could you open the histogram of the porosity?", {"intent": "open_panel"}, {"intent": "ask"}),
    ("quelle porosité lit-on dans le log du puits F-12 vers 2600 m ?", {"intent": "value"}),
    ("what is the porosity at 2500 m in the well log of F-1?", {"intent": "value"}),
    ("donne-moi les statistiques de la perméabilité", {"intent": "open_panel"}),
    ("les stats de la saturation en eau stp", {"intent": "open_panel"}),
    # ---- the colour gestures
    ("remets l'ombrage mais garde la palette viridis", {"intent": "flat_colors"}),
    ("enlève l'ombrage, je garde le jet", {"intent": "flat_colors"}),
    ("mets la palette en niveaux de gris", {"intent": "colormap"}, {"intent": "flat_colors"}),
    ("passe tout en inferno", {"intent": "colormap"}, {"intent": "rescale"}),
    ("règle l'échelle de couleurs de 0,1 à 0,3", {"intent": "color_range"},
     {"intent": "rescale", "min": 0.1, "max": 0.3}),
    # ---- cells of a zone, with or without a well
    ("which cells of the oil zone go above 0.25 porosity?", {"intent": TH, "category": "oil"}),
    ("quelles mailles de la zone à gaz passent au-dessus de 0,3 de porosité ?", {"intent": TH, "category": "gas"}),
    ("les mailles d'huile du 25/11-15", {"intent": WC, "category": "oil"}),
    ("les cellules à eau du 16/2-6", {"intent": WC, "category": "water"}),
    ("the gas cells", {"intent": TH, "category": "gas"}, {"intent": WC, "category": "gas"}),
    ("les cases d'eau de la grille", {"intent": TH, "category": "water"}, {"intent": WC, "category": "water"}),
    # ---- each kind of reading again, in other words
    ("enlève-moi ce gaz de l'affichage", {"intent": TH, "category": "gas", "exclude": True},
     {"intent": "hide", "category": "gas"}),
    ("je ne souhaite plus voir l'eau", {"intent": TH, "category": "water", "exclude": True},
     {"intent": "show", "category": "water"}),
    ("I'd rather not see the shale", {"intent": TH, "category": "shale", "exclude": True}),
    ("can you stop showing the gas", {"intent": TH, "category": "gas", "exclude": True}),
    ("conserve uniquement l'huile", {"intent": TH, "category": "oil", "exclude": False}),
    ("plus que le calcaire à l'écran", {"intent": TH, "category": "limestone", "exclude": False}),
    ("everything except the sand please", {"intent": TH, "category": "sandstone", "exclude": True}),
    ("hide everything apart from the oil", {"intent": TH, "category": "oil", "exclude": False}),
    ("la grille sans le grès stp", {"intent": TH, "category": "sandstone", "exclude": True}),
    ("ne laisse plus que le gaz", {"intent": TH, "category": "gas", "exclude": False}),
    ("filtre pour ne garder que l'argile", {"intent": TH, "category": "shale", "exclude": False}),
    ("supprime l'eau et le gaz", {"intent": TH, "category": "water", "exclude": True},
     {"intent": "hide", "category": "water"}),
    ("affiche l'huile, enlève le reste", {"intent": TH, "category": "oil", "exclude": False}),
    ("remove the wells that do not reach the sandstone", {"intent": WC, "category": "sandstone", "well_filter": KEEP},
     {"intent": WC, "category": "sandstone", "well_filter": HIDE}),
    ("keep only the boreholes outside the oil", {"intent": WC, "category": "oil", "well_filter": HIDE}),
    ("je veux garder les puits qui ne rentrent pas dans l'eau",
     {"intent": WC, "category": "water", "well_filter": HIDE}),
    ("vire les puits en dehors du gaz", {"intent": WC, "category": "gas", "well_filter": KEEP},
     {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("hide the wells going through the limestone", {"intent": WC, "category": "limestone", "well_filter": HIDE}),
    ("quels forages ne touchent pas l'huile ?", {"intent": WC, "category": "oil"}),
    ("isolate the wells that cross the water", {"intent": WC, "category": "water", "well_filter": KEEP}),
    ("montre les blocs des forages dans l'eau", {"intent": WC}),
    ("define blocked wellbore", {"intent": "ask"}),
    ("show the faulted blocks next to the wells", {"intent": "show"}),
    ("ta réponse me va très bien", {"intent": "unknown"}),
    ("ta réponse tombe complètement à côté", {"intent": "complain"}, {"intent": "show"}),
    ("je vois que la grille est chargée, montre la porosité", {"intent": "show"}),
    ("on ne voit que du blanc", {"intent": "complain"}, {"intent": "colormap"}),
    ("lance-moi le nuage de points poro perm", {"intent": "open_panel"}, {"intent": "ask"}),
    ("que contient le panneau des stats ?", {"intent": "ask"}),
    ("tu peux me montrer l'histogramme de la porosité ?", {"intent": "open_panel"}, {"intent": "ask"}),
    ("garde la palette jet et enlève les ombres", {"intent": "flat_colors"}),
    ("passe en turbo", {"intent": "colormap"}, {"intent": "rescale"}),
    ("les mailles de grès traversées par le 34/10-A-1", {"intent": WC, "category": "sandstone"}),
    ("the shale cells", {"intent": TH, "category": "shale"}, {"intent": WC, "category": "shale"}),
    ("cache les forages", {"intent": "hide"}, {"intent": WC, "well_filter": HIDE}, {"intent": "unknown"}),
    ("n'enlève pas les puits", {"intent": "show"}, {"intent": WC, "well_filter": HIDE}),
]

# wrong answers left without an exclude: the zone's polarity is not plain
# (a negation, an exception, a restriction, the rest, no verb that hides,
# a zone said in words the lexicon lacks), and the application asks
ASKED = [
    ("don't show anything except the gas", {"intent": "hide", "category": "gas"}),
    ("je veux pas voir autre chose que le grès", {"intent": "hide", "category": "sandstone"}),
    ("affiche la grille sans l'eau", {"intent": "show", "category": "water"}),
    ("ne cache pas l'huile", {"intent": "show", "category": "oil"}),
    ("don't hide the gas", {"intent": "show", "category": "gas"}),
    ("arrête de masquer l'eau", {"intent": "show", "category": "water"}),
    ("stop hiding the oil zone", {"intent": "show", "category": "oil"}),
    ("n'enlève pas le calcaire", {"intent": "show", "category": "limestone"}),
    ("planque le gaz", {"intent": "hide", "category": "gas"}),
    ("hide only the gas", {"intent": "hide", "category": "gas"}),
    ("cache seulement l'eau", {"intent": "hide", "category": "water"}),
    ("masque tout sauf le calcaire", {"intent": "hide", "category": "limestone"}),
    ("show everything but the shale", {"intent": "show", "category": "shale"}),
    ("montre la grille sans le gaz", {"intent": "show", "category": "gas"}),
    ("je ne veux voir que le siltstone", {"intent": "hide", "category": "siltstone"}),
    ("keep the limestone, remove everything else", {"intent": "hide", "category": "limestone"}),
    ("montre-moi la zone à eau", {"intent": "show", "category": "water"}),
    ("cache-moi tout le reste sauf le gaz", {"intent": "hide", "category": "gas"}),
    ("montre l'huile et cache le gaz", {"intent": "show", "category": "oil"}),
    ("l'huile, cache-la", {"intent": "hide", "category": "oil"}),
    ("masque les mailles schisteuses", {"intent": TH, "category": "shale"}),
    ("everything except the sand please", {"intent": "show", "category": "sandstone"}),
    ("hide everything apart from the oil", {"intent": "hide", "category": "oil"}),
    ("la grille sans le grès stp", {"intent": "show", "category": "sandstone"}),
    ("affiche l'huile, enlève le reste", {"intent": "hide", "category": "oil"}),
]

# wrong answers returned as the model gave them: an exclude or a well filter
# it states (no word pattern overrides one), or an intent no narrow reading
# covers ("blocs", a judgement out of the list, a panel with no verb that
# opens it)
STANDS = [
    ("I don't want to see anything but the oil", {"intent": TH, "category": "oil", "exclude": True}),
    ("je ne veux plus voir que l'huile", {"intent": TH, "category": "oil", "exclude": True}),
    ("masque tout sauf le calcaire", {"intent": TH, "category": "limestone", "exclude": True}),
    ("je ne veux voir que le siltstone", {"intent": TH, "category": "siltstone", "exclude": True}),
    ("rien d'autre que l'huile, merci", {"intent": TH, "category": "oil", "exclude": True}),
    ("I only want to see the water", {"intent": TH, "category": "water", "exclude": True}),
    ("show the oil and the gas but not the water", {"intent": TH, "category": "water", "exclude": False}),
    ("just the sandstone, nothing else", {"intent": TH, "category": "sandstone", "exclude": True}),
    ("conserve uniquement l'huile", {"intent": TH, "category": "oil", "exclude": True}),
    ("ne laisse plus que le gaz", {"intent": TH, "category": "gas", "exclude": True}),
    ("filtre pour ne garder que l'argile", {"intent": TH, "category": "shale", "exclude": True}),
    ("garde seulement les trajectoires qui traversent le calcaire",
     {"intent": WC, "category": "limestone", "well_filter": HIDE}),
    ("ne laisse que les forages qui touchent le gaz", {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("n'affiche que les trajectoires passant dans le gaz", {"intent": WC, "category": "gas", "well_filter": HIDE}),
    ("isolate the wells that cross the water", {"intent": WC, "category": "water", "well_filter": HIDE}),
    ("est-ce que des puits traversent l'huile ?", {"intent": WC, "category": "oil", "well_filter": KEEP}),
    ("combien de forages recoupent le grès ?", {"intent": WC, "category": "sandstone", "well_filter": HIDE}),
    ("surligne les mailles traversées par les puits", {"intent": WC, "well_filter": KEEP}),
    ("dis-moi où les puits percent le réservoir", {"intent": WC, "well_filter": HIDE}),
    ("indique les couches recoupées par les sondages", {"intent": WC, "well_filter": KEEP}),
    ("affiche les blocs des puits", {"intent": "show"}),
    ("affiche les blocs des puits", {"intent": "unknown"}),
    ("montre les blocs des forages dans l'eau", {"intent": "show"}),
    ("ta réponse n'a rien à voir avec ce que j'ai demandé", {"intent": TH}),
    ("I can't see anything in the view", {"intent": "show"}),
    ("donne-moi les statistiques de la perméabilité", {"intent": "value"}),
    ("les stats de la saturation en eau stp", {"intent": "value"}),
]


def got(text, given):
    """What /v1/command returns for the model's answer `given`."""
    return read_command(text, dict(given), NAMES, None, CATEGORIES)


def holds(text, given, right):
    """Whether the command returned for `given` is the right one: its intent,
    its well filter (none when the label has none), its category when the
    label states one, and for a threshold on a zone the exclude the label
    states -- one left out is no answer: the application asks."""
    out = got(text, given)
    if out["intent"] != right["intent"] or out.get("well_filter") != right.get("well_filter"):
        return False
    if right.get("category") and canonical_category(out.get("category")) != canonical_category(right["category"]):
        return False
    if right["intent"] == TH and right.get("category") and "exclude" in right:
        return out.get("exclude") is right["exclude"]
    return True


@pytest.mark.parametrize("text, right", [(row[0], row[1]) for row in PARAPHRASES],
                         ids=[f"{i}" for i in range(len(PARAPHRASES))])
def test_a_right_answer_stays_right(text, right):
    assert holds(text, right, right), (text, got(text, right))


@pytest.mark.parametrize("text, wrong, right", [(row[0], w, row[1]) for row in PARAPHRASES for w in row[2:]],
                         ids=[f"{i}-{j}" for i, row in enumerate(PARAPHRASES) for j in range(len(row) - 2)])
def test_the_reading_written_for_a_wrong_answer_fixes_it(text, wrong, right):
    assert holds(text, wrong, right), (text, wrong, got(text, wrong))


@pytest.mark.parametrize("text, given", ASKED, ids=[f"{i}" for i in range(len(ASKED))])
def test_a_polarity_that_is_not_plain_is_asked(text, given):
    out = got(text, given)
    assert out["intent"] == TH and out["category"] == canonical_category(given["category"]) \
        and out["exclude"] is None, (text, given, out)


@pytest.mark.parametrize("text, given", STANDS, ids=[f"{i}" for i in range(len(STANDS))])
def test_what_the_model_states_stands(text, given):
    out = got(text, given)
    assert {k: out.get(k) for k in given} == {k: canonical_category(v) if k == "category" else v
                                              for k, v in given.items()}, (text, given, out)


def test_the_set_is_broad_enough_to_measure_the_readings():
    """Enough paraphrases for each reading, and wrong answers for the
    readings to fix: a set that only holds right answers would pass a
    service with no reading at all."""
    assert len(PARAPHRASES) >= 100
    assert sum(len(row) - 2 for row in PARAPHRASES) >= 40
    # the wrong answers kept apart are answers to sentences of the set
    assert {text for text, _given in ASKED + STANDS} <= {row[0] for row in PARAPHRASES}


CORPUS = os.environ.get("FESPP_IA_CORPUS", "")


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="FESPP_IA_CORPUS does not name the corpus folder")
def test_no_paraphrase_is_a_sentence_of_the_corpus_or_the_bench():
    def norm(s):
        return " ".join(_fold(s).split())
    texts = set()
    for path in glob.glob(os.path.join(CORPUS, "corpus_*.jsonl")):
        texts |= {norm(json.loads(x)["text"]) for x in open(path, encoding="utf-8") if x.strip()}
    assert len(texts) > 1000
    assert not [row[0] for row in PARAPHRASES if norm(row[0]) in texts]
