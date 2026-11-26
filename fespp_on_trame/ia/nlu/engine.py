"""``parse(text, objects)``: a sentence becomes ONE command of the catalogue.

    {"intent": "threshold", "confidence": 0.97,
     "alternatives": [("show", 0.02), …],
     "slots": {"kind": "porosity", "min": 0.2, "max": None, …},
     "targets": [{"path": …, "title": "PHIT", "why": "porosity of Hugin"}],
     "missing": [], "sure": True}

`objects` is what the session has loaded, one dict per object:
``{"path", "title", "type", "kind", "parent", "categories"}`` — `kind` the
property kind the data carries, `parent` the path of the grid or the well a
property belongs to, `categories` the code -> label table of a categorical
property. The engine only proposes: the application checks the command and
carries it out.

The classifier gives the first reading; hand-written rules in `parse` then
settle what cue words decide on their own (a crossing word next to a well
word and the grid's cells is well_cells, "stop highlighting" is
clear_highlight…). A rule never overrules a reading the classifier is sure
of without a cue that says otherwise.
"""
import os
import re

from fespp_on_trame.engine import pwls_kinds
from fespp_on_trame.ia.nlu import bilingual, catalogue, lexicon, multi, slots
from fespp_on_trame.ia.nlu.model import IntentModel
from fespp_on_trame.ia.nlu.text import normalize, tokens as _tokens

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "assets", "nlu_intents.npz")
SURE = 0.6            # below this the engine asks instead of doing
NOT_UNDERSTOOD = 0.3  # below this, with nothing recognised in the sentence, it did not understand
OUT_OF_DOMAIN = 0.45  # … and below this when no word of the trade is said either ("the apple pie recipe")
MODEL_SURE = 0.9      # the classifier is this sure of a reading: a rule needs a cue word to overrule it

# the types of a grid: a filter on a category value acts on their properties
GRID_TYPES = ("IjkGrid", "UnstructuredGrid")

# the words that refer back to what the last command was about
REFERS = ("autres", "autre", "reste", "celles", "ceux", "celle", "celui", "ces", "cette", "cela", "meme",
          "idem", "pareil", "them", "others", "other", "ones", "rest", "those", "same", "these", "this", "that",
          "this one", "that one", "leurs", "their", "que ca", "que cela")
# what may follow a pronoun right after its verb ("montre-les sur la grille",
# "surligne-les plutôt") — never a noun ("montre les puits")
_AFTER_PRONOUN = frozenset("plutot aussi encore stp svp maintenant please alors donc sur dans en a au aux avec pour "
                           "vite tout tous".split())
# what is NOT the value said: "the other zones", "every zone but the oil"
# ("but" and "à part" right before a name count too: `_exceptions`)
OTHERS = ("autres", "autre", "autre que", "autres que", "reste", "others", "other", "other than", "rest", "sauf",
          "except", "hormis", "excepte", "but the")
# the sort nouns a zone is referred to by ("this zone", "the other zones"):
# matched to a *Zone representation's title by resemblance, they name nothing
ZONE_NOUNS = ("zone", "zones")


def _refers(toks):
    """A sentence that points back: "the other zones", "the rest",
    "highlight them", "surligne-les" (a pronoun ending the sentence or
    right after its verb: "montre-les sur la grille"), "leurs mailles",
    "garde que ça"."""
    said = " " + " ".join(toks) + " "
    return (any(t in REFERS for t in toks) or _has(said, REFERS) or _pronoun_after_verb(toks)
            or (len(toks) >= 2 and toks[-1] in ("les", "la", "le", "them", "it")))


def _pronoun_after_verb(toks):
    """A "les" / "la" / "le" right after a verb and before no noun: the
    pronoun of "montre-les sur la grille", "surligne-la plutôt"."""
    return any(t in multi.VERBS and toks[i + 1] in ("les", "la", "le")
               and (i + 2 == len(toks) or toks[i + 2] in _AFTER_PRONOUN)
               for i, t in enumerate(toks[:-1]))


# the words that say which gesture a category value asks for ("que
# l'huile" keeps only the oil where it is restrictive: `_restrictive`)
FILTER_WORDS = ("filtre", "filtrer", "filtres", "seuil", "seuille", "garde", "garder", "gardes", "laisse", "laissez",
                "laisser", "uniquement", "seulement", "n affiche que", "ne montre que", "only", "keep", "filter",
                "threshold", "cutoff")
HIGHLIGHT_WORDS = ("surligne", "surligner", "surlignes", "surlignez", "surlignee", "surlignees", "surlignage",
                   "surbrillance", "evidence", "ressortir", "ressorte", "ressortent", "allume", "signale", "signaler",
                   "repere", "reperer", "pointe", "highlight",
                   "highlighted", "highlite", "hilight", "mark", "emphasize", "light up", "colore en rouge",
                   "stand out", "spotlight", "flag", "flagged", "point out", "bright colour", "bright color",
                   "en couleur", "marque", "marquer", "marquez", "marquees", "glow", "pop", "pop out", "outline",
                   "outlined", "en rouge", "in red", "briller", "brille", "en lumiere", "lit up", "light it up")
# the cells a highlight lit, said as such ("cache les mailles surlignées")
LIT_WORDS = ("surlignees", "surlignes", "surlignee", "en surbrillance", "qui est surligne", "qui sont surligne",
             "deja surligne", "mises en evidence", "mis en evidence", "highlighted", "what is lit", "lit cells")
# the verbs before a restrictive "que" ("montre-moi que l'huile", "garde que
# le gaz") — after "je voudrais", "j'aimerais" it is a wish ("…que l'huile
# ressorte")
_ONLY_VERBS = frozenset(("montre", "montrez", "affiche", "affichez", "garde", "gardez", "laisse", "laissez",
                         "filtre", "filtrez", "rien"))
# seeing said NOT: "je veux pas voir l'eau", "don't show the gas" — hiding
NOT_SEE = ("veux pas voir", "veux plus voir", "ne veux pas voir", "ne veux plus voir", "don t want to see",
           "dont want to see", "do not want to see", "want to see no", "dont show", "don t show", "do not show",
           "ne montre pas", "ne montre plus", "n affiche pas", "n affiche plus", "ne pas afficher",
           "ne plus afficher", "n affichez pas", "n affichez plus", "dont display", "don t display",
           "do not display")
# hiding said otherwise than the lexicon's verbs: "vire les", "take them
# off", "mask the wells", and seeing said not
HIDE_MORE = ("virer", "vires", "virez", "enleves", "enlevez", "caches", "cachez", "masques", "masquez", "retires",
             "retirez", "supprimes", "supprimez", "degage", "degager", "take off", "take them off", "take it off",
             "mask", "masks") + NOT_SEE
# said of wells that stay OUT of a zone: a negation for the well filter
OUT_WORDS = ("hors", "hors de", "en dehors", "out of", "outside", "stay out", "stays out", "restent hors",
             "reste hors", "not in", "are not in", "is not in", "pas dans")
# "I still have wells that do not cross the oil": those wells are to go
STILL_WORDS = ("j ai encore", "j ai toujours", "il reste", "il y a encore", "il y a toujours", "i still have",
               "there are still", "there is still", "i still see", "still see", "still have")
# a statistic asked "along the wells" is a statistic, not the cells
STAT_WORDS = ("moyenne", "moyen", "mediane", "mean", "average", "median", "minimum", "maximum", "min", "max",
              "maximale", "minimale", "ecart type", "std", "p10", "p90", "somme", "sum")
NEGATION = ("not", "don t", "dont", "do not", "doesn t", "does not", "without", "never", "jamais", "aucun",
            "aucune", "isn t", "aren t")
# "no, I wanted porosity", "i meant highlight", "I said water and gas": the
# last command, redone
CORRECTION = ("je voulais", "je voulai", "je parlais", "je parlai", "je pensais", "i wanted", "i meant", "i was",
              "i said", "not what i", "pas ce que je", "j avais dit", "je t ai dit", "je t avais dit", "j ai dit",
              "i told you", "as i said")
# where a correction goes on about what was asked BEFORE ("…que je t'avais
# demandé de surligner"): the gesture of that clause is the old one
_EARLIER = (("que", "je", "t", "avais"), ("que", "je", "t", "ai"), ("que", "j", "avais"), ("que", "j", "ai"),
            ("que", "tu", "avais"), ("qu", "on", "avait"), ("that", "i", "asked"), ("i", "asked", "you"),
            ("i", "had", "asked"))
# the words that stop a highlight ("stop highlighting", "cancel the highlight",
# "ne surligne pas l'huile")
STOP_LIGHT = ("arrete", "arretez", "arreter", "stop", "cesse", "cessez", "n affiche plus", "ne surligne plus",
              "ne surligne pas", "ne surlignez pas", "ne surlignez plus", "don t highlight", "dont highlight",
              "do not highlight", "desactive", "desactivez", "desactiver", "disable", "eteins", "eteindre", "annule",
              "annuler", "cancel")
# the words that take a highlight OFF ("remove the highlight")
CLEAR_WORDS = ("enleve", "retire", "efface", "supprime", "remove", "clear", "turn off", "off", "unhighlight",
               "no more", "vide", "desurligne") + STOP_LIGHT
# "highlight the oil cells BUT KEEP EVERYTHING VISIBLE": said not to filter
KEEP_ALL = ("garde tout", "tout visible", "sans cacher", "sans masquer", "sans filtrer", "sans rien cacher",
            "garde le reste", "gardant le reste", "laisse le reste", "laissez le reste", "laisse les autres",
            "laissez les autres", "laisse tout", "keep everything", "keeping everything", "without hiding",
            "without filtering", "keep the rest", "keeping the rest", "leave the rest", "leave the others",
            "leave everything", "hiding nothing")
# the words that say the cells a well goes THROUGH — "the cells the wells
# cross", "where the wellbores intersect the oil zone", "the well blocks",
# "blocked wellbores": next to a well's word they are the well_cells
# command, whatever the verb (highlight, show, which wells…)
CROSSING_WORDS = ("traverse", "traversent", "traversee", "traversees", "traverses", "intersecte", "intersectent",
                  "intersection", "intersections", "croise", "croisent", "croisee", "croisees", "perce", "percee",
                  "percees", "percent", "rencontre", "rencontrent", "rencontrees", "le long", "bloque", "bloques",
                  "blocked", "block wellbore", "block wellbores", "well block", "well blocks", "blocs de puits",
                  "blocks des", "blocs des", "blocks of the", "coupent", "recoupe", "recoupent", "recoupees",
                  "well cells", "well cell", "touche", "touchent", "touch", "touches", "rentre dans",
                  "rentrent dans", "hors de", "en dehors", "out of", "outside", "not in", "are not in",
                  "is not in", "pas dans",
                  "cross", "crosses", "crossed", "crossing", "intersect", "intersects", "intersected",
                  "penetrate", "penetrates", "penetrated", "pass through", "passes through", "passing through",
                  "go through", "goes through", "going through", "run through", "runs through",
                  "drilled through", "traversed", "along the well", "along the wells", "le long des puits",
                  "le long du puits", "atteint", "atteignent", "atteindre", "reach", "reaches", "reaching",
                  # "il existe des puits sur ces zones" (there are wells in these
                  # zones): where the wells ARE, in the grid's cells (a bare
                  # "where are the wells" stays a show)
                  "il existe", "existe t il", "y a t il")
WELL_WORDS = ("puits", "puit", "forage", "forages", "wellbore", "wellbores", "well", "wells", "borehole",
              "boreholes", "trajectoire", "trajectoires", "trajectory", "trajectories", "sondage", "sondages",
              "bloque", "bloques", "blocked", "bw")
# what the well_cells command is about: the grid's cells — a crossing said
# of them, of a zone, of the grid or of a value is the cells the wells go
# through; "the GR along the well" is a log, "how deep does the well
# reach" a value
CELL_WORDS = ("maille", "mailles", "cellule", "cellules", "cell", "cells", "bloc", "blocs", "block", "blocks",
              "bloque", "bloques", "blocked", "bw", "voxel", "voxels", "zone", "zones", "grille", "grilles", "grid",
              "grids", "maillage", "modele", "model", "reservoir")
# the zones or the grid, said: after the wells through a zone, "hide the
# other zones" is about the grid's values, not the wells
ZONE_GRID_WORDS = ("zone", "zones", "grille", "grilles", "grid", "grids", "maillage", "mailles", "cellules",
                   "cells")
# the values a zone is said by ("the oil", "le gaz"), in a session that
# lists them or not
_VALUE_WORDS = tuple(normalize(w) for ws in lexicon.CATEGORIES.values() for w in ws)

# a question about what is seen or why ("pourquoi ce puits est encore
# affiché ?", "est-ce que tu vois des chenaux ?"): an answer, not a gesture
WHY_WORDS = ("pourquoi", "why", "how come", "comment ca se fait", "comment se fait il")
SEE_QUESTIONS = ("est ce que tu vois", "est ce que tu as vu", "vois tu", "tu vois des", "do you see",
                 "can you see", "did you see")
# … but "pourquoi je ne vois rien ?" is a complaint
COMPLAINT_MARKS = ("rien", "nothing", "vois pas", "vois plus", "voit pas", "voit plus", "vois rien", "voit rien",
                   "don t see", "dont see", "can t see", "cant see", "cannot see", "see no", "doesn t work",
                   "does not work", "not working", "marche pas", "fonctionne pas", "s affiche pas",
                   "apparait pas", "affiche rien", "est vide", "is empty", "disparu", "disappeared")
# … and in a "why" question, what is empty ("why is the grid empty?")
_EMPTY = ("empty", "vide", "vides", "blank")
# "what's PHIT", "c'est quoi Hugin": a name asked about is described
_WHAT_IS = (("what", "s"), ("whats",), ("what", "is"), ("c", "est", "quoi"), ("qu", "est", "ce", "que"),
            ("qu", "est", "ce", "qu"), ("tell", "me", "about"))
