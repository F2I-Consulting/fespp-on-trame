"""The application's side of the assistant (widgets/assistant).

It lists the objects the command engine may name and carries out every
command of the catalogue on the application's own controllers. The panel
itself (the conversation, the questions, the choices, the undo stack) is
the widget's `AssistantController`; the sentence is read by the command
engine (ia/nlu); this adapter is the only place that knows the application:
which controller a gesture calls, in which argument order, and when the
state must be flushed.

Everything runs from the panel's controller (a trame event), never from a
`@state.change` handler: a flush inside a flush does nothing, and a load
asked for in one step would not be there for the next.
"""
import math
import os
import re
import time

from fespp_on_trame.app.views.camera import CAMERA_PROPERTIES
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import tree_families
from fespp_on_trame.ia import llm as ia_llm
from fespp_on_trame.ia.nlu import catalogue
from fespp_on_trame.ia.nlu import engine as nlu_engine
from fespp_on_trame.ia.nlu import lexicon as nlu_lexicon
from fespp_on_trame.ia.nlu import multi as nlu_multi
from fespp_on_trame.ia.nlu import slots as nlu_slots
from fespp_on_trame.ia.nlu.text import normalize, tokens as nlu_tokens
from fespp_on_trame.engine.utils import numfmt

_GRIDS = ("IjkGrid", "UnstructuredGrid")
# the order objects are offered in when a command names none
_OBJECT_RANK = {"IjkGrid": 0, "UnstructuredGrid": 0, "Grid2d": 1, "TriangulatedSet": 2,
                "PolylineSet": 3, "Wellbore": 4, "PointSet": 5, "Sub": 6}
# a category code as a string lookup writes it ("1", "2.0")
_NUMBER = nlu_engine._NUMBER
# what a threshold can cut (boot's ISOLATABLE)
_ISOLATABLE = ("IjkGrid", "UnstructuredGrid", "Sub")
# the commands that act on what is drawn in 3D: a derived property never
# enters the VTK pipeline (engine/derived_props creates no proxy), so an
# eye, a colour table, a filter or a highlight on it would act on nothing,
# or on another table
_DRAWN = ("show", "hide", "isolate", "threshold", "highlight", "colormap", "color_range",
          "rescale", "hide_nan", "well_cells", "color_scale", "color_bar")
# the colour gestures: nothing named, they act on the Colormap card's target
_COLOUR = ("colormap", "color_range", "rescale", "hide_nan", "color_scale", "color_bar")
# the property types that vary in time, and the ones with several realizations
_TIMED = ("TimeSeries", "MultiRealizationTimeSeries")
_MULTI = ("MultiRealization", "MultiRealizationTimeSeries")
# the filter-or-highlight question is not asked: the filter runs at once and
# its reply offers the highlight instead (the panel's "instead:" choice)
_RUN_FIRST = ("threshold", "highlight")
# the parts of a well: the wellbore stands for them, they are not listed apart
_WELL_PARTS = ("Trajectory", "Frame", "MarkerFrame", "Completion", "Perfo", "Perforation",
               "WellboreMarker", "Marker", "SeismicWellboreFrame")
_TABS = {"Reservoir": "reservoir", "Surface": "surface", "Well": "well"}
_UNDO_KEEP = 20
# set after the name of a threshold entry an undo puts back while a filter
# made since holds that name: the entry is added back afresh
_UNDONE = "#undo"
_NAMES_SHOWN = 10          # names per row of a list
_CHOICES = 8               # object buttons under a question
# the objects the local AI is told about (its prompt keeps fewer)
_LLM_OBJECTS = 80
# how often the local AI's health is asked: a service that went down is
# found within a minute, and the panel never waits on a dead one meanwhile
_HEALTH_EVERY_S = 60.0
_HEALTH_TIMEOUT_S = 2.0
# the commands whose bounds a sentence's numbers give, the engine's rule
_BOUNDED = ("threshold", "highlight", "color_range", "slice", "well_cells")
# hiding said with a negated showing verb: "don't show the water" hides it
_HIDE_SAID = ("dont show", "don t show", "do not show", "ne montre pas", "n affiche pas", "ne montre plus",
              "n affiche plus")
# a zone made to go: "rends le gaz invisible", "fais disparaître l'eau"
_GONE = ("invisible", "invisibles", "disparaitre", "disparaissent", "disparaisse")
# a hiding verb said not: "ne cache pas l'huile", "don't hide the gas",
# "sans masquer" — the word hides nothing, whatever reads it as a hiding
_NOT_HIDING = ("ne cache pas", "ne cachez pas", "ne masque pas", "ne masquez pas", "ne vire pas", "n enleve pas",
               "ne retire pas", "ne cache plus", "ne masque plus", "dont hide", "don t hide", "do not hide",
               "never hide", "stop hiding", "sans cacher", "sans masquer", "sans rien cacher", "arrete de cacher",
               "arrete de masquer", "arretez de cacher", "arretez de masquer", "cesse de cacher", "cesse de masquer",
               # "cache l'huile mais laisse l'eau", "hide the gas but keep the
               # oil": the value after the keep stays (the conjunction forms
               # only: "ne garde pas l'huile" is a hiding)
               "mais laisse", "mais laissez", "et laisse", "et laissez", "mais garde", "mais gardez", "et garde",
               "et gardez", "but keep", "and keep", "but leave", "and leave")
# a value asked to be seen AGAIN ("je veux revoir l'huile", "ramène
# l'huile", "restore the oil", "the oil again"): what is hidden of it comes
# back, the other values stay as they are
_AGAIN = ("revoir", "remontre", "remontrer", "remontrez", "reaffiche", "reafficher", "reaffichez", "remets",
          "remettez", "remettre", "reapparaitre", "reapparaissent", "de nouveau", "a nouveau", "again", "back",
          "unhide", "bring back", "put back", "ramene", "ramener", "ramenez", "retablis", "retablir",
          "retablissez", "restaure", "restaurer", "restaurez", "restore", "retrouver", "retrouve", "ravoir")
# a value said with a showing verb is to be SEEN: "non, je voulais voir
# l'huile", "remets l'huile", "no, I wanted to see the oil" — never hidden
# on the last command's polarity (a seeing said not, "je ne veux plus voir",
# is a hiding phrase, read before these). One list with the engine's: its
# showing words, then the ones it lacks
_ENGINE_SHOW = tuple(getattr(nlu_engine, "SHOW_WORDS", None) or getattr(nlu_engine, "_SHOW_WORDS", ()))
_SHOW_SAID = _ENGINE_SHOW + tuple(w for w in _AGAIN + ("voit",) if w not in _ENGINE_SHOW)
_SHOW_PLAIN = tuple(w for w in _SHOW_SAID if w not in _AGAIN)
# a sentence said not ("je ne veux plus revoir le gaz", "don't bring the
# gas back"): its words of seeing again bring nothing back
_NOT_FR = ("pas", "plus", "jamais")
_NOT_EN = ("don t", "dont", "do not", "does not", "doesn t", "did not", "didn t", "never", "no longer", "won t",
           "will not")
# a sentence that corrects the last one replaces what that one named: the
# engine's correction words, "non" first, and these — never a bare "pas" or
# "not": "ne montre pas le gaz" hides the gas, it corrects nothing; nor a
# "c'est" said in passing ("c'est bien, cache le gaz aussi"): only "c'est
# l'huile que je voulais" corrects (`_its_value_that`)
_CORRECTING = ("plutot", "rather", "instead", "au lieu de", "au lieu du", "au lieu des", "en fait", "finalement",
               "oups", "oops", "my bad", "je me suis trompe", "je me suis trompee", "erreur", "actually", "i meant")
# said first, "pardon" and "sorry" take the last request back ("sorry, the
# gas"); said after it they are politeness ("et l'huile aussi, pardon"), and
# followed by "and" a request of their own ("pardon, et le gaz ?")
_SORRY = ("pardon", "sorry")
# a value added to the last request's, said in so many words: it adds up
# whatever correction word comes with it ("pardon, cache aussi l'huile",
# "actually, hide the gas too") — unless the sentence says what it replaces
_ALSO = ("aussi", "egalement", "en plus", "too", "also", "as well")
_INSTEAD = ("au lieu de", "au lieu du", "au lieu des", "au lieu d", "instead", "plutot", "rather")
# a leading "no" that takes the last request back is followed by a pause or
# by what was meant ("no, the gas", "no the oil", "no I said water") — "no
# gas" and "no more gas" say the value not, they correct nothing
_NO_CORRECTS = re.compile(r"^\W*no\b\s*(?:[,;:.!-]|(?:the|i|it|not|that|this|only|just|wait)\b)")
# the commands whose request may name more values for the one before ("hide
# the oil zone then the gas"): the values add up — unless the request says
# "only" ("…then keep only the gas"), which replaces them
_ADDING = ("threshold", "highlight")
_ONLY = ("que le", "que la", "que les", "que l", "que du", "que des", "rien que", "seulement", "uniquement",
         "only", "just", "juste")
# a percent said with the sign or in words ("20 %", "vingt pour cent")
_PERCENT_SAID = ("%", "pour cent", "pourcent", "pourcents", "percent", "pct")
# a value said with a negation and no verb that hides ("sans l'eau", "no
# water"): hidden, or kept? asked when the local AI's service does not say
_NEGATED_ZONE = ("sans", "without", "pas de", "pas d", "aucun", "aucune", "no")
# the little words between a value and the word that governs it ("sans LES
# MAILLES DE gaz", "instead OF THE water"), skipped to find that word
_LEAD_SKIP = frozenset(("le", "la", "les", "l", "du", "des", "de", "d", "un", "une", "the", "a", "an", "any", "some",
                        "of", "zone", "zones", "maille", "mailles", "cell", "cells"))
# a pause of the sentence (a comma, a semicolon, a full stop) as a word: "no,
# the gas" corrects, "no gas" says the value not
_PAUSE = "zzpause"
_PAUSES = re.compile(r"(?<!\d)[,;:.!?]|[,;:.!?](?!\d)")
# what ends the clause a value is said in, for the verb that governs it
_CLAUSE_ENDS = frozenset((_PAUSE, "mais", "but", "puis", "then"))

# a short verb per command, as a button says it (French, English)
LABELS = {
    "show": ("afficher", "show"),
    "complain": ("ce n'est pas ce que je voulais", "not what I wanted"),
    "hide": ("masquer", "hide"),
    "isolate": ("isoler", "isolate"),
    "threshold": ("filtrer par valeur", "filter by value"),
    "clear_threshold": ("enlever le filtre", "remove the filter"),
    "highlight": ("surligner des mailles", "highlight cells"),
    "clear_highlight": ("enlever la surbrillance", "remove the highlight"),
    "well_cells": ("les mailles traversées par les puits", "the cells the wells go through"),
    "slice": ("couper selon I, J ou K", "slice along I, J or K"),
    "hide_nan": ("masquer les valeurs absentes", "hide missing values"),
    "colormap": ("changer la table de couleurs", "change the colour table"),
    "color_range": ("fixer la plage de couleurs", "set the colour range"),
    "rescale": ("recaler les couleurs", "rescale the colours"),
    "flat_colors": ("couleurs exactes", "exact colours"),
    "reset_camera": ("recadrer la vue", "reset the camera"),
    "z_scale": ("exagération verticale", "vertical exaggeration"),
    "new_view": ("nouvelle vue 3D", "new 3D view"),
    "open_panel": ("ouvrir un panneau", "open a panel"),
    "describe": ("décrire un objet", "describe an object"),
    "list": ("lister les données", "list the data"),
    "value": ("donner une statistique", "give a statistic"),
    "undo": ("annuler", "undo"),
    "save_session": ("enregistrer la session", "save the session"),
    "help": ("aide", "help"),
    "ask": ("répondre à une question", "answer a question"),
    "close_panel": ("fermer un panneau", "close a panel"),
    "camera_view": ("orienter la caméra", "point the camera"),
    "zoom": ("zoomer", "zoom"),
    "time_step": ("changer de pas de temps", "go to a time step"),
    "time_play": ("animer les pas de temps", "play the time steps"),
    "realization": ("changer de réalisation", "show another realization"),
    "rep_style": ("changer le mode de dessin", "change the drawing style"),
    "color_scale": ("échelle des couleurs log ou linéaire", "log or linear colour scale"),
    "color_bar": ("barre de couleurs", "colour bar"),
    "open_tool": ("ouvrir une carte outil", "open a tool card"),
    "hide_all": ("vider la vue", "clear the view"),
    "unsupported": ("demande que je ne sais pas faire", "a request I cannot do yet"),
}
# the English description of each command (the catalogue holds the French one)
_HELP_EN = {
    "show": "show an object or a property in the view",
    "hide": "hide an object from the view",
    "isolate": "show only this object",
    "threshold": "filter the cells by value",
    "clear_threshold": "remove the value filter",
    "highlight": "highlight the cells that meet a condition",
    "clear_highlight": "remove the highlight",
    "well_cells": "the grid cells the wells go through (blocked wellbores), lit within a zone",
    "slice": "cut the grid along I, J or K",
    "hide_nan": "hide or show the missing values",
    "colormap": "change the colour table",
    "color_range": "set the range of the colour table",
    "rescale": "fit the colour table to the data",
    "flat_colors": "exact colours (no shading)",
    "reset_camera": "reset the camera",
    "z_scale": "vertical exaggeration",
    "new_view": "open a new 3D view",
    "open_panel": "open an analysis panel",
    "describe": "describe an object",
    "list": "list what is loaded",
    "value": "give a statistic (mean, min, max)",
    "undo": "undo the last gesture",
    "save_session": "save the session",
    "complain": "say the reply was not what you wanted (it can be undone, and what you meant is learned)",
    "help": "what the assistant can do",
    "ask": "answer a question about the domain or the application (local AI, from the documentation)",
    "close_panel": "close an analysis panel",
    "camera_view": "point the camera (top view, from the north…)",
    "zoom": "zoom in or out one step",
    "time_step": "go to a time step (number, next, previous, first, last)",
    "time_play": "play or stop the time steps",
    "realization": "show another realization of a property",
    "rep_style": "change the drawing style (surface, edges, wireframe, points)",
    "color_scale": "switch the colour scale to logarithmic or linear",
    "color_bar": "show or hide the colour bar",
    "open_tool": "open a tool card of the view",
    "hide_all": "clear the view (hide everything, nothing is unloaded)",
    "unsupported": "a request the assistant cannot do yet",
}
# a sentence the help table gives for the view's gestures (French, English)
_HELP_EXAMPLES = {
    "close_panel": ("ferme les statistiques", "close the statistics"),
    "camera_view": ("vue de dessus", "top view"),
    "zoom": ("zoome", "zoom out"),
    "time_step": ("pas de temps suivant", "next time step"),
    "time_play": ("lance l'animation du temps", "play the time steps"),
    "realization": ("réalisation suivante", "next realization"),
    "rep_style": ("passe en fil de fer", "switch to wireframe"),
    "color_scale": ("échelle de couleurs logarithmique", "logarithmic colour scale"),
    "color_bar": ("masque la barre de couleurs", "hide the colour bar"),
    "open_tool": ("ouvre la carte des seuils", "open the thresholds card"),
    "hide_all": ("masque tout", "hide everything"),
}
# where the camera sits for each direction (nav_axis: on the + side of the
# axis, "+z" looks from above), and how a reply says it
_AXIS_OF = {"top": "+z", "bottom": "-z", "north": "+y", "south": "-y", "east": "+x", "west": "-x"}
_DIRECTION_WORDS = {"top": ("vue de dessus", "top view"), "bottom": ("vue de dessous", "bottom view"),
                    "north": ("depuis le nord", "from the north"), "south": ("depuis le sud", "from the south"),
                    "east": ("depuis l'est", "from the east"), "west": ("depuis l'ouest", "from the west")}
# zoom steps, as the title bar's buttons give them
_ZOOM_IN, _ZOOM_OUT = 0.8, 1.25
# the drawing styles (render_panel.REP_STYLES, ParaView's names) in words
_STYLE_WORDS = {"Surface": ("surface pleine", "plain surface"),
                "Surface With Edges": ("surface avec arêtes", "surface with edges"),
                "Wireframe": ("fil de fer", "wireframe"), "Points": ("points", "points"),
                "Outline": ("contour (boîte englobante)", "outline (bounding box)")}
# the tool cards a sentence may open (tools_config.TOOLS but the Globe, which
# rebuilds the scene and drops the filters), named as their title bars show
# them in either language
_TOOL_TITLES = {"tree": "Data tree", "colormap": "Colormap", "slicers": "Geometry slicer",
                "thresholds": "Property slicer", "volumetrics": "Volumetrics", "timereal": "Time & Realizations",
                "navigation": "Navigation", "camlink": "Synchronize camera"}
# a card not offered on this server (app/core/previews) is not named either
from fespp_on_trame.app.core import previews as _previews  # noqa: E402
_TOOL_TITLES = {k: v for k, v in _TOOL_TITLES.items() if _previews.offered(k)}
# the cards a Globe view does not offer, and what the others wait for
_TOOLS_RENDER_ONLY = ("slicers", "thresholds", "volumetrics", "navigation", "camlink")
_TOOL_NEEDS = {"slicers": ("il faut une grille IJK lue dans la vue", "it needs an IJK grid read in the view"),
               "thresholds": ("il faut une grille ou une sous-représentation lue, avec une propriété",
                              "it needs a grid or a sub-representation read, with a property"),
               "volumetrics": ("il faut une grille lue dont les mailles ont un volume",
                               "it needs a grid read whose cells have a volume")}
# the gestures the application has outside the assistant, and where: what an
# unsupported request is told when it names one (normalised words, first
# match wins: an export or a server before a file)
_ELSEWHERE = (
    (("capture", "captures", "screenshot", "copie d ecran", "imprime ecran", "impression ecran", "snapshot"),
     "L'application ne fait pas de capture d'écran : utilisez celle de votre système.",
     "The application takes no screenshot: use your system's own."),
    (("csv", "export", "exporte", "exporter", "exportez", "excel", "tableur", "spreadsheet"),
     "Le bouton Copy CSV du panneau Statistiques copie ses valeurs.",
     "The Copy CSV button of the Statistics panel copies its values."),
    (("osdu", "etp", "serveur", "server", "dataspace"),
     "La connexion à un serveur OSDU ou ETP se fait par Import data > ETP.",
     "Connecting to an OSDU or ETP server is in Import data > ETP."),
    (("fichier", "fichiers", "file", "files", "epc", "importe", "importer", "importez", "import"),
     "Un fichier s'ouvre par la porte Import data.", "A file is opened through the Import data door."),
    (("opacite", "transparence", "transparent", "transparente", "opacity", "transparency", "translucent"),
     "L'opacité se règle dans la carte Colormap de la vue, par sa courbe d'opacité.",
     "The opacity is set in the Colormap card, with its opacity curve."),
    (("fond", "arriere plan", "background"),
     "La couleur du fond n'est pas réglable.", "The background colour cannot be changed."),
    (("pilier", "piliers", "pillar", "pillars"),
     "Les piliers d'une grille ne s'affichent pas encore.", "A grid's pillars cannot be shown yet."),
    (("lier", "lie les", "relie", "relier", "synchronise", "synchroniser", "link", "sync"),
     "Les caméras se lient par le menu de liaison de la barre de titre de la vue.",
     "Cameras are linked from the link menu of the view's title bar."),
    (("globe", "terre", "earth"),
     "Le Globe s'ouvre par son bouton de la barre du haut.",
     "The Globe opens from its button in the top bar."),
    (("volumetrie", "volumetrique", "volumes", "volumetrics", "stoiip", "giip", "hcpv"),
     "Les volumes se calculent dans la carte Volumetrics de la vue.",
     "Volumes are computed in the view's Volumetrics card."),
    (("cross plot", "crossplot", "nuage de points", "scatter"),
     "Deux propriétés se croisent dans le cross-plot du panneau Statistiques.",
     "Two properties are crossed in the cross-plot of the Statistics panel."),
    (("decharge", "decharger", "dechargez", "decoche", "decocher", "decochez", "unload", "untick", "uncheck"),
     "Un objet se décharge en le décochant dans l'arbre des données.",
     "An object is unloaded by unticking it in the data tree."),
)
_GREETINGS = ("bonjour", "bonsoir", "salut", "coucou", "hello", "hi", "hey")
_THANKS = ("merci", "thanks", "thank you", "thx")
# a 3D view named by a request to close a panel: never closed by the assistant
_VIEW_SAID = ("vue", "vues", "view", "views", "onglet", "tab", "3d")
# the reservoir glossary (a copy of ia/corpus/glossaire-reservoir.md): what a
# question is answered from when the local AI is absent or fails
_GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets",
                              "glossaire-reservoir.md")
_GLOSSARY_SOURCE = ("Source : glossaire du réservoir (définition générale, en cours de relecture par un géologue).",
                    "Source: reservoir glossary (general definition, under review by a geologist).")
_GLOSSARY_SHOWN = 2        # entries a reply quotes at most
_glossary_entries = []     # (heading, text, names), read once
# the analysis panels (lexicon.PANELS), each by the name of its VIEW_KINDS kind,
# but for the other words of the Statistics view (`_PANEL_KIND`): its charts,
# asked by name, are that view
_PANELS = {
    "stats": ("Statistiques", "Statistics"),
    "welllog": ("Vue des logs", "Well log"),
    "reconcile": ("Log ↔ Grille", "Log ↔ Grid"),
    "compare": ("Statistiques", "Statistics"),
    "crossplot": ("Statistiques", "Statistics"),
    "distribution": ("Statistiques", "Statistics"),
    "xml": ("Explorateur", "Explorer"),
    "stratigraphy": ("Stratigraphie", "Stratigraphy"),
    "calculator": ("Calculatrice", "Calculator"),
    "health": ("Data health", "Data health"),
}
_PANEL_KIND = {"stats": "compare", "crossplot": "compare", "distribution": "compare"}
# the panels that act on ONE property
_PANEL_PROPERTY = ("stats", "crossplot", "distribution", "calculator", "compare")
# "the stats of every time step / realization" (normalised): the Statistics
# view then pins one row per value, as a row's menu does
_EVERY_STEP = ("tous les pas de temps", "chaque pas de temps", "toutes les dates", "chaque date",
               "pour tous les pas", "all time steps", "all the time steps", "every time step",
               "each time step", "all timesteps", "every timestep", "each timestep", "all dates",
               "every date")
_EVERY_REAL = ("toutes les realisations", "chaque realisation", "all realizations", "all the realizations",
               "every realization", "each realization", "all realisations", "every realisation")
# the property kinds the examples say by name (French, English)
_KIND_WORDS = {
    "porosity": ("la porosité", "porosity"),
    "permeability": ("la perméabilité", "permeability"),
    "net to gross": ("le net sur brut", "net to gross"),
    "water saturation": ("la saturation en eau", "water saturation"),
    "saturation": ("la saturation", "saturation"),
    "temperature": ("la température", "temperature"),
    "pressure": ("la pression", "pressure"),
    "gamma ray": ("le gamma ray", "gamma ray"),
    "depth": ("la profondeur", "depth"),
}
_TYPE_WORDS = {
    "IjkGrid": ("grille IJK", "IJK grid"),
    "UnstructuredGrid": ("grille non structurée", "unstructured grid"),
    "ContinuousProperty": ("propriété continue", "continuous property"),
    "DiscreteProperty": ("propriété discrète", "discrete property"),
    "CategoricalProperty": ("propriété catégorielle", "categorical property"),
    "TimeSeries": ("série temporelle", "time series"),
    "MultiRealization": ("propriété à plusieurs réalisations", "multi-realization property"),
    "MultiRealizationTimeSeries": ("série à plusieurs réalisations",
                                   "multi-realization time series"),
    "DerivedProperty": ("propriété dérivée", "derived property"),
    "Wellbore": ("puits", "wellbore"),
    "Grid2d": ("surface (grille 2D)", "surface (2D grid)"),
    "TriangulatedSet": ("surface triangulée", "triangulated surface"),
    "PolylineSet": ("polylignes", "polylines"),
    "Polyline": ("polyligne", "polyline"),
    "PointSet": ("nuage de points", "point set"),
    "Sub": ("sous-représentation", "sub-representation"),
    "BlockedWellbore": ("puits bloqué", "blocked wellbore"),
}
_GENERIC_EXAMPLES = {
    "fr": ["liste ce qui est chargé", "que peux-tu faire ?", "ouvre Data health",
           "exagération verticale x 3", "recadre la vue", "ouvre une nouvelle vue"],
    "en": ["list what is loaded", "what can you do?", "open data health",
           "vertical exaggeration x 3", "reset the camera", "open a new view"],
}


class _Unavailable(Exception):
    """A controller the command needs is not registered (a test harness, an
    application built without that feature)."""


def _lang(lang):
    return "en" if lang == "en" else "fr"


_PIECE_JOINTS = re.compile(r"[^a-z0-9]+|(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])")


def _pieces(s):
    """Letters and digits apart: "15/9-F-1_A" -> 15, 9, f, 1, a."""
    return [p for p in _PIECE_JOINTS.split(normalize(s)) if p]


def _t(lang, fr, en):
    return en if _lang(lang) == "en" else fr


def _num(v, lang):
    """A measured value the way every panel writes it (engine/utils/numfmt),
    with the decimal comma in French."""
    s = numfmt.fmt(v)
    return s.replace(".", ",") if _lang(lang) == "fr" else s


def _count(n, lang):
    return numfmt.fmt_int(n)


def _plural(n, one, many):
    return one if abs(n) < 2 else many


def _reply(ok, text, **extra):
    out = {"ok": bool(ok), "text": text}
    out.update(extra)
    return out


def _words_of(text):
    """The words of a sentence as the engine reads them, space-padded: a
    word or a phrase is looked for as " <it> "."""
    return " " + " ".join(nlu_tokens(text or "")) + " "


def _has(said, words):
    return any(f" {w} " in said for w in words)