# "why don't you hide the wells", "pourquoi ne pas filtrer…", "why not show
# the porosity": a request said as a question — the request itself (a verb
# follows the lead; "pourquoi tu ne masques pas…" drops its "pas" too)
_INDIRECT = (("why", "don", "t", "you"), ("why", "dont", "you"), ("why", "do", "not", "you"), ("why", "don", "t", "we"),
             ("why", "dont", "we"), ("why", "not"), ("pourquoi", "ne", "pas"), ("pourquoi", "pas"),
             ("pourquoi", "tu", "ne"), ("pourquoi", "ne", "tu"), ("pourquoi", "tu", "n"), ("pourquoi", "on", "ne"))
# a sentence of these words only gives no command: thanks, a go-ahead, a
# pause ("merci", "c'est bon", "vas-y", "hmm", "stop")
_SMALL_TALK = frozenset("""
ok okay oui yes yeah merci thanks thank you super parfait parfaitement cool top bien tres c est bon vas y go ahead
d accord hmm hm euh bof stop wait attends attend great nice good perfect fine ca marche va bravo genial
""".split())
# a complaint that states a bound ("c'est faux, la porosité est encore
# au-dessus de 0,3"): what is wanted is not sure — the assistant asks,
# unless the complaint goes on with its own order ("c'est faux, garde la
# porosité au-dessus de 0,2"): `_orders`
_WRONG_WORDS = ("faux", "erreur", "wrong", "mistake", "incorrect")
_STILL = ("encore", "toujours", "still")
# a depth said by its bound: "deeper than 2500 m", "plus profondes que 2500"
_DEPTH_BOUNDS = ("plus profond que", "plus profonde que", "plus profonds que", "plus profondes que",
                 "moins profond que", "moins profonde que", "moins profonds que", "moins profondes que",
                 "deeper than", "shallower than")
# the verbs that make a gesture said by its noun ("fais le filtre")
_MAKING = frozenset("fais faire faites applique appliquer appliquez mets mettre ajoute ajouter make apply add do put"
                    .split())
# "garde tout sauf le gaz": every value but the one said
_ALL_BUT = (("tout", "sauf"), ("tout", "excepte"), ("tout", "hormis"), ("everything", "but"),
            ("everything", "except"), ("all", "but"), ("all", "except"))
# what may stand between a hiding verb and the others it hides ("cache les
# puits autres que F-4", "hide everything but the oil", "drop the rest")
_TO_OTHERS = frozenset("le la les l the tout tous toutes everything all every each chaque moi me de des du d of"
                       .split())

# the kinds whose values are fractions: "20 %" is 0.2 there — and so is a
# bare 20 ("porosity above 20"), a fraction being never above 1
FRACTIONS = frozenset(("porosity", "net to gross", "water saturation", "gas saturation",
                       "oil saturation", "saturation", "shale volume", "neutron porosity"))
# the commands that take bounds
BOUNDED = ("threshold", "highlight", "color_range", "slice", "well_cells")
# "the top 10 layers", "les 5 premières couches": from the first one — the
# word next to its number, never "from the top" nor the Top of a title
_FIRST_WORDS = ("top", "first", "premieres", "premiers", "premiere", "premier")
# "limite la légende à 0,3", "limit the legend to 0.3": a cap said as the
# request's verb ("la limite basse" is a minimum: lexicon.MIN_WORDS)
_CAPPING = frozenset(("limite", "limitez", "limit", "limits"))
# the verbs that compute ("calcule PHIT * NTG", "compute PHIT times NTG")
# and what makes their object a new property: an operation, or two
# properties — "calcule la moyenne…" stays a value
_COMPUTING = frozenset(("calcule", "calculer", "calculez", "calcules", "compute", "computes"))
_OPERATIONS = ("x", "fois", "times", "+", "/", "produit", "product", "a partir de", "a partir du",
               "a partir des", "multiplie par", "multiplied by", "divise par", "divided by")
# … and the verbs that make one ("create a new property", "make a property
# from PHIT and SW", "crée une nouvelle propriété")
_MAKING_PROPERTY = frozenset("""
create creates build builds make makes derive derives generate cree crees creez creer fabrique fabriquer
construis construire genere generer calcule calculer calculez compute
""".split())
_A_NEW = frozenset(("a", "an", "une", "un", "new", "nouvelle", "nouveau"))
# a palette said NOT ("pas en jet, en viridis", "not in grey, use jet"):
# the words that set it aside
_REFUSING = frozenset(("pas", "not", "no", "never", "jamais", "dont", "plus"))
_REFUSING_PHRASES = ("don t", "do not", "au lieu de", "au lieu du", "instead of", "plutot que", "rather than")
# what may open a suggestion after "why not" / "pourquoi pas" ("pourquoi pas
# la palette jet ?", "why not a slice along i?") — not "de": "pourquoi pas
# de puits ?" asks why there are none
_SUGGESTED = frozenset("le la les l un une the a an en in au aux".split())
# a restriction said not ("ne montre pas que la grille", "don't show only
# the wells"): more is to be shown, nothing isolated (`_not_only`)
_NOT_ONLY = ("pas seulement", "pas uniquement", "not only", "not just", "don t show only", "dont show only",
             "do not show only")
# "show me what I asked for", "fais ce que je t'ai demandé": an order to do
# what was asked — the answer missed, a complaint, no command of its own
# ("c'est ce que je voulais" is no order)
_WHAT_I_ASKED = ("what i asked", "what i wanted", "ce que je t ai demande", "ce que j ai demande",
                 "ce que je t avais demande", "ce que j avais demande", "ce que je voulais")
# the words of the colour scale ("le minimum de l'échelle", "the legend's max")
_SCALE_WORDS = ("echelle", "legende", "palette", "couleurs", "colour scale", "color scale", "colorbar", "colormap",
                "colour range", "color range", "legend", "scale")
# the vertical scale as it is: a factor of one
_TRUE_SCALE = ("no exaggeration", "without exaggeration", "true vertical scale", "true scale", "real scale",
               "normal scale", "normal vertical scale", "sans exageration", "pas d exageration", "echelle reelle",
               "vraie echelle", "echelle normale", "echelle verticale normale", "echelle verticale reelle")

# the view's gestures. A zoom said with a name, or to see everything, frames
# it: "zoom sur Hugin", "zoom to fit" are a reset_camera
_ZOOM_WORDS = frozenset(("zoom", "zoome", "zoomer", "zoomez", "zoomes", "zooming", "dezoom", "dezoome", "dezoomer",
                         "dezoomez", "dezoomes", "unzoom"))
_FIT_WORDS = ("tout", "everything", "fit", "fits", "extents", "extent", "ensemble", "entier", "entiere", "whole",
              "entire", "tienne", "rentre", "cadre", "frame", "all")
# … and a reset said as such stays one ("remets la caméra", "vue par défaut")
_RESET_WORDS = ("recadre", "recadrer", "reinitialise", "reinitialiser", "reset", "recentre", "recentrer", "recenter",
                "centre", "center", "defaut", "default", "d aplomb", "home", "reframe", "remets la camera",
                "remettre la camera", "perdu", "lost")
# a new view said as such ("une nouvelle vue de dessus" is a view of its own)
_NEW_WORDS = ("nouvelle", "nouveau", "new", "autre", "another", "deuxieme", "second", "seconde", "supplementaire",
              "duplique", "split", "divise", "separe")
# the words of time: a step said with one of them is a time step ("reviens au
# pas de temps précédent" is no undo, "go back one step" is)
_TIME_WORDS = ("pas de temps", "time step", "time steps", "timestep", "timesteps", "temps", "time", "date", "dates",
               "annee", "year", "instant", "serie temporelle", "time series")
_REALIZATION_WORDS = ("realisation", "realisations", "realization", "realizations", "tirage", "tirages")
# a play stopped ("arrête l'animation", "pause the time steps")
_STOP_PLAY = ("arrete", "arretez", "arreter", "stop", "stoppe", "stopper", "pause", "suspends", "suspendre", "fige",
              "figer", "freeze", "halt", "interromps", "interrompre", "coupe", "couper", "eteins", "desactive",
              "cesse", "cessez")
# the colour bar said off: a hiding word, an off word, a negation of it
_BAR_OFF = ("sans", "pas de", "plus de", "no", "without", "off", "invisible", "desactive", "desactiver", "disable",
            "turn off", "eteins", "eteindre", "drop", "get rid of")
# what closes a panel ("ferme les stats", "close the histogram")
_CLOSING = ("ferme", "fermer", "fermez", "fermes", "referme", "close", "closes", "shut", "dismiss")
_OPENING_VERBS = ("ouvre", "ouvrir", "ouvrez", "open", "opens", "lance", "launch", "affiche", "show")
# what the application does elsewhere than in the assistant (an unsupported
# request names one): said, the sentence is about the application
_ELSEWHERE_WORDS = ("capture", "captures", "screenshot", "snapshot", "png", "jpeg", "imprime", "print", "csv", "excel",
                    "tableur", "spreadsheet", "exporte", "export", "exporter", "fichier", "fichiers", "file", "files",
                    "epc", "importe", "import", "osdu", "etp", "serveur", "server", "dataspace", "opacite",
                    "transparence", "transparent", "transparente", "translucide", "translucent", "opacity",
                    "transparency", "fond", "arriere plan", "background", "pilier", "piliers", "pillar", "pillars",
                    "camera", "cameras", "globe", "terre", "earth", "decharge", "decharger", "unload")

_MODEL = None


def model():
    """The shipped intent model, loaded once; None when its file is missing."""
    global _MODEL
    if _MODEL is None and os.path.exists(MODEL_PATH):
        _MODEL = IntentModel.load(MODEL_PATH)
    return _MODEL


def use_model(m):
    """Swap the model (the tests, the trainer); None reloads the shipped one."""
    global _MODEL
    _MODEL = m


def known_word(word, m=None):
    """Is `word` (normalised) one a reader types on purpose: a word of the
    patterns, the lexicon or the engine's cues, or one of the sentences the
    model was trained on ("hey", "ctrl+z")?"""
    m = m or model()
    return word in slots.known_words() or bool(m is not None and word in getattr(m, "vocab", ()))


# ------------------------------------------------------------------ kinds
def kind_matches(canonical, obj):
    """Does `obj` (a property) carry the canonical kind: by its kind in the
    data (itself or a PWLS descendant: "total porosity" is a porosity), or
    by its title, a mnemonic of the trade ("PHIT")?"""
    entry = lexicon.KINDS.get(canonical)
    if not entry:
        return False
    k = (obj.get("kind") or "").strip().lower()
    if k:
        if k in entry["kinds"] or any(a in entry["kinds"] for a in pwls_kinds.ancestors(k)):
            return True
    t = normalize(obj.get("title", ""))
    if t in entry["titles"] or t.replace(" ", "_") in entry["titles"]:
        return True
    # a mnemonic leading the title: "PHIT_final", "NTG_2024", "Sw_model"
    lead = slots._pieces(t)[:1]
    if lead and len(t.split()) > 1 and lead[0] in entry["titles"]:
        return True
    # a title that SAYS the kind: "Water Saturation (Gas Zone)" may carry
    # only the generic kind "saturation", its title says water saturation
    # …or says it with a number after ("Lithology1", "facies_2")
    t = re.sub(r"[ _]?\d+$", "", t)
    return any(t == p or t.startswith(p + " ") for p in _title_phrases(canonical))


_TITLE_PHRASES = {}


def _title_phrases(canonical):
    """The lexicon's words for a kind long enough to be read in a title:
    several words, or one of five letters or more ("so" or "gr" never)."""
    if canonical not in _TITLE_PHRASES:
        _TITLE_PHRASES[canonical] = tuple(
            normalize(p) for p in lexicon.KINDS[canonical]["say"]
            if len(p.split()) >= 2 or len(p) >= 5)
    return _TITLE_PHRASES[canonical]


def kind_of(obj):
    """The canonical kind a property carries, None when the lexicon has none
    for it — "PHIT > 15 %" is a porosity, so 15 % is 0.15."""
    for canonical in lexicon.KINDS:
        if canonical != "saturation" and kind_matches(canonical, obj):
            return canonical
    return "saturation" if kind_matches("saturation", obj) else None


def in_group(family, obj):
    """Is `obj` of that sort? A group never takes an object without a type."""
    return slots._family_ok(family, obj) and bool((obj.get("type") or "").strip())


def has_category(obj, category):
    """Does `obj` (a categorical property) list that value ("oil")?"""
    return any(slots.category_of(str(label)) == category
               for label in (obj.get("categories") or {}).values())


def code_of(obj, category):
    """The code of that value in `obj`'s table (Fluids: oil -> 1), or None."""
    for code, label in (obj.get("categories") or {}).items():
        if slots.category_of(str(label)) == category:
            return float(code) if _NUMBER.match(str(code).strip()) else None
    return None


_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


def resolve(objects, found_objects, kind, group=None, category=None):
    """The objects the command is about, each once (see `_resolve`)."""
    return _unique(_resolve(objects, found_objects, kind, group, category))


def _unique(objs):
    """Each object once, in order: a name found twice (the kind's window
    and the title's) is one target."""
    seen, out = set(), []
    for o in objs:
        if o.get("path") not in seen:
            seen.add(o.get("path"))
            out.append(o)
    return out


def _resolve(objects, found_objects, kind, group=None, category=None):
    """The objects the command is about. A named property is itself; a named
    grid or well with a kind is its properties of that kind; a kind alone
    is every property of that kind in the session; a group ("all the
    wells") every top-level object of that sort; a category value ("the oil
    zones") the categorical properties that list it — of the named grid
    when one is named."""
    named = [o for cands in found_objects for o in cands]
    if category:
        # the value guides; a kind said with it ("the oil facies") only
        # breaks a tie between properties that both list the value
        out = []
        if named:
            out = [dict(o, why="named") for o in named if has_category(o, category)]
            for o in named:
                out += [dict(p, why=f"{category} of {o.get('title')}") for p in objects
                        if p.get("parent") == o.get("path") and has_category(p, category)]
        if not out:
            out = [dict(p, why=category) for p in objects if has_category(p, category)]
        if kind and len(out) > 1:
            out = [p for p in out if kind_matches(kind, p)] or out
        if out:
            return out
    if group and not named:
        named = [dict(o, score=1.0) for o in objects if in_group(group, o)
                 and not o.get("parent")]
        if not kind:
            return [dict(o, why=f"every {group}") for o in named]
    if not kind:
        return [dict(o, why="named") for o in named]
    # a property named precisely ("the vertical permeability of Geogrid")
    # is the one meant: its grid does not bring its other permeabilities
    precise = [dict(o, why="named") for o in named if kind_matches(kind, o)]
    if precise:
        return precise
    out = []
    for o in named:
        kids = [p for p in objects if p.get("parent") == o.get("path") and kind_matches(kind, p)]
        out += [dict(p, why=f"{kind} of {o.get('title')}") for p in kids]
    if not named:
        out = [dict(p, why=kind) for p in objects if kind_matches(kind, p)]
    return out


# ------------------------------------------------------------------ parse
def _has(text, words):
    """Is one of `words` a whole word or phrase of `text` (space-padded)?"""
    return any(f" {w} " in text for w in words)


_VERBS = None
_SHORT_VERBS = ()
_ARTICLES = ("le", "la", "les", "l", "du", "de", "d", "des", "the", "a", "an")
# everyday words a reader types on purpose that sit one slip from a verb
_NOT_A_SLIP = frozenset("""
might could would should maybe please thanks rather quite still again there where which while about after
before under over black white clean small large quick tight night right first later today since until every
other whole entire toute toutes cette celle quand comme aussi alors encore ensuite avant apres chose chaque
petit grand grande noire blanc blanche juste vraiment plutot merci pourrais pourriez voudrais
""".split())


def _denied(toks, i):
    """Is the word at `i` said NOT: "pas le gaz", "not the oil", "non
    filtrer" — a negation right before it, an article allowed between."""
    j = i - 1
    if j >= 0 and toks[j] in _ARTICLES:
        j -= 1
    return j >= 0 and toks[j] in ("pas", "not", "non", "no")


def _swapped(a, b):
    """Is `a` the word `b` with two letters side by side swapped ("shwo",
    "show")?"""
    diff = [i for i in range(len(a)) if a[i] != b[i]] if len(a) == len(b) else []
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def _mend(toks, found):
    """The tokens, a slip in a VERB the engine reads mended ("surlingne" ->
    surligne, "anule" -> annule): only a word the spans did not take, that
    no table knows, five letters or more, within its typo budget of one
    verb — or four letters, two of them swapped ("shwo" -> show). Names and
    values stay as typed."""
    global _VERBS, _SHORT_VERBS
    if _VERBS is None:
        words = set(multi.VERBS)
        for group in (HIGHLIGHT_WORDS, FILTER_WORDS, lexicon.HIDING, HIDE_MORE, CROSSING_WORDS,
                      ("annule", "annuler", "recadre", "recentre", "decris", "liste", "ouvre", "sauvegarde")):
            words.update(w for w in group if " " not in w)
        # in a fixed order: of two verbs a slip away from a word, the same
        # one wins at every run
        _VERBS = tuple(sorted(w for w in words if len(w) >= 5))
        _SHORT_VERBS = tuple(sorted(w for w in words if len(w) == 4))
    taken = [False] * len(toks)
    for a, b, *_rest in found:
        for i in range(a, b):
            taken[i] = True
    known = slots.known_words()
    out = list(toks)
    for i, t in enumerate(toks):
        # a word the rules read is said on purpose ("remontre" is no
        # slipped "recentre")
        if taken[i] or t in known or t in cue_words() or t in _NOT_A_SLIP or t[0].isdigit():
            continue
        if len(t) == 4:
            out[i] = next((w for w in _SHORT_VERBS if _swapped(t, w)), t)
            continue
        if len(t) < 5:
            continue
        budget = slots.typo_budget(t)
        best, best_d = None, budget + 1
        for w in _VERBS:
            # a short verb is one slip from too many real words ("might"
            # and light, "clean" and clear): six letters at least
            if len(w) >= 6 and abs(len(w) - len(t)) <= budget:
                d = slots.edit_distance(t, w)
                if d < best_d:
                    best, best_d = w, d
        if best is not None:
            out[i] = best
    return out


# the switches' words: what shows the missing values, what hides them, what
# lights the scene, what the exact colours are called
_SHOW_WORDS = ("montre", "montrer", "montrez", "remontre", "remontrer", "remontrez", "affiche", "afficher",
               "affichez", "reaffiche", "reafficher", "reaffichez", "remets", "remettez", "remettre", "revoir", "voir",
               "vois", "visible", "visibles", "apparaitre", "reapparaitre", "reapparaissent", "de nouveau",
               "a nouveau", "show", "display", "see", "unhide", "bring back", "put back", "again", "back")
# (a seeing said not is a showing word turned over by its negation, below)
_HIDE_WORDS = lexicon.HIDING + tuple(w for w in HIDE_MORE if w not in NOT_SEE) + (
    "hiding", "masking", "cachant", "masquant", "invisible", "invisibles", "disparaitre")
_SWITCH_NEGATION = ("veux pas voir", "veux plus voir", "arrete", "arretez", "arreter", "stop", "cesse", "cessez",
                    "don t", "dont", "do not", "no longer", "not", "never")
_LIGHT_WORDS = ("ombrage", "ombrages", "ombre", "ombres", "eclairage", "lumiere", "relief", "shading", "shaded",
                "shade", "shadow", "shadows", "lighting")
_FLAT = [tuple(p.split()) for p in (
    "couleurs plates", "couleur plate", "couleurs exactes", "couleur exacte", "couleurs franches",
    "couleurs unies", "couleurs nettes", "couleurs a plat", "aplats", "aplat", "flat colors", "flat colours",
    "flat color", "flat colour", "exact colors", "exact colours", "solid colors", "solid colours",
    "plain colors", "plain colours")]
_FLAT_OFF = [tuple(p.split()) for p in lexicon.OFF + ("arrete", "stop", "desactivez", "no more", "plus de")]

_CUES = None


def cue_words():
    """Every word the rules read (the verbs of multi.split, the cue lists
    above): said on purpose, never a slip of another word."""
    global _CUES
    if _CUES is None:
        # (the bound words too: "limite basse" is no slipped "limiter")
        lists = (REFERS, OTHERS, FILTER_WORDS, HIGHLIGHT_WORDS, HIDE_MORE, OUT_WORDS, STILL_WORDS, STAT_WORDS,
                 NEGATION, CORRECTION, STOP_LIGHT, CLEAR_WORDS, KEEP_ALL, CROSSING_WORDS, WELL_WORDS, CELL_WORDS,
                 WHY_WORDS, SEE_QUESTIONS, COMPLAINT_MARKS, _SHOW_WORDS, _HIDE_WORDS, _SWITCH_NEGATION,
                 _LIGHT_WORDS, _TRUE_SCALE, _FIRST_WORDS, lexicon.HIDING, lexicon.MAX_WORDS, lexicon.MIN_WORDS,
                 _CAPPING, _HIDDEN, _OPERATIONS, _COMPUTING)
        _CUES = frozenset(w for group in lists for p in group for w in p.split()) | multi.VERBS
    return _CUES


_STOPPING = frozenset(("arrete", "arretez", "arreter", "cesse", "cessez", "stop", "quit"))
_NEG_AFTER = frozenset(("pas", "plus", "jamais", "point"))
_CLITICS = frozenset("les la le l me m te t lui leur y en nous vous se s".split())
_MODALS = frozenset("veux voudrais peux dois doit doivent faut souhaite veut voulons voulez".split())
_EN_GAP = frozenset("to want wanna need you i we them it really even ever be been being get".split())
# a participle after "be" ("qu'ils soient masqués") and the subject between
# it and its "que" ("je ne veux plus que les NaN soient cachés")
_BE = frozenset("etre soient soit sont est restent reste rester".split())
_SUBJECTS = frozenset("ils elles il elle on tu je nous vous ce ca cela ces ceux celles nan nans valeurs manquantes "
                      "absentes mailles".split())
# the hiding participles, read by the missing values' switch only ("the
# NaN, I don't want them hidden"); elsewhere "les puits sont cachés" is a
# complaint, not a gesture
_HIDDEN = ("hidden", "masked", "cachee", "cachees", "masquee", "masquees")


def _infinitive(word):
    """A French infinitive ("cacher", "voir", "remettre"): what "pas" bears
    on in "pas les cacher"."""
    return len(word) > 3 and word.endswith(("er", "ir", "re"))


def _a_verb(word):
    return word in multi.VERBS or word in _HIDE_WORDS or word in _SHOW_WORDS or _infinitive(word)


# the verbs of the switches' words (not "invisibles", "à nouveau"): what a
# "pas" said without "ne" may follow
_VERB_WORDS = frozenset(multi.VERBS | set(lexicon.HIDING) | set(HIDE_MORE)) - {
    "visible", "visibles", "invisible", "invisibles"}


def _refused_before(toks, i):
    """Is the thing at `i` (a noun, not a verb) said NOT by what comes right
    before it: "pas d'ombrage", "pas les couleurs plates", "sans ombres",
    "no shading", "je ne veux plus d'ombrage", "I don't want flat colours"
    — not the "plus" of "mets plus d'ombrage" (more of it)?"""
    j = i - 1
    if j >= 0 and toks[j] in ("de", "d", "des", "du", "les", "la", "le", "l", "the", "any"):
        j -= 1
    if j >= 0 and toks[j] in ("pas", "jamais", "sans", "no", "not", "without", "never"):
        return True
    if j >= 1 and toks[j] == "plus" and (toks[j - 1] in ("ne", "n") or toks[j - 1] in _MODALS):
        return True
    j = i - 1
    while j >= 0 and toks[j] in _EN_GAP:
        j -= 1
    if j >= 0 and toks[j] in ("not", "never", "dont", "doesnt", "didnt"):
        return True
    return j >= 1 and toks[j] == "t" and toks[j - 1] in ("don", "doesn", "didn", "won", "wouldn")


def _occurrences(toks, phrases):
    """(start, length) of every place one of `phrases` is said."""
    out = []
    for p in phrases:
        w = p.split()
        out += [(i, len(w)) for i in range(len(toks) - len(w) + 1) if toks[i:i + len(w)] == w]
    return out


def _negated(toks, i, n=1):
    """Does a negation bear on the verb at toks[i:i+n]: "ne masque plus",
    "ne les cache pas", "ne plus afficher", "je ne veux plus les voir",
    "je veux pas voir", "pas les cacher", "cache pas les NaN" (the "ne"
    left out), "je ne veux plus qu'ils soient masqués", "arrête de
    cacher", "stop hiding", "don't hide", "I don't want to see them",
    "shouldn't be hidden" — not one said of another verb ("masque les NaN,
    je ne veux plus les voir": the masking is not said not; "je veux les
    voir, pas les cacher": the "pas" is the hiding's)."""
    j = i - 1
    if j >= 0 and toks[j] in ("de", "d"):
        j -= 1
    if j >= 0 and toks[j] in _STOPPING:
        return True
    j = i - 1
    while j >= 0 and toks[j] in _CLITICS:
        j -= 1
    k = i + n
    while k < len(toks) and toks[k] in _CLITICS:
        k += 1
    if j >= 0 and toks[j] in ("ne", "n"):
        return k < len(toks) and toks[k] in _NEG_AFTER
    # "les NaN ne doivent plus être cachés": the participle after "être",
    # said not with its modal
    if j >= 0 and toks[j] in _BE:
        while j >= 0 and (toks[j] in _BE or toks[j] in _CLITICS):
            j -= 1
    # "ne plus afficher", "(ne) veux plus [les] voir", "pas les cacher": the
    # infinitive said not
    if j >= 0 and toks[j] in _NEG_AFTER and (
            (j >= 1 and (toks[j - 1] in ("ne", "n") or toks[j - 1] in _MODALS)) or _infinitive(toks[i])):
        return True
    # "cache pas les NaN", "masque plus les NaN": the "ne" left out, after a
    # verb — not the "pas" of the next verb, nor the "plus" of "plus de",
    # "plus que", nor a contrast after a word that is no verb ("rends les NaN
    # invisibles, pas la grille")
    if n == 1 and toks[i] in _VERB_WORDS and k < len(toks) and toks[k] in _NEG_AFTER:
        m = k + 1
        while m < len(toks) and toks[m] in _CLITICS:
            m += 1
        comparing = toks[k] == "plus" and toks[k + 1:k + 2] in (["de"], ["d"], ["que"], ["qu"])
        if not comparing and not (m < len(toks) and _a_verb(toks[m])):
            return True
    if _wished_not(toks, i):
        return True
    j = i - 1
    while j >= 0 and toks[j] in _EN_GAP:
        j -= 1
    if j >= 0 and toks[j] in ("not", "never", "dont", "doesnt", "didnt", "longer"):
        return True
    return j >= 1 and toks[j] == "t" and toks[j - 1] in ("don", "doesn", "didn", "won", "wouldn", "shouldn")


def _wished_not(toks, i):
    """Is the participle at `i` what a wish said not bears on: "je ne veux
    plus qu'ils soient masqués", "je ne veux pas que les NaN soient
    cachés"?"""
    j = i - 1
    while j >= 0 and toks[j] in _BE:
        j -= 1
    for q in range(j, max(-1, j - 5), -1):
        if toks[q] in ("que", "qu"):
            return q >= 2 and toks[q - 1] in _NEG_AFTER and (toks[q - 2] in _MODALS or toks[q - 2] in ("ne", "n"))
        if toks[q] not in _SUBJECTS and toks[q] not in _CLITICS and toks[q] not in _ARTICLES:
            return False
    return False


def _said_with_pas(toks, i, n):
    """A "pas" in the clause of the verb at toks[i:i+n] ("pas question de
    les cacher"): a negation the forms of `_negated` may not read."""
    return "pas" in toks[max(0, i - 4):i] or "pas" in toks[i + n:i + n + 2]