def _glossary():
    """The reservoir glossary's entries: (heading, text, names), a name being
    the words of one of the notion's French or English names as the engine
    reads them ("### Maille, cellule (cell)": maille, cellule, cell)."""
    if _glossary_entries:
        return _glossary_entries
    try:
        with open(_GLOSSARY_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as exc:
        print("[assistant] the reservoir glossary cannot be read:", exc, flush=True)
        return []
    out, head, body = [], None, []
    for line in lines + ["#"]:
        if line.startswith("#"):
            if head:
                names = [tuple(nlu_tokens(n)) for n in re.split(r"[(),]", head)]
                out.append((head, " ".join(b for b in body if b), [n for n in names if n]))
            head, body = (line[4:].strip() if line.startswith("### ") else None), []
        elif head is not None:
            body.append(line.strip())
    # whole, in one assignment: a question answered off the loop may read it
    _glossary_entries[:] = out
    return out


def _slips(said, name, known):
    """The letters slipped when the words `said` name `name`, or None: each
    word the same, a plural of it, or — a word not typed on purpose (the
    engine's `known_words`) — within the engine's typo budget ("pilar" is
    "pillar")."""
    slips = 0
    for w, q in zip(said, name):
        if w == q or (len(q) > 3 and (w in (q + "s", q + "x") or q in (w + "s", w + "x"))):
            continue
        if w in known or len(w) < 4 or w[0].isdigit():
            return None
        d = nlu_slots.edit_distance(w, q, cap=2)
        if d > nlu_slots.typo_budget(q):
            return None
        slips += d
    return slips


def _glossary_named(question):
    """The glossary entries `question` names, in the order it names them
    (at most _GLOSSARY_SHOWN): at one place of the sentence the longest name
    wins ("propriété dérivée" over "propriété"), and a name of two letters or
    fewer ("GR", "k") counts only typed in capitals."""
    toks = nlu_tokens(question)
    caps = nlu_slots.capitals(question)
    try:
        known = nlu_slots.known_words()
    except Exception as exc:
        print("[assistant] the engine's words, for the glossary:", exc, flush=True)
        known = frozenset()
    entries = _glossary()
    hits = []
    for k, (_head, _text, names) in enumerate(entries):
        for name in names:
            short = len("".join(name)) <= 2
            for i in range(len(toks)):
                n = len(name)
                slips = _slips(toks[i:i + n], name, known) if i + n <= len(toks) else None
                if slips is None and n > 1 and toks[i] == "".join(name):
                    # a name of several words said as one ("crossplot")
                    slips, n = 0, 1
                if slips is None or (short and toks[i] not in caps):
                    continue
                hits.append((i, -n, slips, k))
    taken, spans = [], []
    for i, neg, _slip, k in sorted(hits):
        end = i - neg
        if k in taken or any(i < e and s < end for s, e in spans):
            continue
        taken.append(k)
        spans.append((i, end))
        if len(taken) == _GLOSSARY_SHOWN:
            break
    return [entries[k] for k in taken]


class FesppAssistantHost:
    """The host the assistant's controller talks to: the catalogue of
    objects, the parsing, the questions and the gestures with their undo."""

    # the examples are built from the data: asked again when a file is read
    # (a new tree) or a grid is (the loaded one comes first)
    examples_watch = ("assembly_rev", "lazy_rev", "ui_loaded_rep_paths")

    def __init__(self, server, ia=None):
        self.server = server
        self.state = server.state
        self.ctx = server.context
        self.ctrl = server.controller
        # the local AI service (ia/fespp_ia: a language model and the
        # documentation's index) when FESPP_IA_URL names it — the slow
        # path, run off the event loop
        from fespp_on_trame.ia.llm import LocalIA
        self.ia = ia if ia is not None else LocalIA.from_env()
        self._cache = None          # (key, static catalogue)
        self._asm_version = 0
        self._issued = []           # the undo tokens handed out, oldest first
        self._context = None        # the last command that worked (_remember)
        self._undone = set()        # ids of the tokens already applied
        self._next_token = 0
        # per view, the category values the last highlight lit: (property
        # path, values) — gone once that highlight is undone or replaced
        self._lit = {}
        # per (view, grid), the name each threshold entry an undo token holds
        # has now, when this adapter put it back under another one (IjkGrid
        # names an entry added again afresh): an earlier token still finds it
        self._aliases = {}
        # the local AI's state as last seen: (when, up, why it is not)
        self._ia_seen = None
        try:
            # a new file read, another tree layout: the catalogue is walked again
            # and objects a lazy load left on the store were read: kinds, units
            self.state.change("assembly_rev", "lazy_rev")(self._on_assembly)
        except Exception as exc:
            print("[assistant] no assembly watcher, the catalogue is walked on every"
                  " change of the tree object:", exc, flush=True)

    def _on_assembly(self, **_):
        self._asm_version += 1

    def forget_view(self, vid):
        """A closed view's memories go with it: what its last highlight lit,
        the threshold names of its grids (app/core/lifecycle)."""
        self._lit.pop(vid, None)
        for key in [k for k in self._aliases if isinstance(k, tuple) and k and k[0] == vid]:
            self._aliases.pop(key, None)

    def examples_wanted(self):
        """Only an open assistant view shows examples: building them reads
        the category names of every categorical property, which a lazy ETP
        load left on the store (4.5 s on demo/Volve, the PO 14/10)."""
        mv = self._mv()
        try:
            return bool(mv is not None and mv.panel_ids_of_kind("assistant"))
        except Exception as exc:
            print("[assistant] open panels unknown, the examples are built:", exc, flush=True)
            return True

    # ------------------------------------------------------------ helpers
    def _mv(self):
        return getattr(self.ctx, "multi_view", None)

    def _tree(self):
        return getattr(self.ctx, "tree", None)

    def _get(self, name, default=None):
        v = getattr(self.state, name, None)
        return default if v is None else v

    def _flush(self):
        """Push what was written to its watchers at once (a load, the eyes,
        the cards), as `with state:` does on its way out."""
        try:
            self.state.flush()
        except Exception as exc:
            print("[assistant] state flush:", exc, flush=True)

    def _ctrl(self, name):
        """The controller `name`, or None when the application has none."""
        fn = getattr(self.ctrl, name, None)
        if fn is None:
            return None
        exists = getattr(fn, "exists", None)
        if callable(exists):
            try:
                if not exists():
                    return None
            except Exception as exc:
                print(f"[assistant] controller {name}:", exc, flush=True)
                return None
        return fn

    def _call(self, name, *args):
        fn = self._ctrl(name)
        if fn is None:
            raise _Unavailable(name)
        return fn(*args)

    def _vid(self):
        """The 3D view a command acts on (the active one, else the last one
        worked in, else the first) — None when no 3D view is open."""
        from fespp_on_trame.engine import view_routing
        mv = self._mv()
        if mv is None:
            return None
        try:
            ids = list(mv.view_ids() or [])
        except Exception as exc:
            print("[assistant] view ids:", exc, flush=True)
            return None
        vid = view_routing.resolve_active_render_panel(self.state)
        return vid if vid and vid in ids else None

    def _no_view(self, lang):
        return _reply(False, _t(lang, "Ouvrez une vue 3D d'abord.", "Open a 3D view first."))

    def _loaded(self):
        return (set(self._get("ui_loaded_rep_paths", [])) |
                set(self._get("ui_loaded_array_paths", [])))

    # ------------------------------------------------------------ the catalogue
    def _catalogue(self):
        """The objects of every file read, walked once per tree: what the
        engine names, loaded or not (a grid can be shown before it is
        ticked). One dict per object — see `objects`."""
        tree = self._tree()
        asm = getattr(tree, "_data_assembly", None) if tree is not None else None
        if asm is None:
            return []
        key = (id(tree), id(asm), self._asm_version)
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        try:
            rows = self._walk(tree)
        except Exception as exc:
            print("[assistant] catalogue walk:", exc, flush=True)
            rows = []
        self._cache = (key, rows)
        return rows

    def _walk(self, tree):
        """One catalogue row per selectable node of the tree (the fields
        are listed in `objects`)."""
        from fespp_on_trame.engine import element_type, stats_dispatch
        self._prefetch_categories(tree)
        out = []
        parent_of, family, skip = {}, {}, set()
        for nid, kids in tree.iter_nodes():
            for c in kids:
                parent_of[c] = nid
            if nid in skip:
                skip.update(kids)
                continue
            if nid == 0:
                continue
            typ = tree.find_type(nid) or ""
            # the tab of the data tree the node sits in: the family of the
            # first node on its path that has one (a log is a Well)
            family[nid] = (family.get(parent_of.get(nid))
                           or tree_families.name_of(tree, nid) or node_kinds.family_of_type(typ))
            e = element_type.for_kind(typ)
            title = tree.find_title(nid) or ""
            if not e.is_selectable() or title.startswith(node_kinds.PARTIAL_PREFIX):
                skip.update(kids)
                continue
            if e.is_multi_realization():
                skip.update(kids)             # one row per MR property, not per realization
            path = tree.find_path(nid) or ""
            if not path:
                continue
            tab = _TABS.get(family[nid], "")
            wid = tree.find_parent_node_id_with_type(nid, "Wellbore")
            well = (tree.find_path(wid) or "") if wid is not None and wid != nid else ""
            obj = None
            if e.is_property():
                rid = tree.find_representation_node(nid)
                rep = (tree.find_path(rid) or "") if rid is not None else ""
                obj = {"path": path, "type": typ,
                       "title": stats_dispatch._title_and_kind(tree, path)[0] or title,
                       "kind": (tree.find_attribute_value(nid, "propertyKind") or "").strip().lower(),
                       "parent": well or rep, "rep_path": rep,
                       "rep_type": (tree.find_type(rid) or "") if rid is not None else "",
                       "uom": tree.find_attribute_value(nid, "uom") or "",
                       "vmin": tree.find_attribute_value(nid, "minvalue"),
                       "vmax": tree.find_attribute_value(nid, "maxvalue")}
                if typ == "CategoricalProperty":
                    # the value names ("oil", "Sandstone"): what "the oil
                    # zones" is matched against — read from the file's
                    # string lookup, without reading the data
                    cats = self._category_names(tree, path)
                    if cats:
                        obj["categories"] = cats
            elif typ in _GRIDS:
                # the geometry leaf IS the grid: what loads, the eyes and the
                # thresholds key on; its name is the GridContainer's
                obj = {"path": path, "type": typ, "title": tree.find_rep_title(nid) or title,
                       "kind": "", "parent": None, "rep_path": path, "rep_type": typ}
            elif typ == "Wellbore":
                tid = tree.find_first_child_of_type(nid, "Trajectory")
                traj = (tree.find_path(tid) or "") if tid is not None else ""
                obj = {"path": path, "type": typ, "title": title, "kind": "", "parent": None,
                       "rep_path": traj, "rep_type": "Trajectory" if traj else "",
                       "trajectory": traj}
            elif typ not in _WELL_PARTS and tree.renders(nid):
                obj = {"path": path, "type": typ, "title": title, "kind": "",
                       "parent": well or None, "rep_path": path, "rep_type": typ}
            if obj is not None:
                obj.update(role=tree.find_role(nid) or "", tab=tab)
                out.append(obj)
        return out

    def _prefetch_categories(self, tree):
        """The categorical properties a lazy ETP load left on the store
        ("lazy" = "1" on the node), read in ONE request before the walk asks
        their category names one by one: thirty requests and 4.5 s on
        demo/Volve otherwise (the PO, 14/10)."""
        from fespp_on_trame.engine import repo_query
        asm = getattr(tree, "_data_assembly", None)
        if asm is None:
            return
        uuids = []
        try:
            for nid, _kids in tree.iter_nodes():
                if (nid and tree.find_type(nid) == "CategoricalProperty"
                        and tree.find_attribute_value(nid, "lazy") == "1"):
                    name = asm.GetNodeName(nid) or ""
                    if name.startswith("_"):
                        uuids.append(name[1:])
        except Exception as exc:
            print("[assistant] categorical properties not listed:", exc, flush=True)
            return
        if not uuids:
            return
        registry = getattr(self.ctx, "source_registry", None)
        try:
            reader = registry.shared_source() if registry is not None else None
            if reader is not None:
                repo_query.lazy_fetch(reader, 5000, 0, uuids)
        except Exception as exc:
            print("[assistant] category names, grouped read:", exc, flush=True)

    def _category_names(self, tree, path):
        """{code: name} of a categorical property, {} when unreadable."""
        from fespp_on_trame.engine.utils import categories as _cat
        reader = None
        registry = getattr(self.ctx, "source_registry", None)
        try:
            reader = registry.shared_source() if registry is not None else None
        except Exception as exc:
            print("[assistant] no reader for the category names:", exc, flush=True)
        try:
            labels = _cat.labels_for(tree, path, None, reader) or {}
        except Exception as exc:
            print(f"[assistant] category names of {path}:", exc, flush=True)
            return {}
        out = {}
        for code, name in labels.items():
            text = str(code).strip()
            if not _NUMBER.match(text):
                print(f"[assistant] {path}: category code {code!r} is not a number, left out", flush=True)
                continue
            value = float(text)
            out[int(value) if value.is_integer() else value] = str(name)
        return out

    def _derived(self, index):
        """The calculator's derived properties: not in the tree, named by
        their title only (no PWLS kind)."""
        store = getattr(self.ctx, "derived_store", None)
        if store is None:
            return []
        from fespp_on_trame.engine import derived_props
        out = []
        try:
            paths = list(store.active_paths() or [])
        except Exception as exc:
            print("[assistant] derived properties:", exc, flush=True)
            return []
        for p in paths:
            rep, name = derived_props.parse_path(p)
            grid = index.get(rep) or {}
            out.append({"path": p, "type": "DerivedProperty", "title": store.title(p) or name or p,
                        "kind": "", "parent": rep, "rep_path": rep,
                        "rep_type": grid.get("type", ""), "role": "", "tab": grid.get("tab", ""),
                        "uom": "", "loaded": True})
        return out

    def objects(self):
        """The engine's catalogue, the live flags added:
        {path, title, type, kind, parent, role, rep_path, trajectory
        (wellbores), loaded} — plus rep_type, tab, uom for the adapter."""
        loaded = self._loaded()
        out = []
        for o in self._catalogue():
            o = dict(o)
            o["loaded"] = (o.get("trajectory") or o["path"]) in loaded
            out.append(o)
        index = {o["path"]: o for o in out}
        return out + self._derived(index)

    def _index(self):
        return {o["path"]: o for o in self.objects()}

    # ------------------------------------------------------------ what a command is about
    @staticmethod
    def _is_prop(o):
        return node_facts.is_property_kind((o or {}).get("type") or "")

    def _title_of(self, path, index=None):
        o = (index if index is not None else self._index()).get(path or "")
        return (o or {}).get("title") or ""

    def _name(self, o, lang, index=None):
        """The name a reply gives `o`: a property is qualified by the grid
        or the well that holds it ("Geogrid Total Porosity")."""
        parent = self._title_of(o.get("parent"), index) if self._is_prop(o) else ""
        if not parent:
            return o.get("title") or o.get("path", "")
        return _t(lang, f"{o['title']} de {parent}", f"{parent} {o['title']}")

    def _active_property(self, vid):
        """The property the view's tree has active, as a catalogue row."""
        if not vid:
            return None
        path = self._get(f"active_path__{vid}", "")
        o = self._index().get(path) if path else None
        return o if self._is_prop(o) else None

    @staticmethod
    def _named(cmd):
        sl = cmd.get("slots") or {}
        return bool(cmd.get("targets") or sl.get("objects") or sl.get("kind") or sl.get("group"))

    def _need(self, cmd):
        """What the command acts on: "property" (ONE), "object" (ONE),
        "objects" (one or more) or None."""
        intent = cmd.get("intent")
        sl = cmd.get("slots") or {}
        if intent in ("threshold", "highlight", "value"):
            return "property"
        if intent in _COLOUR or intent == "realization":
            # nothing named: the Colormap card's own target, or the one
            # property of several realizations that colours the view
            return "property" if self._named(cmd) else None
        if intent == "open_panel":
            panel = sl.get("panel")
            if panel in ("crossplot", "distribution"):
                return "property"
            if panel in _PANEL_PROPERTY:
                return "property" if self._named(cmd) else None
            if panel in ("xml", "health"):
                return "object" if self._named(cmd) else None
            return None
        if intent == "describe":
            return "object"
        if intent in ("show", "hide", "isolate"):
            return "objects"
        return None

    @staticmethod
    def _well_named(cmd):
        sl = cmd.get("slots") or {}
        return any(o.get("type") == "Wellbore" for cands in sl.get("objects") or () for o in cands)

    def _narrow(self, cmd, props):
        """What the command can act on among the properties the words name:
        a filter or a highlight works on a grid's cells, never on a log; a
        kind said without a well means the grid's property, not the logs of
        that kind the wells carry ("the porosity" is the grid's porosity
        even when every well logs one too)."""
        if cmd.get("intent") in ("threshold", "highlight"):
            props = [p for p in props if p.get("rep_type") in _ISOLATABLE]
        if cmd.get("intent") == "realization":
            # another realization: the properties that have several
            props = [p for p in props if p.get("type") in _MULTI] or props
        if cmd.get("intent") in _DRAWN:
            # a derived property is never drawn: offered only when nothing
            # else answers, so the gesture can say why it cannot
            drawn = [p for p in props if p.get("type") != "DerivedProperty"]
            if drawn:
                props = drawn
        if len(props) > 1 and not self._well_named(cmd):
            grid = [p for p in props if p.get("rep_type") in _ISOLATABLE]
            if grid and len(grid) < len(props):
                props = grid
        return props

    def _prop_candidates(self, cmd):
        """The properties the words name — a named property is itself, a
        named grid or well without a kind is its properties (the view's
        active one when it is among them and the command acts on ONE) —
        narrowed to what the command can act on. A kind with several
        properties on one grid stays several: the panel asks."""
        cands = [dict(t) for t in cmd.get("targets") or ()]
        props = [c for c in cands if self._is_prop(c)]
        holders = [c for c in cands if not self._is_prop(c)]
        if holders:
            everything = self.objects()
            seen = {p["path"] for p in props}
            for h in holders:
                for o in everything:
                    if self._is_prop(o) and o.get("parent") == h.get("path") and o["path"] not in seen:
                        props.append(o)
                        seen.add(o["path"])
        props = self._narrow(cmd, props)
        if holders and len(props) > 1 and self._need(cmd) == "property":
            act = self._active_property(self._vid())
            if act is not None and any(p["path"] == act["path"] for p in props):
                return [act]
        return props

    def targets(self, cmd):
        """Every candidate object of `cmd` — what a "target:<path>" choice
        picks from."""
        need = self._need(cmd)
        named = self._named(cmd)
        drawn = cmd.get("intent") in _DRAWN
        if need == "property":
            if named:
                return self._prop_candidates(cmd)
            props = [o for o in self.objects() if self._is_prop(o)
                     and not (drawn and o.get("type") == "DerivedProperty")]
            if cmd.get("intent") in ("threshold", "highlight"):
                props = [p for p in props if p.get("rep_type") in _ISOLATABLE]
            # a grid's properties before the wells' logs, what is read first
            return sorted(props, key=lambda o: (o.get("rep_type") not in _ISOLATABLE, not o.get("loaded")))
        if need in ("object", "objects") and not named:
            # nothing named: the top-level objects (grids, surfaces, wells)
            # ranked by kind, so the question never opens on a list of
            # well-marker picks
            objs = [o for o in self.objects() if not o.get("parent")
                    and not (drawn and o.get("type") == "DerivedProperty")]
            return sorted(objs, key=lambda o: (_OBJECT_RANK.get(o.get("type"), 9), not o.get("loaded"),
                                               o.get("title", "")))
        cands = [dict(t) for t in cmd.get("targets") or ()]
        if need == "objects":
            kept = {p["path"] for p in self._narrow(cmd, [c for c in cands if self._is_prop(c)])}
            cands = [c for c in cands if not self._is_prop(c) or c["path"] in kept]
        return cands

    def missing(self, cmd):
        """What the command still lacks — the catalogue's needs, and ONE
        property where several answer ("show the permeability" on a grid
        that holds two)."""
        intent = cmd.get("intent")
        if intent not in catalogue.INTENTS:
            return []
        sl = cmd.get("slots") or {}
        wanted = dict(sl, object=sl.get("objects") or sl.get("group") or None)
        if sl.get("category") and wanted.get("min") is None:
            # a category value IS the range (its code is read in the property)
            wanted["min"] = sl["category"]
        miss = catalogue.missing(intent, wanted)
        if (intent == "well_cells" and "min|max" not in miss and wanted.get("min") is None
                and wanted.get("max") is None
                and (sl.get("kind") or any(self._is_prop(t) for t in cmd.get("targets") or ()))):
            # a zone said without its value ("the wells through the
            # porosity"): which cells is asked before anything runs, with
            # the property's range or its values as buttons
            miss.append("min|max")
        need = self._need(cmd)
        named = self._named(cmd)
        if need == "property":
            miss = [m for m in miss if m != "object|kind"]
            if named:
                if len(self._prop_candidates(cmd)) > 1:
                    miss.append("object|kind")
            elif self._active_property(self._vid()) is None:
                miss.append("object|kind")
        elif need == "object" and len(cmd.get("targets") or ()) > 1:
            miss = [m for m in miss if m != "object|kind"] + ["object|kind"]
        elif intent == "show":
            # one colouring property per representation: two on one grid is a question
            reps = [t.get("rep_path") for t in self.targets(cmd) if self._is_prop(t)]
            if len(reps) != len(set(reps)):
                miss = [m for m in miss if m != "object|kind"] + ["object|kind"]
        if (intent == "threshold" and "exclude" in sl and sl["exclude"] is None and self._values(cmd)
                and sl.get("values_mode") != "spare"):
            # values whose polarity nothing said (a local AI's service that
            # sends none): hidden, or kept? asked once they are known
            miss.append("exclude")
        if intent == "close_panel" and "panel" in miss and self._view_said(cmd):
            # a 3D view: the gesture says how to close its tab, nothing to ask
            miss.remove("panel")
        return miss

    @staticmethod
    def _view_said(cmd):
        return _has(_words_of(cmd.get("text") or ""), _VIEW_SAID)

    def _one_property(self, cmd, vid, lang):
        """(the property the command acts on, None) or (None, a reply)."""
        if self._named(cmd):
            props = self._prop_candidates(cmd)
            if props:
                fresh = self._index()
                o = fresh.get(props[0]["path"], props[0])
                if cmd.get("intent") in _DRAWN and o.get("type") == "DerivedProperty":
                    return None, self._not_drawn([o], lang)
                return o, None
            if cmd.get("intent") in ("threshold", "highlight") and cmd.get("targets"):
                return None, _reply(False, _t(
                    lang, "Cela agit sur les mailles d'une grille : nommez une propriété de grille.",
                    "That acts on the cells of a grid: name a grid property."))
            return None, self._not_found(cmd, lang)
        act = self._active_property(vid)
        if act is not None:
            return act, None
        return None, _reply(False, _t(
            lang, "De quelle propriété parlez-vous ? Nommez-la, par exemple « … de la porosité ».",
            "Which property do you mean? Name it, for instance “… of the porosity”."))

    def _objects_of(self, cmd):
        fresh = self._index()
        return [fresh.get(t.get("path"), t) for t in self.targets(cmd) if t.get("path")]

    def _not_found(self, cmd, lang):
        sl = cmd.get("slots") or {}
        what = sl.get("kind") or ""
        if what:
            # say what IS there: the named grid's properties, else the grids'
            named = [o for cands in sl.get("objects") or () for o in cands if not self._is_prop(o)]
            holders = named or [o for o in self.objects() if o.get("type") in _GRIDS]
            props = [p["title"] for p in self.objects() if self._is_prop(p)
                     and p.get("parent") in {h.get("path") for h in holders}]
            where = ", ".join(dict.fromkeys(h.get("title", "") for h in holders))
            have = ", ".join(dict.fromkeys(props)) if props else ""
            fr = f"Je ne trouve aucune propriété « {what} » dans les données lues."
            en = f"I find no “{what}” property in the data read."
            if where and have:
                fr += f" {where} a : {have}."
                en += f" {where} has: {have}."
            return _reply(False, _t(lang, fr, en))
        return _reply(False, _t(lang, "Je ne trouve pas cet objet dans les données lues.",
                                "I cannot find that object in the data read."))

    @staticmethod
    def _not_drawn(objs, lang):
        names = ", ".join(o.get("title") or o.get("path", "") for o in objs
                          if o.get("type") == "DerivedProperty")
        return _reply(False, _t(
            lang, f"{names} est une propriété dérivée : elle ne se dessine pas dans la vue 3D"
                  " (ni œil, ni couleurs, ni filtre). Les statistiques, la distribution et le"
                  " cross-plot la lisent.",
            f"{names} is a derived property: it is not drawn in the 3D view (no eye, colours"
            " or filter). Statistics, distribution and cross-plot read it."))

    def _globe(self, vid):
        """The Globe view hosts no isolate (one built there would draw
        local-CRS metres thousands of km off the Earth)."""
        return bool(vid) and bool(self._get(f"ui_globe_mode__{vid}", False))

    @staticmethod
    def _no_globe(lang):
        return _reply(False, _t(lang, "La vue est le Globe : filtres, coupes et surbrillance n'y"
                                      " sont pas disponibles. Faites-le dans une vue 3D.",
                                "The view is the Globe: filters, slices and highlights are not"
                                " available there. Do it in a 3D view."))

    # ------------------------------------------------------------ the host protocol
    def parse(self, text):
        """The command of `text` — and, when the sentence holds several
        ("show the porosity and switch to viridis"), the words of each other
        one under `then`: the panel reads each when its turn comes, after
        the one before has run, so "show the oil zones then the wells that
        cross them" knows the zone, and "… and filter above 0.2" the
        property just shown."""
        parts = nlu_multi.split(text)
        # an addition the cut took as a joint between two requests ("c'est le
        # gaz qu'il faut aussi masquer"): said of the first one
        also = len(parts) > 1 and self._adds(_words_of(text)) and not any(self._adds(_words_of(p)) for p in parts)
        cmd = self._parse_one(parts[0] if len(parts) > 1 else text, also=also)
        if len(parts) > 1:
            cmd["then"] = list(parts[1:])
        return cmd

    def parse_next(self, text):
        """A later request of a sentence, read when its turn comes (the one
        before has run): one request, read as `parse` reads it — and one
        that names more values of a property ("hide the oil zone then the
        gas", "keep the oil then the gas") adds them to the ones its filter
        already hides or keeps: the sentence asked for both."""
        return self._parse_one(text, follow=True)

    def _parse_one(self, text, follow=False, also=False):
        """The engine's reading of one request. A sentence of words the
        engine does not know is its own call (intent None): it reads the
        normalised words, a slip in a verb mended ("Annule !", "anule").
        `follow`: a later request of the same sentence; `also`: an addition
        said in the sentence, outside this request's words."""
        objs = self.objects()
        try:
            cmd = nlu_engine.parse(text, objs, context=self._context)
        except Exception as exc:
            print("[assistant] parse:", exc, flush=True)
            return {"intent": None, "confidence": 0.0, "alternatives": [], "slots": {},
                    "targets": [], "missing": [], "sure": False, "text": text}
        if cmd.get("intent"):
            if follow:
                cmd["follow"] = True
            if also:
                cmd["also_said"] = True
            self._read_values(cmd)
            cmd["missing"] = self.missing(cmd)
            cmd["sure"] = (cmd.get("confidence", 0.0) >= nlu_engine.SURE and not cmd["missing"]
                           and not cmd.get("choose_between"))
            if tuple(cmd.get("choose_between") or ()) == _RUN_FIRST:
                # filter by default: the panel runs the filter and offers the
                # highlight instead, rather than asking first
                cmd["run_first"] = True
        return cmd

    def _read_values(self, cmd):
        """What a gesture on category values does with the values it names:
        its polarity (`_take_up_polarity`), the values said not
        (`_settle_negations`), and how they meet the filter's
        (`_mark_values`)."""
        self._take_up_polarity(cmd)
        self._settle_negations(cmd)
        self._mark_values(cmd, bool(cmd.get("follow")))

    def with_intent(self, cmd, intent):
        """The command with the gesture a button chose ("filtrer par valeur"
        under "Did you mean…?"): the sentence's words read again for it — a
        hiding said stays a hiding ("masque des mailles de Fluids" then
        "filter by value" hides the value chosen next, never keeps only it)."""
        cmd = dict(cmd, intent=intent, slots=dict(cmd.get("slots") or {}))
        if intent == "threshold" and not cmd["slots"].get("exclude") and self._hides_said(cmd):
            cmd["slots"]["exclude"] = True
        self._read_values(cmd)
        return cmd

    def _hides_said(self, cmd):
        """The sentence's own words hide its value ("masque", "don't show",
        "rends invisible") — not a hiding verb said not ("ne cache pas"),
        nor the other values hidden ("cache le reste": keep the value)."""
        said = _words_of(cmd.get("text"))
        return self._hides(said) and not _has(said, _NOT_HIDING)

    @staticmethod
    def _hiding_said(said):
        """A hiding word or phrase of the sentence's own ("cache", "vire",
        "je ne veux plus voir", "don't show", "invisible")."""
        return _has(said, nlu_lexicon.HIDING + nlu_engine.HIDE_MORE + _HIDE_SAID + _GONE)

    @staticmethod
    def _negated(said):
        """A sentence said not: "ne … pas / plus / jamais", "don't", "never"."""
        words = said.split()
        return bool((("ne" in words or "n" in words) and any(w in _NOT_FR for w in words)) or _has(said, _NOT_EN))

    def _again_said(self, said):
        """A value asked to be seen again ("je veux revoir l'huile", "restore
        the oil") — never when it is said not ("je ne veux plus revoir le
        gaz") or hidden in the same breath ("masque à nouveau l'huile")."""
        return _has(said, _AGAIN) and not self._negated(said) and not self._hiding_said(said)

    def _gesture_said(self, said):
        """A gesture the sentence says itself, other than hiding: showing,
        keeping, highlighting ("voir", "remets", "garde", "surligne")."""
        return (_has(said, _SHOW_PLAIN + nlu_engine.FILTER_WORDS + nlu_engine.HIGHLIGHT_WORDS + nlu_engine.KEEP_ALL)
                or self._again_said(said))

    def _take_up_polarity(self, cmd):
        """The last command's polarity on a sentence that only names another
        value of it: after "hide the oil zone", "and the gas?" and "I said
        water and gas" hide those values too. A sentence that says its own
        gesture is read as it says it: a showing word ("non, je voulais voir
        l'huile", "ramène l'huile", "I wanted to see the oil") or a keeping
        one is never turned into a hiding by the last command — nor is the
        hiding the engine took from that command alone kept on it."""
        ctx = self._context or {}
        sl = cmd.get("slots")
        if not (ctx.get("exclude") and isinstance(sl, dict) and sl.get("category")):
            return
        said = _words_of(cmd.get("text"))
        if self._hiding_said(said):
            return              # its own hiding: the engine's reading stands
        if self._gesture_said(said):
            if sl.get("exclude") and not _has(said, nlu_engine.OTHERS):
                # no hiding word: the engine took it from the last command
                sl.pop("exclude", None)
            return
        if _has(said, nlu_engine.OTHERS) or sl.get("exclude"):
            return
        if not (sl.get("repeat") or sl.get("from_context")) or cmd.get("intent") != ctx.get("intent"):
            return
        sl["exclude"] = True

    def _mark_values(self, cmd, follow):
        """How a gesture on category values meets what the property's filter
        already does, in its slots' `values_mode` — the values themselves
        are read from the view when the gesture runs (`_do_threshold`), so
        an undo, "remove the filters" or a gesture in between never leaves
        a value of before behind:

          "add"      the values join the ones the filter hides, or keeps:
                     every hiding ("hide the gas", "don't show the gas",
                     "and the gas?" after a hiding) — what is hidden stays
                     hidden until it is shown —, a value added in so many
                     words ("and the gas as well", "surligne aussi l'huile":
                     `also` in the slots) and, in one sentence, a later
                     request ("…then the gas") after a keep or a highlight
                     of the same property
          "again"    the values asked to be seen again come back, the
                     others stay hidden ("je veux revoir l'huile")
          "correct"  a correction ("en fait le gaz", "I said water and
                     gas") replaces the values the last command named
          "spare"    every value named is said not to be hidden ("ne cache
                     pas l'huile"): nothing is done (`_settle_negations`)
          (none)     the values replace the filter's ("keep only the gas",
                     "hide everything but the water", a keep or a highlight
                     said again in a sentence of its own)"""
        sl = cmd.get("slots")
        intent = cmd.get("intent")
        if not (isinstance(sl, dict) and sl.get("category") and intent in _ADDING):
            return
        sl.pop("also", None)
        if sl.get("values_mode") == "spare":
            return
        said = _words_of(cmd.get("text"))
        also = self._adds(said) or bool(cmd.get("also_said"))
        mode = None
        if _has(said, _ONLY + nlu_engine.OTHERS):
            mode = None
        elif intent == "threshold" and self._again_said(said) and not _has(said, nlu_engine.FILTER_WORDS):
            # seen again, not kept again ("garde à nouveau l'huile" keeps it)
            mode = "again"
        elif self._corrects(cmd) or (not also and self._denies_value(cmd)):
            mode = "correct" if intent == "threshold" else None
        elif intent == "highlight":
            mode = "add" if (follow or also) and not sl.get("exclude") else None
        elif sl.get("exclude") or follow or also:
            mode = "add"
        if mode:
            sl["values_mode"] = mode
        else:
            sl.pop("values_mode", None)
        if mode == "add" and also:
            sl["also"] = True

    @staticmethod
    def _adds(said):
        """A value added in so many words ("aussi", "too", "as well") — not
        in a sentence that says what it replaces ("au lieu de", "instead",
        "plutôt")."""
        return _has(said, _ALSO) and not _has(said, _INSTEAD)

    def _corrects(self, cmd):
        """A sentence that corrects the last one: "je voulais", "I said",
        "non, l'eau", "en fait le gaz", "sorry, the gas", "plutôt le gaz",
        "c'est l'huile que je voulais". Never one that adds in so many words
        ("pardon, cache aussi l'huile", "actually, the gas too") unless it
        says what it replaces; never "pardon" or "sorry" said after the
        request ("et l'huile aussi, pardon") or followed by "and" ("pardon,
        et le gaz ?"); never a leading "no" that says the value not ("no
        more gas", "no gas")."""
        text = str(cmd.get("text") or "")
        said = _words_of(text)
        if self._adds(said) or cmd.get("also_said"):
            return False
        words = said.split()
        if _has(said, nlu_engine.CORRECTION + _CORRECTING) or words[:1] in (["non"], ["nope"]):
            return True
        if words[:1] == ["no"]:
            return bool(_NO_CORRECTS.match(text.strip().lower()))
        if words[:1] in [[w] for w in _SORRY]:
            return words[1:2] not in (["et"], ["and"])
        return self._its_value_that(cmd)

    def _its_value_that(self, cmd):
        """ "C'est l'huile que je voulais", "c'est le gaz qu'il faut
        cacher": a value set apart by "c'est … que" — the one meant instead
        of the last request's. A "c'est" said in passing ("c'est bien",
        "c'est ce que je voulais") names no value there."""
        toks = nlu_tokens(cmd.get("text") or "")
        starts = [i + 2 for i in range(len(toks) - 1) if toks[i] == "c" and toks[i + 1] == "est"]
        if not starts:
            return False
        for a, b, typ, *_rest in nlu_slots.spans(toks, self.objects()):
            if typ == "category" and any(s <= a <= s + 3 for s in starts) and \
                    any(t in ("que", "qu") for t in toks[b:b + 2]):
                return True
        return False

    def _denies_value(self, cmd):
        """A value the last request named that the sentence names but the
        command does not act on — said not, next to the one meant ("non, pas
        le gaz, l'huile"): a correction. A value said not that the last
        request did not name corrects nothing ("cache le gaz, pas l'huile"
        after "masque l'eau": the water stays hidden, the oil is left as it
        is)."""
        found = nlu_slots.spans(nlu_tokens(cmd.get("text") or ""), self.objects())
        said = {f[3] for f in found if len(f) > 3 and f[2] == "category"}
        last = set((self._context or {}).get("said") or ())
        return bool((said - set(self._values(cmd))) & last)

    # --- the values said not ---------------------------------------------------
    def _settle_negations(self, cmd):
        """The values a filter on category values names but must not act on,
        read from the words that govern each one:

          after a hiding verb said not ("ne cache pas l'huile", "surtout ne
              masque pas l'huile", "don't hide the gas"): left as they are —
              with no other value named, nothing is done ("spare")
          after "au lieu de", "instead of", "plutôt que": the values the
              request replaces (`instead`), which a correction gives back
          with a zone said not ("sans le gaz", "plus de gaz", "no gas",
              "without the gas", "le gaz en moins"): hidden — a keep keeps
              the other values it names, and with none it hides these"""
        sl = cmd.get("slots")
        if cmd.get("intent") != "threshold" or not (isinstance(sl, dict) and sl.get("category")):
            return
        sl.pop("instead", None)
        if sl.get("values_mode") == "spare":
            sl.pop("values_mode", None)
        toks = nlu_tokens(_PAUSES.sub(f" {_PAUSE} ", str(cmd.get("text") or "")))
        found = [(a, b, f[0]) for a, b, typ, *f in nlu_slots.spans(toks, self.objects()) if typ == "category"]
        if not found:
            return
        not_hiding = self._phrases_at(toks, _NOT_HIDING)
        hiding = [p for p in self._phrases_at(toks, nlu_lexicon.HIDING + nlu_engine.HIDE_MORE + _HIDE_SAID + _GONE)
                  if not any(s <= p[0] < e for s, e in not_hiding)]
        spared, instead, gone = set(), set(), set()
        for a, b, value in found:
            lead, skipped = self._lead(toks, a)
            if self._governed_by_not_hiding(toks, a, not_hiding, hiding):
                spared.add(value)
            elif lead[-2:] == ["au", "lieu"] or lead[-1:] == ["instead"] or lead[-2:] in (
                    ["plutot", "que"], ["plutot", "qu"], ["rather", "than"]):
                instead.add(value)
            elif self._zone_said_not(toks, a, b, lead, skipped):
                gone.add(value)
        values = self._values(cmd)
        if values and set(values) <= spared:
            # "ne cache pas l'huile": nothing to hide, nor to keep alone
            sl["values_mode"] = "spare"
            return
        # a hiding hides neither a value said not to be hidden nor the one it
        # replaces; a keep keeps neither a zone said not nor the one replaced
        drop = (spared | instead) if sl.get("exclude") else (gone | instead)
        acted = [v for v in values if v not in drop]
        if not acted and not sl.get("exclude") and gone & set(values):
            # "sans le gaz" after a keep: the gas goes, the other values stay
            acted = [v for v in values if v in gone and v not in instead]
            sl["exclude"] = True
        if not acted:
            return
        sl["category"], sl["categories"] = acted[0], acted
        if instead:
            sl["instead"] = sorted(instead)

    @staticmethod
    def _phrases_at(toks, phrases):
        """[(start, end)] of each phrase of `phrases` in the tokens."""
        out = []
        for p in phrases:
            words = p.split()
            n = len(words)
            out += [(i, i + n) for i in range(len(toks) - n + 1) if toks[i:i + n] == words]
        return sorted(set(out))

    @staticmethod
    def _lead(toks, a):
        """(the three words before position `a` once the little words are
        skipped, the little words skipped) — "sans les mailles de gaz":
        (["sans"], ["les", "mailles", "de"])."""
        i = a
        while i > 0 and toks[i - 1] in _LEAD_SKIP:
            i -= 1
        return toks[max(0, i - 3):i], toks[i:a]

    @staticmethod
    def _governed_by_not_hiding(toks, a, not_hiding, hiding):
        """Whether the last verb said before position `a` in its clause is a
        hiding verb said not ("cache le gaz, ne cache pas l'huile": the oil,
        not the gas)."""
        start = max([i + 1 for i in range(a) if toks[i] in _CLAUSE_ENDS] or [0])
        # (a not-hiding phrase may start on the clause end itself: "mais laisse")
        said = [(e, True) for s, e in not_hiding if e > start and e <= a] + \
               [(e, False) for s, e in hiding if start <= s and e <= a]
        return bool(said) and max(said)[1]

    @staticmethod
    def _zone_said_not(toks, a, b, lead, skipped):
        """A value said not as a zone: "sans le gaz", "sans aucun gaz",
        "without the gas", "plus de gaz", "pas d'huile", "no gas", "no more
        gas", "le gaz en moins" — not "no, the gas" (a pause: a correction),
        nor "en plus le gaz" (an addition)."""
        prev = lead[-1] if lead else ""
        prev2 = lead[-2] if len(lead) > 1 else ""
        first = skipped[0] if skipped else ""
        return (prev in ("sans", "without", "aucun", "aucune")
                or (prev == "no" and not skipped)
                or (prev == "more" and prev2 == "no")
                or (prev in ("plus", "pas") and first in ("de", "d") and prev2 not in ("en", "de"))
                or toks[b:b + 2] == ["en", "moins"])

    def readonly(self, intent):
        return bool(catalogue.INTENTS.get(intent, {}).get("readonly", False))

    def label(self, intent, lang):
        fr, en = LABELS.get(intent, (intent, intent))
        return _t(lang, fr, en)

    def instead_label(self, cmd, intent, lang):
        """The button that takes back the gesture run by default and runs
        `intent` with the same words ("Surligner plutôt")."""
        verb = {"highlight": ("Surligner", "Highlight"), "threshold": ("Filtrer", "Filter")}.get(intent)
        if verb is None:
            return None
        return _t(lang, f"{verb[0]} plutôt", f"{verb[1]} instead")

    def choice_label(self, cmd, intent, lang):
        """A button's words for THIS command: a gesture on category values
        names them ("Keep only the “oil” cells", "Highlight the “water” and
        “gas” cells on the whole grid"); None: the general words."""
        values = self._values(cmd)
        if not values or intent not in ("threshold", "highlight"):
            return None
        targets = cmd.get("targets") or []
        shown = [next((str(lb) for t in targets for lb in (t.get("categories") or {}).values()
                       if nlu_slots.category_of(str(lb)) == v), v) for v in values]
        said = self._said_values(shown, lang)
        prop = targets[0].get("title", "") if targets else ""
        on = f" ({prop})" if prop else ""
        if intent == "threshold" and (cmd.get("slots") or {}).get("values_mode") == "again":
            return _t(lang, f"Afficher de nouveau les mailles {said}{on}", f"Show the {said} cells again{on}")
        if intent == "threshold" and (cmd.get("slots") or {}).get("values_mode") == "spare":
            return _t(lang, f"Laisser les mailles {said} telles quelles{on}", f"Leave the {said} cells as they are{on}")
        if intent == "threshold" and (cmd.get("slots") or {}).get("exclude"):
            return _t(lang, f"Masquer les mailles {said}{on}", f"Hide the {said} cells{on}")
        if intent == "threshold":
            return _t(lang, f"Ne garder que les mailles {said}{on}", f"Keep only the {said} cells{on}")
        return _t(lang, f"Surligner les mailles {said} sur toute la grille",
                  f"Highlight the {said} cells on the whole grid")

    @staticmethod
    def _values(cmd):
        """The category values the command names, in the sentence's order:
        the engine's `categories` ("the water and gas zones") when they
        start with its `category`, else that one value — a value a button
        chose, or the one a correction kept ("not the gas, the oil"),
        replaces what the list says."""
        sl = cmd.get("slots") or {}
        cat = sl.get("category")
        if not cat:
            return []
        many = [str(c) for c in sl.get("categories") or () if c]
        if many and many[0] == cat:
            return list(dict.fromkeys(many))
        return [cat]

    @staticmethod
    def _said_values(labels, lang):
        """The values as a reply quotes them: « water » et « gas »."""
        quoted = [f"« {lb} »" if _lang(lang) == "fr" else f"“{lb}”" for lb in labels]
        if len(quoted) < 2:
            return "".join(quoted)
        return ", ".join(quoted[:-1]) + _t(lang, " et ", " and ") + quoted[-1]

    def _codes(self, cmd, o, lang):
        """The category values the command names, as `o` lists them: (their
        labels, their codes, None); (None, None, a reply) when `o` does not
        list one of them; ([], [], None) when no value is named."""
        labels, codes = [], []
        for v in self._values(cmd):
            label = next((str(lb) for lb in (o.get("categories") or {}).values()
                          if nlu_slots.category_of(str(lb)) == v), None)
            code = nlu_engine.code_of(o, v) if label is not None else None
            if code is None:
                return None, None, _reply(False, _t(lang, f"{o.get('title')} n'a pas de valeur « {v} ».",
                                                    f"{o.get('title')} has no “{v}” value."))
            labels.append(label)
            codes.append(code)
        return labels, codes, None

    @staticmethod
    def _all_codes(o):
        """Every code of a categorical property's table, as numbers."""
        out = []
        for c in (o.get("categories") or {}):
            text = str(c).strip()
            if _NUMBER.match(text):
                out.append(float(text))
        return out

    @staticmethod
    def _runs(codes):
        """Codes as [lo, hi] runs of consecutive codes: water 0 and gas 2
        are two runs, [0, 0] and [2, 2]; oil 1 and gas 2 one, [1, 2]."""
        runs = []
        for c in sorted(set(codes)):
            if runs and c - runs[-1][1] == 1:
                runs[-1][1] = c
            else:
                runs.append([c, c])
        return runs

    @staticmethod
    def _without(entries, lo, hi, whole=(None, None)):
        """The [lo, hi] runs left when the range [lo, hi] is hidden from
        what the filter `entries` (side by side on one array) keep — from
        the data's `whole` range when there is none (None: its own end). A
        bound of the range hidden is hidden too, as it was lit."""
        def number(v):
            # a bound the catalogue or the filter holds as text, or none
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError) as exc:
                print("[assistant] a filter's bound is not a number:", exc, flush=True)
                return None

        below = math.nextafter(lo, -math.inf) if lo is not None else None
        above = math.nextafter(hi, math.inf) if hi is not None else None
        runs = []
        for a, b in [[number(e.get("low")), number(e.get("high"))] for e in entries] or [list(map(number, whole))]:
            if below is not None and (a is None or a <= below):
                runs.append([a, below if b is None else min(b, below)])
            if above is not None and (b is None or b >= above):
                runs.append([above if a is None else max(a, above), b])
        return runs

    @staticmethod
    def _span_words(lo, hi, lang):
        """A range in words: "de 0,1 à 0,2", "à partir de 0,2", "jusqu'à 0,1"."""
        if lo is not None and hi is not None:
            return _t(lang, f"de {_num(lo, lang)} à {_num(hi, lang)}", f"from {_num(lo, lang)} to {_num(hi, lang)}")
        if lo is not None:
            return _t(lang, f"à partir de {_num(lo, lang)}", f"from {_num(lo, lang)} up")
        return _t(lang, f"jusqu'à {_num(hi, lang)}", f"up to {_num(hi, lang)}")

    def _kept(self, o, codes, exclude):
        """The codes a gesture on category values keeps: the ones named, or,
        when they are hidden, every other code of `o`."""
        if not exclude:
            return sorted(set(codes))
        return [c for c in sorted(set(self._all_codes(o))) if c not in set(codes)]

    def _label_of(self, o, code):
        names = o.get("categories") or {}
        key = int(code) if float(code).is_integer() else code
        return str(names.get(key, names.get(code, code)))

    def _ask_bounds(self, cmd, lang, cancel):
        """The bounds question, said with the property and its range; a
        categorical property offers its values as buttons; with nothing
        named, the grids' category values are the buttons — the reader
        never has to wonder "values of what"."""
        sl = cmd.get("slots") or {}
        props = self._prop_candidates(cmd) if self._named(cmd) else []
        o = props[0] if len(props) == 1 else (None if props else self._active_property(self._vid()))
        if o is None and not props and sl.get("kind"):
            # a kind said with no property of it read yet: its words
            fr, en = _KIND_WORDS.get(sl["kind"], (sl["kind"], sl["kind"]))
            return {"text": _t(lang, f"Entre quelles valeurs de {fr} ? Redites-le avec une borne, par exemple"
                                     " « au-dessus de 0,2 » ou « entre 10 et 20 ».",
                               f"Between which values of {en}? Say it again with a bound, for instance"
                               " “above 0.2” or “between 10 and 20”."), "choices": [cancel]}
        # the value the local AI read in words the lexicon lacks ("la
        # flotte"): offered first, never taken without the reader's click
        first = sl.get("suggested")
        if o is not None and o.get("categories"):
            labels = sorted((str(v) for v in o["categories"].values()),
                            key=lambda lb: nlu_slots.category_of(lb) != first)[:_CHOICES]
            if sl.get("exclude") or (cmd.get("intent") == "threshold" and self._hides_said(cmd)):
                text = _t(lang, f"Quelles mailles de {o['title']} masquer ?", f"Which cells of {o['title']} to hide?")
            else:
                text = _t(lang, f"Quelles mailles de {o['title']} ?", f"Which cells of {o['title']}?")
            return {"text": text, "choices": [{"id": f"category:{lb}", "label": lb} for lb in labels] + [cancel]}
        if o is not None:
            rng = self._range_words(o, lang)
            ex = _num(self._example_value(o), lang)
            return {"text": _t(lang, f"Entre quelles valeurs de {o['title']}{rng} ? Redites-le avec une borne,"
                                     f" par exemple « au-dessus de {ex} ».",
                               f"Between which values of {o['title']}{rng}? Say it again with a bound,"
                               f" for instance “above {ex}”."), "choices": [cancel]}
        cats = sorted(((p, str(lb)) for p in self.objects() if self._is_prop(p) and p.get("categories")
                       and p.get("rep_type") in _ISOLATABLE for lb in p["categories"].values()),
                      key=lambda pl: nlu_slots.category_of(pl[1]) != first)[:_CHOICES]
        choices = [{"id": f"category:{lb}", "label": f"{lb} ({p['title']})"} for p, lb in cats] + [cancel]
        tail = _t(lang, ", ou choisissez une valeur :", ", or pick a value:") if cats else "."
        return {"text": _t(lang, "Quelles mailles ? Dites la propriété et la condition, par exemple"
                                 " « la porosité au-dessus de 0,2 »" + tail,
                           "Which cells? Say the property and the condition, for instance"
                           " “porosity above 0.2”" + tail), "choices": choices}

    @staticmethod
    def _range_words(o, lang):
        """The range a question appends (" (from 0.02 to 0.35)"), or ""
        when the node carries none."""
        if o.get("vmin") is None or o.get("vmax") is None:
            return ""
        try:
            lo, hi = float(o["vmin"]), float(o["vmax"])
        except (TypeError, ValueError) as exc:
            print("[assistant] a property's range is not a number:", exc, flush=True)
            return ""
        return _t(lang, f" (de {_num(lo, lang)} à {_num(hi, lang)})", f" (from {_num(lo, lang)} to {_num(hi, lang)})")

    def with_category(self, cmd, label):
        """The command with the category value a button chose ("oil" under
        "Which cells of Fluids?"): the value in its slots and, when it
        names no property, the grid property that lists the value as its
        target. A filter whose sentence hides ("masque des mailles de
        Fluids") hides the value chosen, which meets the values the filter
        hides already as a value said would (`_mark_values`)."""
        cmd = dict(cmd)
        sl = dict(cmd.get("slots") or {})
        cat = nlu_slots.category_of(str(label))
        sl.update(category=cat, categories=[cat], min=None, max=None)
        for key in ("values_mode", "also", "instead"):
            sl.pop(key, None)
        if cmd.get("intent") == "threshold" and not sl.get("exclude") and self._hides_said(cmd):
            sl["exclude"] = True
        cmd["slots"] = sl
        if not any(self._is_prop(t) for t in cmd.get("targets") or ()):
            hits = [p for p in self.objects() if self._is_prop(p) and nlu_engine.has_category(p, cat)]
            grids = [p for p in hits if p.get("rep_type") in _ISOLATABLE]
            if hits:
                cmd["targets"] = [dict(p) for p in (grids or hits)[:1]]
        self._mark_values(cmd, bool(cmd.get("follow")))
        return cmd

    def ask_missing(self, cmd, lang):
        """The question that asks for what `cmd` still lacks, with its
        choice buttons (Cancel always last)."""
        miss = list(cmd.get("missing") or self.missing(cmd))
        cancel = {"id": "cancel", "label": _t(lang, "Annuler", "Cancel")}
        # what a button cannot answer first: the sentence is said again with it
        for need in miss:
            if need == "min|max":
                # the wells' walk asks about its zone, the grid's property
                asked = dict(cmd, targets=self._zone(cmd)) if cmd.get("intent") == "well_cells" else cmd
                return self._ask_bounds(asked, lang, cancel)
            if need == "preset":
                return {"text": _t(lang, "Quelle table de couleurs ? Par exemple viridis, turbo, jet,"
                                         " arc-en-ciel ou gris.",
                                   "Which colour table? For instance viridis, turbo, jet, rainbow"
                                   " or grayscale."), "choices": [cancel]}
            if need == "panel":
                names = ", ".join(dict.fromkeys(_t(lang, fr, en) for fr, en in _PANELS.values()))
                return {"text": _t(lang, f"Quel panneau ? {names}.", f"Which panel? {names}."),
                        "choices": [cancel]}
            if need == "axis":
                return {"text": _t(lang, "Selon quel axe : I, J ou K ?", "Along which axis: I, J or K?"),
                        "choices": [cancel]}
            if need == "factor":
                return {"text": _t(lang, "De combien ? Par exemple « exagération verticale x 3 ».",
                                   "By how much? For instance “vertical exaggeration x 3”."),
                        "choices": [cancel]}
            if need == "exclude":
                return self._ask_polarity(cmd, lang, cancel)
            text = self._slot_question(need, cmd, lang)
            if text:
                return {"text": text, "choices": [cancel]}
        cands = self.targets(cmd)
        if not cands:
            return {"text": _t(lang, "De quel objet ou de quelle propriété parlez-vous ?",
                               "Which object or property do you mean?"), "choices": [cancel]}
        index = self._index()
        choices = [{"id": f"target:{o['path']}", "label": self._name(o, lang, index)}
                   for o in cands[:_CHOICES]]
        text = _t(lang, "Lequel voulez-vous dire ?", "Which one do you mean?")
        if len(cands) > _CHOICES:
            text += _t(lang, f" … et {len(cands) - _CHOICES} autres : précisez le nom sinon.",
                       f" … and {len(cands) - _CHOICES} more: give the name otherwise.")
        return {"text": text, "choices": choices + [cancel]}

    @staticmethod
    def _slot_question(need, cmd, lang):
        """The question for a parameter of the view's gestures, said again
        with it (no button can carry it), or None."""
        if need == "direction":
            return _t(lang, "Dans quelle direction : de dessus, de dessous, depuis le nord, le sud, l'est ou l'ouest ?",
                      "Which direction: top, bottom, from the north, the south, the east or the west?")
        if need == "step" and cmd.get("intent") == "realization":
            return _t(lang, "Quelle réalisation ? Par exemple « réalisation 2 » ou « réalisation suivante ».",
                      "Which realization? For instance “realization 2” or “next realization”.")
        if need == "step":
            return _t(lang, "Quel pas de temps ? Un numéro, « suivant », « précédent », « premier » ou « dernier ».",
                      "Which time step? A number, “next”, “previous”, “first” or “last”.")
        if need == "style":
            return _t(lang, "Quel mode de dessin : surface pleine, surface avec arêtes, fil de fer, points ou contour ?",
                      "Which drawing style: plain surface, surface with edges, wireframe, points or outline?")
        if need == "scale":
            return _t(lang, "Quelle échelle des couleurs : logarithmique ou linéaire ?",
                      "Which colour scale: logarithmic or linear?")
        if need == "tool":
            names = ", ".join(_TOOL_TITLES.values())
            return _t(lang, f"Quelle carte ? {names}.", f"Which card? {names}.")
        return None

    def _ask_polarity(self, cmd, lang, cancel):
        """Hide the values named, or keep only them: one button each, the
        command's own words ("Hide the “gas” cells (Fluids)")."""
        sl = dict(cmd.get("slots") or {})
        hide = dict(cmd, slots=dict(sl, exclude=True))
        keep = dict(cmd, slots=dict(sl, exclude=False))
        targets = cmd.get("targets") or []
        shown = [next((str(lb) for t in targets for lb in (t.get("categories") or {}).values()
                       if nlu_slots.category_of(str(lb)) == v), v) for v in self._values(cmd)]
        said = self._said_values(shown, lang)
        return {"text": _t(lang, f"Masquer les mailles {said}, ou ne garder qu'elles ?",
                           f"Hide the {said} cells, or keep only them?"),
                "choices": [{"id": "exclude:true", "label": self.choice_label(hide, "threshold", lang)},
                            {"id": "exclude:false", "label": self.choice_label(keep, "threshold", lang)},
                            cancel]}

    def examples(self, lang):
        """Six sentences that work on what is loaded, generic ones otherwise."""
        lang = _lang(lang)
        objs = self.objects()
        grids = sorted((o for o in objs if o["type"] in _GRIDS), key=lambda o: not o.get("loaded"))
        for g in grids:
            props = [o for o in objs if self._is_prop(o) and o.get("parent") == g["path"]]
            if not props:
                continue
            kinds = [(nlu_engine.kind_of(p), p) for p in props]
            known = [(k, p) for k, p in kinds if k in _KIND_WORDS]
            k, p = (sorted(known, key=lambda kp: kp[0] != "porosity")[0] if known else (None, props[0]))
            v = self._example_value(p)
            # a highlight lights the cells one by one (highlight_where caps
            # it): its example asks for the top of the range, not half the grid
            vh = self._example_value(p, 0.9)
            G = g["title"]
            if k:
                fr, en = _KIND_WORDS[k]
                return ([f"montre {fr} de {G}", f"filtre {fr} au-dessus de {_num(v, 'fr')}",
                         f"surligne les mailles où {fr} dépasse {_num(vh, 'fr')}",
                         f"quelle est {fr} moyenne ?", f"décris {G}", "ouvre les statistiques"]
                        if lang == "fr" else
                        [f"show the {en} of {G}", f"filter {en} above {_num(v, 'en')}",
                         f"highlight the cells where {en} is above {_num(vh, 'en')}",
                         f"what is the mean {en}?", f"describe {G}", "open statistics"])
            T = p["title"]
            return ([f"montre {T} de {G}", f"filtre {T} au-dessus de {_num(v, 'fr')}",
                     f"surligne les mailles où {T} dépasse {_num(vh, 'fr')}",
                     f"quelle est la moyenne de {T} ?", f"décris {G}", "ouvre les statistiques"]
                    if lang == "fr" else
                    [f"show {T} of {G}", f"filter {T} above {_num(v, 'en')}",
                     f"highlight the cells where {T} is above {_num(vh, 'en')}",
                     f"what is the mean of {T}?", f"describe {G}", "open statistics"])
        wells = [o for o in objs if o["type"] == "Wellbore"]
        if wells:
            W = wells[0]["title"]
            return ([f"montre le puits {W}", f"décris {W}", f"ouvre la vue des logs du puits {W}",
                     "liste ce qui est chargé", "recadre la vue", "exagération verticale x 3"]
                    if lang == "fr" else
                    [f"show the well {W}", f"describe {W}", f"open the log view of well {W}",
                     "list what is loaded", "reset the camera", "vertical exaggeration x 3"])
        return list(_GENERIC_EXAMPLES[lang])

    @staticmethod
    def _example_value(p, frac=0.5):
        """A round value inside the property's range (at `frac` of it), when
        the reader wrote one on the node; 0.2 otherwise."""
        if p.get("vmin") is None or p.get("vmax") is None:
            return 0.2
        try:
            lo, hi = float(p["vmin"]), float(p["vmax"])
        except (TypeError, ValueError) as exc:
            print("[assistant] a property's range is not a number:", exc, flush=True)
            return 0.2
        if not hi > lo:
            return 0.2
        v = lo + (hi - lo) * frac
        if abs(v) >= 10:
            return float(round(v))
        # one digit when it stays inside the range (0.36 of [0, 0.4] is not 0.4)
        r = float(f"{v:.1g}")
        return r if lo < r < hi else float(f"{v:.2g}")

    # ------------------------------------------------------------ questions (readonly)
    def answer(self, cmd, lang):
        """The reply to a read-only command; any other command of the
        catalogue is carried out, its reply returned without an undo."""
        lang = _lang(lang)
        intent = cmd.get("intent")
        fn = getattr(self, f"_ans_{intent}", None) if intent else None
        if fn is None:
            if intent in catalogue.INTENTS:
                r = self.execute(cmd, lang)
                r.pop("undo", None)
                return r
            return _reply(False, _t(lang, "Je ne sais pas répondre à cela.", "I cannot answer that."))
        try:
            r = fn(cmd, lang)
        except _Unavailable as exc:
            print("[assistant] missing controller:", exc, flush=True)
            return _reply(False, _t(lang, f"Ce geste n'est pas disponible ici ({exc}).",
                                    f"That gesture is not available here ({exc})."))
        if r.get("ok") and intent in ("value", "describe"):
            # "what is the mean of GasSat?" then "highlight them"
            self._remember(cmd)
        return r

    def _ans_complain(self, cmd, lang):
        """The panel's controller answers a complaint itself (undo offered,
        the rephrasing tied to the sentence that went wrong); a caller
        without it gets the invitation."""
        return _reply(True, _t(lang, "Désolé. Dites-moi autrement ce que vous vouliez.",
                               "Sorry. Tell me another way what you wanted."))

    # --- the local AI: questions, and the sentences the engine did not read
    SLOW = ("ask",)
    # the longest the panel waits for the local AI's reading of a sentence:
    # what its waiting message tells the reader
    llm_wait_s = ia_llm.COMMAND_TIMEOUT_S

    def slow(self, intent):
        """A command answered by the local AI service: seconds, off the loop.
        Without one, a question is answered from the glossary, at once."""
        return intent in self.SLOW and self.ia is not None

    @staticmethod
    def llm_reason(why, lang):
        """Why the local AI failed or is out, in the reader's words (a
        timeout, a refused connection, a full queue, a model loading); a
        reason the client does not know is given as it came."""
        return ia_llm.reason_words(why, _lang(lang))

    def llm_available(self):
        """Whether the local AI can read a sentence the engine did not:
        configured, and up when last seen. Its health is asked at most once
        a minute — a call that answered or failed since counts as a look —
        so a service that is down never makes a reader wait for it."""
        if self.ia is None:
            return False
        if self._ia_seen is None or time.monotonic() - self._ia_seen[0] >= _HEALTH_EVERY_S:
            self._ia_seen = self._probe_ia()
        return self._ia_seen[1]

    def _probe_ia(self):
        """(when, up, why not) from the service's /v1/health — a short
        timeout: the probe runs on the event loop, and a service that is
        there answers it at once. A client without a health call counts as
        up: its calls will tell."""
        now = time.monotonic()
        health = getattr(self.ia, "health", None)
        if not callable(health):
            return now, True, ""
        h = health(timeout=_HEALTH_TIMEOUT_S)
        if not h:
            return now, False, getattr(self.ia, "last_error", "") or "no answer"
        status = str(h.get("status") or "ok")
        if status == "ok":
            return now, True, ""
        return now, False, status + (f": {h['error']}" if h.get("error") else "")

    def llm_problem(self):
        """Why the local AI cannot read sentences now ("connection refused",
        "loading"), or "" when it can, or when there is none: what a "not
        understood" reply adds, so the reader knows the fallback was out."""
        if self.ia is None or self._ia_seen is None or self._ia_seen[1]:
            return ""
        return self._ia_seen[2] or "?"

    def _ans_ask(self, cmd, lang):
        """A question, answered from the documentation by fespp_ia — or,
        when there is none or it fails, from the reservoir glossary."""
        q = str((cmd.get("slots") or {}).get("question") or cmd.get("text") or "").strip()
        if not q:
            return _reply(False, _t(lang, "Quelle est la question ?", "What is the question?"))
        why = ""
        if self.ia is not None:
            out = self.ia.ask(q, lang)
            if out is not None:
                rows = [[s.get("title") or "", s.get("source") or ""] for s in out.get("sources") or []][:6]
                return _reply(True, out["text"].strip(), rows=rows)
            why = self.llm_reason(getattr(self.ia, "last_error", "") or "", lang)
        return self._glossary_answer(q, why, lang)

    @staticmethod
    def _glossary_answer(q, why, lang):
        """The glossary's entries the question names, with their source; with
        none, that definitions need the local AI. `why`: why the local AI did
        not answer, "" when there is none."""
        found = _glossary_named(q)
        if found:
            sep = _t(lang, " : ", ": ")
            text = "\n\n".join(f"{head}{sep}{body}" for head, body, _names in found)
            text += "\n\n" + _t(lang, *_GLOSSARY_SOURCE)
            if why:
                text += _t(lang, f" (L'IA locale n'a pas répondu : {why}.)", f" (The local AI did not answer: {why}.)")
            return _reply(True, text)
        if why:
            return _reply(False, _t(lang, f"Le service d'IA n'a pas répondu ({why}), et le glossaire du réservoir"
                                          " n'a pas cette notion.",
                                    f"The AI service did not answer ({why}), and the reservoir glossary does not"
                                    " have that notion."))
        return _reply(False, _t(lang, "Le glossaire du réservoir n'a pas cette notion : les autres définitions"
                                      " demandent l'IA locale, qui n'est pas installée ici.",
                                "The reservoir glossary does not have that notion: other definitions need the"
                                " local AI, which is not installed here."))

    def catalogue_for_llm(self):
        """The commands as the service's prompt lists them: name, French
        and English words, each followed by what the model tends to get
        wrong (ia.llm.LLM_HINTS) -- the help table keeps the short words."""
        from fespp_on_trame.ia.llm import LLM_HINTS
        out = []
        for name, spec in catalogue.INTENTS.items():
            if name == "ask":
                continue
            fr, en = spec.get("fr", ""), _HELP_EN.get(name, "")
            hint_fr, hint_en = LLM_HINTS.get(name, ("", ""))
            out.append({"name": name,
                        "fr": f"{fr} — {hint_fr}" if hint_fr else fr,
                        "en": f"{en} — {hint_en}" if hint_en else en})
        return out

    def objects_for_llm(self):
        """The session's objects as the service's prompt lists them, the ones
        a sentence most likely names first — what is read, then the grids
        and the wells, the grids' properties, the other objects, the wells'
        logs — since the prompt keeps only the first ones. A property
        carries the title of its grid or well: two "Total Porosity" are told
        apart."""
        objs = self.objects()
        index = {o["path"]: o for o in objs}

        def rank(o):
            typ = o.get("type")
            if typ in _GRIDS:
                group = 0
            elif typ == "Wellbore":
                group = 1
            elif self._is_prop(o):
                group = 2 if o.get("rep_type") in _ISOLATABLE else 4
            else:
                group = 3 if not o.get("parent") else 5
            return not o.get("loaded"), group

        out = []
        for o in sorted(objs, key=rank):
            row = {"title": o.get("title"), "type": o.get("type"), "kind": o.get("kind") or ""}
            parent = self._title_of(o.get("parent"), index) if self._is_prop(o) else ""
            if parent:
                row["parent"] = parent
            if o.get("categories"):
                row["categories"] = [str(v) for v in o["categories"].values()]
            out.append(row)
        return out[:_LLM_OBJECTS]

    def llm_prepare(self, text, lang="fr"):
        """The local AI's reading of `text`, prepared on the event loop: what
        it is told (the commands, the session's objects) is read from the
        application now, and the call returned only makes the HTTP request —
        the panel runs it in a thread and hands its answer to `llm_finish`,
        back on the loop. None without a local AI."""
        if self.ia is None:
            return None
        ia, commands, objects = self.ia, self.catalogue_for_llm(), self.objects_for_llm()
        vocab = ia_llm.vocabulary()

        def call():
            ia.last_error = ""
            got = ia.command(text, commands, objects, lang, vocab=vocab, timeout=ia_llm.COMMAND_TIMEOUT_S)
            if got is None:
                # the reason, for the reply: a timeout, a full queue, a refusal
                return {"error": getattr(ia, "last_error", "") or "no command in the reply"}
            return got
        return call

    def llm_finish(self, text, got, lang="fr"):
        """The local AI's answer `got` (what `llm_prepare`'s call returned)
        as a command in the engine's shape, on the event loop: {"intent":
        None, "error": why} when the call failed, None when the model read
        no command of the catalogue — see `_merge` for the rest."""
        got = dict(got or {})
        error = got.get("error")
        self._ia_seen = (time.monotonic(), not error, str(error or ""))
        if error:
            return {"intent": None, "error": str(error), "confidence": 0.0, "alternatives": [], "slots": {},
                    "targets": [], "missing": [], "sure": False, "text": text, "by": "llm"}
        intent = got.get("intent")
        if intent == "ask":
            return {"intent": "ask", "confidence": 0.9, "alternatives": [], "sure": True, "text": text,
                    "slots": {"question": got.get("question") or text}, "targets": [], "missing": [],
                    "by": "llm", "seconds": got.get("_seconds")}
        if intent not in catalogue.INTENTS:
            return None
        return self._merge(text, got)

    def llm_command(self, text, lang="fr"):
        """`llm_prepare`, its call and `llm_finish` in one go, for a caller
        without an event loop."""
        call = self.llm_prepare(text, lang)
        return None if call is None else self.llm_finish(text, call(), lang)

    def _merge(self, text, got):
        """The model's reading of `text` merged with the engine's reading of
        the same sentence, and checked against the sentence itself: the
        model names the command, the engine's rules read what the words say.

          intent        the model's
          kind          the engine's word, else the model's made canonical
                        (a title, "wellbore" or "mean" is no kind)
          category      values of the session the sentence names as zones,
                        never a word of the kind ("saturation en eau" is no
                        water zone): the engine's, else the model's; when
                        the engine read nothing of the sentence, a value of
                        the session the model read in words the lexicon
                        lacks ("la flotte") is offered first among the
                        buttons, never taken unasked
          objects       the engine's; else the model's titles the sentence
                        names (every object of a shared title)
          min / max     read from the sentence's numbers by the engine's
                        rules (above, below, between, a percent of a
                        fraction); when the engine read nothing of the
                        sentence (a number in words), the model's — made a
                        fraction where the kind is one, as the engine does
          well_filter   only with a word that removes or keeps wells
          exclude       a hidden zone ("cache l'huile" keeps the rest): the
                        engine's or the sentence's hiding word, else the
                        service's; with neither (a service that sends no
                        polarity), the words that keep say keep, and
                        nothing said is asked
          panel, preset, axis, factor, on: the engine's, else the service's
        """
        objs = self.objects()
        toks = nlu_tokens(text)
        said = " " + " ".join(toks) + " "
        intent = got["intent"]
        try:
            eng = nlu_engine.parse(text, objs, context=self._context)
        except Exception as exc:
            print("[assistant] the engine's reading under the local AI's:", exc, flush=True)
            eng = {}
        # the engine read nothing of the sentence — no name, value, kind or
        # number: the model's reading is all there is (the true fallback)
        alone = not nlu_slots.spans(toks, objs)
        sl = dict(eng.get("slots") or {})
        sl["objects"] = [list(c) for c in sl.get("objects") or ()]
        sl["kind"] = sl.get("kind") or self._canonical_kind(got.get("kind"))
        session = {nlu_slots.category_of(str(lb)) for o in objs for lb in (o.get("categories") or {}).values()}
        values = self._values({"slots": sl})
        model_value = nlu_slots.category_of(str(got["category"])) if got.get("category") else None
        suggested = None
        if (not values and model_value and model_value in session
                and not self._in_kind(model_value, sl["kind"])):
            if self._zone_said(model_value, said):
                values = [model_value]
            elif alone and intent in ("threshold", "highlight", "well_cells"):
                suggested = model_value
        values = [v for v in values if v in session and not self._in_kind(v, sl["kind"])]
        sl["category"], sl["categories"] = (values[0] if values else None), values
        if suggested:
            sl["suggested"] = suggested
        if not any(sl["objects"]):
            sl["objects"] = self._named_by(got.get("objects"), toks, objs)
        lo, hi, raw = self._read_bounds(toks, objs, intent, sl["kind"], said)
        if lo is None and hi is None and alone and intent in _BOUNDED:
            lo, hi, raw = self._model_bounds(got, sl, said)
        sl["min"], sl["max"] = lo, hi
        # the numbers as said where a percent of a fraction was made one, as
        # the engine leaves them (`_bounds_on`: a property stored in percent)
        sl.pop("raw", None)
        if raw:
            sl["raw"] = raw
        if intent == "well_cells":
            wf = sl.get("well_filter") or got.get("well_filter")
            ok = wf in ("keep_crossing", "hide_crossing") and self._removes_wells(said)
            sl["well_filter"] = wf if ok else None
        else:
            sl.pop("well_filter", None)
        sl["exclude"] = self._polarity(intent, sl, got, toks, objs, bool(values or suggested))
        for key, check in (("panel", self._panel_of), ("preset", self._preset_of), ("axis", self._axis_of),
                           ("factor", self._factor_of)):
            if sl.get(key) is None:
                sl[key] = check(got.get(key))
        if intent == "z_scale" and sl.get("factor") is None and sl.get("numbers"):
            sl["factor"] = sl["numbers"][0]
        if intent in ("hide_nan", "flat_colors") and eng.get("intent") != intent:
            sl["on"] = self._switch(intent, toks, sl, got.get("on"))
        elif sl.get("on") is None and isinstance(got.get("on"), bool):
            sl["on"] = got["on"]
        zone = sl["category"] or suggested
        targets = nlu_engine.resolve(objs, sl["objects"], sl["kind"], sl.get("group"), zone)
        if intent in ("threshold", "highlight", "show", "well_cells") and zone:
            # a value is filtered on a grid: its properties first, as the engine does
            grids = {o.get("path") for o in objs if (o.get("type") or "") in _GRIDS}
            targets = [t for t in targets if t.get("parent") in grids] or targets
        cmd = {"intent": intent, "confidence": 0.9, "alternatives": [], "text": text, "slots": sl,
               "targets": targets, "by": "llm", "seconds": got.get("_seconds")}
        # the values meet the filter's as the engine's reading would
        self._mark_values(cmd, False)
        cmd["missing"] = list(self.missing(cmd) or [])
        cmd["sure"] = not cmd["missing"]
        return cmd

    def _polarity(self, intent, sl, got, toks, objs, zone):
        """Whether the zone named is hidden (True, the other values kept),
        kept (False), or not said (None: the reader is asked). The engine's
        reading and the sentence's own hiding word first, then the service's
        `exclude` — the one reading of a hiding verb said not ("ne cache pas
        l'huile"). A service that sends none leaves it to the words: the
        words that keep say keep,
        and a sentence of words the engine knows, none of them hiding, shows
        the value named ("the oil cells"); but a value said with a word the
        engine does not know — a verb that may hide ("planque le gaz",
        "zappe la flotte") — or with a negation ("sans l'eau") is never kept
        by default: the reader is asked."""
        said = " " + " ".join(toks) + " "
        if intent not in ("threshold", "highlight") or not zone:
            return False
        # a hiding verb said not ("ne cache pas l'huile") hides nothing: the
        # hiding a word list read in it is no reading, the service's is
        denied = _has(said, _NOT_HIDING)
        if not denied and (sl.get("exclude") or (intent == "threshold" and self._hides(said))):
            return True
        if isinstance(got.get("exclude"), bool):
            return got["exclude"]
        if intent == "highlight":
            return False
        if denied or _has(said, _NEGATED_ZONE):
            return None
        if _has(said, nlu_engine.FILTER_WORDS + _SHOW_SAID + nlu_engine.OTHERS):
            return False
        return None if self._unknown_words(toks, objs) else False

    @staticmethod
    def _unknown_words(toks, objs):
        """The sentence's words the engine's rules do not read — no name,
        value or number, no little word, no verb or cue of theirs: what only
        the local AI reads ("planque", "zappe", "flotte")."""
        taken = {i for a, b, *_rest in nlu_slots.spans(toks, objs) for i in range(a, b)}
        known = nlu_engine.cue_words() | set(nlu_multi.VERBS) | set(nlu_slots.STOP)
        return [t for i, t in enumerate(toks) if i not in taken and not t[:1].isdigit() and t not in known]

    def _model_bounds(self, got, sl, said):
        """The model's bounds, for a sentence whose numbers the engine could
        not read ("au-delà de vingt pour cent"): (min, max, the numbers as
        said where one was made a fraction). A fraction kind's bound above 1
        is a percent, made one as the engine does; with the kind not known
        yet, a percent said is kept for the property the gesture will act on
        (`_bounds_on`)."""
        lo, hi = self._number(got.get("min")), self._number(got.get("max"))
        raw = {}
        if sl.get("kind") in nlu_engine.FRACTIONS:
            for key, v in (("min", lo), ("max", hi)):
                if v is not None and 1 < v <= 100:
                    raw[key] = v
            lo, hi = (v / 100.0 if v is not None and 1 < v <= 100 else v for v in (lo, hi))
        elif _has(said, _PERCENT_SAID):
            sl["percent"] = True
        return lo, hi, raw

    @staticmethod
    def _number(value):
        """A number the service wrote (0.2, "0,2"), or None."""
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        text = str(value).strip().replace(",", ".")
        return float(text) if _NUMBER.match(text) else None

    @staticmethod
    def _canonical_kind(kind):
        """A kind the model wrote, as the lexicon names it ("water_saturation"
        -> "water saturation", "Lithology1" -> "facies", "avg porosity" ->
        "porosity"), or None for a word that is no kind (a title,
        "wellbore", "mean")."""
        if not kind:
            return None
        k = re.sub(r"\s*\d+$", "", normalize(str(kind).replace("_", " ")))
        if k in nlu_lexicon.KINDS:
            return k
        for name, entry in nlu_lexicon.KINDS.items():
            if k in entry["say"] or k in entry["titles"] or k in entry["kinds"]:
                return name
        hits = {name for name, entry in nlu_lexicon.KINDS.items() if name != "saturation"
                for w in entry["say"] if len(w) >= 4 and re.search(r"\b" + re.escape(w) + r"\b", k)}
        return hits.pop() if len(hits) == 1 else None

    @staticmethod
    def _zone_words(value):
        """The words a sentence says a category value with: its name and the
        lexicon's ("oil": huile, pétrole…)."""
        return {normalize(w) for w in (value,) + tuple(nlu_lexicon.CATEGORIES.get(value, ()))} - {""}

    def _zone_said(self, value, said):
        """Whether the sentence names the value: one of its words, plural or
        derived ("l'huile", "oils", "huileux", "gazeux") — the local AI is
        reached for the words the lexicon lacks, but never for a value the
        sentence does not say."""
        words = said.split()
        for w in self._zone_words(value):
            if " " in w:
                if f" {w} " in said:
                    return True
            elif any(t == w or (len(w) >= 3 and t.startswith(w) and len(t) - len(w) <= 4) for t in words):
                return True
        return False

    def _in_kind(self, value, kind):
        """Whether the value's word is a word of the kind's name — "eau" in
        "saturation en eau", "clay" in "clay volume": the property is meant,
        not the zone."""
        if not kind:
            return False
        names = [normalize(kind)] + [normalize(p) for p in (nlu_lexicon.KINDS.get(kind) or {}).get("say", ())]
        return any(f" {w} " in f" {n} " for w in self._zone_words(value) for n in names)

    def _named_by(self, titles, toks, objs):
        """The objects behind the titles the model gave that the sentence
        itself names — the model may copy the session's list, or every well
        for "the wells". A title matches by its normalised form or closely
        (`object_score` 0.85: "F-12" is "15/9-F-12"); every object of a
        shared title is kept, one candidate list per title (the question
        then asks which)."""
        out, seen = [], set()
        for t in titles or ():
            words = nlu_tokens(str(t))
            if not words:
                continue
            hit = {normalize(o.get("title", "")) for o in objs if normalize(o.get("title", "")) == normalize(str(t))}
            if not hit:
                hit = {normalize(o.get("title", "")) for o in objs if self._says_title(words, o.get("title", ""))}
            cands = [dict(o, score=1.0) for o in objs if normalize(o.get("title", "")) in hit
                     and o.get("path") not in seen and self._title_said(toks, o.get("title", ""))]
            if cands:
                seen.update(o["path"] for o in cands)
                out.append(cands)
        return out

    @staticmethod
    def _says_title(words, title):
        """Whether `words` name `title` closely: the engine's `object_score`
        0.85 or more, or the last pieces of a numbered name ("33-1" for
        "55/33-1": digits the score leaves out, so that a number is never
        taken for a name)."""
        if nlu_slots.object_score(words, title) >= 0.85:
            return True
        mine, theirs = _pieces(" ".join(words)), _pieces(title)
        return (len(mine) >= 2 and any(p.isdigit() for p in mine) and len(theirs) > len(mine)
                and theirs[-len(mine):] == mine)

    def _title_said(self, toks, title):
        """Whether a few words of the sentence name `title` closely, as the
        engine's spans read a title (never from a word of its stop list)."""
        n = min(len(normalize(title).split()) + 1, 5)
        for i in range(len(toks)):
            for k in range(1, n + 1):
                win = toks[i:i + k]
                if len(win) < k or win[0] in nlu_slots.STOP or win[-1] in nlu_slots.STOP:
                    continue
                if self._says_title(win, title):
                    return True
        return False

    @staticmethod
    def _read_bounds(toks, objs, intent, kind, said):
        """The bounds the sentence's numbers give `intent`, read as the
        engine reads them: "above", "below", "between … and …", a lone
        number by its words (a max with "cap"), the bound said with a hiding
        verb turned over, a percent of a fraction made one — (min, max, the
        numbers as said where one was made a fraction). (None, None, {})
        without a number: a bound the model made up is never used."""
        found = nlu_slots.spans(toks, objs)
        if not any(f[2] == "num" for f in found):
            return None, None, {}
        read = nlu_slots.read(toks, found)
        lo, hi, nums = read["min"], read["max"], list(read["numbers"])

        def has(words):
            return any(f" {w} " in said for w in words)

        if intent in _BOUNDED and lo is None and hi is None:
            if len(nums) >= 2:
                lo, hi = min(nums[:2]), max(nums[:2])
            elif len(nums) == 1:
                if has(nlu_lexicon.MAX_WORDS) and not has(nlu_lexicon.MIN_WORDS):
                    hi = nums[0]
                else:
                    lo = nums[0]
        if intent == "threshold" and has(nlu_lexicon.HIDING) and (lo is None) != (hi is None):
            lo, hi = hi, lo
        raw = {}
        if read["percent"] and kind in nlu_engine.FRACTIONS:
            raw = {key: v for key, v in (("min", lo), ("max", hi)) if v is not None and v > 1}
            lo = lo / 100.0 if lo is not None and lo > 1 else lo
            hi = hi / 100.0 if hi is not None and hi > 1 else hi
        return lo, hi, raw

    @staticmethod
    def _removes_wells(said):
        """A word that removes wells or keeps only some: what a well filter
        needs ("which wells cross the oil?" asks, it hides nothing)."""
        words = nlu_lexicon.HIDING + nlu_engine.HIDE_MORE + nlu_engine.FILTER_WORDS + nlu_engine.STILL_WORDS
        return any(f" {w} " in said for w in words) or " isol" in said

    @staticmethod
    def _hides(said):
        """A zone hidden ("cache l'huile", "don't show the water", "rends le
        gaz invisible"), not the others hidden ("hide the rest": keep the
        value)."""
        return (any(f" {w} " in said for w in nlu_lexicon.HIDING + nlu_engine.HIDE_MORE + _HIDE_SAID + _GONE)
                and not any(f" {w} " in said for w in nlu_engine.OTHERS))

    @staticmethod
    def _switch(intent, toks, sl, said_by_model):
        """on / off for hide_nan and flat_colors, by the engine's reading of
        the words ("montre les valeurs absentes" shows them); the model's
        when the engine has no such reading."""
        switch = getattr(nlu_engine, "_switch", None)
        if callable(switch):
            try:
                return switch(intent, toks, dict(sl))
            except Exception as exc:
                print("[assistant] on/off of the local AI's command:", exc, flush=True)
        if sl.get("on") is not None:
            return sl["on"]
        return said_by_model if isinstance(said_by_model, bool) else None

    @staticmethod
    def _panel_of(value):
        """A panel the service named, as the lexicon has it, or None."""
        if not value:
            return None
        v = normalize(str(value))
        if v in nlu_lexicon.PANELS:
            return v
        return next((p for p, words in nlu_lexicon.PANELS.items() if v in (normalize(w) for w in words)), None)

    @staticmethod
    def _preset_of(value):
        """A colour table the service named, as ParaView names it, or None."""
        if not value:
            return None
        if value in nlu_lexicon.PRESETS:
            return value
        v = normalize(str(value))
        return next((p for p, words in nlu_lexicon.PRESETS.items()
                     if v == normalize(p) or v in (normalize(w) for w in words)), None)

    @staticmethod
    def _axis_of(value):
        """An axis the service named, i / j / k, or None."""
        v = str(value or "").strip().lower()
        return v if v in ("i", "j", "k") else None

    @staticmethod
    def _factor_of(value):
        """A factor the service gave, a positive number, or None."""
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        text = str(value).strip().replace(",", ".")
        f = float(text) if _NUMBER.match(text) else 0.0
        return f if f > 0 else None

    def _ans_help(self, cmd, lang):
        rows = []
        for i in catalogue.INTENTS:
            text = _t(lang, catalogue.INTENTS[i]["fr"], _HELP_EN.get(i, ""))
            if i in _HELP_EXAMPLES:
                text += f" : « {_HELP_EXAMPLES[i][0]} »" if lang == "fr" else f": “{_HELP_EXAMPLES[i][1]}”"
            rows.append([self.label(i, lang), text])
        return _reply(True, _t(lang, f"Voici ce que je sais faire. Par exemple : {self._examples_said(lang)}.",
                               f"Here is what I can do. For instance: {self._examples_said(lang)}."), rows=rows)

    def _examples_said(self, lang):
        return " ; ".join(f"« {e} »" if lang == "fr" else f"“{e}”" for e in self.examples(lang)[:3])

    def _ans_unsupported(self, cmd, lang):
        """A request the assistant cannot do: said honestly, nothing done —
        with where the gesture lives when the application has it elsewhere.
        A greeting or a thank-you gets a short answer and examples."""
        said = _words_of(cmd.get("text") or "")
        where = next((_t(lang, fr, en) for words, fr, en in _ELSEWHERE if _has(said, words)), "")
        if not where and _has(said, _GREETINGS + _THANKS):
            head = (_t(lang, "Avec plaisir.", "You are welcome.") if _has(said, _THANKS)
                    else _t(lang, "Bonjour !", "Hello!"))
            return _reply(True, head + _t(lang, f" Essayez par exemple : {self._examples_said(lang)}.",
                                          f" Try for instance: {self._examples_said(lang)}."))
        text = _t(lang, "Je ne sais pas encore faire ça.", "I cannot do that yet.")
        return _reply(False, f"{text} {where}".strip())

    def _ans_save_session(self, cmd, lang):
        fn = self._ctrl("session_save")
        if fn is None:
            return _reply(False, _t(lang, "L'enregistrement de session n'est pas disponible ici.",
                                    "Saving the session is not available here."))
        fn("assistant")
        return _reply(True, _t(lang, "Session enregistrée : le fichier se télécharge.",
                               "Session saved: the file is downloading."))

    def _ans_list(self, cmd, lang):
        objs = self.objects()
        if not objs:
            return _reply(True, _t(lang, "Rien n'est lu pour l'instant : importez un fichier.",
                                   "Nothing is read yet: import a file."), rows=[])
        if self._named(cmd):
            named = {t["path"] for t in self.targets(cmd)}
            objs = [o for o in objs if o["path"] in named or o.get("parent") in named]
        mark = " ✓"

        def names(items):
            items = sorted(items, key=lambda o: not o.get("loaded"))
            shown = [o["title"] + (mark if o.get("loaded") else "") for o in items[:_NAMES_SHOWN]]
            more = len(items) - len(shown)
            return ", ".join(shown) + (f" … (+{more})" if more > 0 else "")

        grids = [o for o in objs if o["type"] in _GRIDS]
        wells = [o for o in objs if o["type"] == "Wellbore"]
        well_paths = {w["path"] for w in wells}
        props = [o for o in objs if self._is_prop(o)]
        logs = [o for o in props if o.get("parent") in well_paths]
        surfaces = [o for o in objs if not self._is_prop(o) and o["type"] not in _GRIDS
                    and o["type"] != "Wellbore" and not o.get("parent")]
        rows = []
        for g in grids:
            gp = [o for o in props if o.get("parent") == g["path"]]
            if gp:
                said = _t(lang, f"{len(gp)} {_plural(len(gp), 'propriété', 'propriétés')} : ",
                          f"{len(gp)} {_plural(len(gp), 'property', 'properties')}: ") + names(gp)
            else:
                said = _t(lang, "aucune propriété", "no property")
            rows.append([g["title"] + (mark if g.get("loaded") else ""), said])
        if wells:
            rows.append([_t(lang, "Puits", "Wells"), names(wells)])
        if logs:
            rows.append([_t(lang, "Courbes de puits", "Well logs"), names(logs)])
        if surfaces:
            rows.append([_t(lang, "Surfaces et autres", "Surfaces and others"), names(surfaces)])
        held = {o["path"] for o in logs} | {g["path"] for g in grids}
        orphans = [o for o in props if o["path"] not in held and o.get("parent") not in held]
        if orphans:
            rows.append([_t(lang, "Autres propriétés", "Other properties"), names(orphans)])
        n_props = len(props) - len(logs)
        parts = [(len(grids), ("grille", "grilles"), ("grid", "grids")),
                 (n_props, ("propriété", "propriétés"), ("property", "properties")),
                 (len(wells), ("puits", "puits"), ("well", "wells")),
                 (len(logs), ("courbe", "courbes"), ("log", "logs")),
                 (len(surfaces), ("surface", "surfaces"), ("surface", "surfaces"))]
        said = [f"{n} {_plural(n, *(fr if lang == 'fr' else en))}" for n, fr, en in parts if n]
        return _reply(True, _t(lang, f"{', '.join(said)} — ✓ = lu.", f"{', '.join(said)} — ✓ = read."),
                      rows=rows)

    def _ans_describe(self, cmd, lang):
        cands = self._objects_of(cmd)
        if not cands:
            return self._not_found(cmd, lang) if self._named(cmd) else _reply(
                False, _t(lang, "Quel objet dois-je décrire ?", "Which object shall I describe?"))
        o = cands[0]
        index = self._index()
        typ = o.get("type") or ""
        parent = self._title_of(o.get("parent"), index)
        tword = _TYPE_WORDS.get(typ, (typ, typ))
        if self._is_prop(o) and parent and (index.get(o.get("parent")) or {}).get("type") == "Wellbore":
            tword = ("courbe de puits", "well log")
        rows = [[_t(lang, "Titre", "Title"), o.get("title") or ""],
                ["Type", _t(lang, *tword)]]
        if o.get("kind"):
            rows.append([_t(lang, "Type de propriété", "Property kind"), o["kind"]])
        if parent:
            rows.append([_t(lang, "Sur", "On"), parent])
        if o.get("uom"):
            rows.append([_t(lang, "Unité", "Unit"), o["uom"]])
        rows.append([_t(lang, "Lu", "Read"), _t(lang, "oui", "yes") if o.get("loaded")
                     else _t(lang, "non", "no")])
        cit = self._citation(o)
        for key, fr, en in (("creation", "Créé le", "Created"), ("last_update", "Mis à jour", "Last update"),
                            ("originator", "Auteur", "Originator"), ("format", "Format", "Format"),
                            ("uuid", "UUID", "UUID")):
            if cit.get(key):
                rows.append([_t(lang, fr, en), cit[key]])
        head = _t(lang, tword[0], tword[1])
        text = f"{o.get('title')} : {head}" if lang == "fr" else f"{o.get('title')}: {head}"
        if parent:
            text += _t(lang, f" de {parent}", f" of {parent}")
        if o.get("kind"):
            text += f", {o['kind']}"
        if cit.get("originator"):
            text += _t(lang, f", créé par {cit['originator']}", f", created by {cit['originator']}")
        return _reply(True, text + ".", rows=rows)

    def _citation(self, o):
        """The Citation of the object's XML (creation, last update,
        originator, format) and its uuid — {} when unreadable."""
        from fespp_on_trame.engine import repo_query, row_object
        path = o.get("path") or ""
        if o.get("type") == "DerivedProperty" or "/" not in path:
            return {}
        uuid = row_object.uuid_of(path.rsplit("/", 1)[-1])
        if not uuid:
            return {}
        out = {"uuid": uuid}
        src_of = getattr(self.ctx, "active_data_source", None)
        if src_of is None:
            return out
        try:
            xml = repo_query.object_xml(src_of.get_source(), uuid)
        except Exception as exc:
            print("[assistant] describe, object xml:", exc, flush=True)
            return out
        try:
            from trame_fespp_session.format import citation_of
        except ImportError as exc:
            print("[assistant] describe, no citation reader:", exc, flush=True)
            return out
        out.update({k: v for k, v in citation_of(xml or "").items() if v})
        return out

    # the statistics a sentence may ask for, by its words (normalised)
    _STAT_WORDS = (("Minimum", ("min", "minimum", "minimale", "minimal", "plus petite", "lowest",
                                "smallest")),
                   ("Maximum", ("max", "maximum", "maximale", "maximal", "plus grande", "highest",
                                "largest")),
                   ("Median", ("mediane", "median")),
                   ("Standard Deviation", ("ecart type", "ecart", "std", "standard deviation")),
                   ("P10", ("p10",)), ("P90", ("p90",)))

    def _read_hidden(self, o, lang):
        """Read a property born hidden, without the large-read question (a
        statistic, a panel's values): None when it is read, else the reply."""
        p = o["path"]
        if o.get("type") == "DerivedProperty" or p in self._loaded():
            return None
        self._call("session_select", [p])
        self._flush()
        if p in self._loaded():
            return None
        return _reply(False, _t(lang, f"{o['title']} n'a pas pu être lue.",
                                f"{o['title']} could not be read."))

    def _realization(self, vid, p):
        """(the realization index the view shows for `p`, whether `p` has
        several): the Time & Realizations card's choice, else the first —
        what the colours, a filter and a highlight of that view use."""
        from fespp_on_trame.engine import realization_dispatch
        tree = self._tree()
        try:
            multi = bool(realization_dispatch.is_multirealization_property(tree, p))
        except Exception as exc:
            print("[assistant] realizations of", p, exc, flush=True)
            multi = False
        from fespp_on_trame.engine import view_axes
        return view_axes.real_for(self.state, tree, vid, p), multi

    def _ans_value(self, cmd, lang):
        from fespp_on_trame.engine import property_values, stats_dispatch
        vid = self._vid()
        o, err = self._one_property(cmd, vid, lang)
        if o is None:
            return err
        p = o["path"]
        refused = self._read_hidden(o, lang)
        if refused is not None:
            return refused
        tree = self._tree()
        rep = stats_dispatch._rep_path_for_array_path(tree, p)
        real, multi = self._realization(vid, p)
        # a property that varies in time is read at the step the view shows
        # (not at whatever step the reader last ran), and the step is said
        ts, step_said = None, ""
        if (self._index().get(p) or {}).get("type") in _TIMED:
            t = self._timereal(vid).get("time") or {}
            if int(t.get("nb") or 0) > 0:
                ts = int(t.get("index") or 0)
                step_said = f"{ts + 1} / {int(t['nb'])}{self._step_label(t)}"
        vals = property_values.values_for(self.state, tree, getattr(self.ctx, "source_registry", None),
                                          p, rep, real_idx=real, ts_idx=ts)
        if vals is None:
            why = property_values.last_error() or ""
            return _reply(False, _t(lang, f"Les valeurs de {o['title']} sont illisibles. {why}",
                                    f"The values of {o['title']} cannot be read. {why}").strip())
        row = stats_dispatch._row_stats_from_values(vals, o["title"])
        unit = stats_dispatch._unit_for_array_path(tree, p) or o.get("uom") or ""
        name = self._name(o, lang)
        if multi and real is not None:
            # the realization the view shows, said: another one gives other figures
            name += _t(lang, f" (réalisation {real})", f" (realization {real})")
        if step_said:
            name += _t(lang, f" (pas de temps {step_said})", f" (time step {step_said})")
        n = int(row.get("Cardinality") or 0)
        if not n:
            return _reply(True, _t(lang, f"{name} : aucune valeur.", f"{name}: no value."),
                          rows=[[_t(lang, "Valeurs absentes", "NaN count"),
                                 _count(row.get("NaN_count"), lang)]])
        rows = [["Minimum", _num(row.get("Minimum"), lang)],
                ["Maximum", _num(row.get("Maximum"), lang)],
                [_t(lang, "Moyenne", "Mean"), _num(row.get("Mean"), lang)],
                [_t(lang, "Médiane", "Median"), _num(row.get("Median"), lang)],
                [_t(lang, "Écart type", "Std"), _num(row.get("Standard Deviation"), lang)],
                ["P10", _num(row.get("P10"), lang)],
                ["P90", _num(row.get("P90"), lang)],
                [_t(lang, "Valeurs absentes", "NaN count"), _count(row.get("NaN_count"), lang)],
                [_t(lang, "Unité", "Unit"), unit or "–"]]
        if multi and real is not None:
            rows.append([_t(lang, "Réalisation", "Realization"), str(real)])
        if step_said:
            rows.append([_t(lang, "Pas de temps", "Time step"), step_said])
        u = f" {unit}" if unit else ""
        # the words as the engine reads them: "Médiane", "écart-type" and
        # "minimale ?" are "mediane", "ecart type" and "minimale"
        text = " " + normalize(cmd.get("text") or "") + " "
        asked = next((key for key, words in self._STAT_WORDS
                      if any(f" {w} " in text for w in words)), None)
        if asked:
            label = {"Minimum": ("minimum", "minimum"), "Maximum": ("maximum", "maximum"),
                     "Median": ("médiane", "median"),
                     "Standard Deviation": ("écart type", "standard deviation"),
                     "P10": ("P10", "P10"), "P90": ("P90", "P90")}[asked]
            lead = _t(lang, f"{name} : {label[0]} {_num(row.get(asked), lang)}{u}",
                      f"{name}: {label[1]} {_num(row.get(asked), lang)}{u}")
        else:
            lead = _t(lang, f"{name} : moyenne {_num(row.get('Mean'), lang)}{u}",
                      f"{name}: mean {_num(row.get('Mean'), lang)}{u}")
        tail = _t(lang, f", de {_num(row.get('Minimum'), lang)} à {_num(row.get('Maximum'), lang)}"
                        f" ({_count(n, lang)} {_plural(n, 'valeur', 'valeurs')}).",
                  f", from {_num(row.get('Minimum'), lang)} to {_num(row.get('Maximum'), lang)}"
                  f" ({_count(n, lang)} {_plural(n, 'value', 'values')}).")
        return _reply(True, lead + tail, rows=rows)

    # ------------------------------------------------------------ gestures
    def execute(self, cmd, lang):
        """Carry out `cmd`: the reply, with an undo token when the gesture
        worked (a read-only command is answered, with no undo)."""
        lang = _lang(lang)
        intent = cmd.get("intent")
        if intent in catalogue.INTENTS and self.readonly(intent):
            return dict(self.answer(cmd, lang), undo=None)
        fn = getattr(self, f"_do_{intent}", None) if intent else None
        if fn is None:
            return _reply(False, _t(lang, "Je ne sais pas encore faire cela.", "I cannot do that yet."),
                          undo=None)
        vid = self._vid()
        empty_before = bool(vid) and not self._get(f"visible_paths__{vid}", [])
        # the gesture's own copy: a gesture on values settles in its slots the
        # values it acted on (the ones the filter already hid, added), what
        # the session remembers
        cmd = dict(cmd, slots=dict(cmd.get("slots") or {}))
        try:
            r = fn(cmd, lang)
        except _Unavailable as exc:
            print("[assistant] missing controller:", exc, flush=True)
            r = _reply(False, _t(lang, f"Ce geste n'est pas disponible ici ({exc}).",
                                 f"That gesture is not available here ({exc})."))
        r.setdefault("undo", None)
        if not r["ok"]:
            r["undo"] = None
        else:
            self._remember(cmd)
            # nothing was in sight before and the gesture put something
            # there: the camera may point anywhere (a session restored with
            # nothing shown), so it is reset to frame what the gesture drew
            if (empty_before and intent in _DRAWN and self._get(f"visible_paths__{vid}", [])
                    and not self._globe(vid) and self._ctrl("nav_reset") is not None):
                self._call("nav_reset", vid)
        return r

    def _remember(self, cmd):
        """The session's small memory: what the last command that WORKED was
        about — the engine takes it up for a sentence that refers back ("the
        other zones", "highlight them"). One per session (this host), gone
        with it."""
        sl = cmd.get("slots") or {}
        if sl.get("unchanged"):
            # nothing was done (a value in sight already, a value said not to
            # be hidden): the last gesture is still what a sentence refers to
            return
        paths = [t.get("path") for t in cmd.get("targets") or () if t.get("path")]
        if paths or sl.get("category") or sl.get("kind") or sl.get("lit"):
            # the polarity too: "and the gas?" after "hide the oil zone"
            # hides the gas (_take_up_polarity); `said`, the values the
            # sentence named, is what a correction takes back — and `again`,
            # values seen again, the ones it hides again ("non, pas l'eau,
            # le gaz" after "remontre l'eau")
            values = self._values(cmd)
            self._context = {"category": sl.get("category"), "categories": values,
                             "said": list(sl.get("named") or values),
                             "exclude": bool(sl.get("exclude")), "kind": sl.get("kind"),
                             "targets": paths, "intent": cmd.get("intent"),
                             "again": bool(sl.get("shown_again")),
                             # the range a highlight lit, and of which
                             # property: "masque-les" hides it
                             "lit": sl.get("lit"), "lit_on": sl.get("lit_on")}

    def _token(self, op, intent, what, **data):
        """An undo token: the small state from before the gesture, and what
        to say when it is undone."""
        self._next_token += 1
        tok = dict(data, op=op, id=self._next_token, intent=intent, what=what)
        self._issued.append(tok)
        del self._issued[:-_UNDO_KEEP]
        return tok

    def _view_pre(self, vid):
        return {"eyes": list(self._get(f"visible_paths__{vid}", [])),
                "active": self._get(f"active_path__{vid}", ""),
                "by_tab": dict(self._get(f"active_by_tab__{vid}", {}))}

    def _set_eyes(self, vid, eyes):
        eyes = list(eyes)
        self.state[f"visible_paths__{vid}"] = eyes
        self._call("on_eye_changed", vid, eyes)

    def _restore_view(self, vid, pre):
        """The eyes and the active nodes as they were (what was read stays read)."""
        self.state[f"active_by_tab__{vid}"] = dict(pre.get("by_tab") or {})
        self.state[f"active_path__{vid}"] = pre.get("active") or ""
        self._set_eyes(vid, pre.get("eyes") or [])
        self._flush()

    def _activate(self, vid, o, tab_path=None):
        """The view's active node, as a click in its tree: the Colormap,
        Attributes, Slicers and Thresholds cards follow it."""
        path = self._eye_of(o)
        self.state[f"active_path__{vid}"] = path
        by_tab = dict(self._get(f"active_by_tab__{vid}", {}))
        tab = o.get("tab") or ("reservoir" if o.get("rep_type") in _ISOLATABLE else "")
        if tab:
            by_tab[tab] = tab_path or path
            self.state[f"active_by_tab__{vid}"] = by_tab
        self._flush()

    @staticmethod
    def _eye_of(o):
        return (o.get("trajectory") or o["path"]) if o.get("type") == "Wellbore" else o["path"]

    def _eyes_of(self, o):
        """The eyes that SHOW `o`: a property's eye only colours its
        representation (BlockScope: an array eye never shows the dataset,
        and the implicit un-hide only fires for an eye that just opened),
        so the representation's own eye goes with it."""
        e = self._eye_of(o)
        rep = o.get("rep_path")
        if self._is_prop(o) and rep and rep != e:
            return [rep, e]
        return [e]

    def _read(self, objs, lang):
        """Read what is not read yet, as a tick would (born visible). None
        when all is read, else the reply that says why not."""
        from fespp_on_trame.engine import tick_confirm
        loaded = self._loaded()
        want = []
        for o in objs:
            p = self._eye_of(o)
            if o.get("type") != "DerivedProperty" and p and p not in loaded and p not in want:
                want.append(p)
        if not want:
            return None
        if len(want) > tick_confirm.MAX_TICK_LOAD:
            return _reply(False, _t(lang, f"Cela lirait {len(want)} objets d'un coup : précisez lesquels"
                                          f" (au plus {tick_confirm.MAX_TICK_LOAD}).",
                                    f"That would read {len(want)} objects at once: say which ones"
                                    f" (at most {tick_confirm.MAX_TICK_LOAD})."))
        note = self._get("empty_color_snackbar_text", "")
        sel = list(self._get("selected_paths", []))
        self._call("select_paths", sel + [p for p in want if p not in sel])
        self._flush()
        failed = [p for p in want if p not in self._loaded()]
        if not failed:
            return None
        why = self._get("empty_color_snackbar_text", "")
        why = why if why and why != note else ""
        index = self._index()
        names = ", ".join(self._title_of(p, index) or p for p in failed)
        return _reply(False, _t(lang, f"Lecture refusée ou impossible : {names}. {why}",
                                f"Could not read: {names}. {why}").strip())

    def _ensure_visible(self, vid, o):
        """Open the grid's eye when it is closed in the view — a filter or a
        highlight on a hidden grid would be invisible, and a property eye
        alone does not show its grid — and the property's too when no
        property of that grid colours it."""
        eyes = list(self._get(f"visible_paths__{vid}", []))
        rep = o.get("rep_path")
        if not rep or rep in eyes:
            return
        index = self._index()
        add = [rep]
        coloured = any(self._is_prop(index.get(e)) and index[e].get("rep_path") == rep for e in eyes)
        if not coloured and o["path"] not in eyes:
            add.append(o["path"])
        self._set_eyes(vid, eyes + add)

    # --- show / hide / isolate -------------------------------------------
    def _do_show(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        objs = self._objects_of(cmd)
        if not objs:
            return self._not_found(cmd, lang)
        if any(o.get("type") == "DerivedProperty" for o in objs):
            return self._not_drawn(objs, lang)
        pre = self._view_pre(vid)
        refused = self._read(objs, lang)
        if refused is not None:
            # what did load came in born visible: the view as it was
            self._restore_view(vid, pre)
            return refused
        # the load may have opened eyes already (born visible): only add —
        # a property's grid too (its eye may have been closed since)
        eyes = list(self._get(f"visible_paths__{vid}", []))
        for o in objs:
            for e in self._eyes_of(o):
                if e and e not in eyes:
                    eyes.append(e)
        self._set_eyes(vid, eyes)
        self._activate(vid, objs[-1])
        index = self._index()
        names = ", ".join(self._name(o, lang, index) for o in objs)
        tok = self._token("view", "show", self._what("show", names), vid=vid, pre=pre)
        return _reply(True, _t(lang, f"Affiché : {names}.", f"Shown: {names}."), undo=tok)

    @staticmethod
    def _what(intent, names):
        """What an undo says it undid, in both languages."""
        fr, en = LABELS.get(intent, (intent, intent))
        return (f"« {fr} » {names}".strip(), f"“{en}” {names}".strip())

    def _do_hide(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        objs = self._objects_of(cmd)
        if not objs:
            return self._not_found(cmd, lang)
        if any(o.get("type") == "DerivedProperty" for o in objs):
            return self._not_drawn(objs, lang)
        pre = self._view_pre(vid)
        eyes = pre["eyes"]
        index = self._index()
        drop = set()
        for o in objs:
            if self._is_prop(o):
                drop.add(o["path"])
                continue
            # an object: its own eye, every eye under it (a wellbore's
            # trajectory, frames, logs, markers) and its properties' eyes
            p, rep = o["path"], o.get("rep_path") or o["path"]
            for e in eyes:
                if e in (p, rep) or e.startswith(p + "/") or (index.get(e) or {}).get("rep_path") == rep:
                    drop.add(e)
        names = ", ".join(self._name(o, lang, index) for o in objs)
        kept = [e for e in eyes if e not in drop]
        if kept == eyes:
            return _reply(True, _t(lang, f"{names} n'était pas affiché.", f"{names} was not shown."))
        self._set_eyes(vid, kept)
        self._flush()
        tok = self._token("view", "hide", self._what("hide", names), vid=vid, pre=pre)
        return _reply(True, _t(lang, f"Masqué : {names}.", f"Hidden: {names}."), undo=tok)

    def _do_isolate(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        objs = self._objects_of(cmd)
        if not objs:
            return self._not_found(cmd, lang)
        if any(o.get("type") == "DerivedProperty" for o in objs):
            return self._not_drawn(objs, lang)
        pre = self._view_pre(vid)
        refused = self._read(objs, lang)
        if refused is not None:
            self._restore_view(vid, pre)
            return refused
        shown = list(self._get(f"visible_paths__{vid}", []))
        index = self._index()
        eyes = []
        for o in objs:
            if o.get("type") == "Wellbore":
                # the well as the view shows it (its logs, its markers), else its trajectory
                under = [e for e in shown if e.startswith(o["path"] + "/")]
                add = under or [self._eye_of(o)]
            elif self._is_prop(o):
                # a property with its grid: its eye alone only colours
                add = self._eyes_of(o)
            else:
                # the object as the view shows it: its eye and the property eyes colouring it
                e0, rep = self._eye_of(o), o.get("rep_path") or o["path"]
                add = [e0] + [e for e in shown if e != e0 and self._is_prop(index.get(e))
                              and index[e].get("rep_path") == rep]
            eyes += [e for e in add if e not in eyes]
        self._set_eyes(vid, eyes)
        self._activate(vid, objs[-1])
        index = self._index()
        names = ", ".join(self._name(o, lang, index) for o in objs)
        tok = self._token("view", "isolate", self._what("isolate", names), vid=vid, pre=pre)
        return _reply(True, _t(lang, f"Seul affiché : {names}.", f"Only shown: {names}."), undo=tok)

    # --- threshold / highlight --------------------------------------------
    def _bounds(self, cmd):
        sl = cmd.get("slots") or {}
        lo, hi = sl.get("min"), sl.get("max")
        return (float(lo) if lo is not None else None), (float(hi) if hi is not None else None)

    def _bounds_on(self, cmd, o):
        """The command's bounds on the property `o`, in its own unit. A
        percent said of a fraction is made one ("montre la porosité et filtre
        au-dessus de 20 %": 0.2): the engine converts it when the sentence
        names a fraction kind, the property may come from the view instead
        (the one just shown), which only the adapter knows — a fraction is
        never above 1, a bound from 1 to 100 is the percent, as the engine
        reads it. The other way round, a property stored in percent (%,
        p.u.) takes the numbers as said where the engine made them a
        fraction by the kind alone (the slots' `raw`): "porosity above 20"
        is 20 there."""
        lo, hi = self._bounds(cmd)
        sl = cmd.get("slots") or {}
        if o is None:
            return lo, hi
        raw = sl.get("raw") if isinstance(sl.get("raw"), dict) else {}
        if raw and self._in_percent(o):
            lo = float(raw["min"]) if raw.get("min") is not None else lo
            hi = float(raw["max"]) if raw.get("max") is not None else hi
        elif sl.get("percent") and sl.get("kind") not in nlu_engine.FRACTIONS and self._is_fraction(o):
            lo, hi = (v / 100.0 if v is not None and 1 < v <= 100 else v for v in (lo, hi))
        return lo, hi

    @staticmethod
    def _in_percent(o):
        """Whether the values of the property `o` are stored in percent: its
        unit says so (%, p.u.)."""
        return str(o.get("uom") or "").strip().lower() in node_kinds.PERCENT_UNITS

    @staticmethod
    def _is_fraction(o):
        """Whether the values of the property `o` are a fraction (0 to 1): a
        fraction unit (m3/m3, v/v…) or a fraction kind (porosity, net to
        gross, a saturation) — never a property stored in percent (%, p.u.)
        nor one whose data go above 1."""
        uom = str(o.get("uom") or "").strip().lower()
        if uom in node_kinds.PERCENT_UNITS:
            return False
        try:
            if o.get("vmax") is not None and float(o["vmax"]) > 1:
                return False
        except (TypeError, ValueError) as exc:
            print("[assistant] a property's maximum is not a number:", exc, flush=True)
        return (bool(uom) and uom in node_kinds.FRACTION_UNITS) or nlu_engine.kind_of(o) in nlu_engine.FRACTIONS

    @staticmethod
    def _past(lo, hi, rng):
        """The data's (min, max) when a bound lies past its other end — a
        minimum above the data's maximum, a maximum below its minimum: no
        value would be left, and swapping the bounds would make another
        range than the one said. None when the bounds meet the data, or
        the range is not known."""
        rng = list(rng or ())
        if len(rng) < 2 or rng[0] is None or rng[1] is None:
            return None
        try:
            dlo, dhi = float(rng[0]), float(rng[1])
        except (TypeError, ValueError) as exc:
            print("[assistant] a data range that is not numbers:", rng, exc, flush=True)
            return None
        if (lo is not None and lo > dhi) or (hi is not None and hi < dlo):
            return dlo, dhi
        return None

    @staticmethod
    def _bound_words(lo, hi, lang):
        """The bounds as a sentence says them: "au-dessus de 20"."""
        if lo is not None and hi is not None:
            return _t(lang, f"entre {_num(lo, lang)} et {_num(hi, lang)}",
                      f"between {_num(lo, lang)} and {_num(hi, lang)}")
        if lo is not None:
            return _t(lang, f"au-dessus de {_num(lo, lang)}", f"above {_num(lo, lang)}")
        if hi is not None:
            return _t(lang, f"en dessous de {_num(hi, lang)}", f"below {_num(hi, lang)}")
        return ""

    def _nothing_left(self, name, lo, hi, past, lang, lit=False):
        """The reply to bounds past the data's range: the range, and what
        the bounds would have left — nothing."""
        dlo, dhi = past
        what = _t(lang, "aucune maille ne serait surlignée" if lit else "aucune maille ne resterait",
                  "no cell would be highlighted" if lit else "no cell would be left")
        return _reply(False, _t(lang, f"{name} va de {_num(dlo, lang)} à {_num(dhi, lang)} :"
                                      f" {self._bound_words(lo, hi, lang)}, {what}.",
                                f"{name} goes from {_num(dlo, lang)} to {_num(dhi, lang)}:"
                                f" {self._bound_words(lo, hi, lang)}, {what}."))

    def _no_bounds(self, cmd, lang):
        """A gesture that reached its controllers without a bound: the
        question `_ask_bounds` asks, which names the property and its range
        — never a bare "a value, please" that leaves the reader wondering of
        what. A failed gesture's reply carries no button: a categorical
        property's values are said in words."""
        q = self._ask_bounds(cmd, lang, {"id": "cancel", "label": ""})
        values = [c["label"] for c in q.get("choices") or () if str(c.get("id", "")).startswith("category:")]
        text = q["text"].rstrip()
        if values and text.endswith(":"):
            text += " " + ", ".join(values) + "."
        elif values:
            text += " " + _t(lang, "Valeurs : ", "Values: ") + ", ".join(values) + "."
        return _reply(False, text)

    def _vtk_name(self, vid, path):
        from fespp_on_trame.engine import realization_dispatch, stats_dispatch
        tree = self._tree()
        real = realization_dispatch.get_active_realization_for_view(self.state, vid, path)
        if real is None:
            real = stats_dispatch._default_real_idx(self.state, tree, path)
        return stats_dispatch._resolve_vtk_name(tree, path, real)[2]

    def _iso_chain(self, vid, rep):
        """The threshold chain of ONE grid of the view, its isolate's own —
        `ui_thresholds__<vid>` holds the chain last pushed by a gesture,
        maybe another grid's, and a failed add still pushes the target's."""
        iso = (getattr(self.ctx, "grid_isolates", None) or {}).get((vid, rep))
        if iso is None:
            return []
        try:
            return [dict(e) for e in iso.get_chain() or () if isinstance(e, dict)]
        except Exception as exc:
            print(f"[assistant] threshold chain of {rep} ({vid}):", exc, flush=True)
            return []

    @staticmethod
    def _drawn(chain):
        """The entries that filter what is on screen: visible, and every
        ancestor visible — a hidden ancestor drops its whole branch
        (IjkGrid.visible_leaf_tips), so an entry under it filters nothing."""
        by = {e.get("name"): e for e in chain}

        def drawn(e):
            seen = set()
            while e is not None and e.get("name") not in seen:
                if e.get("visible", True) is False:
                    return False
                seen.add(e.get("name"))
                p = e.get("parent_name")
                e = by.get(p) if p else None
            return True
        return [e for e in chain if drawn(e)]

    @staticmethod
    def _ancestors_drawn(chain, entry):
        """Every ancestor of `entry` visible (the entry itself may be hidden:
        showing it again then draws it)."""
        by = {e.get("name"): e for e in chain}
        p, seen = entry.get("parent_name"), set()
        while p and p not in seen:
            seen.add(p)
            e = by.get(p)
            if e is None:
                return True
            if e.get("visible", True) is False:
                return False
            p = e.get("parent_name")
        return True

    def _tip(self, chain):
        """The entry a new one chains under: the last DRAWN one nothing drawn
        chains under (in a linear chain, the last one); none drawn (all
        hidden, or no filter): None, a new root, drawn on its own."""
        drawn = self._drawn(chain)
        parents = {e.get("parent_name") for e in drawn}
        tips = [e for e in drawn if e.get("name") not in parents]
        return (tips or drawn)[-1].get("name") if drawn else None

    def _value_runs(self, chain):
        """The drawn tips of the chain when they are several entries side by
        side — one array, one parent, nothing under them: the runs of ONE
        filter on category values (water and gas, the oil hidden), which a
        new filter must apply to all at once. [] for a single tip, or a
        union made otherwise."""
        drawn = self._drawn(chain)
        parents = {e.get("parent_name") for e in drawn}
        tips = [e for e in drawn if e.get("name") not in parents]
        if len(tips) < 2:
            return []
        with_child = {e.get("parent_name") for e in chain if e.get("parent_name")}
        first = tips[0]
        if any(e.get("parent_name") != first.get("parent_name") or e.get("array") != first.get("array")
               or e.get("name") in with_child for e in tips):
            return []
        return tips

    def _move_under(self, vid, rep, runs, parent):
        """The entries `runs` (side by side, nothing under them) moved under
        the entry `parent`: each taken off and added back under it with its
        range and eye. False when one could not be added back."""
        for s in runs:
            self._call("threshold_remove", s["name"], vid)
            have = {e.get("name") for e in self._iso_chain(vid, rep)}
            self._call("threshold_add", [s.get("array"), parent], vid)
            back = [e for e in self._iso_chain(vid, rep) if e.get("name") not in have]
            if not back:
                print(f"[assistant] filter: {s.get('array')} not put back under {parent}", flush=True)
                return False
            if s.get("low") is not None and s.get("high") is not None:
                self._call("threshold_range", [back[-1]["name"], [float(s["low"]), float(s["high"])]], vid)
            if s.get("visible", True) is False:
                self._call("threshold_visible", [back[-1]["name"], False], vid)
        return True

    def _chain_note(self, chain, name, lang, titles=None):
        """What the grid's other DRAWN filters do to the cells the reply
        names: a linear chain is an intersection (they apply too), a
        branching one a union (the cells they keep stay shown) — the runs of
        one filter on values side by side count as one filter. Hidden ones
        filter nothing and are not named; `titles` maps a VTK array name to
        the property title the reader knows."""
        chain = self._drawn(chain)
        with_child = {e.get("parent_name") for e in chain if e.get("parent_name")}
        seen = {(e.get("parent_name"), e.get("array")) for e in chain
                if e.get("name") == name and e.get("name") not in with_child}
        merged = []
        for e in chain:
            if e.get("name") != name and e.get("name") not in with_child:
                key = (e.get("parent_name"), e.get("array"))
                if key in seen:
                    continue
                seen.add(key)
            merged.append(e)
        chain = merged
        titles = titles or {}
        others = [e for e in chain if e.get("name") != name]
        if not others:
            return ""
        parents = [e.get("parent_name") for e in chain if e.get("parent_name")]
        roots = [e for e in chain if not e.get("parent_name")]
        if len(roots) == 1 and len(parents) == len(set(parents)):
            arrays = ", ".join(dict.fromkeys(titles.get(e.get("array"), e.get("array") or e.get("name"))
                                             for e in others))
            return _t(lang, f" Les autres filtres de la grille s'appliquent aussi ({arrays}).",
                      f" The grid's other filters still apply ({arrays}).")
        return _t(lang, " La grille a des filtres en parallèle (une union) : les mailles qu'ils"
                        " gardent restent affichées aussi.",
                  " The grid has filters in parallel (a union): the cells they keep stay shown too.")

    def _do_threshold(self, cmd, lang):
        """One filter per property and grid: an entry on the same array has
        its range changed; otherwise the new entry chains under the grid's
        last one (an intersection) — never a new root, whose cells would
        join the others' (a union) and widen what the reply says is kept.
        Several entries side by side on the property (a value hidden,
        values apart in the table) give way to the one filter asked for.
        Category values meet the ones the property's filter hides or keeps
        now, as the gesture's `values_mode` says (`_values_on`)."""
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        if self._globe(vid):
            return self._no_globe(lang)
        o, err = self._one_property(cmd, vid, lang)
        if o is None:
            return err
        lo, hi = self._bounds_on(cmd, o)
        labels, codes, err = self._codes(cmd, o, lang)
        if err is not None:
            return err
        name = self._name(o, lang)
        named = self._values(cmd)
        runs, exclude = [], False
        if labels:
            # the values kept: the ones named, or every other one when they
            # are hidden ("hide the water and gas zones")
            exclude = bool((cmd.get("slots") or {}).get("exclude"))
            if o.get("rep_type") in _ISOLATABLE:
                codes, exclude, done = self._values_on(cmd, o, vid, labels, codes, exclude, name, lang)
                if done is not None:
                    return done
                labels = [self._label_of(o, c) for c in codes]
            runs = self._runs(self._kept(o, codes, exclude))
            if not runs:
                said = self._said_values(labels, lang)
                return _reply(False, _t(lang, f"{name} : toutes les mailles sont {said}, rien ne resterait.",
                                        f"{name}: every cell is {said}, nothing would be left."))
            lo, hi = runs[0][0], runs[-1][1]
        if lo is None and hi is None:
            return self._no_bounds(cmd, lang)
        if o.get("rep_type") not in _ISOLATABLE:
            return _reply(False, _t(lang, f"Le filtre par valeur agit sur une grille : {name} n'en est pas sur une.",
                                    f"The value filter acts on a grid: {name} is not on one."))
        rep = o["rep_path"]
        # an entry on this array under a hidden ancestor filters nothing:
        # it is not reused, a drawn one is chained instead
        same = self._same_array(vid, rep, o)
        if not labels and (cmd.get("slots") or {}).get("exclude"):
            # a range hidden ("hide these cells" after a highlight): what the
            # property's filter keeps now, that range taken out — the runs
            # on either side of it
            runs = self._without(same, lo, hi, (o.get("vmin"), o.get("vmax")))
            if not runs:
                said = self._span_words(lo, hi, lang)
                return _reply(False, _t(lang, f"{name} : masquer les mailles {said} ne laisserait rien.",
                                        f"{name}: hiding the cells {said} would leave nothing."))
            return self._filter_codes(o, vid, runs, [], True, name, lang, hidden=(lo, hi))
        if exclude or len(runs) > 1 or len(same) > 1:
            # re-ranging one of several entries would leave the others'
            # cells shown (a union): the filter goes in their place
            r = self._filter_codes(o, vid, runs or [[lo, hi]], labels, exclude, name, lang)
        else:
            r = self._filter_one(o, vid, lo, hi, labels, name, cmd, lang)
        if r.get("ok") and labels:
            self._settle_values(cmd, o, codes, exclude, named)
        return r

    def _filter_one(self, o, vid, lo, hi, labels, name, cmd, lang):
        """The property's one filter entry set to [lo, hi]: the drawn entry
        on its array re-ranged (and shown, when it was hidden), else a new
        one chained under the grid's last drawn filter."""
        rep = o["rep_path"]
        same = self._same_array(vid, rep, o)
        # bounds said (a category value's codes come from its own table)
        past = self._past(lo, hi, same[0].get("data_range") or ()) if same and not labels else None
        if past is not None:
            return self._nothing_left(name, lo, hi, past, lang)
        pre = self._view_pre(vid)
        refused = self._read([o], lang)
        if refused is not None:
            self._restore_view(vid, pre)
            return refused
        self._ensure_visible(vid, o)
        # the chain as it was, what the undo puts back
        before_chain = self._iso_chain(vid, rep)
        # the Thresholds card acts on the Reservoir tab's grid; the property
        # active so its note is empty
        self._activate(vid, o, tab_path=rep)
        vtk = self._vtk_name(vid, o["path"])
        same = self._same_array(vid, rep, o)
        runs = []
        if same:
            entry = same[-1]
        else:
            chain = self._iso_chain(vid, rep)
            # the runs of one filter on values side by side at the chain's
            # end: the new filter goes above them (under their parent, then
            # they move under it), so it applies to every one of them — an
            # intersection — never under the last alone
            runs = self._value_runs(chain)
            before = {e.get("name") for e in chain}
            self._call("threshold_add", [vtk, runs[0].get("parent_name") if runs else self._tip(chain)], vid)
            new = [e for e in self._iso_chain(vid, rep) if e.get("name") not in before]
            if not new:
                self._restore_view(vid, pre)
                note = self._get(f"ui_thresholds_note__{vid}", "")
                return _reply(False, _t(lang, f"Le filtre sur {name} n'a pas pu être ajouté. {note}",
                                        f"The filter on {name} could not be added. {note}").strip())
            entry = new[-1]
        dr = list(entry.get("data_range") or [entry.get("low"), entry.get("high")])
        # a bound past the data's other end is said, never swapped into
        # another range ("above 20" on a porosity of 0 to 0.4)
        past = self._past(lo, hi, dr) if not labels else None
        said_lo, said_hi = lo, hi
        lo = lo if lo is not None else dr[0]
        hi = hi if hi is not None else dr[1]
        if past is not None or lo is None or hi is None:
            if not same:
                self._call("threshold_remove", entry["name"], vid)
            self._restore_view(vid, pre)
            if past is not None:
                return self._nothing_left(name, said_lo, said_hi, past, lang)
            return self._no_bounds(cmd, lang)
        lo, hi = min(float(lo), float(hi)), max(float(lo), float(hi))
        self._call("threshold_range", [entry["name"], [lo, hi]], vid)
        if runs and not self._move_under(vid, rep, runs, entry["name"]):
            self._restore_chain(vid, rep, before_chain, pre["by_tab"])
            self._restore_view(vid, pre)
            return _reply(False, _t(lang, f"Le filtre sur {name} n'a pas pu être posé.",
                                    f"The filter on {name} could not be set."))
        if same and entry.get("visible", True) is False:
            # a hidden entry filters nothing on screen
            self._call("threshold_visible", [entry["name"], True], vid)
        tok = self._chain_token("threshold", name, vid, [{"rep": rep, "chain": before_chain}], pre["by_tab"], pre)
        note = self._chain_note(self._iso_chain(vid, rep), entry["name"], lang, self._titles_on(vid, rep))
        if labels:
            said = self._said_values(labels, lang)
            text = _t(lang, f"{name} : seules les mailles {said} sont gardées.",
                      f"{name}: only the {said} cells are kept.")
        else:
            text = _t(lang, f"{name} : mailles gardées de {_num(lo, lang)} à {_num(hi, lang)}.",
                      f"{name}: cells kept from {_num(lo, lang)} to {_num(hi, lang)}.")
        return _reply(True, text + note, undo=tok)

    def _titles_on(self, vid, rep):
        """{VTK array name: property title} of the grid `rep`'s properties:
        a filter named the way the reader knows it."""
        return {self._vtk_name(vid, p["path"]): p["title"] for p in self.objects()
                if self._is_prop(p) and p.get("rep_path") == rep}

    def _same_array(self, vid, rep, o):
        """The grid's filter entries on the property `o` that filter what is
        drawn (every ancestor visible)."""
        vtk = self._vtk_name(vid, o["path"])
        chain = self._iso_chain(vid, rep)
        return [e for e in chain if e.get("array") == vtk and self._ancestors_drawn(chain, e)]

    # --- what a property's filter hides now ---------------------------------
    def _kept_now(self, vid, o):
        """The codes of the categorical property `o` its grid's filters
        leave in sight now, or None when no drawn filter is on `o` (none of
        its values hidden by value). The cells drawn are the union of the
        drawn chain's leaves, each the intersection of its path
        (IjkGrid.visible_leaf_tips): a code is in sight when the ranges on
        `o` along some leaf's path all hold it."""
        vtk = self._vtk_name(vid, o["path"])
        drawn = self._drawn(self._iso_chain(vid, o["rep_path"]))
        if not any(e.get("array") == vtk for e in drawn):
            return None
        by = {e.get("name"): e for e in drawn}
        parents = {e.get("parent_name") for e in drawn}
        codes = self._all_codes(o)
        kept = set()
        for leaf in (e for e in drawn if e.get("name") not in parents):
            ranges, e, seen = [], leaf, set()
            while e is not None and e.get("name") not in seen:
                seen.add(e.get("name"))
                if e.get("array") == vtk:
                    ranges.append((e.get("low"), e.get("high")))
                e = by.get(e.get("parent_name")) if e.get("parent_name") else None
            kept |= {c for c in codes if all(a is not None and b is not None and float(a) <= c <= float(b)
                                             for a, b in ranges)}
        return kept

    def _last_values(self, o, exclude, now):
        """The codes the last command named, when that command set the
        property's filter as it is now — the same property, the same
        polarity, and the codes it hid (or kept) the ones `now` holds; None
        after an undo, another gesture or a filter set otherwise."""
        ctx = self._context or {}
        if (now is None or ctx.get("intent") != "threshold" or bool(ctx.get("exclude")) != bool(exclude)
                or o.get("path") not in (ctx.get("targets") or ())):
            return None

        def codes(values):
            return {float(c) for c in (nlu_engine.code_of(o, v) for v in values or ()) if c is not None}
        if not codes(ctx.get("categories")) or codes(ctx.get("categories")) != set(now):
            return None
        return codes(ctx.get("said") or ctx.get("categories"))

    @staticmethod
    def _ordered(first, codes):
        """The codes already hidden or kept (in the table's order), then the
        ones named (in the sentence's order), each once."""
        return list(dict.fromkeys([float(c) for c in sorted(first)] + [float(c) for c in codes]))

    def _values_on(self, cmd, o, vid, labels, codes, exclude, name, lang):
        """The codes a gesture on category values acts on, read against what
        the property's filter hides (or keeps) now — the view's own state,
        so an undo or a gesture in between leaves no value behind —
        by the gesture's `values_mode` (`_mark_values`): (codes, exclude,
        None), or (…, a reply) when the gesture is done here (values seen
        again, nothing that would change)."""
        sl = cmd.get("slots") or {}
        mode = sl.get("values_mode")
        kept_now = self._kept_now(vid, o)
        hidden_now = set() if kept_now is None else set(self._all_codes(o)) - kept_now
        if mode == "spare":
            return codes, exclude, self._spared(cmd, o, codes, hidden_now, name, lang)
        if mode == "again":
            back = [c for c in codes if c in hidden_now]
            if back:
                left = [c for c in sorted(hidden_now) if c not in set(back)]
                return codes, True, self._show_again(cmd, o, vid, back, left, name, lang)
            # nothing of it hidden: in sight already, nothing to do
            return codes, False, self._in_sight(cmd, o, codes, hidden_now, name, lang)
        if mode == "add" and exclude:
            codes = self._ordered(hidden_now, codes)
        elif mode == "add" and kept_now is not None and (
                sl.get("also") or self._last_values(o, False, kept_now) is not None):
            # "keep the oil then the gas", "and the gas as well": the values
            # the filter keeps now, and these
            codes = self._ordered(kept_now, codes)
        elif mode == "add" and sl.get("also"):
            # nothing filtered on the property: every value is in sight
            return codes, False, self._in_sight(cmd, o, codes, hidden_now, name, lang)
        elif mode == "correct":
            ctx = self._context or {}
            if ctx.get("again") and o.get("path") in (ctx.get("targets") or ()) and not exclude:
                return self._correct_again(cmd, o, vid, codes, hidden_now, name, lang)
            now = hidden_now if exclude else (kept_now or set())
            replaced = {float(c) for c in (nlu_engine.code_of(o, v) for v in sl.get("instead") or ()) if c is not None}
            last = replaced or self._last_values(o, exclude, hidden_now if exclude else kept_now)
            if last:
                # the values the corrected command named (or the ones the
                # sentence says it replaces) give way to these
                codes = self._ordered(now - last, codes)
        if kept_now is not None and set(self._kept(o, codes, exclude)) == kept_now:
            self._settle_values(cmd, o, codes, exclude, self._values(cmd))
            return codes, exclude, self._already(o, labels, codes, exclude, name, lang)
        return codes, exclude, None

    def _correct_again(self, cmd, o, vid, codes, hidden_now, name, lang):
        """A correction of values just seen again ("remontre l'eau", then
        "non, pas l'eau, le gaz"): those are hidden again and the values
        meant come back instead — what the codes, polarity and reply of
        `_values_on` say."""
        ctx = self._context or {}
        last = {float(c) for c in (nlu_engine.code_of(o, v) for v in ctx.get("said") or ()) if c is not None}
        hidden = (hidden_now | last) - set(codes)
        back = [c for c in codes if c in hidden_now | last]
        if back:
            return codes, True, self._show_again(cmd, o, vid, back, sorted(hidden), name, lang)
        if hidden != hidden_now:
            return sorted(hidden), True, None
        return codes, False, self._in_sight(cmd, o, codes, hidden_now, name, lang)

    def _in_sight(self, cmd, o, codes, hidden_now, name, lang):
        """Values asked to be seen (again, or as well) that nothing hides:
        said, and nothing is done — never the other values hidden for it."""
        said = self._said_values([self._label_of(o, c) for c in codes], lang)
        left = ", ".join(self._label_of(o, c) for c in sorted(hidden_now))
        cmd.setdefault("slots", {})["unchanged"] = True
        tail = _t(lang, f" Restent masquées : {left}.", f" Still hidden: {left}.") if left else ""
        return _reply(True, _t(lang, f"{name} : les mailles {said} sont déjà affichées.",
                               f"{name}: the {said} cells are shown already.") + tail)

    def _spared(self, cmd, o, codes, hidden_now, name, lang):
        """Values said not to be hidden ("ne cache pas l'huile"): nothing is
        hidden; what is hidden of them already is said, with how to see it
        again."""
        cmd.setdefault("slots", {})["unchanged"] = True
        shown = [c for c in codes if c not in hidden_now]
        hidden = [c for c in codes if c in hidden_now]
        parts = []
        if shown:
            said = self._said_values([self._label_of(o, c) for c in shown], lang)
            parts.append(_t(lang, f"{name} : les mailles {said} ne sont pas masquées, rien à faire.",
                            f"{name}: the {said} cells are not hidden, nothing to do."))
        if hidden:
            said = self._said_values([self._label_of(o, c) for c in hidden], lang)
            parts.append(_t(lang, f"{name} : rien n'est masqué de plus ; les mailles {said} le sont déjà —"
                                  " demandez à les revoir pour les afficher.",
                            f"{name}: nothing more is hidden; the {said} cells are hidden already — ask to see"
                            " them again to show them."))
        return _reply(True, " ".join(parts))

    def _already(self, o, labels, codes, exclude, name, lang):
        """Nothing would change — the values named are hidden already, or
        already the only ones kept: said, and nothing to undo."""
        if exclude:
            said = self._said_values(labels, lang)
            left = ", ".join(self._label_of(o, c) for c in self._kept(o, codes, True))
            return _reply(True, _t(lang, f"{name} : les mailles {said} sont déjà masquées ; restent : {left}.",
                                   f"{name}: the {said} cells are already hidden; left: {left}."))
        said = self._said_values([self._label_of(o, c) for c in codes], lang)
        return _reply(True, _t(lang, f"{name} : seules les mailles {said} sont déjà gardées.",
                               f"{name}: only the {said} cells are kept already."))

    def _settle_values(self, cmd, o, codes, exclude, named):
        """The values the gesture acted on, in its slots for the session's
        memory (`_remember`): the ones hidden or kept now, and the ones the
        sentence named (what a correction takes back)."""
        values = [nlu_slots.category_of(self._label_of(o, c)) for c in codes]
        sl = cmd.setdefault("slots", {})
        sl.update(category=values[0] if values else None, categories=values, exclude=bool(exclude),
                  named=list(named))

    def _show_again(self, cmd, o, vid, back, left, name, lang):
        """The values asked to be seen again come back; the others the
        property's filter hides stay hidden — with none left, its filter
        goes, the filters chained under it moving up to its parent."""
        said = self._said_values([self._label_of(o, c) for c in back], lang)
        if left:
            r = self._filter_codes(o, vid, self._runs(self._kept(o, left, True)),
                                   [self._label_of(o, c) for c in left], True, name, lang, back=said)
        else:
            r = self._unfilter(o, vid, name, said, lang)
        if r.get("ok"):
            values = [nlu_slots.category_of(self._label_of(o, c)) for c in back]
            cmd.setdefault("slots", {}).update(category=values[0], categories=values, exclude=False, named=values,
                                               shown_again=True)
        return r

    def _unfilter(self, o, vid, name, said, lang):
        """Every filter entry on the property `o` taken off, its values all
        in sight again; the entries chained under them move up to their
        parent (IjkGrid.delete_threshold), and the undo puts the chain back
        as it was."""
        pre = self._view_pre(vid)
        rep = o["rep_path"]
        before_chain = self._iso_chain(vid, rep)
        self._activate(vid, o, tab_path=rep)
        vtk = self._vtk_name(vid, o["path"])
        for e in reversed([e for e in before_chain if e.get("array") == vtk]):
            self._call("threshold_remove", e["name"], vid)
        self._flush()
        tok = self._chain_token("threshold", name, vid, [{"rep": rep, "chain": before_chain}], pre["by_tab"], pre)
        note = self._chain_note(self._iso_chain(vid, rep), None, lang, self._titles_on(vid, rep))
        return _reply(True, _t(lang, f"{name} : les mailles {said} sont de nouveau affichées, plus aucune valeur"
                                     " n'est masquée.",
                               f"{name}: the {said} cells are shown again, no value is hidden any more.") + note,
                      undo=tok)

    def _filter_codes(self, o, vid, runs, labels, exclude, name, lang, back=None, hidden=None):
        """Put the filter asked for in place of the property's own: one
        entry per run of codes — category values one range cannot hold, the
        others of a value hidden ("hide the oil zone": water and gas) or
        values apart in the table ("keep the water and gas zones") — or the
        one range of bounds where the property held several entries side by
        side. The entries go side by side under the grid's last drawn
        filter: a cell is kept when it is in any of them (their union) and
        passes the grid's other filters (an intersection) — new roots would
        join those filters' cells and keep more than the reply says. The
        filters already on this property are taken off first; the undo puts
        the grid's chain back as it was. `back`: the values just seen again
        (`_show_again`), what the reply says; `hidden`: the (lo, hi) range a
        hiding took out (`_do_threshold`), likewise."""
        pre = self._view_pre(vid)
        refused = self._read([o], lang)
        if refused is not None:
            self._restore_view(vid, pre)
            return refused
        self._ensure_visible(vid, o)
        rep = o["rep_path"]
        by_tab = dict(self._get(f"active_by_tab__{vid}", {}))
        self._activate(vid, o, tab_path=rep)
        vtk = self._vtk_name(vid, o["path"])
        chain = self._iso_chain(vid, rep)
        mine = [e for e in chain if e.get("array") == vtk]
        if not labels and hidden is None:
            # bounds past the data's other end leave nothing: said before
            # anything is taken off
            rng = next((e.get("data_range") for e in mine if e.get("data_range")), None) or ()
            past = self._past(runs[0][0], runs[0][1], rng)
            if past is not None:
                self._restore_view(vid, pre)
                return self._nothing_left(name, runs[0][0], runs[0][1], past, lang)
        for e in reversed(mine):
            self._call("threshold_remove", e["name"], vid)
        tip = self._tip(self._iso_chain(vid, rep))
        made, kept = [], []
        for lo, hi in runs:
            before = {e.get("name") for e in self._iso_chain(vid, rep)}
            self._call("threshold_add", [vtk, tip], vid)
            new = [e for e in self._iso_chain(vid, rep) if e.get("name") not in before]
            if not new:
                print(f"[assistant] filter: no entry added on {vtk} for {lo}..{hi}", flush=True)
                continue
            # a bound not said: the data's own end
            dr = list(new[-1].get("data_range") or [new[-1].get("low"), new[-1].get("high")])
            lo = lo if lo is not None else dr[0]
            hi = hi if hi is not None else dr[1]
            # (a run beside a range hidden that reaches the data's end holds
            # nothing: past that end)
            if lo is None or hi is None or (hidden is not None and float(lo) > float(hi)):
                self._call("threshold_remove", new[-1]["name"], vid)
                continue
            lo, hi = min(float(lo), float(hi)), max(float(lo), float(hi))
            self._call("threshold_range", [new[-1]["name"], [lo, hi]], vid)
            made.append(new[-1]["name"])
            kept.append((lo, hi))
        if not made:
            # nothing set: the grid's filters as they were
            self._restore_chain(vid, rep, chain, by_tab)
            self._restore_view(vid, pre)
            if hidden is not None:
                said = self._span_words(hidden[0], hidden[1], lang)
                return _reply(False, _t(lang, f"{name} : masquer les mailles {said} ne laisserait rien.",
                                        f"{name}: hiding the cells {said} would leave nothing."))
            return _reply(False, _t(lang, f"Le filtre sur {name} n'a pas pu être posé.",
                                    f"The filter on {name} could not be set."))
        said = self._said_values(labels, lang)
        tok = self._chain_token("threshold", name, vid, [{"rep": rep, "chain": chain}], by_tab, pre)
        # what the grid's other filters do: the entries made count as one
        note = self._chain_note([e for e in self._iso_chain(vid, rep) if e.get("name") not in made[:-1]],
                                made[-1], lang, self._titles_on(vid, rep))
        if hidden is not None:
            said = self._span_words(hidden[0], hidden[1], lang)
            return _reply(True, _t(lang, f"{name} : mailles {said} masquées.",
                                   f"{name}: cells {said} hidden.") + note, undo=tok)
        if not labels:
            lo, hi = kept[0]
            return _reply(True, _t(lang, f"{name} : mailles gardées de {_num(lo, lang)} à {_num(hi, lang)}.",
                                   f"{name}: cells kept from {_num(lo, lang)} to {_num(hi, lang)}.") + note,
                          undo=tok)
        if back:
            return _reply(True, _t(lang, f"{name} : les mailles {back} sont de nouveau affichées ; restent"
                                         f" masquées : {', '.join(labels)}.",
                                   f"{name}: the {back} cells are shown again; still hidden: {', '.join(labels)}.")
                          + note, undo=tok)
        if not exclude:
            return _reply(True, _t(lang, f"{name} : seules les mailles {said} sont gardées.",
                                   f"{name}: only the {said} cells are kept.") + note, undo=tok)
        others = ", ".join(self._label_of(o, c) for lo, hi in runs for c in self._all_codes(o) if lo <= c <= hi)
        return _reply(True, _t(lang, f"{name} : les mailles {said} sont masquées ; restent : {others}.",
                               f"{name}: the {said} cells are hidden; left: {others}.") + note, undo=tok)

    def _do_clear_threshold(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        if self._globe(vid):
            return self._no_globe(lang)
        isos = getattr(self.ctx, "grid_isolates", None) or {}
        reps = [rep for (ivid, rep), iso in list(isos.items())
                if ivid == vid and (iso.get_chain() or [])]
        named = self._objects_of(cmd) if self._named(cmd) else []
        on_grids = [o for o in named if self._is_prop(o) and o.get("rep_type") in _ISOLATABLE]
        if on_grids and all(self._is_prop(o) for o in named):
            # "retire le filtre de la porosité": that property's entries only
            return self._clear_properties(vid, on_grids, reps, lang)
        wanted = {o.get("rep_path") or o["path"] for o in named} if self._named(cmd) else None
        if wanted is not None:
            reps = [r for r in reps if r in wanted]
        if not reps:
            return _reply(True, _t(lang, "Aucun filtre par valeur dans cette vue.",
                                   "No value filter in this view."))
        by_tab = dict(self._get(f"active_by_tab__{vid}", {}))
        saved = []
        for rep in reps:
            chain = [dict(e) for e in isos[(vid, rep)].get_chain() or []]
            self.state[f"active_by_tab__{vid}"] = dict(by_tab, reservoir=rep)
            for e in reversed(chain):
                self._call("threshold_remove", e["name"], vid)
            saved.append({"rep": rep, "chain": chain})
        self.state[f"active_by_tab__{vid}"] = by_tab
        self._flush()
        index = self._index()
        names = ", ".join(self._title_of(r, index) or r for r in reps)
        tok = self._chain_token("clear_threshold", names, vid, saved, by_tab)
        return _reply(True, _t(lang, f"Filtres par valeur enlevés : {names}.",
                               f"Value filters removed: {names}."), undo=tok)

    def _clear_properties(self, vid, props, reps, lang):
        """The filter entries on the properties named taken off — the
        grid's other filters stay, the entries chained under a removed one
        moving up to its parent (IjkGrid.delete_threshold)."""
        by_tab = dict(self._get(f"active_by_tab__{vid}", {}))
        saved, gone = [], []
        for rep in dict.fromkeys(p["rep_path"] for p in props):
            if rep not in reps:
                continue
            mine = [p for p in props if p["rep_path"] == rep]
            arrays = {self._vtk_name(vid, p["path"]) for p in mine}
            chain = self._iso_chain(vid, rep)
            drop = [e for e in self._parents_first(chain) if e.get("array") in arrays]
            if not drop:
                continue
            self.state[f"active_by_tab__{vid}"] = dict(by_tab, reservoir=rep)
            for e in reversed(drop):
                self._call("threshold_remove", e["name"], vid)
            saved.append({"rep": rep, "chain": chain})
            gone += [p for p in mine if self._vtk_name(vid, p["path"]) in {e.get("array") for e in drop}]
        self.state[f"active_by_tab__{vid}"] = by_tab
        self._flush()
        index = self._index()
        if not gone:
            names = ", ".join(self._name(p, lang, index) for p in props)
            return _reply(True, _t(lang, f"Aucun filtre par valeur sur {names}.", f"No value filter on {names}."))
        names = ", ".join(self._name(p, lang, index) for p in gone)
        tok = self._chain_token("clear_threshold", names, vid, saved, by_tab)
        return _reply(True, _t(lang, f"Filtre par valeur enlevé : {names}.", f"Value filter removed: {names}."),
                      undo=tok)

    def _chain_token(self, intent, names, vid, grids, by_tab, pre=None):
        """The undo token of a filter gesture: each grid's threshold chain as
        it was before the gesture and as the gesture left it, and the view
        before and after — `_undo_chain` takes back what the gesture changed
        and only that."""
        return self._token("chain", intent, self._what(intent, names), vid=vid,
                           grids=[{"rep": g["rep"], "chain": [dict(e) for e in g.get("chain") or ()],
                                   "after": self._iso_chain(vid, g["rep"])}
                                  for g in grids],
                           by_tab=dict(by_tab or {}), pre=pre, post=self._view_pre(vid))

    def _cond(self, title, lo, hi, lang):
        if lo is not None and hi is not None:
            return f"{_num(lo, lang)} ≤ {title} ≤ {_num(hi, lang)}"
        if lo is not None:
            return f"{title} ≥ {_num(lo, lang)}"
        return f"{title} ≤ {_num(hi, lang)}"

    def _category_range(self, cmd, o, lang, walk=False):
        """The ONE range of codes a highlight (or, `walk`, the wells' walk
        through a zone) takes for the category values the command names —
        boot lights the cells of one range at a time: (lo, hi, the
        condition in words, None); (None, None, None, None) when no value
        is named; (None, None, None, a reply) when the values kept are not
        one run of codes ("water and gas" around oil)."""
        labels, codes, err = self._codes(cmd, o, lang)
        if err is not None:
            return None, None, None, err
        if not labels:
            return None, None, None, None
        exclude = bool((cmd.get("slots") or {}).get("exclude")) and not walk
        kept = self._kept(o, codes, exclude)
        said = self._said_values(labels, lang)
        if not kept:
            return None, None, None, _reply(False, _t(lang, f"{o['title']} : toutes les mailles sont {said}.",
                                                      f"{o['title']}: every cell is {said}."))
        runs = self._runs(kept)
        if len(runs) > 1:
            apart = self._said_values([self._label_of(o, c) for c in kept], lang)
            if walk:
                return None, None, None, _reply(False, _t(
                    lang, f"Je ne suis les puits que dans une suite de valeurs à la fois : {apart} ne se suivent"
                          f" pas dans {o['title']}. Nommez une zone à la fois.",
                    f"I follow the wells through one run of values at a time: {apart} are not next to each"
                    f" other in {o['title']}. Name one zone at a time."))
            # a highlight replaces the one before: lighting them one by one
            # would never show them together, a filter does
            return None, None, None, _reply(False, _t(
                lang, f"Je ne surligne qu'une suite de valeurs à la fois : {apart} ne se suivent pas dans"
                      f" {o['title']}. Pour les voir ensemble, filtrez sur ces valeurs.",
                f"I highlight one run of values at a time: {apart} are not next to each other in"
                f" {o['title']}. To see them together, filter on these values."))
        cond = (_t(lang, f"{o['title']} sauf {said}", f"{o['title']} except {said}") if exclude
                else f"{o['title']} {said}")
        return runs[0][0], runs[0][1], cond, None

    def _do_highlight(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        if self._globe(vid):
            return self._no_globe(lang)
        o, err = self._one_property(cmd, vid, lang)
        if o is None:
            return err
        lo, hi = self._bounds_on(cmd, o)
        sl = cmd.setdefault("slots", {})
        lit = self._lit.get(vid)
        if sl.get("values_mode") == "add" and self._values(cmd) and lit and lit[0] == o["path"]:
            # "highlight the water then the oil": the values the highlight
            # lit on this property (still lit: an undo or another highlight
            # forgets them) and these
            values = list(dict.fromkeys(list(lit[1]) + self._values(cmd)))
            sl.update(category=values[0], categories=values)
        clo, chi, shown, err = self._category_range(cmd, o, lang)
        if err is not None:
            return err
        if shown is not None:
            lo, hi = clo, chi
        if lo is None and hi is None:
            return self._no_bounds(cmd, lang)
        past = self._past(lo, hi, (o.get("vmin"), o.get("vmax"))) if shown is None else None
        if past is not None:
            return self._nothing_left(self._name(o, lang), lo, hi, past, lang, lit=True)
        fn = self._ctrl("highlight_where")
        if fn is None:
            raise _Unavailable("highlight_where")
        pre = self._view_pre(vid)
        refused = self._read([o], lang)
        if refused is not None:
            self._restore_view(vid, pre)
            return refused
        self._ensure_visible(vid, o)
        # the highlight acts on the view's ACTIVE node's array
        self._activate(vid, o)
        res = fn([lo, hi], vid) or {}
        if res.get("error"):
            self._restore_view(vid, pre)
            return _reply(False, _t(lang, f"Surbrillance impossible : {res['error']}",
                                    f"Cannot highlight: {res['error']}"))
        n = int(res.get("count") or 0)
        total = int(res.get("valid", res.get("total")) or 0)
        cells = res.get("assoc", "CELLS") != "POINTS"
        cond = self._cond(o["title"], lo, hi, lang) if shown is None else shown
        if res.get("too_many"):
            # nothing was lit: past the cap, the id selection alone would
            # hold the server for seconds (boot.HIGHLIGHT_MAX_IDS)
            self._restore_view(vid, pre)
            cap = int(res["too_many"])
            return _reply(False, _t(
                lang, f"{_count(n, lang)} {'mailles' if cells else 'points'} sur {_count(total, lang)}"
                      f" vérifient {cond} : trop pour les surligner une à une (au plus"
                      f" {_count(cap, lang)}). Resserrez la condition, ou filtrez plutôt :"
                      f" « filtre {o['title']} au-dessus de … ».",
                f"{_count(n, lang)} of {_count(total, lang)} {'cells' if cells else 'points'} meet"
                f" {cond}: too many to highlight one by one (at most {_count(cap, lang)})."
                f" Narrow the condition, or filter instead: “filter {o['title']} above …”."))
        if lang == "fr":
            unit = _plural(n, "maille", "mailles") if cells else _plural(n, "point", "points")
            done = _plural(n, "surlignée", "surlignées") if cells else _plural(n, "surligné", "surlignés")
            text = f"{_count(n, lang)} {unit} sur {_count(total, lang)} {done} : {cond}."
        else:
            unit = _plural(total, "cell", "cells") if cells else _plural(total, "point", "points")
            text = f"{_count(n, lang)} of {_count(total, lang)} {unit} highlighted: {cond}."
        tok = self._token("highlight", "highlight", self._what("highlight", o["title"]),
                          vid=vid, pre=pre)
        if shown is not None and not sl.get("exclude"):
            self._lit[vid] = (o["path"], tuple(self._values(cmd)))
        else:
            self._lit.pop(vid, None)
        # what the session remembers: "masque-les" then hides these cells
        sl["lit"], sl["lit_on"] = [lo, hi], o["path"]
        follow = self._lit_follow(cmd, o, lo, hi, shown, lang) if cells and o.get("rep_type") in _ISOLATABLE else []
        return _reply(True, text, undo=tok, follow=follow)

    def _lit_follow(self, cmd, o, lo, hi, shown, lang):
        """The next steps a highlight's reply offers: keep only the cells it
        lit, or hide them — a filter on the same values, or on the same
        range (`_do_threshold`), of the property it lit."""
        if shown is not None:
            # category values: the same ones — a filter hiding values leaves
            # hidden the ones it hides already
            values = self._values(cmd)
            out = bool((cmd.get("slots") or {}).get("exclude"))   # "everything but the water" was lit
            same = {"category": values[0], "categories": values, "named": values}
            keep = dict(same, exclude=out, values_mode="add" if out else None)
            hide = dict(same, exclude=not out, values_mode=None if out else "add")
        else:
            keep = {"min": lo, "max": hi, "exclude": False}
            hide = {"min": lo, "max": hi, "exclude": True}
        steps = ((_t(lang, "Ne garder que ces mailles", "Keep only these cells"), keep),
                 (_t(lang, "Masquer ces mailles", "Hide these cells"), hide))
        return [{"label": label, "cmd": {"intent": "threshold", "confidence": 1.0, "alternatives": [],
                                         "slots": slots, "targets": [o], "missing": [], "sure": True,
                                         "text": label}}
                for label, slots in steps]

    def _do_clear_highlight(self, cmd, lang):
        vid = self._vid() or ""
        self._call("node_highlight", [], vid)
        self._lit.pop(vid, None)
        return _reply(True, _t(lang, "Surbrillance enlevée.", "Highlight removed."))

    # --- the cells the wells go through -----------------------------------
    def _zone(self, cmd):
        """What a wells' walk takes its zone from: the command's targets on
        a grid, else the grids' properties of the kind said or listing the
        values said — the zone is on the GRID: a well's log of the same kind
        ("Total Porosity (Original Log)") is not it, nor is the well itself
        ("…porosity above 0.2 crossed by the well F-4" read the kind on the
        well named)."""
        sl = cmd.get("slots") or {}
        values = self._values(cmd)
        on_grid = [t for t in cmd.get("targets") or ()
                   if (t.get("rep_type") if self._is_prop(t) else t.get("type")) in _GRIDS]
        if not on_grid:
            on_grid = [o for o in self.objects() if self._is_prop(o) and o.get("rep_type") in _GRIDS
                       and ((sl.get("kind") and nlu_engine.kind_matches(sl["kind"], o))
                            or (values and nlu_engine.has_category(o, values[0])))]
        if values:
            # category values pick the property that lists them, over one
            # whose name merely resembles the words
            listing = [t for t in on_grid if self._is_prop(t)
                       and all(nlu_engine.has_category(t, v) for v in values)]
            on_grid = listing or on_grid
        return on_grid

    def _grid_of(self, cmd, vid):
        """The grid a command acts on: the one named, else the view's
        Reservoir tab's (or its active node's), else the first grid read."""
        index = self._index()
        sl = cmd.get("slots") or {}
        for o in (o for cands in sl.get("objects") or () for o in cands):
            g = index.get(o.get("rep_path") or o.get("path") or "")
            if g is not None and g.get("type") in _GRIDS:
                return g
        by_tab = self._get(f"active_by_tab__{vid}", {}) or {}
        for p in (by_tab.get("reservoir"), self._get(f"active_path__{vid}", "")):
            o = index.get(p or "")
            g = index.get((o or {}).get("rep_path") or "") if o else None
            if g is not None and g.get("type") in _GRIDS:
                return g
        grids = [o for o in index.values() if o.get("type") in _GRIDS]
        return next((g for g in grids if g.get("loaded")), grids[0] if grids else None)

    def _do_well_cells(self, cmd, lang):
        """The cells the wells go through ("highlight the cells the wells
        cross", "which wells cross the oil zone?"): the wells (the ones
        named, else all) and the grid in sight, plus the property colouring
        it when a zone is asked; boot's well_cells_where walks each
        trajectory through the grid's cells, lights the crossed cells
        (within the zone when one is asked) and the reply counts them per
        well. No blocked wellbore is needed: the geometry alone says which
        cells a trajectory crosses."""
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        if self._globe(vid):
            return self._no_globe(lang)
        sl = cmd.get("slots") or {}
        index = self._index()
        wells_all = [o for o in self.objects() if o.get("type") == "Wellbore" and o.get("trajectory")]
        if not wells_all:
            return _reply(False, _t(lang, "Aucun puits avec une trajectoire dans les données lues.",
                                    "No well with a trajectory in the data read."))
        named = [index.get(o["path"], o) for cands in sl.get("objects") or () for o in cands
                 if o.get("type") == "Wellbore" and not o.get("by_sort")]
        if named and not all(o.get("trajectory") for o in named):
            names = ", ".join(o.get("title", "") for o in named if not o.get("trajectory"))
            return _reply(False, _t(lang, f"{names} n'a pas de trajectoire : rien à suivre dans la grille.",
                                    f"{names} has no trajectory: nothing to follow through the grid."))
        wells = list({o["path"]: o for o in (named or wells_all)}.values())
        # the zone: a property said, with category values or bounds
        prop, lo, hi, shown = None, None, None, None
        if self._values(cmd) or sl.get("kind") or any(self._is_prop(t) for t in cmd.get("targets") or ()):
            prop, err = self._one_property(dict(cmd, targets=self._zone(cmd)), vid, lang)
            if prop is None:
                return err
            lo, hi = self._bounds_on(cmd, prop)
            clo, chi, shown, err = self._category_range(cmd, prop, lang, walk=True)
            if err is not None:
                return err
            if shown is not None:
                lo, hi = clo, chi
            if lo is None and hi is None:
                return self._no_bounds(dict(cmd, targets=[prop]), lang)
            if prop.get("rep_type") not in _GRIDS:
                return _reply(False, _t(lang, f"{prop['title']} n'est pas une propriété de grille : les puits"
                                              " se suivent dans les mailles d'une grille.",
                                        f"{prop['title']} is not a grid property: wells are followed"
                                        " through the cells of a grid."))
        grid = index.get(prop["rep_path"]) if prop else self._grid_of(cmd, vid)
        if grid is None:
            return _reply(False, _t(lang, "Aucune grille dans les données lues.", "No grid in the data read."))
        fn = self._ctrl("well_cells_where")
        if fn is None:
            raise _Unavailable("well_cells_where")
        pre = self._view_pre(vid)
        refused = self._read(wells + [grid] + ([prop] if prop else []), lang)
        if refused is not None:
            self._restore_view(vid, pre)
            return refused
        eyes = list(self._get(f"visible_paths__{vid}", []))
        for o in wells + [grid] + ([prop] if prop else []):
            for e in self._eyes_of(o):
                if e and e not in eyes:
                    eyes.append(e)
        self._set_eyes(vid, eyes)
        self._activate(vid, prop or grid)
        res = fn({"grid": grid["path"], "trajectories": [w["trajectory"] for w in wells],
                  "array": prop["path"] if prop else None, "lo": lo, "hi": hi}, vid) or {}
        if res.get("error"):
            self._restore_view(vid, pre)
            return _reply(False, _t(lang, f"Impossible de suivre les puits dans la grille : {res['error']}",
                                    f"Cannot follow the wells through the grid: {res['error']}"))
        per = res.get("per") or {}
        lit = int(res.get("lit") or 0)
        names = ", ".join(w["title"] for w in wells)
        if res.get("too_many"):
            self._restore_view(vid, pre)
            cap = int(res["too_many"])
            return _reply(False, _t(lang, f"{_count(lit, lang)} mailles traversées : trop pour les surligner"
                                          f" une à une (au plus {_count(cap, lang)}). Nommez un puits ou une zone.",
                                    f"{_count(lit, lang)} cells crossed: too many to highlight one by one"
                                    f" (at most {_count(cap, lang)}). Name a well or a zone."))
        text = self._well_cells_text(wells, per, lit, prop, shown, lo, hi, lang)
        # the well filter: "remove the wells that miss the oil zone" hides
        # the wells that stay out of it, "hide the wells that cross it" the
        # ones in it — the undo puts the eyes back
        wf = sl.get("well_filter")
        if wf in ("keep_crossing", "hide_crossing"):
            def crosses(w):
                d = per.get(w.get("trajectory")) or {}
                return int(d.get("in" if prop else "crossed") or 0) > 0
            hidden = [w for w in wells if crosses(w) == (wf == "hide_crossing")]
            if hidden:
                gone = {e for w in hidden for e in self._eyes_of(w)}
                self._set_eyes(vid, [e for e in self._get(f"visible_paths__{vid}", []) if e not in gone])
                who = ", ".join(w["title"] for w in hidden)
                text += _t(lang, f" {_count(len(hidden), lang)} {_plural(len(hidden), 'puits masqué', 'puits masqués')} : {who}.",
                           f" {_count(len(hidden), lang)} {'well' if len(hidden) == 1 else 'wells'} hidden: {who}.")
            else:
                text += _t(lang, " Aucun puits à masquer.", " No well to hide.")
        tok = self._token("highlight", "well_cells", self._what("well_cells", names), vid=vid, pre=pre)
        # the wells' cells replace what a highlight lit
        self._lit.pop(vid, None)
        return _reply(True, text, undo=tok)

    def _well_cells_text(self, wells, per, lit, prop, shown, lo, hi, lang):
        """Each well and its cells: within the zone (on the cells it
        crosses) when one was asked, crossed otherwise; the wells that
        stay out of the zone, or out of the grid, named as such."""
        def counts(w):
            d = per.get(w.get("trajectory")) or {}
            return int(d.get("crossed") or 0), int(d.get("in") or 0)
        outside = [w["title"] for w in wells if counts(w)[0] == 0]
        if lang == "fr":
            out_grid = (" " + ", ".join(outside) + (" ne traversent pas la grille." if len(outside) > 1
                                                    else " ne traverse pas la grille.")) if outside else ""
            lit_text = f" {_count(lit, lang)} {_plural(lit, 'maille surlignée', 'mailles surlignées')}."
        else:
            out_grid = (" " + ", ".join(outside) + (" do not cross the grid." if len(outside) > 1
                                                    else " does not cross the grid.")) if outside else ""
            lit_text = f" {_count(lit, lang)} {'cell' if lit == 1 else 'cells'} highlighted."
        if prop is None:
            parts = [f"{w['title']} ({_count(counts(w)[0], lang)})" for w in wells if counts(w)[0]]
            head = _t(lang, "Mailles traversées par les puits : ", "Cells the wells go through: ")
            body = ", ".join(parts) + "." if parts else ""
            return (head + body if parts else "") + out_grid + lit_text
        cond = self._cond(prop["title"], lo, hi, lang) if shown is None else shown
        inside = [w for w in wells if counts(w)[1]]
        missed = [w["title"] for w in wells if counts(w)[0] and not counts(w)[1]]
        if lang == "fr":
            parts = [f"{w['title']} ({_count(counts(w)[1], lang)} sur {_count(counts(w)[0], lang)} traversées)"
                     for w in inside]
            head = (f"{_count(len(inside), lang)} {_plural(len(inside), 'puits traverse', 'puits traversent')}"
                    f" {cond} : " + ", ".join(parts) + "." if inside else f"Aucun puits ne traverse {cond}.")
            miss = (" " + ", ".join(missed) + (" n'y passent pas." if len(missed) > 1 else " n'y passe pas.")
                    if missed else "")
        else:
            parts = [f"{w['title']} ({_count(counts(w)[1], lang)} of {_count(counts(w)[0], lang)} crossed)"
                     for w in inside]
            head = (f"{_count(len(inside), lang)} {_plural(len(inside), 'well crosses', 'wells cross')}"
                    f" {cond}: " + ", ".join(parts) + "." if inside else f"No well crosses {cond}.")
            miss = (" " + ", ".join(missed) + (" stay out of it." if len(missed) > 1 else " stays out of it.")
                    if missed else "")
        return head + miss + out_grid + lit_text

    # --- slice ------------------------------------------------------------
    def _slice_grid(self, cmd, vid):
        index = self._index()
        for o in self._objects_of(cmd) if self._named(cmd) else ():
            g = index.get(o.get("rep_path") or o["path"])
            if g is not None and g.get("type") == "IjkGrid":
                return g
        by_tab = self._get(f"active_by_tab__{vid}", {}) or {}
        for p in (by_tab.get("reservoir"), self._get(f"active_path__{vid}", "")):
            o = index.get(p or "")
            g = index.get((o or {}).get("rep_path") or "")
            if g is not None and g.get("type") == "IjkGrid":
                return g
        return next((o for o in index.values() if o.get("type") == "IjkGrid" and o.get("loaded")), None)

    def _slicer_pre(self, vid, rep):
        """The grid isolate's slicer state as `_undo_slice` replays it, or
        None when the grid has no isolate in the view."""
        iso = (getattr(self.ctx, "grid_isolates", None) or {}).get((vid, rep))
        if iso is None:
            return None
        return {"mode": getattr(iso, "_range_mode", "full"),
                "ranges": {a: list(getattr(iso, f"_range_{a}", None) or []) for a in "ijk"},
                "positions": {a: list(getattr(iso, f"_slices_{a}_list", None) or []) for a in "ijk"},
                "visible": {a: list(getattr(iso, f"_slices_{a}_visible_list", None) or []) for a in "ijk"},
                "volumes": [[list(r) for r in vol] for vol in (getattr(iso, "_volumes", None) or [])],
                "volumes_visible": list(getattr(iso, "_volumes_visible", None) or [])}

    def _do_slice(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        if self._globe(vid):
            return self._no_globe(lang)
        axis = ((cmd.get("slots") or {}).get("axis") or "").lower()
        if axis not in ("i", "j", "k"):
            return _reply(False, _t(lang, "Selon quel axe : I, J ou K ?", "Along which axis: I, J or K?"))
        g = self._slice_grid(cmd, vid)
        if g is None:
            return _reply(False, _t(lang, "La coupe I, J, K s'applique à une grille IJK : aucune n'est lue.",
                                    "An I, J, K slice needs an IJK grid: none is read."))
        pre = self._view_pre(vid)
        refused = self._read([g], lang)
        if refused is not None:
            self._restore_view(vid, pre)
            return refused
        before = self._slicer_pre(vid, g["path"])
        # the slicers act on the Reservoir tab's grid; activating it (again)
        # has the Slicers card publish its extents
        active = self._get(f"active_path__{vid}", "")
        if (self._index().get(active) or {}).get("rep_path") != g["path"]:
            self._activate(vid, g)
        else:
            self.state[f"active_by_tab__{vid}"] = dict(pre["by_tab"], reservoir=g["path"])
            dirty = getattr(self.state, "dirty", None)
            if callable(dirty):
                dirty(f"active_path__{vid}")
            self._flush()
        card = self._get(f"ui_slicers__{vid}", {}) or {}
        # the grid's whole extent per axis: what an undo puts back when the
        # command built the grid's slicer state
        full = {a: [int(x) for x in card.get(f"range_{a}") or []] for a in "ijk"}
        ext = full[axis] if len(full[axis]) == 2 else []
        lo, hi = self._bounds(cmd)
        A = axis.upper()
        if lo is None and hi is None:
            if len(ext) != 2:
                self._restore_view(vid, pre)
                return _reply(False, _t(lang, "Donnez les couches, par exemple « coupe selon K entre 10 et 20 ».",
                                        "Give the layers, for instance “slice along K between 10 and 20”."))
            mid = int((ext[0] + ext[1]) // 2)
            self._call("slicer_positions", [axis, [mid]], vid)
            text = _t(lang, f"{g['title']} : coupe {A} = {mid}.", f"{g['title']}: {A} slice at {mid}.")
        else:
            if (lo is None or hi is None) and len(ext) != 2:
                self._restore_view(vid, pre)
                return _reply(False, _t(lang, "Donnez les deux bornes, par exemple « entre 10 et 20 ».",
                                        "Give both bounds, for instance “between 10 and 20”."))
            lo = int(lo) if lo is not None else int(ext[0])
            hi = int(hi) if hi is not None else int(ext[1])
            lo, hi = min(lo, hi), max(lo, hi)
            if len(ext) == 2:
                lo, hi = max(lo, int(ext[0])), min(hi, int(ext[1]))
                if lo > hi:
                    # outside the grid: an inverted box would draw nothing
                    self._restore_view(vid, pre)
                    return _reply(False, _t(
                        lang, f"{g['title']} : {A} va de {ext[0]} à {ext[1]} ; ces couches n'y sont pas.",
                        f"{g['title']}: {A} goes from {ext[0]} to {ext[1]}; those layers are not in it."))
            self._call("slicer_range", [axis, [lo, hi]], vid)
            text = _t(lang, f"{g['title']} : {A} gardé de {lo} à {hi}.", f"{g['title']}: {A} kept from {lo} to {hi}.")
        tok = self._token("slice", "slice", self._what("slice", g["title"]),
                          vid=vid, rep=g["path"], grid=before, full=full, pre=pre)
        return _reply(True, text, undo=tok)

    # --- colours ----------------------------------------------------------
    def _card(self, vid):
        return dict(self._get(f"ui_colormap__{vid}", {}) or {})

    def _colour_target(self, cmd, vid, lang):
        """Activate the named property (read if need be), so the Colormap
        card targets it; nothing named: the card's own target. Returns
        (pre, None) or (None, a reply)."""
        pre = self._view_pre(vid)
        if self._named(cmd):
            o, err = self._one_property(cmd, vid, lang)
            if o is None:
                return None, err
            refused = self._read([o], lang)
            if refused is not None:
                self._restore_view(vid, pre)
                return None, refused
            self._activate(vid, o)
        if not self._card(vid).get("array"):
            self._restore_view(vid, pre)
            return None, _reply(False, _t(lang, "Aucune propriété ne colore la vue : nommez-en une, par exemple"
                                                " « passe la porosité en viridis ».",
                                          "No property colours the view: name one, for instance"
                                          " “porosity in viridis”."))
        return pre, None

    def _tables_token(self, intent, vid, pre):
        """Capture the view's colour tables before a colour gesture; the
        callable returned makes the undo token once the gesture is done."""
        tables = self._call("session_view_tables", vid) or []
        label = self._card(vid).get("label") or ""
        # the preset the Colormap card names (cmap_preset writes it; the
        # tables do not carry it, so the card would name the new one)
        preset = (self._get("ui_active_colormap_by_view", {}) or {}).get(vid)
        return lambda: self._token("tables", intent, self._what(intent, label),
                                   vid=vid, tables=tables, pre=pre, preset=preset,
                                   act=self._get(f"active_path__{vid}", ""))

    def _do_colormap(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        preset = (cmd.get("slots") or {}).get("preset")
        if not preset:
            return _reply(False, _t(lang, "Quelle table de couleurs ? Par exemple viridis.",
                                    "Which colour table? For instance viridis."))
        pre, err = self._colour_target(cmd, vid, lang)
        if err is not None:
            return err
        make = self._tables_token("colormap", vid, pre)
        self._call("cmap_preset", preset, vid)
        card = self._card(vid)
        short = preset.split(" (")[0]
        applied = str(card.get("preset") or "")
        if "preset" in card and applied.split(" (")[0].lower() != short.lower():
            # the card names what IS applied: a table this ParaView lacks is
            # said, never announced as done
            return _reply(False, _t(lang, f"La table de couleurs {short} n'existe pas dans ce ParaView.",
                                    f"There is no {short} colour table in this ParaView."))
        return _reply(True, _t(lang, f"Table de couleurs {short} sur {card.get('label', '')}.",
                               f"{short} colour table on {card.get('label', '')}."), undo=make())

    def _do_color_range(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        lo, hi = self._bounds(cmd)
        if lo is None and hi is None:
            return self._no_bounds(cmd, lang)
        pre, err = self._colour_target(cmd, vid, lang)
        if err is not None:
            return err
        # the card's property, now the view's active one: a percent of a
        # fraction is made one there
        lo, hi = self._bounds_on(cmd, self._active_property(vid))
        card = self._card(vid)
        # the data's range — the colours may have been narrowed since — or,
        # on a card that does not give it, the colours' own
        data = ((card.get("data_min"), card.get("data_max"))
                if card.get("data_min") is not None and card.get("data_max") is not None
                else (card.get("min"), card.get("max")))
        # one bound said past the data's other end: no value would be coloured
        past = self._past(lo, hi, data) if lo is None or hi is None else None
        said = self._bound_words(lo, hi, lang)
        # the other bound: the colours' own while it stays on its side of the
        # one said, else the data's end ("above 0.25" on colours from 0.1 to
        # 0.2: from 0.25 to the top of the data, never swapped to 0.2 – 0.25)
        cur_lo, cur_hi = card.get("min"), card.get("max")
        if lo is None:
            lo = cur_lo if isinstance(cur_lo, (int, float)) and hi is not None and cur_lo < hi else data[0]
        if hi is None:
            hi = cur_hi if isinstance(cur_hi, (int, float)) and lo is not None and cur_hi > lo else data[1]
        if past is not None or lo is None or hi is None:
            self._restore_view(vid, pre)
            if past is None:
                return self._no_bounds(cmd, lang)
            label = card.get("label", "")
            return _reply(False, _t(lang, f"Les valeurs de {label} vont de {_num(past[0], lang)} à"
                                          f" {_num(past[1], lang)} : {said}, aucune ne serait colorée. Donnez les"
                                          " deux bornes.",
                                    f"{label} values go from {_num(past[0], lang)} to {_num(past[1], lang)}:"
                                    f" {said}, none would be coloured. Give both bounds."))
        lo, hi = min(float(lo), float(hi)), max(float(lo), float(hi))
        make = self._tables_token("color_range", vid, pre)
        self._call("cmap_range", [lo, hi], vid)
        return _reply(True, _t(lang, f"Couleurs de {card.get('label', '')} fixées de {_num(lo, lang)} à {_num(hi, lang)}.",
                               f"{card.get('label', '')} colours set from {_num(lo, lang)} to {_num(hi, lang)}."),
                      undo=make())

    def _do_rescale(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        pre, err = self._colour_target(cmd, vid, lang)
        if err is not None:
            return err
        make = self._tables_token("rescale", vid, pre)
        self._call("cmap_rescale", "data", vid)
        card = self._card(vid)
        return _reply(True, _t(lang, f"Couleurs de {card.get('label', '')} recalées sur les données"
                                     f" ({_num(card.get('min'), lang)} – {_num(card.get('max'), lang)}).",
                               f"{card.get('label', '')} colours fitted to the data"
                               f" ({_num(card.get('min'), lang)} – {_num(card.get('max'), lang)})."), undo=make())

    def _do_hide_nan(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        on = (cmd.get("slots") or {}).get("on")
        on = True if on is None else bool(on)
        pre, err = self._colour_target(cmd, vid, lang)
        if err is not None:
            return err
        prev = bool(self._card(vid).get("hide_nan"))
        self._call("cmap_hide_nan", on, vid)
        card = self._card(vid)
        if bool(card.get("hide_nan")) != on:
            why = card.get("hide_nan_why") or ""
            # refused: the property read or activated for it goes back too
            self._restore_view(vid, pre)
            return _reply(False, _t(lang, f"Impossible de le faire ici. {why}", f"Cannot do that here. {why}").strip())
        label = card.get("label", "")
        tok = self._token("hide_nan", "hide_nan", self._what("hide_nan", label),
                          vid=vid, prev=prev, pre=pre, act=self._get(f"active_path__{vid}", ""))
        return _reply(True, _t(lang, f"Mailles sans valeur de {label} {'masquées' if on else 'montrées'}.",
                               f"Cells without a {label} value {'hidden' if on else 'shown'}."), undo=tok)

    def _do_flat_colors(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        on = (cmd.get("slots") or {}).get("on")
        on = True if on is None else bool(on)
        prev = bool(self._get(f"ui_flat_colors__{vid}", False))
        self._call("set_flat_colors", vid, on)
        tok = self._token("flat", "flat_colors", self._what("flat_colors", ""), vid=vid, prev=prev)
        return _reply(True, _t(lang, "Couleurs exactes, sans ombrage." if on else "Ombrage rétabli.",
                               "Exact colours, no shading." if on else "Shading back on."), undo=tok)

    # --- the view ---------------------------------------------------------
    def _camera(self, vid):
        pvv = self._mv().get_pv_view(vid) if self._mv() is not None else None
        cam = {}
        if pvv is None:
            return cam
        # the camera an undo puts back, the pivot included
        for prop in CAMERA_PROPERTIES:
            try:
                v = getattr(pvv, prop)
                cam[prop] = list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
            except Exception as exc:
                print(f"[assistant] camera {prop} ({vid}):", exc, flush=True)
        return cam

    def _do_reset_camera(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        if self._get(f"ui_globe_mode__{vid}", False):
            return _reply(False, _t(lang, "La vue est en mode Globe : la caméra s'y règle autrement.",
                                    "The view is a Globe: its camera works differently."))
        cam = self._camera(vid)
        pre = self._view_pre(vid)
        objs = self._objects_of(cmd) if self._named(cmd) else []
        if objs:
            o = objs[0]
            if o.get("rep_path") not in self._loaded():
                return _reply(False, _t(lang, f"{o['title']} n'est pas lu : affichez-le d'abord.",
                                        f"{o['title']} is not read: show it first."))
            self._activate(vid, o)
            self._call("nav_zoom_active", vid)
            text = _t(lang, f"Vue cadrée sur {o['title']}.", f"View framed on {o['title']}.")
        else:
            self._call("nav_reset", vid)
            pre = None
            text = _t(lang, "Vue recadrée.", "Camera reset.")
        tok = self._token("camera", "reset_camera", self._what("reset_camera", ""),
                          vid=vid, cam=cam, pre=pre) if cam else None
        return _reply(True, text, undo=tok)

    def _do_z_scale(self, cmd, lang):
        sl = cmd.get("slots") or {}
        f = sl.get("factor")
        if f is None and sl.get("numbers"):
            f = sl["numbers"][0]
        try:
            f = float(f)
        except (TypeError, ValueError) as exc:
            print("[assistant] z scale, no factor:", exc, flush=True)
            return _reply(False, _t(lang, "De combien ? Par exemple « exagération verticale x 3 ».",
                                    "By how much? For instance “vertical exaggeration x 3”."))
        if not 0.01 <= f <= 100:
            return _reply(False, _t(lang, "L'exagération verticale va de 0,01 à 100.",
                                    "The vertical exaggeration goes from 0.01 to 100."))
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        prev = float(self._get(f"ui_scale_z__{vid}", 1.0) or 1.0)
        self._call("set_zscale", f, vid)
        tok = self._token("zscale", "z_scale", self._what("z_scale", ""), vid=vid, prev=prev)
        return _reply(True, _t(lang, f"Exagération verticale × {_num(f, lang)}.",
                               f"Vertical exaggeration × {_num(f, lang)}."), undo=tok)

    def _closable(self, pid):
        mv = self._mv()
        return bool(pid) and mv is not None and callable(getattr(mv, "remove_panel", None))

    def _do_new_view(self, cmd, lang):
        mv = self._mv()
        if mv is None:
            return _reply(False, _t(lang, "Aucune vue ne peut être ouverte ici.", "No view can be opened here."))
        before = set(mv.view_ids() or [])
        self._call("open_render_view", None)
        new = [v for v in (mv.view_ids() or []) if v not in before]
        if not new:
            return _reply(False, _t(lang, "La vue n'a pas pu s'ouvrir.", "The view could not be opened."))
        tok = (self._token("close", "new_view", self._what("new_view", ""), pid=new[0])
               if self._closable(new[0]) else None)
        return _reply(True, _t(lang, "Nouvelle vue 3D ouverte.", "New 3D view opened."), undo=tok)

    # --- panels -----------------------------------------------------------
    def _panels(self, panel):
        """The open panels a word of `_PANELS` names."""
        mv = self._mv()
        kind = _PANEL_KIND.get(panel, panel)
        try:
            return list(mv.panel_ids_of_kind(kind) or []) if mv is not None else []
        except Exception as exc:
            print(f"[assistant] panels of kind {kind}:", exc, flush=True)
            return []

    def _every(self, cmd):
        """The dimensions the sentence asks the statistics of, one row per
        value ("les stats de tous les pas de temps"): 'ts' for every time
        step, 'real' for every realization."""
        text = " " + normalize(cmd.get("text") or "") + " "
        return [dim for dim, words in (("ts", _EVERY_STEP), ("real", _EVERY_REAL))
                if any(" " + w + " " in text for w in words)]

    def _pin_every(self, path, every):
        """One pinned row per value of the dimensions `every`, from the
        property's own row, as its menu does; how many of its rows are pinned
        then."""
        def rows():
            return [it for it in self._get("ui_compare_items", []) if it.get("path") == path]
        own = next((it for it in rows() if not it.get("pinned")), None) or next(iter(rows()), None)
        if own is not None:
            for dim in every:
                self._call("compare_set", "pin_all", [own.get("uid"), dim])
        self._flush()
        return sum(1 for it in rows() if it.get("pinned"))

    def _do_open_panel(self, cmd, lang):
        panel = (cmd.get("slots") or {}).get("panel")
        if panel not in _PANELS:
            return _reply(False, _t(lang, "Quel panneau ?", "Which panel?"))
        if self._mv() is None:
            return _reply(False, _t(lang, "Aucun panneau ne peut s'ouvrir ici.", "No panel can be opened here."))
        vid = self._vid()
        before = set(self._panels(panel))
        pre = self._view_pre(vid) if vid else None
        o = None
        if self._need(cmd) == "property":
            o, err = self._one_property(cmd, vid, lang)
            if o is None:
                return err
        index = self._index()
        objs = self._objects_of(cmd) if self._named(cmd) else []
        every, rows = [], 0
        if _PANEL_KIND.get(panel, panel) == "compare":
            every = self._every(cmd) if o is not None else []
            if every:
                # the steps and the realizations of a property are known once
                # it is read
                refused = self._read_hidden(o, lang)
                if refused is not None:
                    return refused
            if o is not None:
                # what is not read is read, born hidden, and the view opens
                self._call("add_to_stats", o["path"])
            else:
                self._call("open_compare")
            if every:
                rows = self._pin_every(o["path"], every)
        elif panel == "welllog":
            wells = []
            for t in objs:
                w = t["path"] if t.get("type") == "Wellbore" else t.get("parent")
                if (index.get(w) or {}).get("type") == "Wellbore" and w not in wells:
                    wells.append(w)
            self._call("open_welllog")
            if wells:
                pid = (self._panels("welllog") or [None])[0]
                cur = list(self._get(f"welllog_tree_selected__{pid}", []))
                self._call("welllog_tree_wells", pid, cur + [w for w in wells if w not in cur])
            o = index.get(wells[0]) if wells else None
        elif panel == "reconcile":
            self._call("open_reconcile")
            if objs:
                pid = (self._panels("reconcile") or [None])[0]
                cur = list(self._get(f"reconcile_tree_selected__{pid}", []))
                self._call("reconcile_tree_paths", pid, cur + [t["path"] for t in objs if t["path"] not in cur])
                o = objs[0]
        elif panel == "xml":
            o = objs[0] if objs else None
            if o is not None and vid:
                self.state[f"active_path__{vid}"] = o["path"]
                self._flush()
                self._call("xml_open_active", vid)
            elif o is not None:
                from fespp_on_trame.engine import row_object
                uuid, note = row_object.resolve(o["path"].rsplit("/", 1)[-1], o.get("title", ""))
                if not uuid:
                    return _reply(False, _t(lang, f"{o['title']} n'a pas d'objet XML propre.",
                                            f"{o['title']} has no XML object of its own."))
                self._call("xml_open", uuid, o.get("title") or uuid[:8], note)
            elif vid:
                self._call("xml_open_active", vid)
            else:
                return self._no_view(lang)
        elif panel == "stratigraphy":
            self._call("open_stratigraphy")
        elif panel == "calculator":
            self._call("open_calculator", o["path"] if o is not None else None)
        elif panel == "health":
            o = objs[0] if objs else None
            if o is not None:
                self._call("health_focus", o["path"])
            else:
                self._call("open_health")
        now = self._panels(panel)
        if not now:
            return _reply(False, _t(lang, "Le panneau n'a pas pu s'ouvrir.", "The panel could not be opened."))
        name = _t(lang, *_PANELS[panel])
        on = self._name(o, lang, index) if o is not None else ""
        new = [p for p in now if p not in before]
        tok = None
        if new and self._closable(new[-1]):
            restore = pre if panel == "xml" and o is not None else None
            tok = self._token("close", "open_panel", self._what("open_panel", name),
                              pid=new[-1], vid=vid, pre=restore)
        if on:
            text = _t(lang, f"Panneau « {name} » ouvert sur {on}.", f"{name} panel opened on {on}.")
        else:
            text = _t(lang, f"Panneau « {name} » ouvert.", f"{name} panel opened.")
        if every and rows:
            text += _t(lang, f" {rows} ligne(s) épinglée(s), une par "
                             f"{'pas de temps' if every == ['ts'] else 'réalisation' if every == ['real'] else 'valeur'}.",
                       f" {rows} row(s) pinned, one per "
                       f"{'time step' if every == ['ts'] else 'realization' if every == ['real'] else 'value'}.")
        elif every:
            text += _t(lang, f" {on or 'Cette propriété'} n'a qu'un seul "
                             f"{'pas de temps' if every == ['ts'] else 'réalisation'} : rien à épingler de plus.",
                       f" {on or 'This property'} has a single "
                       f"{'time step' if every == ['ts'] else 'realization'}: nothing more to pin.")
        return _reply(True, text, undo=tok)

    def _do_close_panel(self, cmd, lang):
        """An analysis panel of the kind named: the active one when it is of
        that kind, else the last opened. A 3D view is never closed here."""
        panel = (cmd.get("slots") or {}).get("panel")
        if panel not in _PANELS and self._view_said(cmd):
            return _reply(False, _t(lang, "Je ne ferme pas une vue 3D : fermez son onglet, par la croix de son titre.",
                                    "I do not close a 3D view: close its tab, with the cross on its title."))
        if panel not in _PANELS:
            return _reply(False, _t(lang, "Quel panneau ?", "Which panel?"))
        mv = self._mv()
        if mv is None or not callable(getattr(mv, "remove_panel", None)):
            return _reply(False, _t(lang, "Aucun panneau ne peut être fermé ici.", "No panel can be closed here."))
        name = _t(lang, *_PANELS[panel])
        pids = self._panels(panel)
        if not pids:
            return _reply(False, _t(lang, f"Aucun panneau « {name} » n'est ouvert.", f"No {name} panel is open."))
        active = self._get("fespp_active_panel_id", "")
        pid = active if active in pids else pids[-1]
        kind = _PANEL_KIND.get(panel, panel)
        snap = self._panel_snapshot(kind, pid)
        mv.remove_panel(pid)
        tok = self._token("reopen", "close_panel", self._what("close_panel", name), panel=kind, snap=snap)
        return _reply(True, _t(lang, f"Panneau « {name} » fermé.", f"{name} panel closed."), undo=tok)

    def _panel_snapshot(self, kind, pid):
        """What a panel shows that the undo can open it on again: the wells
        or properties ticked in its tree, the object an XML explorer shows."""
        if kind in ("welllog", "reconcile", "compare"):
            return {"paths": list(self._get(f"{kind}_tree_selected__{pid}", []) or [])}
        if kind == "xml":
            tabs = list(self._get(f"xml_tabs__{pid}", []) or [])
            idx = int(self._get(f"xml_tab__{pid}", 0) or 0)
            return {"tab": tabs[min(max(idx, 0), len(tabs) - 1)] if tabs else None, "tabs": len(tabs)}
        return {}

    def _do_camera_view(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        d = (cmd.get("slots") or {}).get("direction")
        if d in ("in", "out"):
            return self._do_zoom(cmd, lang)
        if d not in _AXIS_OF:
            return _reply(False, self._slot_question("direction", cmd, lang))
        if self._globe(vid):
            return _reply(False, _t(lang, "La vue est en mode Globe : la caméra s'y règle autrement.",
                                    "The view is a Globe: its camera works differently."))
        cam = self._camera(vid)
        self._call("nav_axis", vid, _AXIS_OF[d])
        words = _t(lang, *_DIRECTION_WORDS[d])
        tok = self._token("camera", "camera_view", self._what("camera_view", words), vid=vid, cam=cam,
                          pre=None) if cam else None
        return _reply(True, _t(lang, f"Caméra orientée : {words}.", f"Camera: {words}."), undo=tok)

    def _do_zoom(self, cmd, lang):
        """One step of the title bar's zoom — offered on a Globe too: it reads
        no bounds, it slides the eye along where it looks."""
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        out = (cmd.get("slots") or {}).get("direction") == "out"
        cam = self._camera(vid)
        self._call("nav_zoom_step", vid, _ZOOM_OUT if out else _ZOOM_IN)
        tok = self._token("camera", "zoom", self._what("zoom", ""), vid=vid, cam=cam, pre=None) if cam else None
        return _reply(True, _t(lang, "Zoom arrière." if out else "Zoom avant.",
                               "Zoomed out." if out else "Zoomed in."), undo=tok)

    def _timereal(self, vid):
        """The Time & Realizations card of the view: {"time": {index, nb,
        label, playing}, "specs": [{array_path, title, available_indices,
        current_idx}]}."""
        return dict(self._get(f"ui_timereal__{vid}", {}) or {})

    def _time_steps(self, vid):
        """The number of time steps when a property that varies in time
        colours the view, else 0."""
        nb = int((self._timereal(vid).get("time") or {}).get("nb") or 0)
        index = self._index()
        shown = (any((index.get(e) or {}).get("type") in _TIMED for e in self._get(f"visible_paths__{vid}", []))
                 or bool(self._card(vid).get("is_ts")))
        return nb if shown and nb > 1 else 0

    @staticmethod
    def _no_time(lang):
        return _reply(False, _t(lang, "Aucune propriété de cette vue ne varie dans le temps.",
                                "No property of this view varies in time."))

    def _time_labels(self):
        """The label of each time step, as the Time & Realizations card
        writes them (a date when the data gives one)."""
        try:
            from paraview import simple as pvsimple
            from fespp_on_trame.engine import time_realization
            values = [float(t) for t in (pvsimple.GetTimeKeeper().TimestepValues or [])]
            return [time_realization.label_for_time_value(self._tree(), v) for v in values]
        except Exception as exc:
            print("[assistant] time labels:", exc, flush=True)
            return []

    def _time_index_of(self, step, nb):
        """The index of the time step said by its number (counted from 1, as
        the card shows it) or by its label (a date, a year), or None."""
        s = str(step).strip()
        if _NUMBER.match(s) and float(s).is_integer() and 1 <= float(s) <= nb:
            return int(float(s)) - 1
        key = normalize(s)
        if not key:
            return None
        said = re.compile(rf"(?<![0-9a-z]){re.escape(key)}(?![0-9a-z])")
        return next((i for i, lb in enumerate(self._time_labels()[:nb]) if said.search(normalize(lb))), None)

    @staticmethod
    def _step_label(t):
        """" (2015-06-01)" for a step the data names, "" otherwise (the card's
        fallback label is the time value itself)."""
        label = str((t or {}).get("label") or "")
        return f" ({label})" if label and not label.startswith("time") else ""

    def _do_time_step(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        nb = self._time_steps(vid)
        if not nb:
            return self._no_time(lang)
        step = (cmd.get("slots") or {}).get("step")
        if step in (None, ""):
            return _reply(False, self._slot_question("step", cmd, lang))
        t = self._timereal(vid).get("time") or {}
        cur = int(t.get("index") or 0)
        if step in ("next", "previous"):
            idx = cur + (1 if step == "next" else -1)
            if not 0 <= idx < nb:
                # the ends stop the walk: a wrap would jump across the series
                return _reply(True, _t(lang, f"C'est déjà le {'dernier' if step == 'next' else 'premier'} pas de"
                                             f" temps ({cur + 1} / {nb}).",
                                       f"This is already the {'last' if step == 'next' else 'first'} time step"
                                       f" ({cur + 1} / {nb})."))
        elif step in ("first", "last"):
            idx = 0 if step == "first" else nb - 1
        else:
            idx = self._time_index_of(step, nb)
            if idx is None:
                return _reply(False, _t(lang, f"Je ne trouve pas le pas de temps « {step} » : la série en compte {nb}"
                                              f" (de 1 à {nb}).",
                                        f"I cannot find the time step “{step}”: the series has {nb} (from 1 to {nb})."))
        if idx == cur:
            return _reply(True, _t(lang, f"La vue est déjà au pas de temps {cur + 1} / {nb}{self._step_label(t)}.",
                                   f"The view is already at time step {cur + 1} / {nb}{self._step_label(t)}."))
        self._call("time_index", idx, vid)
        lab = self._step_label(self._timereal(vid).get("time"))
        tok = self._token("time", "time_step", self._what("time_step", f"{idx + 1} / {nb}"), vid=vid, prev=cur)
        return _reply(True, _t(lang, f"Pas de temps {idx + 1} / {nb}{lab}.", f"Time step {idx + 1} / {nb}{lab}."),
                      undo=tok)

    def _do_time_play(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        on = (cmd.get("slots") or {}).get("on")
        on = True if on is None else bool(on)
        t = self._timereal(vid).get("time") or {}
        prev = bool(t.get("playing"))
        if on and not self._time_steps(vid):
            return self._no_time(lang)
        if prev == on:
            return _reply(True, _t(lang, "L'animation est déjà lancée." if on else "L'animation n'est pas lancée.",
                                   "The animation is already playing." if on else "The animation is not playing."))
        self._call("time_play", on, vid)
        tok = self._token("play", "time_play", self._what("time_play", ""), vid=vid, prev=prev)
        if on:
            return _reply(True, _t(lang, "Animation des pas de temps lancée.", "Time steps playing."), undo=tok)
        t = self._timereal(vid).get("time") or t
        at = f"{int(t.get('index') or 0) + 1} / {int(t.get('nb') or 0)}"
        return _reply(True, _t(lang, f"Animation arrêtée au pas de temps {at}.", f"Animation stopped at time step {at}."),
                      undo=tok)

    def _do_realization(self, cmd, lang):
        """Another realization of the property named, else of the one
        property of several realizations colouring the view. A realization
        is named by its own index (the card's list), next / previous move
        among the ones available."""
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        specs = list(self._timereal(vid).get("specs") or [])
        if self._named(cmd):
            o, err = self._one_property(cmd, vid, lang)
            if o is None:
                return err
            spec = next((s for s in specs if s.get("array_path") == o["path"]), None)
            if spec is None:
                name = self._name(o, lang)
                if o.get("type") not in _MULTI:
                    return _reply(False, _t(lang, f"{name} n'a qu'une réalisation.", f"{name} has one realization only."))
                return _reply(False, _t(lang, f"{name} ne colore pas cette vue : affichez-la d'abord.",
                                        f"{name} does not colour this view: show it first."))
        elif not specs:
            return _reply(False, _t(lang, "Aucune propriété à plusieurs réalisations ne colore cette vue.",
                                    "No property with several realizations colours this view."))
        elif len(specs) > 1:
            titles = ", ".join(s.get("title") or "" for s in specs)
            return _reply(False, _t(lang, f"Plusieurs propriétés à plusieurs réalisations colorent la vue : {titles}."
                                          f" Laquelle ? Par exemple « réalisation 2 de {specs[0].get('title')} ».",
                                    f"Several properties with realizations colour the view: {titles}. Which one?"
                                    f" For instance “realization 2 of {specs[0].get('title')}”."))
        else:
            spec = specs[0]
        title = spec.get("title") or ""
        avail = [int(i) for i in spec.get("available_indices") or []]
        if not avail:
            return _reply(False, _t(lang, f"{title} n'a aucune réalisation lisible.", f"{title} has no realization to read."))
        cur = int(spec["current_idx"]) if spec.get("current_idx") is not None else avail[0]
        listed = ", ".join(str(i) for i in avail)
        step = (cmd.get("slots") or {}).get("step")
        if step in ("next", "previous"):
            pos = (avail.index(cur) if cur in avail else 0) + (1 if step == "next" else -1)
            if not 0 <= pos < len(avail):
                return _reply(True, _t(lang, f"C'est déjà la {'dernière' if step == 'next' else 'première'} réalisation"
                                             f" de {title} ({cur}).",
                                       f"This is already the {'last' if step == 'next' else 'first'} realization of"
                                       f" {title} ({cur})."))
            idx = avail[pos]
        elif step in ("first", "last"):
            idx = avail[0] if step == "first" else avail[-1]
        else:
            s = str(step if step is not None else "").strip()
            idx = int(float(s)) if _NUMBER.match(s) and float(s).is_integer() else None
            if idx not in avail:
                return _reply(False, _t(lang, f"Réalisations de {title} : {listed}. Laquelle ?",
                                        f"Realizations of {title}: {listed}. Which one?"))
        if idx == cur:
            return _reply(True, _t(lang, f"{title} montre déjà la réalisation {idx}.",
                                   f"{title} already shows realization {idx}."))
        self._call("set_realization", [spec["array_path"], idx], vid)
        tok = self._token("realization", "realization", self._what("realization", title), vid=vid,
                          path=spec["array_path"], prev=cur)
        return _reply(True, _t(lang, f"{title} : réalisation {idx}.", f"{title}: realization {idx}."), undo=tok)

    def _do_rep_style(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        style = (cmd.get("slots") or {}).get("style")
        if style not in _STYLE_WORDS:
            return _reply(False, self._slot_question("style", cmd, lang))
        prev = self._get(f"ui_rep_style__{vid}", "Surface") or "Surface"
        words = _t(lang, *_STYLE_WORDS[style])
        if prev == style:
            return _reply(True, _t(lang, f"La vue est déjà dessinée en {words}.", f"The view is already drawn as {words}."))
        self._call("set_rep_style", vid, style)
        tok = self._token("style", "rep_style", self._what("rep_style", words), vid=vid, prev=prev)
        return _reply(True, _t(lang, f"Vue dessinée en {words}.", f"View drawn as {words}."), undo=tok)

    def _do_color_scale(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        scale = (cmd.get("slots") or {}).get("scale")
        if scale not in ("log", "linear"):
            return _reply(False, self._slot_question("scale", cmd, lang))
        pre, err = self._colour_target(cmd, vid, lang)
        if err is not None:
            return err
        card = self._card(vid)
        label = card.get("label", "")
        words = _t(lang, "logarithmique" if scale == "log" else "linéaire", "logarithmic" if scale == "log" else "linear")
        if card.get("scale", "log" if card.get("log") else "linear") == scale:
            if self._named(cmd):
                self._restore_view(vid, pre)
            return _reply(True, _t(lang, f"Les couleurs de {label} sont déjà en échelle {words}.",
                                   f"The {label} colours are already on a {words} scale."))
        make = self._tables_token("color_scale", vid, pre)
        self._call("cmap_scale", scale, vid)
        card = self._card(vid)
        if "log" in card and bool(card["log"]) != (scale == "log"):
            self._restore_view(vid, pre)
            return _reply(False, _t(lang, f"L'échelle des couleurs de {label} n'a pas pu changer.",
                                    f"The {label} colour scale could not be changed."))
        note = ""
        low = card.get("data_min")
        if scale == "log" and isinstance(low, (int, float)) and low <= 0:
            # ParaView cannot place a value at or below zero on a log scale:
            # boot moves the table's start above zero, those values clamp
            note = _t(lang, f" Ses valeurs descendent à {_num(low, lang)} : une échelle logarithmique ne place pas les"
                            " valeurs nulles ou négatives, elles prennent la couleur du bas de l'échelle (qui"
                            f" commence à {_num(card.get('min'), lang)}).",
                      f" Its values go down to {_num(low, lang)}: a logarithmic scale cannot place zero or negative"
                      " values, they take the colour of the bottom of the scale (which starts at"
                      f" {_num(card.get('min'), lang)}).")
        return _reply(True, _t(lang, f"Couleurs de {label} en échelle {words}.", f"{label} colours on a {words} scale.")
                      + note, undo=make())

    def _do_color_bar(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        on = (cmd.get("slots") or {}).get("on")
        on = True if on is None else bool(on)
        pre, err = self._colour_target(cmd, vid, lang)
        if err is not None:
            return err
        card = self._card(vid)
        label = card.get("label", "")
        prev = bool(card.get("bar", True))
        done_fr, done_en = ("affichée", "shown") if on else ("masquée", "hidden")
        if prev == on:
            if self._named(cmd):
                self._restore_view(vid, pre)
            return _reply(True, _t(lang, f"La barre de couleurs de {label} est déjà {done_fr}.",
                                   f"The {label} colour bar is already {done_en}."))
        self._call("cmap_bar", on, vid)
        tok = self._token("bar", "color_bar", self._what("color_bar", label), vid=vid, prev=prev, pre=pre,
                          act=self._get(f"active_path__{vid}", ""))
        return _reply(True, _t(lang, f"Barre de couleurs de {label} {done_fr}.", f"{label} colour bar {done_en}."),
                      undo=tok)

    def _open_tools(self, vid):
        return list((self._get("ui_open_tools_by_view", {}) or {}).get(vid) or [])

    def _do_open_tool(self, cmd, lang):
        """A tool card of the view, opened only when it is closed and the
        view offers it (its toolbar: view_tools_<vid>)."""
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        key = (cmd.get("slots") or {}).get("tool")
        if key == "globe":
            if not self._get("ui_globe_ok", True):
                why = self._get("ui_globe_why", "")
                return _reply(False, _t(lang, f"Le Globe n'est pas proposé : {why}.",
                                        f"The Globe is not offered: {why}."))
            self._call("open_globe")
            return _reply(True, _t(lang, "Vue « Globe » ouverte.", "Globe view opened."))
        if key == "attributes":
            self._call("open_values")
            return _reply(True, _t(lang, "Vue « Values » ouverte.", "Values view opened."))
        if key not in _TOOL_TITLES:
            return _reply(False, self._slot_question("tool", cmd, lang))
        name = _TOOL_TITLES[key]
        if key in self._open_tools(vid):
            return _reply(True, _t(lang, f"La carte « {name} » est déjà ouverte.", f"The {name} card is already open."))
        offered = [t.get("key") for t in self._get(f"view_tools_{vid}", []) or ()
                   if isinstance(t, dict) and not t.get("disabled")]
        if key not in offered:
            if not offered:
                why = _t(lang, "importez des données d'abord, les cartes agissent sur elles",
                         "import data first, the cards act on it")
            elif self._globe(vid) and key in _TOOLS_RENDER_ONLY:
                why = _t(lang, "la vue est en mode Globe", "the view is a Globe")
            else:
                why = _t(lang, *_TOOL_NEEDS.get(key, ("elle n'y sert à rien pour l'instant",
                                                      "it has nothing to act on for now")))
            return _reply(False, _t(lang, f"La carte « {name} » n'est pas proposée dans cette vue : {why}.",
                                    f"The {name} card is not offered in this view: {why}."))
        self._call("toggle_tool", key, vid)
        tok = self._token("tool", "open_tool", self._what("open_tool", name), vid=vid, key=key)
        return _reply(True, _t(lang, f"Carte « {name} » ouverte.", f"{name} card opened."), undo=tok)

    def _shown_extracts(self, vid):
        """The selection extracts this view draws: its visible session rows
        of kind "extract" (a formula is an eye, in the eye set)."""
        return [r.get("path") for r in (self._get(f"ui_session_rows__{vid}", []) or [])
                if r.get("kind") == "extract" and r.get("visible") and r.get("path")]

    def _do_hide_all(self, cmd, lang):
        vid = self._vid()
        if not vid:
            return self._no_view(lang)
        pre = self._view_pre(vid)
        # the selection extracts hide too: they are on screen, and "already
        # empty" said over them was false (04-verification D33)
        rows = self._shown_extracts(vid)
        if not pre["eyes"] and not rows:
            return _reply(True, _t(lang, "La vue est déjà vide.", "The view is already empty."))
        self._set_eyes(vid, [])
        for path in rows:
            self._call("session_row_eye", {"path": path}, vid)
        self._flush()
        tok = self._token("view", "hide_all", self._what("hide_all", ""), vid=vid, pre=pre,
                          rows=rows)
        return _reply(True, _t(lang, "Vue vidée : tout est masqué, rien n'est déchargé.",
                               "View cleared: everything hidden, nothing unloaded."), undo=tok)

    # --- undo -------------------------------------------------------------
    def _do_undo(self, cmd, lang):
        """An undo said rather than clicked: the last gesture this adapter
        carried out and has not undone yet."""
        live = [t for t in self._issued if t["id"] not in self._undone]
        if not live:
            return _reply(True, _t(lang, "Rien à annuler.", "Nothing to undo."))
        r = self.undo(live[-1], lang)
        return dict(r, undo=None)

    def undo(self, token, lang):
        """Apply `token`. An `_undo_<op>` returns None when all is put back,
        or a reply: ok with a note (undone, said differently), or not ok —
        the token then stays live, so a later spoken undo can apply it."""
        lang = _lang(lang)
        if not isinstance(token, dict) or not token.get("op"):
            return _reply(False, _t(lang, "Rien à annuler.", "Nothing to undo."))
        if token.get("id") in self._undone:
            return _reply(True, _t(lang, "C'est déjà annulé.", "That is already undone."))
        fn = getattr(self, f"_undo_{token['op']}", None)
        if fn is None:
            return _reply(False, _t(lang, "Ce geste ne s'annule pas.", "That gesture cannot be undone."))
        try:
            said = fn(token, lang)
        except _Unavailable as exc:
            print("[assistant] undo, missing controller:", exc, flush=True)
            return _reply(False, _t(lang, f"Annulation impossible ici ({exc}).", f"Cannot undo here ({exc})."))
        if said is not None and not said.get("ok"):
            return said
        self._undone.add(token.get("id"))
        self._issued = [t for t in self._issued if t.get("id") != token.get("id")]
        what = token.get("what") or ("", "")
        text = _t(lang, f"Annulé : {what[0]}.", f"Undone: {what[1]}.")
        return _reply(True, text + (" " + said["text"] if said and said.get("text") else ""))

    def _live(self, vid):
        return bool(vid) and self._mv() is not None and vid in (self._mv().view_ids() or [])

    @staticmethod
    def _globe_dropped(lang, what):
        """A view flipped to Globe since the gesture: the flip released its
        isolates, the filter or the slice went with them."""
        return _reply(True, _t(lang, f"(La vue est passée en Globe : {what[0]} était déjà enlevé{what[2]}.)",
                               f"(The view became a Globe: {what[1]} was already gone.)"))

    def _undo_view(self, tok, lang):
        vid = tok["vid"]
        if self._live(vid):
            self._restore_view(vid, tok["pre"])
            # the extracts "hide all" put away come back, those still there
            shown = set(self._shown_extracts(vid))
            there = {r.get("path") for r in (self._get(f"ui_session_rows__{vid}", []) or [])}
            for path in tok.get("rows") or ():
                if path in there and path not in shown:
                    self._call("session_row_eye", {"path": path}, vid)

    def _undo_chain(self, tok, lang):
        """A filter gesture undone: what the gesture changed is taken back
        and only that — the entries it added go, the ones it took off come
        back under their parent, the ranges, eyes and parents it changed are
        put back — while every later change (a filter added in the
        Thresholds card, a range moved, an eye closed) stays. When a later
        change touched an entry of the gesture, the reply says what was
        undone and what was left (`_merge_undo`). On a view flipped to Globe
        since, the flip released the filters: with nothing to put back, the
        gesture's filter went with them; filters to put back cannot be built
        there — the token stays live for an undo once the view is 3D again."""
        vid = tok["vid"]
        if not self._live(vid):
            return None
        grids = tok.get("grids") or ()
        if self._globe(vid):
            if any(g.get("chain") for g in grids):
                return _reply(False, _t(lang, "La vue est en mode Globe : les filtres ne peuvent pas y être"
                                              " remis. Repassez-la en vue 3D, puis dites « annule ».",
                                        "The view is a Globe: the filters cannot be put back there. Switch it"
                                        " back to 3D, then say “undo”."))
            if tok.get("pre"):
                self._restore_view(vid, tok["pre"])
            return self._globe_dropped(lang, ("le filtre", "the filter", ""))
        notes = []
        for g in grids:
            if g.get("after") is None:
                # a token without the chain the gesture left: the chain before it
                self._restore_chain(vid, g["rep"], g.get("chain") or (), tok.get("by_tab"))
                continue
            target, said = self._merge_undo(self._now_named(vid, g["rep"], g.get("chain") or ()),
                                            self._now_named(vid, g["rep"], g["after"]),
                                            self._iso_chain(vid, g["rep"]), self._titles_on(vid, g["rep"]), lang)
            # the Reservoir tab as it is now: the view is put back below
            self._restore_chain(vid, g["rep"], target, dict(self._get(f"active_by_tab__{vid}", {})))
            notes += [n for n in said if n not in notes]
        if tok.get("pre"):
            if tok.get("post"):
                self._restore_view_merged(vid, tok["pre"], tok["post"])
            else:
                self._restore_view(vid, tok["pre"])
        return _reply(True, " ".join(notes)) if notes else None

    def _restore_view_merged(self, vid, pre, post):
        """The eyes and active nodes a gesture changed put back, the ones
        changed since left as they are: the eyes it opened closed, the ones
        it closed opened, the active node back when it is still the one the
        gesture made active."""
        eyes = list(self._get(f"visible_paths__{vid}", []))
        before, after = list(pre.get("eyes") or ()), list(post.get("eyes") or ())
        opened = [e for e in after if e not in before]
        closed = [e for e in before if e not in after]
        eyes = [e for e in eyes if e not in opened] + [e for e in closed if e not in eyes]
        if self._get(f"active_path__{vid}", "") == (post.get("active") or ""):
            self.state[f"active_path__{vid}"] = pre.get("active") or ""
        if dict(self._get(f"active_by_tab__{vid}", {})) == dict(post.get("by_tab") or {}):
            self.state[f"active_by_tab__{vid}"] = dict(pre.get("by_tab") or {})
        self._set_eyes(vid, eyes)
        self._flush()

    def _merge_undo(self, before, after, now, titles, lang):
        """The chain an undo makes, from the chain before the gesture, the one
        it left (both named as now, `_now_named`) and the one now: (the
        entries, as `_restore_chain` takes them; what the reply says of the
        later changes that touched an entry of the gesture). An entry is the
        same across the three when its name and its array are.

          added by the gesture   taken off — the entries put under it since
                                 move up to its parent, as IjkGrid does —;
                                 changed since, the reader's: left
          taken off by it        put back under its parent (its nearest
                                 ancestor still there) — below the filters
                                 put at that level since, never beside
                                 them in a union that never was
          kept by it             each of its range, eye and parent as before
                                 the gesture where it is still as the
                                 gesture left it, else as changed since
          made since             as it is"""
        def same(x, y):
            return x is not None and y is not None and x.get("array") == y.get("array")
        title = lambda e: titles.get(e.get("array"), e.get("array") or e.get("name"))  # noqa: E731
        state = lambda x: (x.get("low"), x.get("high"), x.get("visible", True) is not False)  # noqa: E731
        B = {e.get("name"): dict(e) for e in before}
        A = {e.get("name"): dict(e) for e in after}
        C = {e.get("name"): dict(e) for e in now}
        added = {n for n, a in A.items() if not same(B.get(n), a)}
        kept = set(A) - added
        removed = [n for n, b in B.items() if not same(b, A.get(n))]
        match = {n: n for n, a in A.items() if same(a, C.get(n))}
        owner = {c: a for a, c in match.items()}
        notes, target, up, from_before = [], {}, {}, {}
        for n, c in C.items():
            an = owner.get(n)
            if an in added and state(c) == state(A[an]):
                # the gesture's own entry goes; what was put under it since moves up
                up[n] = c.get("parent_name")
                continue
            if an in added:
                # changed since (or made again by hand under its name): the
                # reader's own now, left as it is
                notes.append(_t(lang, f"Le filtre sur {title(c)}, changé depuis, est laissé tel quel.",
                                f"The filter on {title(c)}, changed since, is left as it is."))
            e = dict(c)
            if an in kept:
                b, a = B[an], A[an]
                for keys in (("low", "high"), ("visible",)):
                    then, made, was = ([x.get(k, True if k == "visible" else None) for k in keys]
                                       for x in (b, a, c))
                    if was == made:
                        e.update(zip(keys, then))
                    elif then != made:
                        notes.append(_t(lang, f"Le filtre sur {title(c)}, changé depuis, est laissé tel quel.",
                                        f"The filter on {title(c)}, changed since, is left as it is."))
                if c.get("parent_name") == (match.get(a["parent_name"]) if a.get("parent_name") else None):
                    # its parent as the gesture left it: the one before the gesture
                    from_before[n] = b.get("parent_name")
            target[n] = e
        for an in added - set(match):
            notes.append(_t(lang, f"Le filtre sur {title(A[an])} était déjà enlevé.",
                            f"The filter on {title(A[an])} was already removed."))
        for an in kept - set(match):
            if state(B[an]) != state(A[an]):
                notes.append(_t(lang, f"Le filtre sur {title(A[an])}, enlevé depuis, n'est pas remis.",
                                f"The filter on {title(A[an])}, removed since, is not put back."))
        # the entries that were not there before the gesture and stay
        later = {n for n in target if owner.get(n) is None or owner.get(n) in added}
        # what was put since under an entry that goes moves up to its parent
        for n, e in target.items():
            p, seen = e.get("parent_name"), set()
            while p in up and p not in seen and n not in from_before:
                seen.add(p)
                p = up[p]
            if p != e.get("parent_name"):
                e["parent_name"] = p
                if owner.get(n) is None:
                    notes.append(_t(lang, f"Le filtre sur {title(e)}, ajouté depuis, reste.",
                                    f"The filter on {title(e)}, added since, stays."))
        # the entries the gesture took off come back, a name taken since made unique
        key = {n: (n if n not in target and n not in up else f"{n}{_UNDONE}") for n in removed}

        def now_named(p):
            """A parent the chain before the gesture names, as the target
            names it: an entry put back, one still there, else its parent."""
            seen = set()
            while p is not None and p not in seen:
                if p in key:
                    return key[p]
                if p in kept and match.get(p) in target:
                    return match[p]
                seen.add(p)
                p = (B.get(p) or {}).get("parent_name")
            return None
        for n, p in from_before.items():
            target[n]["parent_name"] = now_named(p)
        for n in removed:
            target[key[n]] = dict(B[n], name=key[n], parent_name=now_named(B[n].get("parent_name")))
        restored = set(key.values())
        # what hangs from an entry put back moves with it: never a parent for it
        held = set(restored)
        for x in self._parents_first(list(target.values())):
            if x.get("parent_name") in held:
                held.add(x.get("name"))
        for n in removed:
            e = target[key[n]]
            p = e.get("parent_name")
            if p in restored:
                continue
            # a level that holds filters made since: under them, not beside
            if any(x.get("parent_name") == p and x.get("name") in later for x in target.values()):
                tip = self._tip(self._subtree([x for x in target.values() if x.get("name") not in held], p))
                if tip is not None:
                    e["parent_name"] = tip
        return list(target.values()), list(dict.fromkeys(notes))

    @staticmethod
    def _subtree(chain, root):
        """The entries of `chain` under `root` (every entry for None)."""
        if root is None:
            return list(chain)
        by_parent = {}
        for e in chain:
            by_parent.setdefault(e.get("parent_name"), []).append(e)
        out, todo, seen = [], [root], {root}
        while todo:
            for e in by_parent.get(todo.pop(), ()):
                if e.get("name") not in seen:
                    seen.add(e.get("name"))
                    out.append(e)
                    todo.append(e.get("name"))
        return out

    @staticmethod
    def _parents_first(chain):
        """The chain's entries, each after its parent (an entry whose parent
        is not in the chain counts as a root)."""
        names = {e.get("name") for e in chain}
        out, placed, pending = [], set(), list(chain)
        while pending:
            ready = [e for e in pending if not e.get("parent_name") or e.get("parent_name") not in names
                     or e.get("parent_name") in placed]
            if not ready:
                print("[assistant] a threshold chain whose parents loop:", [e.get("name") for e in pending],
                      flush=True)
                ready = pending
            for e in ready:
                out.append(e)
                placed.add(e.get("name"))
            pending = [e for e in pending if e.get("name") not in placed]
        return out

    def _restore_chain(self, vid, rep, snapshot, by_tab):
        """The grid's threshold chain made `snapshot` again, whatever was
        done to it since. The entries still as they were (same name, parent
        and property, their parent kept too) stay, their range and eye put
        back; every other one is taken off, children first; the missing
        ones are added back parents first, their names regenerated (as the
        session restore does) — an entry whose parent could not be added
        goes under its nearest ancestor that was. The name each one added
        back gets is kept (`_aliases`): the undo tokens that hold it under
        the name of the snapshot still find it."""
        self.state[f"active_by_tab__{vid}"] = dict(by_tab or {}, reservoir=rep)
        want = self._parents_first([dict(e) for e in snapshot])
        by_name = {e.get("name"): e for e in want}
        cur = self._parents_first(self._iso_chain(vid, rep))
        keep = set()
        for e in cur:
            s = by_name.get(e.get("name"))
            if (s is not None and s.get("parent_name") == e.get("parent_name") and s.get("array") == e.get("array")
                    and (not e.get("parent_name") or e.get("parent_name") in keep)):
                keep.add(e.get("name"))
        for e in reversed(cur):
            if e.get("name") not in keep:
                self._call("threshold_remove", e["name"], vid)
        now = {e.get("name"): e for e in self._iso_chain(vid, rep)}
        renamed = {n: n for n in keep}
        for s in want:
            name = s.get("name")
            if name in keep:
                e = now.get(name) or {}
                if (s.get("low") is not None and s.get("high") is not None
                        and (e.get("low"), e.get("high")) != (s.get("low"), s.get("high"))):
                    self._call("threshold_range", [name, [float(s["low"]), float(s["high"])]], vid)
                if (e.get("visible", True) is not False) != (s.get("visible", True) is not False):
                    self._call("threshold_visible", [name, s.get("visible", True) is not False], vid)
                continue
            parent, up, seen = None, s.get("parent_name"), set()
            while up and up not in seen:
                if up in renamed:
                    parent = renamed[up]
                    break
                seen.add(up)
                up = (by_name.get(up) or {}).get("parent_name")
            before = {x.get("name") for x in self._iso_chain(vid, rep)}
            self._call("threshold_add", [s["array"], parent], vid)
            new = [x for x in self._iso_chain(vid, rep) if x.get("name") not in before]
            if not new:
                print(f"[assistant] undo: threshold on {s.get('array')} not re-added", flush=True)
                continue
            renamed[name] = new[-1]["name"]
            if s.get("low") is not None and s.get("high") is not None:
                self._call("threshold_range", [new[-1]["name"], [float(s["low"]), float(s["high"])]], vid)
            if s.get("visible", True) is False:
                self._call("threshold_visible", [new[-1]["name"], False], vid)
        alias = self._aliases.setdefault((vid, rep), {})
        for name, now_name in renamed.items():
            if name in keep:
                continue
            old = str(name).split(_UNDONE)[0]
            for k, v in list(alias.items()):
                if v == old:
                    alias[k] = now_name
            alias[old] = now_name
        self.state[f"active_by_tab__{vid}"] = dict(by_tab or {})
        self._flush()

    def _now_named(self, vid, rep, chain):
        """`chain` (an undo token's) with each entry and parent named as it
        is now (`_aliases`)."""
        alias = self._aliases.get((vid, rep)) or {}

        def now(n):
            return alias.get(n, n) if n else None
        return [dict(e, name=now(e.get("name")), parent_name=now(e.get("parent_name"))) for e in chain]

    def _undo_highlight(self, tok, lang):
        self._call("node_highlight", [], tok["vid"])
        self._lit.pop(tok["vid"], None)
        if self._live(tok["vid"]):
            self._restore_view(tok["vid"], tok["pre"])

    def _undo_slice(self, tok, lang):
        """The grid's slicer state as it was: every axis replayed, an empty
        list too (slicer_positions replaces the axis it names only). When
        the command built that state, the grid's whole extent and one mid
        plane per axis — what a fresh isolate starts with — then Slice off."""
        vid, rep, g = tok["vid"], tok["rep"], tok.get("grid")
        if not self._live(vid):
            return None
        if self._globe(vid):
            self._restore_view(vid, tok["pre"])
            return self._globe_dropped(lang, ("la coupe", "the slice", "e"))
        self.state[f"active_by_tab__{vid}"] = dict(self._get(f"active_by_tab__{vid}", {}), reservoir=rep)
        full = {a: list(r) for a, r in (tok.get("full") or {}).items() if len(r or ()) == 2}
        if g is None and len(full) == 3:
            g = {"mode": "full", "ranges": full,
                 "positions": {a: [(r[0] + r[1]) // 2] for a, r in full.items()},
                 "visible": {a: [True] for a in full},
                 "volumes": [[full["i"], full["j"], full["k"]]], "volumes_visible": [True]}
        if g is not None:
            for a in "ijk":
                rng = (g.get("ranges") or {}).get(a) or full.get(a)
                if rng:
                    self._call("slicer_range", [a, list(rng)], vid)
            for a in "ijk":
                self._call("slicer_positions", [a, list((g.get("positions") or {}).get(a) or [])], vid)
                self._call("slicer_visibility", [a, list((g.get("visible") or {}).get(a) or [])], vid)
            # slicer_range rebuilt ONE box from the ranges: the boxes as they were
            self._call("slicer_volumes", [list(v) for v in g.get("volumes") or []], vid)
            self._call("slicer_volumes_visible", list(g.get("volumes_visible") or []), vid)
        self._call("slicer_mode", (g or {}).get("mode") or "full", vid)
        self._restore_view(vid, tok["pre"])
        return None

    def _undo_tables(self, tok, lang):
        vid = tok["vid"]
        if not self._live(vid):
            return
        # the card's preset name first: session_restore_view_tables pushes the card
        by_view = dict(self._get("ui_active_colormap_by_view", {}) or {})
        if tok.get("preset"):
            by_view[vid] = tok["preset"]
        else:
            by_view.pop(vid, None)
        self.state["ui_active_colormap_by_view"] = by_view
        self._call("session_restore_view_tables", vid, tok.get("tables") or [])
        self._restore_view(vid, tok["pre"])

    def _undo_hide_nan(self, tok, lang):
        vid = tok["vid"]
        if not self._live(vid):
            return
        # the mask is the card's target's: the property it was set on, active again
        self.state[f"active_path__{vid}"] = tok.get("act") or ""
        self._flush()
        self._call("cmap_hide_nan", bool(tok.get("prev")), vid)
        self._restore_view(vid, tok["pre"])

    def _undo_flat(self, tok, lang):
        if self._live(tok["vid"]):
            self._call("set_flat_colors", tok["vid"], bool(tok.get("prev")))

    def _undo_camera(self, tok, lang):
        vid = tok["vid"]
        if not self._live(vid):
            return
        pvv = self._mv().get_pv_view(vid)
        for prop, v in (tok.get("cam") or {}).items():
            try:
                setattr(pvv, prop, v)
            except Exception as exc:
                print(f"[assistant] undo camera {prop} ({vid}):", exc, flush=True)
        # the views linked to this one took the reset too (nav_reset syncs them)
        sync = self._ctrl("camera_link_sync")
        if sync is not None:
            try:
                sync(vid)
            except Exception as exc:
                print(f"[assistant] undo camera, linked views ({vid}):", exc, flush=True)
        sch = getattr(self.ctx, "render_scheduler", None)
        if sch is not None:
            sch.mark_dirty(vid)
            sch.flush()
        if tok.get("pre"):
            self._restore_view(vid, tok["pre"])

    def _undo_zscale(self, tok, lang):
        self._call("set_zscale", float(tok.get("prev") or 1.0), tok.get("vid"))

    def _undo_close(self, tok, lang):
        mv = self._mv()
        titles = getattr(mv, "_titles", None) if mv is not None else None
        # the client closes the tab, then tells the server (MultiView._on_view_closed)
        if mv is not None and (titles is None or tok.get("pid") in titles):
            mv.remove_panel(tok["pid"])
        if tok.get("pre") and self._live(tok.get("vid")):
            self._restore_view(tok["vid"], tok["pre"])

    def _undo_reopen(self, tok, lang):
        """A closed panel opened again, of the same kind, on what it showed
        when that is known; the reply says when its settings are not all back."""
        kind, snap = tok["panel"], tok.get("snap") or {}
        before = set(self._panels(kind))
        lost = kind == "calculator"
        if kind in ("welllog", "reconcile", "compare"):
            self._call(f"open_{kind}")
            paths = list(snap.get("paths") or [])
            if paths:
                now = self._panels(kind)
                pid = next((p for p in now if p not in before), now[0] if now else None)
                fill = {"welllog": "welllog_tree_wells", "reconcile": "reconcile_tree_paths",
                        "compare": "compare_tree_paths"}[kind]
                self._call(fill, pid, paths)
        elif kind == "xml":
            stack = list((snap.get("tab") or {}).get("stack") or [])
            top = stack[-1] if stack else {}
            if not top.get("uuid"):
                return _reply(False, _t(lang, "L'explorateur XML ne peut pas être rouvert : son objet n'est pas connu.",
                                        "The XML explorer cannot be opened again: its object is not known."))
            self._call("xml_open", top["uuid"], top.get("title") or top["uuid"][:8], "")
            lost = len(stack) > 1 or int(snap.get("tabs") or 0) > 1
        elif kind == "calculator":
            self._call("open_calculator", None)
        else:
            self._call({"stratigraphy": "open_stratigraphy", "health": "open_health"}[kind])
        if not self._panels(kind):
            return _reply(False, _t(lang, "Le panneau n'a pas pu être rouvert.", "The panel could not be opened again."))
        if lost:
            return _reply(True, _t(lang, "Ses réglages n'ont pas tous pu être remis.",
                                   "Not all its settings could be put back."))
        return None

    def _undo_time(self, tok, lang):
        if self._live(tok["vid"]):
            self._call("time_index", int(tok.get("prev") or 0), tok["vid"])

    def _undo_play(self, tok, lang):
        if self._live(tok["vid"]):
            self._call("time_play", bool(tok.get("prev")), tok["vid"])

    def _undo_realization(self, tok, lang):
        if self._live(tok["vid"]):
            self._call("set_realization", [tok["path"], int(tok["prev"])], tok["vid"])

    def _undo_style(self, tok, lang):
        if self._live(tok["vid"]):
            self._call("set_rep_style", tok["vid"], tok.get("prev") or "Surface")

    def _undo_bar(self, tok, lang):
        vid = tok["vid"]
        if not self._live(vid):
            return
        # the bar is the card's target's: the property it was set on, active again
        self.state[f"active_path__{vid}"] = tok.get("act") or ""
        self._flush()
        self._call("cmap_bar", bool(tok.get("prev")), vid)
        self._restore_view(vid, tok["pre"])

    def _undo_tool(self, tok, lang):
        # closed only while it is open: a card closed by hand since stays closed
        if self._live(tok["vid"]) and tok["key"] in self._open_tools(tok["vid"]):
            self._call("toggle_tool", tok["key"], tok["vid"])