def _switch(intent, toks, read):
    """on/off for the two switches, read from what the words mean there."""
    text = " " + " ".join(toks) + " "
    if intent == "hide_nan":
        # True: the missing values are hidden. A hiding verb hides them —
        # whatever else is said ("drop the undefined values from the
        # display", "masque les NaN, je ne veux plus les voir"); a hiding
        # verb or participle said not shows them ("NE masque PLUS les NaN",
        # "cache pas les NaN", "stop hiding", "I don't want them hidden");
        # a seeing verb said not hides them ("n'affiche plus les NaN", "I
        # don't want to see them"), said as such shows them — and wins over
        # a hiding said with a "pas" ("pas question de les cacher, je veux
        # les voir"); no verb at all ("plus de NaN", "je ne veux plus les
        # NaN") hides them
        found = _occurrences(toks, _HIDE_WORDS + _HIDDEN)
        hides = [_negated(toks, i, n) for i, n in found]
        shows = [_negated(toks, i, n) for i, n in _occurrences(toks, _SHOW_WORDS)]
        if hides:
            if all(hides):
                return False
            seen = any(not s for s in shows)
            return not (seen and any(_said_with_pas(toks, i, n) for (i, n), h in zip(found, hides) if not h))
        if shows:
            return any(shows)
        return True
    if intent == "flat_colors":
        # "désactive les couleurs plates", "I don't want flat colours
        # anymore": the exact colours said off — before any word of the
        # lighting the same sentence asks for ("…, je veux l'ombrage")
        for i in range(len(toks)):
            for p in _FLAT:
                if tuple(toks[i:i + len(p)]) == p and _flat_said_off(toks, i, len(p)):
                    return False
        if _has(text, _LIGHT_WORDS):
            # "turn the shading on" -> exact colours OFF; the lighting said
            # off ("enlève les ombres", "sans ombrage", "je ne veux pas
            # d'ombrage") -> ON
            dark = any(_light_said_off(toks, i) for i, t in enumerate(toks) if t in _LIGHT_WORDS)
            return dark or read["on"] is False
        return True
    return read["on"]


def _flat_said_off(toks, i, n):
    """An off word or a negation on the exact colours at toks[i:i+n]: right
    before them (an article between: "désactive les couleurs plates", "plus
    de couleurs plates", "pas les couleurs plates", "don't want flat
    colours") or right after ("couleurs plates off")."""
    for q in _FLAT_OFF:
        for gap in (0, 1):
            end = i - gap
            if end - len(q) >= 0 and tuple(toks[end - len(q):end]) == q:
                return True
    if toks[i + n:i + n + 1] in (["off"], ["desactivees"], ["desactive"]):
        return True
    return _refused_before(toks, i)


def _light_said_off(toks, i):
    """Is the lighting word at `i` said off: "pas d'ombrage", "sans
    ombres", "no shading", "I don't want shading"?"""
    return _refused_before(toks, i)


def _main_clause(toks):
    """The tokens before a clause about what was asked earlier ("…que je
    t'avais demandé de surligner"): a correction's gesture is in the main
    clause."""
    for i in range(len(toks)):
        for p in _EARLIER:
            if tuple(toks[i:i + len(p)]) == p:
                return toks[:i]
    return toks


# the words of a correction itself ("j'ai dit", "I told you", "je voulais
# dire"), and the verbs that say no gesture ("fais-le")
_SAYING = frozenset("""
dit dis dire said say told tell meant mean voulais voulai voulu wanted want veux parlais parlai pensais demande
demandais asked ask fais faire fait do did done
""".split())


def _own_verb(main):
    """Does the main clause of a correction say a gesture of its own — a
    verb of the catalogue that is not the correction's ("j'ai dit CACHE les
    puits", "I told you to ZOOM on F-4"; "j'ai dit eau et gaz" says none)?"""
    return any((t in multi.VERBS or t in lexicon.HIDING) and t not in _SAYING and not _denied(main, i)
               for i, t in enumerate(main))


_ORDERING = frozenset(w for w in FILTER_WORDS + HIGHLIGHT_WORDS + lexicon.HIDING if " " not in w)
# the words a complaint starts with, before the order it may go on with
_COMPLAINT_HEAD = frozenset("non no c est faux erreur une wrong that s it is mistake incorrect".split())


def _orders(text):
    """Does a complaint go on with an order of its own — a word of the
    gestures starting a clause ("c'est faux, GARDE la porosité au-dessus de
    0,2", "wrong, FILTER porosity…", "erreur : SEUIL de perméabilité à 50")
    — not a sentence that tells what is seen ("la porosité affichée dépasse
    0,3, c'est une erreur", "ça montre encore…")?"""
    for clause in re.split(r"[,;:.!?]", str(text or "")):
        words = multi._words(clause)
        while words and words[0] in _COMPLAINT_HEAD:
            words = words[1:]
        if words and (words[0] in multi.VERBS or words[0] in _ORDERING) and words[1:2] not in (
                ["encore"], ["toujours"], ["still"]):
            return True
    return False


def _restrictive(toks):
    """A "que" that keeps a value and nothing else: "montre-moi que
    l'huile", "garde que le gaz", "rien que le gaz", "que l'eau", "je ne
    veux que l'huile" — not the wish of "je voudrais que l'huile ressorte",
    nor the "ne … que" of a highlight ("ne surligne que l'huile" lights
    that value alone and hides nothing)."""
    for i, t in enumerate(toks):
        if t != "que" or toks[i + 1:i + 2] not in (["le"], ["la"], ["les"], ["l"]):
            continue
        j = i - 1 if i and toks[i - 1] != "moi" else i - 2
        if i == 0 or (j >= 0 and toks[j] in _ONLY_VERBS):
            return True
        ne = next((k for k in range(i - 1, -1, -1) if toks[k] in ("ne", "n")), None)
        if ne is not None and not _has(" " + " ".join(toks[ne + 1:i]) + " ", HIGHLIGHT_WORDS):
            return True
    return False


def _filters(said, toks):
    """A word that keeps the value said and hides the rest ("filtre",
    "garde", "only", a restrictive "que")."""
    return _has(said, FILTER_WORDS) or _restrictive(toks)


# the verbs that hide (the lexicon's and the engine's, not a seeing said
# not)
_HIDING_VERBS = lexicon.HIDING + tuple(w for w in HIDE_MORE if w not in NOT_SEE)
# the verbs that keep things as they are ("garde tous les puits sauf F-4")
_KEEP_VERBS = ("garde", "gardes", "gardez", "garder", "conserve", "conserves", "conservez", "conserver", "laisse",
               "laisses", "laissez", "laisser", "keep", "keeps", "retain", "leave")
# a limit said with no side ("la limite de la palette à 0,3"): the upper one
_LIMIT_WORDS = ("limite", "limit")
# a value asked to be seen AGAIN ("remets-la", "je veux revoir l'eau"): the
# host's "again" mode on the filter brings it back (assistant_host._AGAIN,
# the same words)
_BACK_WORDS = ("revoir", "remontre", "remontrer", "remontrez", "reaffiche", "reafficher", "reaffichez", "remets",
               "remettez", "remettre", "reapparaitre", "reapparaissent", "de nouveau", "a nouveau", "again", "back",
               "unhide", "bring back", "put back", "ramene", "ramener", "ramenez", "retablis", "retablir",
               "retablissez", "restaure", "restaurer", "restaurez", "restore", "retrouver", "retrouve", "ravoir")


def _exceptions(toks, found):
    """Where the sentence says what is NOT meant: an OTHERS word ("the
    other zones", "sauf", "except"), and "but", "à part", "mais pas" right
    before a name or a value ("every well but F-11 A", "tous les puits à
    part F-4", "everything but oil"), a "pas" after a sort ("les puits, pas
    F-4") — not "but keep the grid", nor "à part ça"."""
    starts = {i for i, _n in _occurrences(toks, OTHERS)}
    named_at = {a for a, _b, typ, *_rest in found if typ in ("obj", "category")}
    for i, t in enumerate(toks):
        if t == "but":
            # "every well but F-11 A", "the wells but not F-4"
            k = i + 2 if toks[i + 1:i + 2] == ["not"] else i + 1
        elif toks[i:i + 2] == ["a", "part"] or toks[i:i + 2] == ["mais", "pas"]:
            k = i + 2                                   # "à part F-4", "mais pas F-4"
        elif t in ("pas", "not") and i and (toks[i - 1] in slots.GENERIC or toks[i - 1] in slots.FAMILY_NOUNS):
            k = i + 1                                   # "les puits, pas F-4" — not "ne cache pas F-4"
        else:
            continue
        if k < len(toks) and toks[k] in _ARTICLES:
            k += 1
        if k in named_at:
            starts.add(i)
    return starts


def _others_hidden(toks, starts):
    """Is a word of what is not meant (`_exceptions`) what a hiding verb
    hides: "hide the other zones", "cache les puits autres que F-4", "cache
    tout sauf l'eau", "drop the rest" — articles, "tout", a sort of object
    allowed between?"""
    for i, n in _occurrences(toks, _HIDING_VERBS):
        k = i + n
        while k < len(toks) and k not in starts and (toks[k] in _TO_OTHERS or toks[k] in slots.GENERIC):
            k += 1
        if k in starts:
            return True
    return False


def _hidden_sort(toks, found, starts, in_obj, verbs):
    """The sort of object the verb (one of `verbs`) acts on before what is
    not meant — a group ("cache TOUS LES PUITS sauf F-4", "show ALL WELLS
    except F-4") or a sort said without a name ("hide WELLS except F-4"):
    "well", "horizon"…, or None. Not the sort of a name ("just the Volve
    grid, hide the rest"), nor what is said before the verb ("show the
    wells and Hugin, hide the rest")."""
    first = min(starts) if starts else 0
    ends = [i + n for i, n in _occurrences(toks, verbs) if i + n <= first]
    begin = max(ends) if ends else first
    for a, b, typ, v, _sc in found:
        if typ == "group" and begin <= a and b <= first:
            return v
    for k in range(begin, first):
        t = toks[k]
        fam = slots.FAMILY_NOUNS.get(t) or slots.FAMILY_NOUNS.get(t[:-1] if t.endswith("s") else t)
        if fam and not in_obj[k] and not (k + 1 < len(toks) and in_obj[k + 1]) and not (k and in_obj[k - 1]):
            return fam
    return None


def _not_only(said, toks):
    """A restriction said not: "ne montre pas que la grille", "n'affiche pas
    que les puits", "pas seulement les puits", "don't show only the wells"
    — not the wish of "je ne veux pas que les puits soient visibles"."""
    return _has(said, _NOT_ONLY) or any(toks[i:i + 2] == ["pas", "que"] and i and toks[i - 1] in _SHOW_WORDS
                                        for i in range(len(toks)))


def _everything_said(objects, read, toks, found, spanned, in_obj):
    """Every object the sentence names, each once: the named ones and the
    properties of each kind said (`resolve`), every object of each group
    said ("the wells and the horizons"), and of each sort said without a
    name ("la grille" beside "les puits" — not the sort of a name: "la
    grille Hugin")."""
    out = resolve(objects, read["objects"], read["kind"]) if (read["objects"] or read["kind"]) else []
    for k in read["kinds"]:
        if k != read["kind"]:
            out += resolve(objects, [], k)
    families = [v for _a, _b, typ, v, _sc in found if typ == "group"]
    for i, t in enumerate(toks):
        fam = slots.FAMILY_NOUNS.get(t)
        if fam and not spanned[i] and not (i + 1 < len(toks) and in_obj[i + 1]) and not (i and in_obj[i - 1]):
            families.append(fam)
    for fam in families:
        out += [o for o in objects if in_group(fam, o) and not o.get("parent")]
    return _unique(out)


def _first_layers(toks, found, in_obj):
    """"keep the top 10 layers", "les 8 premières couches", "the first 15
    layers": a word of the first ones next to the number — not "counting
    from the top", nor the Top of a title ("la couche 3 sous Top Hugin")."""
    for a, _b, typ, _v, _sc in found:
        if typ != "num":
            continue
        before = toks[a - 1] if a and not in_obj[a - 1] else ""
        after = toks[a + 1] if a + 1 < len(toks) and not in_obj[a + 1] else ""
        if before in _FIRST_WORDS or after in _FIRST_WORDS:
            return True
    return False


def _refused(toks, start, end):
    """Is what toks[start:end] says before a palette a refusal of it: "je ne
    veux pas voir la porosité en (jet)", "don't show it in (grey)", "au lieu
    de (jet)"?"""
    seg = toks[start:end]
    return any(t in _REFUSING for t in seg) or _has(" " + " ".join(seg) + " ", _REFUSING_PHRASES)


def _preset_refused(text, preset):
    """Is the one palette said refused in its own clause ("pas en jet", "je
    ne veux pas voir la porosité en jet") — not by another clause ("je ne
    veux pas de NaN, passe en jet")?"""
    words = [tuple(normalize(p).split()) for p in lexicon.PRESETS.get(preset, ())]
    for clause in re.split(r"[,;:.!?]", str(text or "")):
        toks = normalize(clause).split()
        for i in range(len(toks)):
            if any(tuple(toks[i:i + len(w)]) == w for w in words):
                return _refused(toks, 0, i)
    return False


def _unasked(toks):
    """A request said as a question, the request itself: "why don't you
    hide the wells" -> "hide the wells", "pourquoi ne pas filtrer…" ->
    "filtrer…", "pourquoi tu ne masques pas les puits" -> "masques les
    puits"; a thing suggested, the thing asked: "pourquoi pas la palette
    jet ?" -> "la palette jet", "why not a slice along i?" -> "a slice
    along i". A question that asks no gesture ("pourquoi la porosité est si
    basse ?", "pourquoi pas de puits ?") stays as it is."""
    for p in _INDIRECT:
        n = len(p)
        if tuple(toks[:n]) != p or n >= len(toks):
            continue
        rest = toks[n:]
        if rest[0] in ("pas",) and len(rest) > 1:
            rest = rest[1:]
        if rest[0] not in multi.VERBS and rest[0] not in lexicon.HIDING:
            if p in (("why", "not"), ("pourquoi", "pas")) and (
                    rest[0] in _SUGGESTED or slots._match_at(rest, 0, slots._PRESET_PHRASES)[0]):
                return list(rest)
            return toks
        if p[-1] in ("ne", "n") and len(rest) > 1 and rest[1] in ("pas", "plus"):
            rest = rest[:1] + rest[2:]
        return list(rest)
    return toks


def _domain_words():
    """The words of the trade and of the gestures: one of them said, a
    sentence is about the application."""
    global _DOMAIN
    if _DOMAIN is None:
        words = set()
        for table in (lexicon.PANELS, lexicon.PRESETS, lexicon.AXES, lexicon.GROUPS, lexicon.CATEGORIES):
            for ps in table.values():
                for p in ps:
                    words.update(normalize(p).split())
        for v in lexicon.KINDS.values():
            for p in v["say"]:
                words.update(normalize(p).split())
        # the view's gestures, and what the application does elsewhere
        for table in (lexicon.DIRECTIONS, lexicon.ZOOM, lexicon.STYLES, lexicon.SCALES, lexicon.TOOLS,
                      lexicon.TOOLS_IF_OPENED):
            for ps in table.values():
                for p in ps:
                    words.update(normalize(p).split())
        for group in (lexicon.TOPICS, lexicon.HIDING, HIGHLIGHT_WORDS, FILTER_WORDS, HIDE_MORE, CROSSING_WORDS,
                      WELL_WORDS, CELL_WORDS, CLEAR_WORDS, STAT_WORDS, tuple(multi.VERBS), tuple(_ZOOM_WORDS),
                      _TIME_WORDS, _REALIZATION_WORDS, _ELSEWHERE_WORDS, ("animation", "legende", "colorbar")):
            for p in group:
                words.update(normalize(p).split())
        # the everyday verbs and little words say nothing of the domain — a
        # verb of the catalogue does ("show me what I asked for")
        _DOMAIN = frozenset(words - (set(slots.STOP) - multi.VERBS) - _GENERIC_VERBS)
    return _DOMAIN


_DOMAIN = None
_GENERIC_VERBS = frozenset("""
donne donner donnes donnez fais faire faites give make put set get take use utilise utiliser mets mettre passe
passer change changer lance lancer let go see voir dis dire tell want veux voudrais can peux
""".split())


def parse(text, objects=(), m=None, context=None):
    """The command `text` asks for (see the module docstring). `m` replaces
    the shipped model. `context`: what the session's last command was about
    ({"intent", "category", "categories", "kind", "exclude", "targets":
    [paths]}) — a sentence that names nothing new and refers back ("the
    other zones", "highlight them") takes it up."""
    m = m or model()
    # "quels puis traversent…": the "puis" of a well, as multi.split reads it;
    # "why don't you hide the wells": the request itself
    said_toks = _tokens(multi.mend(text))
    toks = _unasked(said_toks)
    objects = list(objects or ())
    found = slots.spans(toks, objects, caps=slots.capitals(text))
    read = slots.read(toks, found)
    # a word of the lexicon that is ALSO the name of an object of the session
    # ("show poro", the property titled poro; "perméabilité horizontale",
    # the one titled Horizontal Permeability — in either language,
    # bilingual.py): the name the reader sees in the tree wins — not every
    # property of that kind
    kind_names = 0
    for s, e, typ, _v, _sc in found:
        if typ != "kind":
            continue
        hits, widest = [], 0
        for a in range(max(0, s - 2), s + 1):
            for b in range(e, min(len(toks), e + 2) + 1):
                hit = [o for o in objects if bilingual.same_name(toks[a:b], o.get("title", ""))]
                if hit and b - a > widest:
                    hits, widest = hit, b - a
        if hits:
            read["objects"].append([dict(o, score=1.0) for o in hits])
        # "c'est quoi le GR": the kind's word is an object's very title
        if hits or any(normalize(o.get("title", "")) == " ".join(toks[s:e]) for o in objects):
            kind_names += 1
    # a slip in a verb, mended before any cue word is looked for
    toks = _mend(toks, found)
    said = " " + " ".join(toks) + " "
    # "no, not the gas, the oil": the value said NOT is not the one
    cats = [(a, v) for a, _b, typ, v, _sc in found if typ == "category"]
    kept = [v for a, v in cats if not _denied(toks, a)]
    if kept and len(kept) < len(cats):
        read["categories"] = list(dict.fromkeys(kept))
        read["category"] = read["categories"][0]
    # "je ne veux pas voir la porosité en jet, mets-la en viridis", "don't
    # show it in grey, use jet instead": the palette said NOT is set aside,
    # the other one taken
    presets = [(a, b, v) for a, b, typ, v, _sc in found if typ == "preset"]
    if len({v for _a, _b, v in presets}) > 1:
        wanted = [v for k, (a, _b, v) in enumerate(presets) if not _refused(toks, presets[k - 1][1] if k else 0, a)]
        if wanted and len(wanted) < len(presets):
            read["preset"] = wanted[0]
    # "passe de jet à viridis", "switch from jet to viridis": the palette
    # after "à" / "to" is the one wanted, the one after "de" / "from" the
    # one left
    for k in range(1, len(presets)):
        (a0, _b0, v0), (a1, _b1, v1) = presets[k - 1], presets[k]
        if (v0 != v1 and a0 > 0 and toks[a0 - 1] in ("de", "from") and a1 > 0
                and toks[a1 - 1] in ("a", "au", "to", "into", "vers")):
            read["preset"] = v1
    # … and "pas en jet" alone sets no palette: the assistant asks (the "pas"
    # of "pourquoi pas en jet ?" suggests it)
    refused_preset = (len({v for _a, _b, v in presets}) == 1 and len(toks) == len(said_toks)
                      and _preset_refused(text, presets[0][2]))
    # a small memory of the session: "now hide the other zones" after the
    # water was lit — the sentence names nothing new, it refers back. In a
    # crossing sentence, wells said by their sort name nothing new ("where
    # the wells cross these zones": the zone is the last command's)
    crossing = (_has(said, CROSSING_WORDS) and _has(said, WELL_WORDS) and not _has(said, STAT_WORDS))
    only_sorts = bool(read["objects"]) and all(o.get("by_sort") for c in read["objects"] for o in c)
    # — nor, there, objects found by a resemblance only ("the blocks of the
    # wellbores crossing this zone": "blocks" is not fault_blocks, "zone"
    # not the OilZone representation)
    approx = bool(read["objects"]) and all(o.get("score", 1.0) < 1.0 for c in read["objects"] for o in c)
    # — nor a zone said as such ("this zone", "the other zones") that only
    # resembles a *Zone representation's title
    zone_words = bool(read["objects"]) and all(
        " ".join(toks[a:b]) in ZONE_NOUNS for a, b, typ, _v, _sc in found if typ == "obj")
    named_new = read["objects"] and not (zone_words or ((only_sorts or approx) and crossing))
    # "the wells" of a crossing sentence are all the wells: no new subject
    grouped = read["group"] and not (crossing and read["group"] == "well")
    # "où les wellbores LES intersectent", "where the wells cross THEM": the
    # pronoun next to the crossing verb is the last command's zone
    pronoun = crossing and any(
        t in ("les", "y", "them", "it") and ((i + 1 < len(toks) and toks[i + 1] in CROSSING_WORDS)
                                            or (i > 0 and toks[i - 1] in CROSSING_WORDS))
        for i, t in enumerate(toks))
    # what the sentence says is NOT meant ("the other zones", "tous les puits
    # sauf F-4", "every well but F-11 A")
    starts = _exceptions(toks, found)
    if (context and not (named_new or read["kind"] or read["category"] or grouped)
            and (_refers(toks) or pronoun)) or _others_of_its_kind(read, context, objects, starts):
        _take_up(read, context, objects)
    if m is None or not toks:
        return {"intent": None, "confidence": 0.0, "alternatives": [], "slots": read,
                "targets": [], "missing": [], "sure": False, "text": text}
    delexed = slots.delex(toks, found)
    probs = dict(zip(m.intents, (float(p) for p in m.proba(delexed))))
    # a reading of a gesture said without the words of that gesture is not
    # it ("encore" is no zoom, "j'ai besoin de la calculatrice" closes
    # nothing): its share goes to the other readings
    if not _cued(max(probs, key=probs.get), toks, said, read):
        drop = {i for i in probs if not _cued(i, toks, said, read)}
        rest = sum(p for i, p in probs.items() if i not in drop)
        if rest > 0:
            probs = {i: (0.0 if i in drop else p / rest) for i, p in probs.items()}
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])[:3]
    intent, conf = ranked[0]
    # the classifier always names SOME command, even for "xqzt". A sentence
    # that names nothing the engine knows (no object, kind, panel, number…)
    # and wins no real confidence is not understood — the assistant then
    # shows examples instead of asking "did you mean help?" ("the surface",
    # "the well": a sort of object said without its name is something
    # recognised — the assistant asks which one)
    # — and whatever the confidence when NO word of the sentence is one the
    # model was trained on or the engine knows: random letters hash to
    # columns that carry weights all the same
    unknown = not any(known_word(t, m) for t in toks)
    # a lone letter ("k", "l") is a slip of the hand, not a request
    if len(toks) == 1 and len(toks[0]) < 2 and not found:
        unknown = True
    # nor is a sentence of no word of the trade, read with little confidence
    # ("give me the apple pie recipe")
    foreign = (conf < OUT_OF_DOMAIN and not any(t in _domain_words() for t in toks)
               and not _has(said, COMPLAINT_MARKS))
    # nor thanks, a go-ahead or a pause ("merci", "vas-y", "hmm"); nor a
    # question that names nothing of the trade ("tell me a joke"): the local
    # AI answers from the documentation of the domain
    small_talk = all(t in _SMALL_TALK for t in toks)
    # (a notion slipped by a letter is still one: "pilar")
    off_topic = (intent == "ask" and not any(t in _domain_words() or _near_topic(t) for t in toks)
                 and not _has(said, COMPLAINT_MARKS))
    # … but "pourquoi il n'y a rien à l'écran ?" is heard as a complaint
    # (below), however unsure the classifier is
    why_empty = _has(" " + " ".join(toks[:4]) + " ", WHY_WORDS) and _has(said, COMPLAINT_MARKS + _EMPTY)
    if ((conf < NOT_UNDERSTOOD or foreign or unknown or small_talk or off_topic) and not found and not why_empty
            and not read.get("from_context") and not any(t in slots.NOUNS for t in toks)):
        return {"intent": None, "confidence": round(conf, 3), "alternatives": ranked[:3],
                "slots": read, "targets": [], "missing": [], "sure": False, "text": text}
    nums = list(read["numbers"])
    hiding = _has(said, lexicon.HIDING + HIDE_MORE)
    # "the other zones", "everything but the oil" — but "keep the rest" says
    # the rest stays
    others = bool(starts) and not _has(said, KEEP_ALL)
    # … and the others are what a hiding verb hides: "hide the other zones",
    # "cache les puits autres que F-4", "drop the rest" — not "masque l'huile
    # et laisse les autres", "…pas les autres", where the others stay
    others_hidden = others and _others_hidden(toks, starts)
    # the cells a well goes through (the blocked wellbores), said with any
    # verb: "highlight the cells the wells cross", "which wells cross the
    # oil zone", "show the blocked wellbores" — the grid's cells, a zone or
    # a value said with it ("the GR along the well" is a log)
    grids = {o.get("path") for o in objects if (o.get("type") or "") in GRID_TYPES}
    cells_said = (_has(said, CELL_WORDS) or bool(read["category"]) or pronoun or _has(said, _VALUE_WORDS)
                  or any(o.get("path") in grids for c in read["objects"] for o in c))
    if crossing and cells_said:
        intent, conf = "well_cells", max(conf, SURE)
        ranked = [("well_cells", conf)] + [r for r in ranked if r[0] != "well_cells"]
    # the last command was about the wells through a zone: "highlight the
    # cells of these wells", "those wells, hide them", "highlight them",
    # "show them on the grid", "affiche leurs mailles" — not "remove the
    # zones other than oil": a sentence of the zones or the grid that names
    # a value or the others is about the grid's values
    if (context and context.get("intent") == "well_cells" and intent != "complain"
            and (_refers(toks) or toks[-1] in ("les", "them", "it"))
            and (_has(said, WELL_WORDS) or not (_has(said, ZONE_GRID_WORDS) and (read["category"] or others)))
            and (_has(said, WELL_WORDS) or _has(said, HIGHLIGHT_WORDS) or hiding or _pronoun_after_verb(toks)
                 or any(t in ("ones", "ceux", "celles", "them", "leurs", "their") for t in toks))):
        intent, conf = "well_cells", max(conf, SURE)
        if read["category"] is None and not read["kind"]:
            read["category"] = context.get("category")
            read["categories"] = _context_categories(context)
            read["from_context"] = True
    # "and for the gas?", "same for the water", "and the water zone now":
    # the last command again, with this value (and as it was: a hidden
    # value hides this one too)
    no_verb = not any(t in multi.VERBS or t in CROSSING_WORDS for t in toks)
    if (context and context.get("intent") in ("threshold", "highlight", "well_cells", "show") and not crossing
            and read["category"] and no_verb and len(toks) <= 7 and not read["kind"] and not nums):
        intent, conf = context["intent"], max(conf, SURE)
        read["repeat"] = True
        if context.get("exclude") and intent == "threshold":
            read["exclude"] = True
    # "et en dessous de 0,1 ?", "and above 0.3?": a bound alone, after a
    # filter or a highlight, is that gesture again, with this bound, on the
    # property the last command was about
    if (context and context.get("intent") in ("threshold", "highlight") and intent in ("threshold", "highlight")
            and not crossing and no_verb
            and not read["category"] and (not read["kind"] or read.get("from_context"))
            and (not read["objects"] or read.get("from_context")) and len(toks) <= 7
            and (nums or read["min"] is not None or read["max"] is not None)):
        intent, conf = context["intent"], max(conf, SURE)
        read["repeat"] = True
        if context.get("kind"):
            read["kind"] = context["kind"]
    # "no, I wanted porosity, not permeability", "i meant highlight", "I said
    # water and gas": the last command redone as corrected — the gesture
    # word of the main clause wins (not the one of "…what I had asked you
    # to highlight"); a hiding verb on a value hides that value
    # — and when the main clause says a gesture of its own ("j'ai dit cache
    # les puits", "I told you to zoom on F-4"), that gesture is the command:
    # the last one is redone only when nothing else is asked
    if _has(said, CORRECTION):
        main = _main_clause(toks)
        main_said = " " + " ".join(main) + " "

        def wanted(words):
            return any(t in words and not _denied(main, i) for i, t in enumerate(main)) or any(
                " " in w and f" {w} " in main_said for w in words)
        before, decided = intent, True
        own = _own_verb(main)
        hides_things = (wanted(lexicon.HIDING + HIDE_MORE) and not read["category"]
                        and bool(read["objects"] or read["group"] or read["kind"]))
        if not context:
            decided = False
            if own and hides_things:
                # "I told you to hide the wells": that hiding, as sure as said
                intent, conf = intent if intent in ("hide", "isolate") else "hide", max(conf, SURE)
        elif read["category"] and wanted(lexicon.HIDING + HIDE_MORE):
            intent = "threshold"
            read["exclude"] = not others_hidden
        elif wanted(HIGHLIGHT_WORDS):
            intent = "highlight"
        elif wanted(FILTER_WORDS) or _restrictive(main):
            intent = "threshold"
        elif own:
            decided = hides_things
            if decided and intent not in ("hide", "isolate"):
                intent = "hide"
        elif context.get("intent") in ("threshold", "highlight", "show", "hide", "well_cells", "value",
                                       "colormap", "describe", "open_panel"):
            intent = context["intent"]
            if intent == "threshold" and context.get("exclude") and read["category"]:
                read["exclude"] = True
        if decided and (intent != before or intent != "complain"):
            conf = max(conf, SURE)
            read["repeat"] = True          # decided here: no "filter or highlight?" after
            if not (read["kind"] or read["category"] or read["objects"] or read["group"]):
                _take_up(read, context, objects)
    # "what's PHIT", "c'est quoi Hugin", "c'est quoi le GR": a name asked
    # about is described — "what is Hugin's porosity" asks a value of it
    spanned = [False] * len(toks)
    in_obj = [False] * len(toks)
    for a, b, typ, *_rest in found:
        for i in range(a, b):
            spanned[i] = True
            in_obj[i] = in_obj[i] or typ == "obj"
    kind_spans = sum(1 for f in found if f[2] == "kind")
    obj_said = any(f[2] == "obj" for f in found)
    for p in _WHAT_IS:
        n = len(p)
        if tuple(toks[:n]) != p or n >= len(toks):
            continue
        if ((obj_said or kind_names) and kind_spans <= kind_names
                and all(spanned[i] or toks[i] in _ARTICLES for i in range(n, len(toks)))):
            intent, conf = "describe", max(conf, SURE)
        elif (read["kind"] and obj_said and kind_spans > kind_names and intent in ("describe", "ask", "show")
              and all(spanned[i] or toks[i] in _ARTICLES or toks[i] in ("s", "of", "de", "du")
                      for i in range(n, len(toks)))):
            intent, conf = "value", max(conf, SURE)
        break
    # "calcule PHIT * NTG", "compute PHIT times NTG", "calcule une porosité
    # effective à partir de PHIT et du NTG", "make a property from PHIT and
    # SW": a new property computed from others is the calculator —
    # "calcule la moyenne de la porosité" stays a value, "compute the
    # statistics…" the panel said
    props_said = sum(1 for _a, _b, typ, v, _sc in found
                     if typ == "kind" or (typ == "obj" and any(o.get("parent") for o in v)))
    computing = (any(t in _COMPUTING for t in toks) and not _has(said, STAT_WORDS)
                 and (bool(re.search(r"[*×]", str(text))) or _has(said, _OPERATIONS) or props_said >= 2))
    making = any(t in _MAKING_PROPERTY and toks[i + 1:i + 2] and toks[i + 1] in _A_NEW
                 and any(w in ("property", "properties", "propriete", "proprietes") for w in toks[i + 1:i + 4])
                 for i, t in enumerate(toks))
    if (computing or making) and read["panel"] in (None, "calculator"):
        intent, conf = "open_panel", max(conf, SURE)
        read["panel"] = "calculator"
    # "la calculette", "les stats": a panel said alone is opened
    if (read["panel"] and intent != "open_panel" and len(toks) <= 3
            and all(spanned[i] or t in _ARTICLES for i, t in enumerate(toks))):
        intent, conf = "open_panel", max(conf, SURE)
    # "poro", "the wells": a name ALONE — every word in a span, an article
    # apart — is a show ("average NTG", "remove Hugin" say more than a name)
    if (len(toks) <= 3 and (read["objects"] or read["group"] or read["kind"]) and not nums
            and not read["category"] and all(spanned[i] or t in _ARTICLES for i, t in enumerate(toks))
            and intent in ("show", "value", "list", "describe", "help", "hide", "isolate", "complain", "ask")):
        intent, conf = "show", max(conf, SURE)
    # "je ne veux pas voir les puits", "n'affiche pas Top Hugin", "don't show
    # the wells": seeing said not, of things, is hiding them — not "ne montre
    # pas QUE la grille", which shows more (below)
    not_only = _not_only(said, toks)
    if (_has(said, NOT_SEE) and not read["category"] and (read["objects"] or read["group"] or read["kind"])
            and intent in ("show", "complain", "describe", "value", "list", "ask", "help", "clear_threshold", "hide_all")
            and not not_only):
        intent, conf = "hide", max(conf, SURE)
    # "I'm thinking of hiding the wells", "c'est pas ça, cache les puits": a
    # hiding verb said of things is a hiding, not a complaint — as sure as
    # the sentence was
    if (intent == "complain" and not read["category"] and (read["objects"] or read["group"] or read["kind"])
            and any(not _negated(toks, i, n) for i, n in _occurrences(toks, _HIDE_WORDS))
            and not _has(said, COMPLAINT_MARKS)):
        intent = "hide"
    # "ne cache pas F-4", "don't hide the wells", "ne masque pas la grille":
    # a hiding said NOT, of things, keeps them in view — a show (a seeing
    # said not, "je ne veux pas voir les puits", is the hiding above)
    if (intent in ("hide", "isolate", "hide_all") and not read["category"]
            and (read["objects"] or read["group"] or read["kind"]) and not _has(said, NOT_SEE)):
        hides = list(_occurrences(toks, _HIDE_WORDS))
        if hides and all(_negated(toks, i, n) for i, n in hides):
            intent, conf = "show", max(conf, SURE)
    # "why not the porosity of Hugin?": a thing suggested is a thing to show
    # — never a statistic or a description asked
    if (len(toks) < len(said_toks) and tuple(said_toks[:2]) in (("why", "not"), ("pourquoi", "pas"))
            and (read["objects"] or read["group"] or read["kind"]) and not read["category"]
            and intent in ("value", "describe", "list", "help", "ask")):
        intent, conf = "show", max(conf, SURE)
    # "show me what I asked for": nothing named, the answer missed
    if (_has(said, _WHAT_I_ASKED) and (multi._words(" ".join(toks))[:1] or [""])[0] in multi.VERBS
            and not (read["objects"] or read["group"] or read["kind"] or read["category"] or read["panel"]
                     or read["preset"])
            and intent in ("list", "help", "show", "ask", "describe", "value")):
        intent = "complain"
    # "porosité pas plus de 0,2": a kind and its bound are a filter, not a
    # complaint — the "pas" is the bound's ("no more than")
    if (intent == "complain" and read["kind"] and (read["min"] is not None or read["max"] is not None)
            and not _has(said, COMPLAINT_MARKS)):
        intent = "threshold"
        ranked = [("threshold", conf)] + [r for r in ranked if r[0] not in ("threshold", "complain")]
    # "stop making the cells stand out", "cancel the highlight", "ne surligne
    # pas l'huile": the highlight goes, it is not asked again
    if intent == "highlight" and _has(said, STOP_LIGHT):
        intent, conf = "clear_highlight", max(conf, SURE)
    # "fais le filtre", "applique le seuil": a gesture made, not removed
    if intent in ("clear_threshold", "clear_highlight") and not _has(said, CLEAR_WORDS + lexicon.HIDING) and any(
            t in _MAKING and toks[i + 1:i + 2] and toks[i + 1] in _ARTICLES and toks[i + 2:i + 3]
            and toks[i + 2] in multi._GESTURE_NOUNS for i, t in enumerate(toks)):
        intent = "threshold" if intent == "clear_threshold" else "highlight"
    # "cut everything with a density under 2.2": a cut at a VALUE of a
    # property, with no axis, is a filter, not a slice
    if (intent == "slice" and not read.get("axis") and read["kind"]
            and (nums or read["min"] is not None or read["max"] is not None)
            and _has(said, lexicon.ABOVE + lexicon.BELOW + ("sous", "under", "over", "au dela", "beyond"))):
        intent, conf = "threshold", max(conf, SURE)
    if intent == "well_cells":
        # "remove the wells that do NOT go through the oil zone", "keep only
        # the wells that cross it": the wells that stay out go; "hide the
        # wells that cross the zone": the ones that do; "hide the other
        # wells" after the crossing ones: the others go
        negated = "pas" in toks or _has(said, NEGATION) or _has(said, OUT_WORDS) or _has(said, OTHERS)
        if hiding:
            read["well_filter"] = "keep_crossing" if negated else "hide_crossing"
        elif _has(said, ("garde", "garder", "gardes", "conserve", "conserver", "keep", "keeps", "isole",
                         "isoler", "isolate", "only", "seulement", "uniquement", "que les", "just the")):
            read["well_filter"] = "keep_crossing"
        elif _has(said, STILL_WORDS) and negated:
            read["well_filter"] = "keep_crossing"
    # the camera, the time steps, the drawing style, the colour scale and
    # bar, the tool cards, the panels closed, the view emptied
    intent, conf = _gestures(intent, conf, toks, said, read, nums, hiding, others)
    # ------------------------------------------------------------------
    # YOUR RULES HERE. A rule: words in the sentence -> a command. The model
    # has already spoken (`intent`, `conf`; `probs` holds its probability
    # of every command); the sentence is in `said` (space-padded, no
    # accents, no capitals, verb slips mended); `_has(said, (...))` tells
    # whether one of those words is there; `read[...]` holds what was read
    # (kind, category, min, max, objects…). A rule sets `intent, conf =
    # "<command>", max(conf, SURE)`. The rules below may still turn a
    # sentence with a category value into a filter or a "filter or
    # highlight?" question: a rule that must win sets `read["repeat"] =
    # True`. Each rule comes with its sentences in tests/unit/test_nlu.py.
    # ------------------------------------------------------------------
    # "hide the other zones" after the oil was lit, "remove the zones other
    # than oil": hide what is NOT that value — keep only it, a filter
    if (read["category"] and intent != "well_cells"
            and ((hiding and others_hidden)
                 or (others and read.get("from_context") and intent in ("hide", "hide_nan", "isolate",
                                                                        "clear_threshold")))):
        intent, conf = "threshold", max(conf, SURE)
    # "hide the oil zone", "hide them" (after the oil was lit), "masque
    # l'huile et laisse les autres": hide THAT value, keep the others — a
    # filter on every other code
    if (read["category"] and hiding and not others_hidden and intent != "well_cells"
            and intent in ("hide", "threshold", "hide_nan", "isolate", "clear_threshold", "show", "complain",
                           "hide_all")):
        intent, conf = "threshold", max(conf, SURE)
        read["exclude"] = True
    # "filtre-les", "garde que ça" on the value just lit: a filter ("filtre
    # les" reads like "les filtres" — remove them — out of context)
    if (read.get("from_context") and read["category"] and _filters(said, toks)
            and intent in ("clear_threshold", "show", "hide_nan", "isolate")):
        intent, conf = "threshold", max(conf, SURE)
    # "on ne voit plus l'huile, remets-la", "je veux revoir l'eau", "bring
    # the gas back": a value asked to be seen again comes back (the host's
    # "again" mode on the filter) — never a camera reset ("remets la caméra"
    # says the camera), never a question; not a value said not, nor one
    # hidden in the same breath
    if (read["category"] and not hiding and not others and not read.get("repeat")
            and not _has(said, HIGHLIGHT_WORDS) and not _has(said, _RESET_WORDS)
            and any(not _negated(toks, i, n) for i, n in _occurrences(toks, _BACK_WORDS))
            and intent in ("reset_camera", "complain", "threshold", "show", "ask", "hide", "isolate", "value",
                           "undo")):
        intent, conf = "threshold", max(conf, SURE)
        read["repeat"] = True
    # "masque la porosité sous 0,05", "cache les mailles de porosité sous
    # 0,1 mais pas les autres", "masque les mailles de porosité au-dessus de
    # 0,3, laisse le reste": a hiding verb on a kind with its bound hides
    # cells by value — a filter (the bound turned over below), whatever
    # the "leave the rest" made the classifier think of a highlight
    if (read["kind"] and (read["min"] is not None or read["max"] is not None) and not read["category"]
            and hiding and not _has(said, HIGHLIGHT_WORDS)
            and intent in ("hide", "isolate", "show", "threshold", "highlight", "hide_all")):
        intent, conf = "threshold", max(conf, SURE)
    # "cache tous les puits sauf F-4", "hide every well but F-11 A", "hide
    # the wells other than F-12": the group said, but the objects named —
    # the other wells are hidden, the grid and the rest stay; "cache tout
    # sauf Hugin": what stays is the object named — an isolation
    # — and "cache tous les autres puits" after F-4 was shown: the wells but
    # the last command's
    # — and "masque les autres fluides" with nothing lit before names no
    # object (the kind's word only resembles the Fluids title): the
    # assistant asks rather than isolate it
    spared = None
    if not read["category"] and others_hidden and read["objects"] and intent in ("hide", "show", "threshold",
                                                                                   "isolate", "hide_all"):
        family = _hidden_sort(toks, found, starts, in_obj, _HIDING_VERBS)
        sort_said = [slots.FAMILY_NOUNS.get(toks[a]) for a, _b, typ, v, _sc in found
                     if typ == "obj" and all(o.get("by_sort") for o in v)]
        if sort_said and len(sort_said) == len(read["objects"]) and context and context.get("targets"):
            intent, conf = "hide", max(conf, SURE)
            spared = (family or sort_said[0], set(context["targets"]))
        elif family:
            intent, conf = "hide", max(conf, SURE)
            spared = (family, {o.get("path") for c in read["objects"] for o in c})
        elif any(f[2] == "obj" for f in found):
            intent, conf = "isolate", max(conf, SURE)
        else:
            conf = min(conf, SURE - 0.01)
    # "garde tous les puits sauf F-4", "keep every well but F-11 A": the
    # wells stay as they are, the one said not goes — a hiding of the one
    # named, nothing isolated
    elif (not read["category"] and others and read["objects"]
          and intent in ("show", "isolate", "hide", "threshold")
          and _hidden_sort(toks, found, starts, in_obj, _KEEP_VERBS)):
        intent, conf = "hide", max(conf, SURE)
        read["group"] = None
    # "show all wells except F-4", "n'affiche que les puits sauf F-4", "isole
    # les puits sauf F-4": the group said, but the objects named, shown or
    # kept alone — never the one said not alone
    elif not read["category"] and others and read["objects"] and intent in ("show", "isolate"):
        family = _hidden_sort(toks, found, starts, in_obj, _SHOW_WORDS + tuple(sorted(multi._ISOLATING)))
        if family:
            conf = max(conf, SURE)
            spared = (family, {o.get("path") for c in read["objects"] for o in c})
            # "show all wells except F-4" shows them; only a word of
            # restriction keeps them alone ("n'affiche que", "isole")
            if (intent == "isolate" and _has(said, _SHOW_WORDS)
                    and not _has(said, _ONLY_WORDS + tuple(multi._ISOLATING))):
                intent = "show"
    # a named property says its kind: "PHIT > 15 %"; a depth its bound:
    # "deeper than 2500 m"
    if read["kind"] is None:
        kinds = {kind_of(o) for cands in read["objects"] for o in cands} - {None}
        if len(kinds) == 1:
            read["kind"] = kinds.pop()
        elif _has(said, _DEPTH_BOUNDS):
            read["kind"] = "depth"
            read["kinds"] = list(read["kinds"]) + ["depth"]
    if intent in BOUNDED and read["min"] is None and read["max"] is None:
        if len(nums) >= 2:
            read["min"], read["max"] = min(nums[:2]), max(nums[:2])
        elif len(nums) == 1 and intent == "slice" and _first_layers(toks, found, in_obj):
            # "keep only the top 10 layers": the first ten
            read["min"], read["max"] = 1.0, nums[0]
        elif len(nums) == 1 and intent == "slice":
            # "montre la couche 12", "cut at k = 10", "show layer 12
            # counting from the top": that one index
            read["min"] = read["max"] = nums[0]
        elif len(nums) == 1:
            # "cap at 150", "palette max at 0.3", "limit the legend to 0.3":
            # a maximum — said outside the names ("filtre Top Hugin à 2500":
            # the Top is a title's), and not of a lower limit
            free = " " + " ".join(t for i, t in enumerate(toks) if not in_obj[i]) + " "
            capping = (multi._words(" ".join(toks))[:1] or [""])[0] in _CAPPING
            # ("fixe la limite de la palette à 0,3": a limit said with no
            # side is the upper one; "limite basse" is a MIN word)
            key = ("max" if (_has(free, lexicon.MAX_WORDS + _LIMIT_WORDS) or capping)
                   and not _has(free, lexicon.MIN_WORDS) else "min")
            read[key] = nums[0]
    # "HIDE the cells below 0.08" keeps what is above: one bound said with a
    # hiding verb is the other bound — "…et garde les autres", "…pas les
    # autres" say it again; "…and drop the rest" hides the rest, not the
    # cells said
    if (intent == "threshold" and _has(said, lexicon.HIDING) and not others_hidden
            and (read["min"] is None) != (read["max"] is None)):
        read["min"], read["max"] = read["max"], read["min"]
    if intent == "z_scale" and read["factor"] is None:
        if nums:
            read["factor"] = nums[0]
        elif read["min"] is not None and read["min"] == read["max"]:
            read["factor"] = read["min"]                        # "z = 1"
        elif _has(said, _TRUE_SCALE):
            read["factor"] = 1.0                                # "back to true vertical scale"
    # a fraction kind: "20 %" and a bare 20 are 0.2 ("porosity above 20") —
    # a bound of a filter, a highlight or a colour range, never a layer of a
    # slice. "raw" keeps the numbers as said: the adapter, which knows the
    # property's unit, takes them back for one stored in % or p.u.
    if read["kind"] in FRACTIONS and intent in ("threshold", "highlight", "color_range", "well_cells"):
        raw = {}
        for key in ("min", "max"):
            v = read[key]
            if v is not None and 1 < v <= 100:
                raw[key], read[key] = v, v / 100.0
        if raw:
            read["raw"] = raw
    if intent in ("hide_nan", "flat_colors"):
        read["on"] = _switch(intent, toks, read)
    bounded = read["min"] is not None or read["max"] is not None
    # "le minimum de l'échelle vaut 0,05 pour la porosité": the side of the
    # colour scale and its number set the colour range, whatever "le
    # minimum de … la porosité" made the classifier think of a statistic
    # asked (which says no number)
    if (intent == "color_range" and bounded and _has(said, _SCALE_WORDS) and not _has(said, ("verticale", "vertical"))
            and _has(said, lexicon.MIN_WORDS + lexicon.MAX_WORDS)):
        conf = max(conf, SURE)
    # two properties or two bounds on the same side for one filter ("poro
    # > 0.2 and perm > 100" said in one breath), a value said NOT ("≠ 0"),
    # a complaint that states a bound ("c'est faux, la porosité est encore
    # au-dessus de 0,3"): the command is not sure, the assistant asks
    if intent in BOUNDED and (read.get("conflict") or read.get("neq")
                              or (len(read.get("kinds") or ()) > 1 and bounded)
                              or (bounded and ((_has(said, _WRONG_WORDS) and not _orders(text))
                                               or (_has(said, _STILL) and toks[0] in ("non", "no"))))):
        conf = min(conf, SURE - 0.01)
    if intent == "colormap" and refused_preset:
        conf = min(conf, SURE - 0.01)
    # a question about what is seen or why ("pourquoi ce puits est encore
    # affiché ?", "est-ce que tu vois des chenaux dans la grille ?") is
    # answered, not carried out — "pourquoi je ne vois rien ?", "why is the
    # grid empty?" are complaints, "est-ce que tu peux masquer…" a gesture
    head = " " + " ".join(toks[:4]) + " "
    if _has(head, WHY_WORDS) and _has(said, COMPLAINT_MARKS + _EMPTY) and intent in ("ask", "value", "describe",
                                                                                     "show", "list", "help"):
        intent, conf = "complain", max(conf, SURE)
    elif not _has(said, COMPLAINT_MARKS) and not (crossing and cells_said) and (
            _has(head, WHY_WORDS) or (_has(said, SEE_QUESTIONS)
                                      and not any(t in multi.VERBS for t in toks if t not in ("voir", "vois")))):
        intent, conf = "ask", max(conf, SURE)
    targets = resolve(objects, read["objects"], read["kind"], read["group"], read["category"])
    # "affiche la porosité et la perméabilité": every kind said is shown —
    # not one said not ("la porosité, pas la perméabilité")
    # — and a kind no object named carries is the session's ("show NTG and
    # porosity": NTG named by its title, the porosity is PHIT's and Poro's)
    if intent in ("show", "hide", "isolate") and len(read["kinds"]) > 1 and not read["category"]:
        denied = {v for a, _b, typ, v, _sc in found if typ == "kind" and _denied(toks, a)}
        for k in read["kinds"]:
            if k != read["kind"] and k not in denied:
                more = resolve(objects, read["objects"], k, read["group"], None)
                if not more and all(o.get("parent") for c in read["objects"] for o in c):
                    more = resolve(objects, [], k)
                targets += more
        targets = _unique(targets)
    coordinated = " et " in said or " and " in said
    # "montre PHIT et Hugin": names said side by side, no kind said (the one
    # PHIT carries filters nothing) — each name is a target
    if (intent in ("show", "hide", "isolate") and coordinated and not read["kinds"] and len(read["objects"]) > 1
            and not read["category"]):
        targets = _unique(targets + [o for c in read["objects"] for o in c])
    # "montre le puits F-4 et la porosité", "affiche SW et SO" (SO named in
    # capitals, SW read as the water saturation): a name and a kind side by
    # side are each a target — a name that the kind would filter away (it is
    # not of that kind and holds no property of it) is one of its own
    if (intent in ("show", "hide", "isolate") and coordinated and read["kind"] and read["objects"]
            and not read["category"]):
        named = _unique([o for c in read["objects"] for o in c])
        idle = [o for o in named if not kind_matches(read["kind"], o)
                and not any(p.get("parent") == o.get("path") and kind_matches(read["kind"], p) for p in objects)]
        if idle:
            extra = list(idle) + (resolve(objects, [], read["kind"]) if len(idle) == len(named) else [])
            targets = _unique(targets + extra)
    # "isole la grille et les puits", "isolate the porosity and the wells":
    # ONE isolation of everything said, the objects, the group and the sorts
    # together; "ne montre pas que la grille, affiche aussi les puits": a
    # restriction said not shows more, it isolates nothing
    together = None
    if not_only and intent in ("isolate", "hide", "show") and not read["category"]:
        intent, conf = "show", max(conf, SURE)
        together = _everything_said(objects, read, toks, found, spanned, in_obj)
    elif intent == "isolate" and coordinated and not read["category"]:
        together = _everything_said(objects, read, toks, found, spanned, in_obj)
    if together and len(together) > len(targets):
        targets = together
    # "cache tous les puits sauf F-4": the group but the objects spared
    if spared:
        family, keep = spared
        targets = [o for o in objects if in_group(family, o) and not o.get("parent") and o.get("path") not in keep]
    # "garde tout sauf le gaz", "show everything but the water": every value
    # but the one said — a filter hiding it; "surligne tout sauf l'eau"
    # lights every other value of the property
    all_but = any(tuple(toks[i:i + 2]) == p for i in range(len(toks) - 1) for p in _ALL_BUT)
    if read["category"] and all_but and not hiding:
        if _has(said, HIGHLIGHT_WORDS):
            props = [t for t in targets if t.get("categories") and t.get("parent") in grids] or \
                    [t for t in targets if t.get("categories")]
            said_values = set(read["categories"] or [read["category"]])
            rest = [c for c in _labels(props[0]) if c not in said_values] if props else []
            if rest:
                read["category"], read["categories"] = rest[0], rest
                intent, conf = "highlight", max(conf, SURE)
                read["repeat"] = True
        elif intent in ("threshold", "show", "highlight"):
            intent, conf = "threshold", max(conf, SURE)
            read["exclude"] = True
            read["repeat"] = True
    # "masque-les", "ne garde que ça", "cache les mailles surlignées", "hide
    # the highlighted cells" after a highlight: the cells it lit (the
    # session's `lit`) — a filter on its values or its range, keeping them,
    # or hiding them (`exclude`); "masque le reste" keeps them — on the
    # property lit (`lit_on`), else the view's active one: the highlight
    # made it so. A kind or objects only taken up from the last command are
    # no other property
    ctx = context or {}
    if (ctx.get("intent") == "highlight" and ctx.get("lit") and not read["category"]
            and (not read["kind"] or (read.get("from_context") and read["kind"] == ctx.get("kind")))
            and all(o.get("path") in (ctx.get("targets") or ()) for c in read["objects"] for o in c)
            and not nums and intent not in ("complain", "undo")
            and (_has(said, LIT_WORDS) or _refers(toks) or toks[-1] in ("ca", "cela"))
            and (hiding or _filters(said, toks))):
        intent, conf = "threshold", max(conf, SURE)
        hide = bool(hiding and not others_hidden)
        lit_on = [o for o in objects if o.get("path") and o.get("path") == ctx.get("lit_on")]
        if lit_on:
            read["kind"], read["objects"], targets = None, [lit_on], lit_on
        if ctx.get("category"):
            read["category"], read["categories"] = ctx["category"], _context_categories(ctx)
            read["from_context"] = True
            read["exclude"] = hide != bool(ctx.get("exclude"))
        else:
            read["min"], read["max"] = ctx["lit"][0], ctx["lit"][1]
            read["exclude"] = hide
        read["repeat"] = True
    # "highlight them" after the oil was kept, "non, surligne-la plutôt": a
    # highlight, not its removal
    if (read["category"] and intent == "clear_highlight" and _has(said, HIGHLIGHT_WORDS)
            and not _has(said, CLEAR_WORDS)):
        intent, conf = "highlight", max(conf, SURE)
    # "show the oil zones": the value's code is the filter's range
    if (intent in ("threshold", "highlight", "show", "well_cells") and read["category"]
            and read["min"] is None and read["max"] is None):
        # a filter acts on a grid: its properties first (the same value may
        # have one code in the grid's lithology, another in the wells'
        # facies logs)
        on_grid = [t for t in targets if t.get("parent") in grids]
        if on_grid:
            targets = on_grid
        codes = {code_of(t, read["category"]) for t in targets} - {None}
        if len(codes) == 1:
            read["min"] = read["max"] = codes.pop()
    # "show the oil zones": keep only those cells, or light them on the
    # whole grid? The sentence does not say: a neutral verb with a category
    # value ASKS, the filter first; "filter", "keep only", "only" filter at
    # once, "highlight" lights at once — and so does a reading the
    # classifier is sure is a highlight ("make the sandstone glow")
    choose_between = None
    if read["category"] and intent in ("threshold", "highlight", "show") and targets and not read.get("repeat"):
        filt, light = _filters(said, toks), _has(said, HIGHLIGHT_WORDS)
        # "hide the others": hiding the rest IS keeping only this value;
        # "hide the oil zone" is a filter too (on the other values)
        filt = filt or bool((others_hidden and hiding) or (others and read.get("from_context")))
        # "keep the rest" says not to filter — unless the value itself is
        # hidden ("masque l'eau et garde le reste"): that is the filter
        filt = (filt and not _has(said, KEEP_ALL)) or bool(read.get("exclude"))
        if light and not filt:
            # a word of lighting said of ONE value lights it, however the
            # sentence goes ("il faudrait que l'huile ressorte") — unless it
            # is said not
            intent = "highlight"
            if (len(read["categories"] or [read["category"]]) == 1 and not any(t in _REFUSING for t in toks)
                    and not _has(said, _REFUSING_PHRASES)):
                conf = max(conf, SURE)
        elif filt and not light:
            intent = "threshold"
        elif not filt and probs.get("highlight", 0.0) >= MODEL_SURE:
            intent, conf = "highlight", max(conf, probs["highlight"])
        else:
            intent, choose_between = "threshold", ["threshold", "highlight"]
            ranked = [("threshold", conf), ("highlight", ranked[1][1] if len(ranked) > 1 else 0.0)]
    # a request no command can carry out that names nothing of the domain
    # either ("écris-moi un poème") is not understood, as before the class
    # of the unsupported requests existed
    if (intent == "unsupported" and not found and not any(t in _domain_words() for t in toks)
            and not read.get("from_context")):
        return {"intent": None, "confidence": round(conf, 3), "alternatives": ranked[:3],
                "slots": read, "targets": [], "missing": [], "sure": False, "text": text}
    wanted = dict(read, object=read["objects"] or read["group"] or None)
    if read["category"]:
        # a category value IS the range: the adapter reads its code in the
        # property it acts on — never "between which values?"
        wanted.update(min=wanted.get("min") if wanted.get("min") is not None else read["category"])
    miss = catalogue.missing(intent, wanted)
    # "show the well" with several wells: which one — the sort said in the
    # singular names ONE object; "the wells" of well_cells are ALL the
    # wells, never a question
    by_sort = any(o.get("by_sort") for cands in read["objects"] for o in cands)
    # — nor is a switch about an object ("cache les NaN mais je veux encore
    # voir la grille": the missing values everywhere), nor "the other wells"
    # — nor a gesture of the view itself ("passe la grille en fil de fer":
    # the style is the view's)
    if (by_sort and len(targets) > 1 and not read["kind"] and not read["category"] and not spared
            and "object|kind" not in miss and intent not in ("well_cells", "hide_nan", "flat_colors")
            and intent not in _VIEW_GESTURES):
        miss.append("object|kind")
    out = {"intent": intent, "confidence": round(conf, 3), "alternatives": ranked[1:],
           "slots": read, "targets": targets, "missing": miss,
           "sure": conf >= SURE and not miss and not choose_between, "text": text}
    if choose_between:
        out["choose_between"] = choose_between
    return out


_VIEW_GESTURES = ("close_panel", "camera_view", "zoom", "time_step", "time_play", "realization", "rep_style",
                  "color_scale", "color_bar", "open_tool", "hide_all", "unsupported")
# the words that restrict a showing to what is said ("n'affiche QUE les puits")
_ONLY_WORDS = ("only", "just", "solely", "nothing but", "seulement", "uniquement", "juste", "que", "rien que")
# the words one of these readings needs to be that command — or the slot
# it reads (`_SLOT_CUES`)
_GESTURE_CUES = {
    "close_panel": _CLOSING + ("plus besoin", "done with", "no need", "fini avec", "finished with", "range",
                               "replie", "kill") + lexicon.HIDING + HIDE_MORE,
    "zoom": tuple(_ZOOM_WORDS) + lexicon.ZOOM["in"] + lexicon.ZOOM["out"],
    "camera_view": ("camera", "cameras", "oriente", "orienter", "orient", "angle", "point de vue", "viewpoint"),
    "time_step": _TIME_WORDS,
    "time_play": _TIME_WORDS + ("animation", "anim", "anime", "animer", "animate", "animating", "play", "playing",
                                "playback", "joue", "jouer", "lecture", "film", "movie", "pause", "defiler",
                                "defilement", "evolution"),
    "realization": _REALIZATION_WORDS,
    "rep_style": ("style", "mode", "rendu", "representation", "rendering", "render", "dessine", "draw"),
    "color_scale": ("log", "echelle", "scale"),
    "color_bar": ("legende", "legend", "colorbar", "barre", "bar"),
    "open_tool": ("carte", "card", "outil", "outils", "tool", "tools", "panneau", "panel", "volet"),
    "hide_all": ("tout", "toute", "tous", "everything", "all", "every", "vide", "vider", "empty", "clear", "nettoie",
                 "clean", "wipe", "blank", "ensemble"),
}
_SLOT_CUES = {"camera_view": "direction", "time_step": "step", "rep_style": "style", "color_scale": "scale",
              "open_tool": "tool"}
# a question of what a thing means ("les piliers, ça veut dire quoi ?")
_ASKING = ("veut dire", "veulent dire", "signifie", "signifient", "c est quoi", "qu est ce que", "quoi", "definition",
           "what is", "what are", "what does", "mean", "means", "meaning")
# the things the application shows elsewhere, said with a showing verb
_ELSEWHERE_NOUNS = ("globe", "earth", "terre", "pilier", "piliers", "pillar", "pillars", "capture", "screenshot",
                    "snapshot", "csv", "excel", "osdu", "etp", "opacite", "opacity", "transparence", "transparency",
                    "transparent", "transparente", "fond", "background", "arriere plan")
_TOPIC_WORDS = None


def _near_topic(word):
    """Is `word` one slip from a one-word notion of the trade ("pilar" for
    "pilier")? Only a word of five letters or more."""
    global _TOPIC_WORDS
    if _TOPIC_WORDS is None:
        _TOPIC_WORDS = tuple(t for t in lexicon.TOPICS if " " not in t and len(t) >= 5)
    return len(word) >= 5 and any(abs(len(word) - len(t)) <= 1 and slots.edit_distance(word, t, cap=1) <= 1
                                  for t in _TOPIC_WORDS)


def _cued(intent, toks, said, read):
    """Is a reading said with the words of its command? A gesture of the
    view needs its own (`_GESTURE_CUES`, a slip of a letter forgiven past
    four letters: "fermme", "réalisaton"; or the slot it reads); the cells
    of the wells a word of the wells or of a crossing, when what the
    sentence names is known to be no well ("les blocs de failles de la
    grille")."""
    if intent == "well_cells":
        named = [o for c in read["objects"] for o in c]
        return bool(_has(said, WELL_WORDS + CROSSING_WORDS) or not named or read.get("from_context")
                    or any("well" in (o.get("type") or "").lower() or not o.get("type") for o in named))
    if intent not in _GESTURE_CUES:
        return True
    slot = _SLOT_CUES.get(intent)
    cues = _GESTURE_CUES[intent]
    if (slot and read.get(slot) is not None) or _has(said, cues):
        return True
    words = [c for c in cues if " " not in c and len(c) >= 5]
    return any(len(t) >= 5 and slots.edit_distance(t, c, cap=1) <= 1 for t in toks for c in words)


def _bar_on(toks, said):
    """Is the colour bar to be shown? A hiding word hides it unless it is
    said not ("ne cache plus la légende"); seeing said not, "sans", "pas
    de", "off"… hide it; anything else shows it."""
    hides = [_negated(toks, i, n) for i, n in _occurrences(toks, _HIDE_WORDS)]
    if hides:
        return all(hides)
    return not _has(said, NOT_SEE + _BAR_OFF)


def _gestures(intent, conf, toks, said, read, nums, hiding, others):
    """The view's gestures, told from their neighbours by the words said:
    a zoom with a name or to see everything frames it (reset_camera), a
    zoom said alone is one step; a direction of the camera is a camera
    view, not a new view nor a reset; a step said with a word of time is a
    time step, with a realization's a realization; a drawing style, a
    colour scale or a tool card said is that gesture; a colour bar given
    numbers is the colour range; "ferme" closes a panel; "cache tout"
    empties the view. Fills the slots these commands read (a zoom's in /
    out, the step, the switches)."""
    anything = bool(read["objects"] or read["group"] or read["kind"])
    # a name said (not a sort said alone: "la grille")
    named = bool(read["group"] or read["kind"]
                 or any(not o.get("by_sort") for c in read["objects"] for o in c))
    bounded = read["min"] is not None or read["max"] is not None
    # the vertical scale said ("remets l'échelle verticale normale") is the
    # vertical exaggeration, not the colours'
    if intent in ("rescale", "color_scale", "color_range", "colormap") and _has(
            said, ("verticale", "vertical", "exageration", "exaggeration")):
        intent, conf = "z_scale", max(conf, SURE)
    # what a thing the application shows elsewhere means is a question
    # ("les piliers, ça veut dire quoi ?"); showing it is a request it
    # cannot do here ("show the earth")
    if intent == "unsupported" and _has(said, _ASKING):
        intent, conf = "ask", max(conf, SURE)
    elif (intent == "show" and not named and not read["panel"] and not read["tool"]
          and _has(said, _ELSEWHERE_NOUNS)):
        intent, conf = "unsupported", max(conf, SURE)
    # a zoom, or a reset of the camera
    if intent == "zoom" and (anything or _has(said, _FIT_WORDS)):
        intent, conf = "reset_camera", max(conf, SURE)
    elif (intent == "reset_camera" and any(t in _ZOOM_WORDS for t in toks) and not anything
          and not _has(said, _FIT_WORDS + _RESET_WORDS)):
        intent, conf = "zoom", max(conf, SURE)
    if intent == "zoom":
        read["direction"] = slots.zoom_direction(toks)
    # where the camera stands, said: "vue de dessus", "top view"
    if (read["direction"] and intent in ("new_view", "reset_camera") and not named
            and not _has(said, _NEW_WORDS)):
        intent, conf = "camera_view", max(conf, SURE)
    # a step of time or a realization said ("reviens au pas de temps
    # précédent", "passe au pas de temps suivant", "montre la réalisation 3")
    stepped = read["step"] is not None or bool(nums)
    realized = _has(said, _REALIZATION_WORDS)
    if realized and stepped and intent in ("time_step", "show", "slice", "complain", "undo", "list", "describe"):
        intent, conf = "realization", max(conf, SURE)
    elif (not realized and stepped and _has(said, _TIME_WORDS)
          and intent in ("complain", "undo", "slice", "ask", "show", "realization", "describe", "list")):
        intent, conf = "time_step", max(conf, SURE)
    if intent in ("time_step", "realization") and read["step"] is None:
        n = nums[0] if nums else (read["min"] if read["min"] is not None else read["max"])
        if n is not None:
            read["step"] = int(n) if float(n).is_integer() else n
    if intent == "time_play":
        read["on"] = not _has(said, _STOP_PLAY)
    # a drawing style said of the view ("affiche les arêtes", "show the cell
    # edges") — not the outline of cells lit by value
    if (read["style"] and intent in ("show", "hide", "clear_threshold", "isolate", "highlight") and not bounded
            and not read["category"] and not read["panel"]):
        intent, conf = "rep_style", max(conf, SURE)
    if intent == "rep_style" and read["style"] == "Surface With Edges" and (hiding or read["on"] is False):
        read["style"] = "Surface"                       # "enlève les arêtes"
    # the colour scale said ("passe la perméabilité en log")
    if (read["scale"] and intent in ("colormap", "color_range", "rescale", "show") and not read["preset"]
            and not bounded):
        intent, conf = "color_scale", max(conf, SURE)
    if intent == "color_scale" and read["scale"] == "log" and (hiding or read["on"] is False):
        read["scale"] = "linear"                        # "enlève l'échelle log"
    # the colour bar: with numbers it is the colour range ("légende de 0 à
    # 0,3"), with a palette the colour table
    if intent == "color_bar":
        if bounded or nums:
            intent = "color_range"
        elif read["preset"]:
            intent = "colormap"
        else:
            read["on"] = _bar_on(toks, said)
    # a tool card named, asked open ("ouvre la carte des seuils", "ouvre
    # les seuils") — not removed, closed, nor a filter with its numbers
    if (read["tool"] and not read["panel"] and not bounded and not nums and not read["preset"]
            and not read["category"] and not read["axis"] and not hiding and not _has(said, _CLOSING)
            and intent in ("open_panel", "threshold", "clear_threshold", "colormap", "show", "slice", "time_step",
                           "realization", "describe")):
        intent, conf = "open_tool", max(conf, SURE)
    elif intent == "open_tool" and not read["tool"] and read["panel"]:
        intent = "open_panel"                           # "ouvre l'outil de comparaison"
    # a panel closed ("ferme les stats"); "close the Eclipse grid" hides it
    if intent == "open_panel" and _has(said, _CLOSING) and not _has(said, _OPENING_VERBS):
        intent, conf = "close_panel", max(conf, SURE)
    elif intent == "close_panel" and not read["panel"] and (read["objects"] or read["group"]):
        intent = "hide"
    # the view emptied ("cache tout", "hide everything") — not a name hidden,
    # nor everything but a name (an isolation, below)
    everything = _has(said, ("tout", "everything"))
    if intent == "hide_all" and anything and not others and not everything:
        intent = "hide"
    elif (intent in ("hide", "isolate", "clear_threshold") and everything and hiding and not anything and not others
          and not read["category"] and not bounded):
        intent, conf = "hide_all", max(conf, SURE)
    return intent, conf


def _labels(prop):
    """The values a categorical property lists, by their code, canonical
    ("Oil" -> "oil")."""
    def order(item):
        code = str(item[0]).strip()
        return (0, float(code), "") if _NUMBER.match(code) else (1, 0.0, code)
    return list(dict.fromkeys(slots.category_of(str(lb)) for _c, lb in sorted(
        (prop.get("categories") or {}).items(), key=order)))

def _context_categories(context):
    """The values the last command was about: its list, or its one value."""
    cats = list(context.get("categories") or ())
    if not cats and context.get("category"):
        cats = [context["category"]]
    return cats


def _others_of_its_kind(read, context, objects, starts):
    """"masque les autres faciès" after the channel was lit, "hide the other
    lithologies" after the shale: the others of the property just lit — the
    kind said is that property's own, it names no new subject (the value is
    taken up, and the filter keeps it)."""
    if not (context and starts and read["kind"] and not read["category"] and not read["group"]
            and _context_categories(context)):
        return False
    paths = set(context.get("targets") or ())
    lit = [o for o in objects if o.get("path") in paths]
    return (bool(lit) and all(kind_matches(read["kind"], o) for o in lit)
            and all(o.get("path") in paths for c in read["objects"] for o in c))


def _take_up(read, context, objects):
    """The last command's subject, taken up by a sentence that refers back:
    its value(s), its kind, its targets."""
    read["category"] = context.get("category")
    read["categories"] = _context_categories(context)
    if read["categories"] and not read["category"]:
        read["category"] = read["categories"][0]
    read["kind"] = context.get("kind")
    by = {o.get("path"): o for o in objects}
    back = [dict(by[p], score=1.0) for p in context.get("targets") or () if p in by]
    if back:
        read["objects"].append(back)
    read["from_context"] = True
