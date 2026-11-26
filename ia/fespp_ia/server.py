"""The gateway: the only door of fespp_ia (port FESPP_IA_PORT, 8000 by default), the /v1 contract.

    GET  /v1/health    the service lives, the model is loaded, which, the queue, the index
    POST /v1/chat      a reply; with a JSON schema the output is CONSTRAINED to it
    POST /v1/ask       a question answered from the index (RAG): text + the sources read
    POST /v1/command   a sentence turned into ONE command of the caller's catalogue, its
                       slots among the caller's vocab and the session's values

One generation at a time per loaded model (FESPP_IA_PARALLEL): the others
wait their turn, and one that waits more than FESPP_IA_QUEUE_TIMEOUT seconds
gets a 503 the client shows as "the assistant is busy".

The index (fespp_ia.rag) is loaded at start from FESPP_IA_INDEX with the
embedding model of FESPP_IA_EMBED; without them the service answers /v1/chat
and /v1/command (without the glossary) and says so in /v1/health.
"""
import asyncio
import contextlib
import itertools
import json
import os
import re
import time
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from fespp_ia import API_VERSION
from fespp_ia.llama import LLAMA_PORT, LlamaProcess
from fespp_ia.rag import _fold


class Message(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    # a JSON schema: the reply is then a JSON document valid for it
    schema_: Annotated[dict | None, Field(alias="schema")] = None
    max_tokens: int = Field(default=512, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


# the characters of each extract the /v1/ask prompt carries
EXTRACT_CHARS = int(os.environ.get("FESPP_IA_EXTRACT_CHARS", "700"))


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=4, ge=1, le=12)
    sources: list[str] | None = None           # limit the reading to these source names
    lang: str = Field(default="fr", pattern="^(fr|en)$")
    max_tokens: int = Field(default=400, ge=1, le=2048)


class Vocab(BaseModel):
    """The caller's canonical names for the slots a command may carry: the
    property kinds, the analysis panels and the colour tables. The schema
    enumerates them, so the model cannot write a name the caller does not
    know ("water_saturation", a well's title as a kind), and the prompt
    lists them. A list is cleaned rather than refused (an empty or overlong
    name dropped, each name once, the first VOCAB_MAX kept): a refusal
    would cost the caller its whole command."""
    kinds: list = []
    panels: list = []
    presets: list = []

    @field_validator("kinds", "panels", "presets", mode="before")
    @classmethod
    def _names(cls, values):
        values = values if isinstance(values, (list, tuple)) else []
        names = (" ".join(v.split()) for v in values if isinstance(v, str))
        return list(dict.fromkeys(v for v in names if 0 < len(v) <= 80))[:VOCAB_MAX]


# the names of one vocab list the schema enumerates and the prompt lists
VOCAB_MAX = 100


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # the caller's catalogue: [{"name", "fr", "en", "slots": [...]}]
    catalogue: list[dict] = Field(min_length=1)
    # what the session holds: [{"title", "type", "kind", "categories": [...]}]
    objects: list[dict] = []
    lang: str = Field(default="fr", pattern="^(fr|en)$")
    # glossary chunks read for the domain words the prompt does not name
    # (two: a command needs a definition, not a reading list)
    k: int = Field(default=2, ge=0, le=8)
    max_tokens: int = Field(default=200, ge=1, le=1024)
    # without it the kind, the panel and the colour table are free text
    # and the prompt lists DEFAULT_KINDS
    vocab: Vocab | None = None


# what the glossary of a command reads: our documents (the reservoir
# glossary) and the PWLS property kinds with their aliases -- never the code
# docstrings or the spec sections, which a command never needs
GLOSSARY_SOURCES = ["docs", "pwls"]
GLOSSARY_CHARS = 250

_ASK_SYSTEM = {
    "fr": ("Tu es l'assistant de fespp_on_trame, un visualiseur de données de réservoir RESQML "
           "(grilles, puits, propriétés) bâti sur ParaView et le plugin FESPP (fesapi). Réponds en "
           "français, brièvement et précisément, UNIQUEMENT à partir des extraits fournis. Si les "
           "extraits ne répondent pas, dis-le en une phrase plutôt que d'inventer. Cite le titre de "
           "l'extrait utilisé entre crochets."),
    "en": ("You are the assistant of fespp_on_trame, a viewer of RESQML reservoir data (grids, wells, "
           "properties) built on ParaView and the FESPP plugin (fesapi). Answer in English, briefly and "
           "precisely, ONLY from the extracts given. When the extracts do not answer, say so in one "
           "sentence rather than invent. Cite the title of the extract used in brackets."),
}

# examples that teach the shape and the traps (a negation, a value word, a
# question, a sentence with no command of the catalogue); worded unlike
# the evaluation sentences, not to teach the test. Each well_filter wording
# lives here OR in the rule, not in both. Their keys come in the schema's
# order and only when the sentence fills them: the model copies that shape.
# A value of the caller's vocab (a panel, a colour table) is written as the
# word to look for in it: the example shows the vocab's own spelling, and
# goes without that key when the vocab has no such entry. The examples that
# name a zone come last: they are said on the session's own values (see
# _zone_example), so they are the one part of the examples a change of
# session alters, and llama-server's prefix cache keeps all before them.
_COMMAND_EXAMPLES = [
    # a number does not make a threshold: highlight keeps every cell
    ("mets en évidence les cellules dont la perméabilité excède 150",
     {"intent": "highlight", "kind": "permeability", "min": 150}),
    ("ne conserve que les cellules où la porosité vaut plus de 0,18",
     {"intent": "threshold", "kind": "porosity", "min": 0.18}),
    # the usual traps: a complaint, and a short question on the last reply;
    # the bounds of the colour scale; a panel, not a number
    ("ça n'affiche rien du tout, ce n'est pas ce que j'attendais", {"intent": "complain"}),
    ("laquelle ? je ne comprends pas de quoi tu parles", {"intent": "complain"}),
    ("borne la palette de couleurs entre 5 et 40", {"intent": "color_range", "min": 5, "max": 40}),
    ("open the histogram of the permeability", {"intent": "open_panel", "kind": "permeability", "panel": "stats"}),
    # the slots of the other gestures: a colour table, an axis, a factor,
    # a switch turned off
    ("applique la table de couleurs inferno", {"intent": "colormap", "preset": "inferno"}),
    ("tranche le modèle dans la direction J", {"intent": "slice", "axis": "j"}),
    ("rends le relief huit fois plus haut", {"intent": "z_scale", "factor": 8}),
    ("redonne de l'ombrage aux surfaces", {"intent": "flat_colors", "on": False}),
    ("à quoi sert un horizon ?", {"intent": "ask", "question": "à quoi sert un horizon ?"}),
    ("give me the median net to gross", {"intent": "value", "kind": "net to gross"}),
    ("fais-moi un café", {"intent": "unknown"}),
    # the zones: a highlight hides nothing; the wells kept or removed by
    # the zone they cross; a fluid or facies zone kept or hidden is a
    # threshold (hidden: exclude, the rest stays); a question on the wells
    # that is a computation
    ("surligne les zones d'huile sans rien cacher", {"intent": "highlight", "category": "oil"}),
    ("supprime les forages qui n'atteignent jamais la zone à gaz",
     {"intent": "well_cells", "category": "gas", "well_filter": "keep_crossing"}),
    ("laisse seulement les puits qui touchent l'eau",
     {"intent": "well_cells", "category": "water", "well_filter": "keep_crossing"}),
    ("il y a encore des puits en dehors du calcaire, enlève-les",
     {"intent": "well_cells", "category": "limestone", "well_filter": "keep_crossing"}),
    ("fais disparaître les trajectoires qui recoupent le grès",
     {"intent": "well_cells", "category": "sandstone", "well_filter": "hide_crossing"}),
    ("fais apparaître uniquement le siltstone", {"intent": "threshold", "category": "siltstone"}),
    ("retire la zone à gaz de la vue", {"intent": "threshold", "category": "gas", "exclude": True}),
    ("est-ce qu'un forage atteint le calcaire ?", {"intent": "well_cells", "category": "limestone"}),
]

# the canonical property kinds of the application (its lexicon), listed
# for a caller that sends no vocab; a caller's vocab replaces them
DEFAULT_KINDS = ("porosity", "permeability", "net to gross", "water saturation", "gas saturation",
                 "oil saturation", "saturation", "gamma ray", "bulk density", "neutron porosity", "resistivity",
                 "sonic", "shale volume", "facies", "fluids", "pressure", "temperature", "depth", "thickness",
                 "cell volume")

# the keys of a command after the intent, in the order the model writes
# them (llama.cpp's grammar keeps the schema's order)
COMMAND_KEYS = ("kind", "category", "exclude", "min", "max", "objects", "well_filter", "panel", "preset",
                "axis", "factor", "on", "question")


def _vocab(vocab):
    """`vocab` as a Vocab: given as one, as a dict, or absent (empty)."""
    if isinstance(vocab, Vocab):
        return vocab
    return Vocab(**vocab) if vocab else Vocab()


def category_values(categories):
    """The values of the session's categorical properties as the model may
    write them: folded (lower case, no accents), each once, in order."""
    return list(dict.fromkeys(v for v in (_fold(str(c)).strip() for c in categories or ()) if v))


def command_schema(names, vocab=None, categories=()):
    """The JSON the model must produce for a command. The intent among the
    catalogue's names, "ask" and "unknown" is the one required key: the
    model writes the keys the sentence fills and stops, and on a CPU every
    character of output costs. A kind, panel or colour table among the
    caller's vocab when it sends one; a category among the session's
    values when it has some; anything else nullable."""
    def among(values):
        values = list(dict.fromkeys(v for v in values if v))
        return {"type": ["string", "null"], "enum": [*values, None]} if values else {"type": ["string", "null"]}
    vocab = _vocab(vocab)
    slots = {"kind": among(vocab.kinds),
             "category": among(category_values(categories)),
             "exclude": {"type": ["boolean", "null"]},
             "min": {"type": ["number", "null"]},
             "max": {"type": ["number", "null"]},
             "objects": {"type": "array", "items": {"type": "string"}},
             "well_filter": {"type": ["string", "null"], "enum": ["keep_crossing", "hide_crossing", None]},
             "panel": among(vocab.panels),
             "preset": among(vocab.presets),
             "axis": {"type": ["string", "null"], "enum": ["i", "j", "k", None]},
             "factor": {"type": ["number", "null"]},
             "on": {"type": ["boolean", "null"]},
             "question": {"type": ["string", "null"]}}
    return {"type": "object",
            "properties": {"intent": {"type": "string", "enum": sorted(set(names) | {"ask", "unknown"})},
                           **{k: slots[k] for k in COMMAND_KEYS}},
            "required": ["intent"], "additionalProperties": False}


# the verbs and fillers of a command sentence: not domain words, so they
# never call for a glossary read (a verb would otherwise pull in an
# unrelated entry, such as the one on trajectories)
_COMMAND_WORDS = set("""
peux peut pouvez pourrais veux voulais voudrais voir mettre mets remets remet montre montrer affiche afficher
enleve enlever retire retirer vire virer masque masquer garde garder coupe coupent passe passent rentre rentrent
ouvre ouvrir ferme fermer recentre recentrer recale recaler annule annuler reste restent
please could would want show open remove hide keep still thru through that those anything nothing everything
""".split())


def new_words(text, vocabulary):
    """The notions of `text` (rag.keywords: folded, four letters or more,
    with their bridge to the other language) that `vocabulary` -- a prompt
    -- does not name, as a word or a stem of one ("perm" / "permeability",
    "puits" / "puit"). Empty: the glossary has nothing to add."""
    from fespp_ia.rag import keywords
    known = {w for group in keywords(vocabulary) for w in group} | _COMMAND_WORDS
    out = []
    for group in keywords(text):
        if not any(g in known or any(v.startswith(g) or g.startswith(v) for v in known) for g in group):
            out.append(group[0])
    return out


# What the model reads wrong the same way every time, settled from the
# sentence itself after the model (settle_command) instead of one more
# paragraph of prompt paid on every call: a fluid or facies zone shown or
# hidden comes back as show/hide; a negated crossing ("the wells that do not
# go through the oil") as hide_crossing; "hide the wells" as a well filter
# with nothing to filter on; "the oil cells" as a well computation without
# a well; a complaint that repeats the request as that request; a panel or
# a colour table as a nearby gesture. Each reading is narrow on purpose --
# an unmatched sentence keeps the model's answer -- and none may turn a
# right answer into a wrong one: given the labelled sentences of the
# application's corpus as the model's answer, they change none of them
# (ia/tests/test_settle_command.py, FESPP_IA_CORPUS), and given the right
# answer to sentences written apart from the corpus and the bench, they keep
# it (ia/tests/test_settle_paraphrases.py).
#
# The exclude and the well_filter the model gives stand: a negation or an
# exception holds in its clause, which a word pattern does not see, and
# overriding the model there turns its right answers wrong. Two things only
# undo them: a contradiction inside the answer (a well filter on another
# gesture than well_cells) and a negated crossing under no verb that keeps
# wells. Where the model leaves exclude out, it is set only when a verb
# plainly hides the zone (_hidden_zone); anything less plain stays out, and
# the application asks whether to hide the zone or keep it alone.
_WELL_NOUNS = r"puits|wel+s?|wel+bores?|forages?|boreholes?|trajectoires?|trajector(?:y|ies)|sondages?"
# a well's name: "15/9-F-4", "NO 15/9-F-5", "34/10-A-1", "25/11-15", "16/2-6 A", "F-12"
_WELL_NAME = (r"\b(?:no\s*)?\d+/\d+\s*-?\s*[a-z]\s*-?\s*\d+|\b(?:no\s*)?\d+/\d+\s*-\s*\d+(?:\s*[a-z]\b)?"
              r"|\bf\s*-\s*\d+")
_WELL_NAMES = re.compile(_WELL_NAME)
# a well in the sentence: its noun, a blocked-wellbore word, "drilled", or a well's name
_WELL_WORDS = re.compile(r"\b(?:" + _WELL_NOUNS + r"|bloquee?s?|blocked|bw|drilled|fores?)\b|" + _WELL_NAME)
# a well's noun alone: "ça bloque" names no well
_WELL_NAMED = re.compile(r"\b(?:" + _WELL_NOUNS + r")\b")
# the verbs that make something go (a causative "fais disparaître", not
# "les puits disparaissent", which is a complaint); taking a thing "out of
# the view" is one of them, not a negation
_HIDE = (r"cache[rsz]?|masque[rsz]?|enleve[rsz]?|retire[rsz]?|vire[rsz]?|supprime[rsz]?|degage[rsz]?|"
         r"efface[rsz]?|elimine[rsz]?|ote[rsz]?|(?:fais|faites|faire)(?:[ -]moi)? (?:disparaitre|partir)|"
         r"hide|remove|mask|get rid of|take (?:it |them )?off|drop|discard|exclude|eliminate|delete|"
         r"filter out|leave out|out of (?:the |my )?(?:view|sight|display|picture|scene|screen)")
_HIDE_VERBS = re.compile(r"\b(?:" + _HIDE + r")\b")
# a French negation after a verb: "pas", "plus" or "jamais" -- not the
# "plus de" of "more", nor a "ne ... que" that keeps only
_NOT = r"\s+(?:pas|plus(?!\s+d)|jamais)\b(?!\s+(?:que|autre chose|rien d))"
# a hiding verb said not to be done: what it names stays ("ne cache pas
# l'huile", "don't hide the gas", "arrête de masquer l'eau")
_NOT_HIDDEN = re.compile(r"\bn(?:e\s+|.\s*)(?:(?:le|la|les|l.)\s*)?(?:" + _HIDE + r")" + _NOT
                         + r"|\b(?:" + _HIDE + r")" + _NOT
                         + r"|\b(?:don.?t|do not|never|no need to|stop|quit)\s+(?:" + _HIDE
                         + r"|hiding|masking|removing)\b|\b(?:arrete[rsz]?|cesse[rsz]?)\s+de\s+(?:" + _HIDE + r")")
# a verb that shows or keeps said not to be done, or not wanting to see:
# what it names goes ("je veux pas voir l'eau", "ne garde pas l'argile",
# "don't show the water") -- not what a view does ("the view doesn't show
# the oil" is a remark on it)
_NOT_SHOWN = re.compile(r"\b(?:ne\s+|n.\s*)?(?:veu[xt]|voudrai[st]|souhaite|aimerai[st])\s+(?:pas|plus)\s+voir\b"
                        r"(?!\s+(?:que|autre chose|rien d))"
                        r"|\bn(?:e\s+|.\s*)(?:(?:le|la|les|l.)\s*)?(?:montre|affiche|garde|conserve|laisse)[rsz]?"
                        + _NOT + r"|\b(?:don.?t|do not|never)\s+(?:want to see|wanna see|show|display|keep)\b")


def _polarised(folded):
    """The folded sentence with each negated verb said as its opposite: "ne
    cache pas" reads "garde", "ne montre pas" and "don't want to see" read
    "cache" -- so that a negated verb never counts as what it negates."""
    return _NOT_SHOWN.sub(" cache ", _NOT_HIDDEN.sub(" garde ", folded))


def _hides(polarised):
    """Whether the polarised sentence says a thing goes."""
    return bool(_HIDE_VERBS.search(polarised))


# a zone kept alone: what the filter keeps ("ne garde que le calcaire",
# "fais apparaître uniquement le siltstone", "I only want to see the water")
_KEEP_ONLY = re.compile(r"\b(?:n(?:e\s+|.\s*)(?:garde|laisse|montre|affiche|conserve)[rsz]?\s+(?:plus\s+)?que|"
                        r"(?:garde|laisse|montre|affiche)(?:[ -]moi)? que|(?:garde|laisse) (?:seulement|uniquement)|"
                        r"only keep|keep only|keep just|(?:veu[xt]|voudrai[st]) (?:voir|montrer|afficher) que|"
                        r"only show|isole|isolate)\b")
# a verb that keeps what it names, its object said or not
_KEEP_VERBS = re.compile(r"\b(?:garde[rsz]?|conserve[rsz]?|keep(?:s|ing)?|retain|isole[rsz]?|isolate)\b")
# the verbs that keep the wells they name: kept over a negated crossing,
# the wells that stay are those that do not cross ("ne garde que les puits
# qui ne touchent pas le gaz", "show only the wells that don't cross the
# oil", "laisse les puits qui ne traversent pas le gaz et vire le reste")
_KEEPS_WELLS = re.compile(_KEEP_VERBS.pattern + "|" + _KEEP_ONLY.pattern + r"|\b(?:(?:ne\s+)?veu[xt]\s+(?:plus\s+)?"
                          r"voir\s+(?:que|seulement|uniquement|juste)|only (?:want to )?see|want to see only|"
                          r"(?:show|display|see) only|only (?:show|display)|"
                          r"(?:montre|affiche|montrez|affichez)(?:[ -]moi)?\s+(?:seulement|uniquement|juste)|"
                          r"laisse[rz]?(?!\s+tomber))\b")
_HIGHLIGHT_VERBS = re.compile(r"\b(?:surlign\w*|surbrillance|evidence|ressortir|allume\w*|signal\w*|repere\w*|"
                              r"marque\w*|highlight\w*|highlite|hilight|mark\w*|emphasi[sz]e\w*|light up|"
                              r"stand out|spotlight|flag\w*|point out|bring out|en couleur)\b")
# the cells, a zone or the grid: what a well computation reads, not the
# wells themselves
_CELL_WORDS = re.compile(r"\b(?:mailles?|cellules?|cells?|cases?|zones?|grilles?|grids?|reservoirs?|"
                         r"intervalles?|intervals?|couches?|layers?)\b")
# the verbs of a well going through a zone (the engine's crossing words)
_CROSSING = (r"(?:traverse|passe|rentre|touche|coupe|recoup|crois(?:e|es|ent|ant|ee|ees)\b|rencontr|"
             r"perce(?:es?)?\b|fore(?:es?|nt|r)?\b|atteint|atteign|le long|bloqu|cross|touch|pass|enter|"
             r"hit(?:s|ting)?\b|intersect|intercept|reach|penetr|drill|along|through|thru|across|go(?:es|ing)?\b|"
             r"bloc)")
_CROSSES = re.compile(r"\b" + _CROSSING)
# a blocked wellbore said as one: "les blocked wellbores", "les puits
# bloqués", "the blocks of the wells" -- not "le bloc nord", "ça bloque",
# "the grid blocks my view of the wells". Folded, the adjective "bloqué"
# is the verb "bloque": followed by an object ("le chargement des puits
# bloque l'appli") it is the verb.
_BLOCKED_WELLS = re.compile(r"\bblocked\s+(?:" + _WELL_NOUNS + r")\b|\b(?:" + _WELL_NOUNS + r")\s+bloquee?s?\b"
                            r"(?!\s+(?:l\W|la\b|le\b|les\b|un\b|une\b|des\b|mon\b|ma\b|mes\b|tout|ca\b|cela\b"
                            r"|ce\b|cet\b|cette\b))"
                            r"|\bblocks?\s+(?:des|du|of(?:\s+the)?)\s+(?:" + _WELL_NOUNS + r")\b")
_FAULT_BLOCKS = re.compile(r"\b(?:fault(?:ed)?\s+blocks?|blocs?\s+(?:de\s+)?faill\w*|blocks?\s+(?:de\s+)?faill\w*)")
# a question on what a thing is, means or is for
_DEFINE = re.compile(r"\b(?:c.est quoi|qu.est.ce|what is|what are|what.s|a quoi (?:sert|servent)|explique\w*|"
                     r"explain\w*|kesako|quesaco|definition|define|defini\w*|signifie|veut dire|meaning|"
                     r"what does (?:\w+\s+){0,4}mean)\b")
_PANEL_WORDS = re.compile(r"\b(?:stats?|statistiques?|statistics|histogrammes?|histograms?|cross ?plot|"
                          r"nuage de points|scatter|logs? du puits|well logs?|log view|comparer|compare|comparaison)\b")
_STAT_WORDS = re.compile(r"\b(?:moyenne|mean|average|avg|min|max|minimum|maximum|mediane|median|ecart|std|p10|p90|"
                         r"somme|sum)\b")
# a value asked for: a question word, or a number (a depth) to read it at
_VALUE_ASKED = re.compile(r"\b(?:quel(?:le)?s?|combien|what|which|how much|vaut|valent|lit.on)\b|(?<![\w/.,-])\d")
# a verb that opens or shows a panel
_OPENS = re.compile(r"\b(?:compare[rz]?|ouvre|ouvrir|affiche|afficher|montre|montrer|open|show|display|lance)\b")
# a question on a panel -- what it shows, why, how -- or a request to tell
# or explain, not a request to open it: "est-ce que tu peux me dire pourquoi
# l'histogramme montre deux pics ?", "can you show me how it is computed?"
_INTERROGATIVE = re.compile(r"\b(?:pourquoi|comment|why|how|what|que|quoi|explique\w*|explain\w*)\b|\bqu['’]"
                            r"|\b(?:tu peux|peux.tu|pourrais.tu|tu pourrais|vous pouvez|pouvez.vous)\s+(?:me|nous)\s+"
                            r"dire\b|\b(?:can|could|would|will) you tell me\b")
# a gesture asked for: a request form, or an opening verb that starts the
# sentence ("est-ce que l'histogramme montre la médiane ?" asks for none)
_ASKS_FOR = re.compile(r"^\s*(?:(?:stp|svp|please)\s+)?(?:ouvre|open|lance|launch|affiche|montre|compare|show|"
                       r"display)\b|\b(?:tu peux|peux.tu|pourrais.tu|tu pourrais|vous pouvez|pouvez.vous|can you|"
                       r"could you|would you|will you|please|stp|svp|s.il te plait|s.il vous plait|j.aimerais|"
                       r"je veux|je voudrais|i want|i.d like|i would like)\b")
_PRESETS = (r"viridis|inferno|plasma|turbo|jet|arc.en.ciel|rainbow|froid chaud|cool to warm|niveaux de gris|"
            r"grayscale|greyscale|noir et blanc|black and white|bleu orange")
_PRESET_WORDS = re.compile(r"\b(?:" + _PRESETS + r")\b")
# the shading of the surfaces named, or the colour table said to stay: a
# colour table there is not what the sentence changes
_SHADING = re.compile(r"\b(?:ombr\w*|shad\w*|flat|a plat|eclair\w*|lighting)\b")
_PRESET_KEPT = re.compile(r"\b(?:garde[rsz]?|conserve[rsz]?|keep|same|meme|toujours|still|sans changer|"
                          r"ne change pas|don.?t change|do not change|leave)\s+(?:\w+\s+){0,3}?"
                          r"(?:palette|colormap|color ?map|colou?r table|table de couleurs?|" + _PRESETS + r")\b")
# a colour scale fitted to the data: the colour table named is the one
# fitted, not one to apply ("ajuste la palette viridis aux valeurs")
_RESCALE_VERBS = re.compile(r"\b(?:ajust\w*|recal\w*|rescal\w*|fit\w*|adapt\w*)\b")
# a complaint: the last reply judged wrong in so many words ("ta réponse est
# fausse", "c'est pas ça", "not what I asked") -- never a bare negation
# after "ta réponse" ("ta réponse ne m'a pas déçu"), nor a judgement said
# not, which praises (_judged_wrong)
_WRONG = r"fausse?s?|faux|nulle?s?|mauvaise?s?|a cote|n.importe quoi|wrong"
_COMPLAINT = re.compile(
    r"\bta reponse\b(?:\s+\S+){0,4}?\s+(?:" + _WRONG + r"|pas bonne?s?|ne (?:me |nous )?convien\w* pas)\b"
    r"|\b(?:c.est|c.etait|ce n.est|ce n.etait)\s+(?:\S+\s+)?(?:fausse?s?|faux|nulle?s?|mauvaise?s?|n.importe quoi|"
    r"pas bon(?:ne)?)\b"
    r"|\b(?:that|it|this)(?:.s| is| was)\s+(?:\S+\s+)?wrong\b|\byou(?:.re| are)\s+(?:\S+\s+)?wrong\b"
    r"|\bwrong (?:answer|reply|response)\b|\b(?:your|the) (?:answer|reply|response) (?:is|was) (?:\S+\s+)?wrong\b"
    r"|\bne (?:me |nous )?convien\w* pas\b|\bc.?est pas ca\b|\bce n.?est pas ca\b|\ba cote de la plaque\b"
    r"|\bpas ce que je (?:voulais|veux|demandais)\b|\bthat.?s not (?:it|right)\b|\bnot what i (?:asked|wanted|meant)\b")
_WRONG_WORD = re.compile(r"\b(?:" + _WRONG + r")\b")
# a negation in the few words before a judgement: "pas fausse", "n'était
# pas mauvaise", "not wrong", "rien de faux"
_SAID_NOT = re.compile(r"\b(?:pas|plus|jamais|rien|not|never|nothing|no)\b(?:\s+\S+){0,2}\s*$|n.t\s+(?:\S+\s+){0,2}$")


def _judged_wrong(folded):
    """Whether the sentence judges the last reply wrong (_COMPLAINT): a
    judgement word said not ("ta réponse n'est pas fausse", "that's not
    wrong") is a praise, no complaint."""
    for m in _COMPLAINT.finditer(folded):
        word = _WRONG_WORD.search(folded, m.start(), m.end())
        if word is None or not _SAID_NOT.search(folded[max(0, word.start() - 40):word.start()]):
            return True
    return False


# nothing to see, or only a colour: "je ne vois que du gris", "je ne vois
# rien" -- not "je vois que les puits sont encore là", a remark
_SEES_NOTHING = re.compile(r"\b(?:je|on)\s+n(?:e\s+|.\s*)(?:vois|voit)\s+(?:que|rien|plus rien)\b"
                           r"|\b(?:je vois|on voit)\s+(?:rien|plus rien|que\s+(?:du|de la|de l.|des)\b)"
                           r"|\bi (?:can )?(?:only )?see nothing\b")
# a view said fine, or a question: no complaint ("je ne vois rien
# d'anormal, merci", "je vois que des puits traversent l'huile, combien ?")
_SEEN_FINE = re.compile(r"\b(?:anormale?s?|bizarres?|a redire|a corriger|parfaite?s?|parfaitement|merci|nickel|"
                        r"bravo|good|wrong)\b")
_QUESTION = re.compile(r"\?|\b(?:pourquoi|comment|combien|quel(?:le)?s?|est.ce|why|how|what|which|where|when)\b")
# a verb that asks for a gesture: with one, a remark on the view is no
# complaint ("je ne vois rien, affiche la porosité")
_ACTS = re.compile(r"\b(?:" + _HIDE + r"|montre[rz]?|affiche[rz]?|ouvre[rz]?|show|display|open|surligne[rz]?|"
                   r"highlight|filtre[rz]?|filter|garde[rz]?|keep|isole[rz]?|isolate|remets|remettre|colorie[rz]?|"
                   r"colou?r)\b")
_CAMERA = re.compile(r"\b(?:recadre|recentre|recentr|recenter|reset|zoom|cadre)\w*")


# the words of a sentence for each usual category value (the model answers
# the value in English whatever the language of the sentence, or the
# session's own label): the application lexicon's ways of saying them
_ZONE_WORDS = {"oil": ("oil", "huile", "huiles", "petrole", "hydrocarbure liquide"),
               "gas": ("gas", "gaz"),
               "water": ("water", "eau", "aquifere", "aquiferes", "aquifer"),
               "sandstone": ("sandstone", "gres", "greseux", "greseuse", "sable", "sables", "sableux", "sableuse",
                             "sand", "sands"),
               "shale": ("shale", "shales", "argile", "argiles", "argileux", "argileuse", "argilite", "schiste",
                         "clay"),
               "siltstone": ("siltstone", "silt", "silts", "siltite", "silteux", "silteuse"),
               "limestone": ("limestone", "calcaire", "calcaires", "carbonate", "carbonates"),
               "coal": ("coal", "charbon", "lignite")}


def canonical_category(value):
    """The usual name of a category value ("Huile", "argiles" -> "oil",
    "shale"), else the value folded; None when empty."""
    folded = " ".join(_fold(str(value or "")).split())
    if not folded:
        return None
    return next((canon for canon, words in _ZONE_WORDS.items() if folded == canon or folded in words), folded)


def _zone_words(category):
    return _ZONE_WORDS.get(category, ()) + (category,)


def _zone_named(folded, category, kind):
    """Whether `category` is a zone the sentence names -- and not a word of
    the property it shows ("water saturation" is a property, not the water
    zone)."""
    words = _zone_words(category)
    named = any(re.search(r"\b" + re.escape(w) + r"s?\b", folded) for w in words)
    return named and not _in_kind(category, kind)


def _in_kind(category, kind):
    """Whether the category's word is a word of the kind, a property kind
    of the application: "water" of "water saturation", "shale" of "shale
    volume" -- not of a kind the model made of the zone itself ("oil")."""
    kind = " ".join(_fold(str(kind or "")).replace("_", " ").split())
    return kind in DEFAULT_KINDS and any(re.search(r"\b" + re.escape(w) + r"\b", kind) for w in _zone_words(category))


def _zone_pattern(category):
    """The regex alternation of the words that say `category` (none for no
    category)."""
    return "|".join(re.escape(w) for w in sorted({w for w in _zone_words(category) if w}, key=len, reverse=True))


# every zone word of the lexicon
_ANY_ZONE = "|".join(re.escape(w) for w in sorted({w for ws in _ZONE_WORDS.values() for w in ws}, key=len,
                                                   reverse=True))


def _negated_crossing(category):
    """A crossing said not: the verb then "pas" or "jamais", "never" or
    "don't" then the verb, the wells' negated auxiliary ("qui n'ont pas de
    block", not "si ce n'est pas trop demander"), the other wells, or a
    place outside a zone ("hors de l'huile", "outside the gas cap", "en
    dehors de la zone") -- not outside anything else ("out of the way",
    "hors de vue", "out of the 3D view" take the wells off the view)."""
    zone = "|".join(filter(None, (_zone_pattern(category), _ANY_ZONE)))
    return re.compile("|".join((
        r"\b" + _CROSSING + r"\w*\s+(?:pas|jamais)\b",          # French: the verb, then "pas" or "jamais"
        r"\b(?:never|not|don.?t)\s+(?:\w+\s+)?" + _CROSSING,     # never touch, don't cross
        r"\bqui\s+n\s*'?\s*(?:ont|a|est|sont)\s+pas\b",           # French: the wells' negated auxiliary
        r"\bles\s+autres\b", r"\bthe\s+others\b",
        r"\b(?:hors|en\s+dehors|pas\s+dans|not\s+in|out\s+of|outside(?:\s+of)?)\s+(?:(?:de|du|des|d.|of)\s*)?"
        r"(?:(?:la|le|les|l.|the)\s*)?(?:zones?|reservoirs?|(?:(?:mailles?|cellules?|cells?)\s+(?:a|de|d.|du|des|of)?"
        r"\s*)?(?:" + zone + r")s?)\b")))


def _keeps_wells_not_crossing(polarised, category):
    """Whether a verb that keeps wells governs a negated crossing -- the
    nearest well verb before it, or the first one after when none comes
    before: "ne garde que les puits qui ne touchent jamais le gaz", "remove
    the ones crossing the oil and keep the others". The wells kept are then
    those that do not cross: the crossing ones go (hide_crossing)."""
    verbs = sorted([(m.start(), "keep") for m in _KEEPS_WELLS.finditer(polarised)]
                   + [(m.start(), "hide") for m in _HIDE_VERBS.finditer(polarised)])
    for neg in _negated_crossing(category).finditer(polarised):
        before = [v for at, v in verbs if at < neg.start()]
        after = [v for at, v in verbs if at >= neg.end()]
        if (before[-1] if before else after[0] if after else None) == "keep":
            return True
    return False


# the words that make a zone's polarity a matter of reading -- an
# exception, a restriction, the rest or the others, a question on it ("cache
# tout sauf l'eau", "hide only the gas", "masque le reste", "ne garde que le
# grès", "pourquoi tu caches l'huile ?"): left to the reader
_UNSURE = re.compile(r"\b(?:sauf|excepte|hormis|a part|a l.exception|except|excepting|excluding|other than|apart from|"
                     r"besides|autres?|reste|restent|rest|stays?|remains?|remaining|others?|else|seulement|juste|"
                     r"uniquement|exclusivement|only|just|solely|pourquoi|comment|why|how)\b"
                     r"|\bque\s+(?:le|la|les|du|des|de)\b|\bque\s+l['’]")
# what ends a clause: a punctuation mark, or a word that starts another
# ("montre l'huile, mais cache le gaz", "hide everything but the oil")
_CLAUSE = re.compile(r"[,;:.!?()]|\b(?:mais|puis|ensuite|alors|sinon|but|then|otherwise)\b")
# a negation or an undoing anywhere in a clause: what it does to a verb is
# for the reader to tell ("ne cache surtout pas", "il ne faut pas cacher",
# "évite de masquer", "never ever hide", "make sure not to hide")
_NEGATION = re.compile(r"\b(?:ne|n|pas|jamais|rien|aucune?|guere|nullement|sans|ni|non|not|no|never|nothing|none|"
                       r"nor|neither|without|cannot|(?:don|doesn|didn|can|won|wouldn|shouldn|couldn|isn|aren|wasn|"
                       r"weren|haven|hasn|mustn).?t|stop\w*|quit|cease|avoid\w*|refrain|arret\w*|cess\w*|evit\w*|"
                       r"inutile|oubli\w*|annul\w*|undo|cancel\w*|revert)\b"
                       r"|(?<!\ben )(?<!\bde )(?<!\bau )\bplus\b(?!\s+(?:de|d|que|qu)\b)")
# a verb said done, not asked for: "tu as caché l'huile", "je l'ai masqué"
_DONE = re.compile(r"\b(?:ai|as|a|avons|avez|ont|avai[st]|avaient|aurai[st]?|est|es|sont|etai[st]|etaient|ete|etre|"
                   r"suis|sommes|etes|soi[st]|soient|sera|seront)\s+(?:\S+\s+)?$")
# the words between a verb and the zone it governs: pronouns, articles, the
# nouns of a zone or of its cells, other zones joined to it ("vire-moi
# l'eau", "cache toutes les mailles d'huile", "masque l'eau et l'huile")
_ZONE_ON = (r"(?:[\s'’-]+(?:moi|nous|me|lui|leur|y|en|toi|vite|aussi|also|stp|svp|please|le|la|les|l|du|des|de|d|"
            r"un|une|ce|cet|cette|ces|mon|ma|mes|the|a|an|this|these|those|my|tout|tous|toute|toutes|all|every|"
            r"zones?|mailles?|cellules?|cells?|cases?|facies|fluides?|fluids?|lithologies?|valeurs?|values?|au|aux|"
            r"of|in|dans|et|and|" + _ANY_ZONE + r"))*[\s'’-]+")
# a verb that shows or keeps, said not as an order or a wish: what it names
# goes ("ne montre plus le gaz", "don't show the water", "je veux pas voir
# l'eau") -- the clause opens on the order, or "je" wishes it: "la vue ne
# montre pas l'huile" and "the view doesn't show the oil" say what a view
# does, nothing to hide
_NOT_SHOWING = re.compile(
    r"^(?:(?:stp|svp|please|alors|et|and|non|no|bon|ok)\s+)*"
    r"(?:(?:ne\s+|n.\s*)(?:(?:le|la|les|l.)\s*)?(?:montre|affiche|garde|conserve|laisse)[rz]?\s+(?:pas|plus|jamais)"
    r"|(?:don.?t|do not|never)\s+(?:show|display|keep)|(?:stop|quit)\s+(?:showing|displaying)"
    r"|arrete[rz]?\s+(?:de\s+|d.)(?:montrer|afficher))"
    r"|\b(?:je|j['’])\s*(?:ne\s+|n.\s*)?(?:veu[xt]|voudrai[st]|souhaite|aimerai[st])\s+(?:pas|plus)\s+"
    r"(?:voir|afficher|garder)"
    r"|\bi\s+(?:don.?t|do not)\s+(?:want|wanna|need)\s+(?:to\s+)?(?:see|keep)|\bi.?d rather not see"
    r"|\bi would rather not see|\b(?:can|could|would|will) you\s+(?:stop|quit)\s+(?:showing|displaying)")
# a word of going beside a seeing said not: what is not to be seen is the
# going ("je ne veux pas voir l'eau disparaître", "... l'eau cachée")
_GOES = re.compile(r"\b(?:" + _HIDE + r"|cachee?s?|masquee?s?|enlevee?s?|retiree?s?|supprimee?s?|disparai\w*|"
                   r"partir|hidden|removed|masked|gone|disappear\w*|vanish\w*)\b")


def _hidden_zone(folded, category):
    """Whether the sentence plainly hides the zone, where the model left
    exclude out: in the zone's clause a verb that hides governs it ("cache
    l'huile", "vire-moi l'eau") -- neither said done ("tu as caché
    l'huile") nor under a negation ("ne cache surtout pas le gaz", "évite
    de masquer l'eau") -- or a verb that shows or keeps is said not as an
    order or a wish (_NOT_SHOWING); and nothing in the sentence makes its
    polarity a matter of reading (_UNSURE). Anything less plain is the
    reader's to say: the application asks whether to hide the zone or keep
    it alone."""
    words = _zone_pattern(category)
    if not words or _UNSURE.search(folded):
        return False
    zone = _ZONE_ON + r"(?:" + words + r")s?\b"
    for clause in _CLAUSE.split(folded):
        clause = clause.strip()
        verbs = re.finditer(r"\b(?:" + _HIDE + r")" + zone, clause)
        if any(not _DONE.search(clause[:m.start()]) for m in verbs) and not _NEGATION.search(clause):
            return True
        said = _NOT_SHOWING.search(clause)
        rest = clause[:said.start()] + " " + clause[said.end():] if said else ""
        if said and re.match(zone, clause[said.end():]) and not _NEGATION.search(rest) and not _GOES.search(rest):
            return True
    return False


def settle_command(text, cmd, categories=()):
    """The command as the sentence settles it (see the readings above).
    `cmd` is the model's JSON, `categories` the values of the session's
    categorical properties (the zones a threshold can name). The copy
    returned differs on intent, well_filter, category and exclude only; a
    well filter or an exclude the model gave is kept, save a well filter on
    another gesture than well_cells and a negated crossing under no verb
    that keeps wells."""
    cmd = dict(cmd or {})
    f = _fold(text or "")
    p = _polarised(f)
    intent, well_filter, kind = cmd.get("intent"), cmd.get("well_filter"), cmd.get("kind")
    category = canonical_category(cmd.get("category"))
    known = {canonical_category(c) for c in categories} - {None}
    has_value = bool(kind) or cmd.get("min") is not None or cmd.get("max") is not None
    wells, crossing = bool(_WELL_WORDS.search(f)), bool(_CROSSES.search(f))
    # zones and wells
    if intent in ("show", "hide") and category in known and _zone_named(f, category, kind):
        # a fluid or facies zone shown or hidden is a threshold on its category
        cmd["intent"] = "threshold"
    elif (intent == "well_cells" and well_filter and not category and not has_value and not crossing
          and not _CELL_WORDS.search(f) and not _HIGHLIGHT_VERBS.search(f)):
        # a well filter with nothing to filter on -- no zone, value, cell or
        # crossing: the wells themselves, shown or hidden
        cmd["intent"] = "hide" if _hides(p) else "show"
        cmd["well_filter"] = None
    elif intent == "well_cells" and well_filter == "hide_crossing" and _negated_crossing(category).search(p) \
            and not _keeps_wells_not_crossing(p, category):
        # "remove the ones that do not cross / that stay out of the zone"
        # keeps the ones that do
        cmd["well_filter"] = "keep_crossing"
    elif intent == "well_cells" and not wells and not crossing and (category or has_value):
        # cells named with neither a well nor a crossing: a zone or a value
        # on the grid (a mistyped well -- "quels puis traversent" -- keeps
        # its crossing verb)
        cmd["intent"] = "highlight" if _HIGHLIGHT_VERBS.search(f) else "threshold"
        cmd["well_filter"] = None
    # the intents the model confuses, on what the readings above left
    intent2 = cmd.get("intent")
    if intent2 in ("unknown", "show", "list") and _BLOCKED_WELLS.search(_FAULT_BLOCKS.sub(" ", f)) \
            and not _DEFINE.search(f):
        # "les blocked wellbores", "les puits bloqués": the cells the wells
        # go through -- not a question on what they are
        cmd["intent"] = "well_cells"
    elif intent2 == "unknown" and _hides(p) and _WELL_NAMED.search(f) and not category:
        # "hide the wells" read as nothing
        cmd["intent"] = "hide"
    elif intent2 == "rescale" and (cmd.get("min") is not None or cmd.get("max") is not None):
        # bounds for the colour scale: a range, not a fit to the data
        cmd["intent"] = "color_range"
    elif intent2 == "value" and _PANEL_WORDS.search(f) and _OPENS.search(f) and not _STAT_WORDS.search(f) \
            and not _VALUE_ASKED.search(_WELL_NAMES.sub(" ", f)):
        # "montre-moi les stats de la porosité": a panel opened, not a
        # number -- unless a number is asked for ("quelle porosité lit-on
        # dans le log à 2600 m ?")
        cmd["intent"] = "open_panel"
    elif intent2 in ("flat_colors", "rescale", "color_range") and _PRESET_WORDS.search(f) and not has_value \
            and not _SHADING.search(f) and not _PRESET_KEPT.search(f) and not _RESCALE_VERBS.search(f):
        # a colour table named among the colour gestures -- not one kept
        # while the shading changes, nor the one fitted to the data
        cmd["intent"] = "colormap"
    elif intent2 not in ("complain", "undo") and _judged_wrong(f):
        # a complaint, even when it repeats what was wanted
        cmd["intent"] = "complain"
    elif intent2 not in ("complain", "reset_camera") and _SEES_NOTHING.search(f) and not _CAMERA.search(f) \
            and not _ACTS.search(f) and not _SEEN_FINE.search(f) and not _QUESTION.search(f):
        # "je ne vois que du gris", "je ne vois rien": the last reply missed
        cmd["intent"] = "complain"
    elif intent2 == "ask" and _PANEL_WORDS.search(f) and _OPENS.search(f) and _ASKS_FOR.search(f) \
            and not _INTERROGATIVE.search(f):
        # "tu peux comparer le log et la grille ?": a panel asked for as a
        # question
        cmd["intent"] = "open_panel"
    # the slots the final intent reads
    final = cmd.get("intent")
    if cmd.get("well_filter") and final != "well_cells":
        # a well filter on another gesture: nothing to filter
        cmd["well_filter"] = None
    if category and _in_kind(category, kind):
        # "la saturation en eau": the property, not the water zone
        cmd["category"] = category = None
    if final == "threshold" and category and not isinstance(cmd.get("exclude"), bool) \
            and _hidden_zone(f, category):
        # the model left exclude out, and a verb plainly hides the zone
        cmd["exclude"] = True
    return cmd


def clean_command(cmd, names, vocab=None, categories=()):
    """The model's JSON as the caller reads it: the intent among the
    catalogue's names, "ask" and "unknown" ("unknown" otherwise), and every
    key of the schema, null (or [] for objects) when the model left it out.
    The category is its usual name ("huile" -> "oil"), dropped when the
    session lists category values and it is none of them; a kind, panel or
    colour table outside the caller's vocab is dropped, a kind written
    "Water_Saturation" read "water saturation"; the question is kept for
    ask only."""
    cmd = cmd if isinstance(cmd, dict) else {}
    vocab = _vocab(vocab)
    intent = cmd.get("intent")
    out = {"intent": intent if isinstance(intent, str) and intent in set(names) | {"ask", "unknown"} else "unknown"}

    def name(value, allowed, loose=False):
        """`value` as the vocab spells it: a kind equal to one of its kinds
        once "_" and case aside, a panel or colour table equal to one or
        else the only one holding it ("viridis")."""
        if not isinstance(value, str) or not value.strip():
            return None
        key = " ".join((value.replace("_", " ") if loose else value).split()).lower()
        if not allowed:
            return key if loose else value.strip()
        same = next((a for a in allowed if " ".join((a.replace("_", " ") if loose else a).split()).lower() == key),
                    None)
        if same or loose:
            return same
        holding = [a for a in allowed if key in a.lower()]
        return holding[0] if len(holding) == 1 else None

    def number(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    known = {canonical_category(c) for c in categories} - {None}
    category = canonical_category(cmd.get("category")) if isinstance(cmd.get("category"), str) else None
    objects = cmd.get("objects") if isinstance(cmd.get("objects"), list) else []
    axis = str(cmd.get("axis") or "").strip().lower()
    question = cmd.get("question")
    out.update({
        "kind": name(cmd.get("kind"), vocab.kinds, loose=True),
        "category": category if category and (not known or category in known) else None,
        "exclude": cmd.get("exclude") if isinstance(cmd.get("exclude"), bool) else None,
        "min": number(cmd.get("min")), "max": number(cmd.get("max")),
        "objects": [o for o in objects if isinstance(o, str) and o.strip()],
        "well_filter": cmd.get("well_filter") if cmd.get("well_filter") in ("keep_crossing", "hide_crossing") else None,
        "panel": name(cmd.get("panel"), vocab.panels), "preset": name(cmd.get("preset"), vocab.presets),
        "axis": axis if axis in ("i", "j", "k") else None,
        "factor": number(cmd.get("factor")),
        "on": cmd.get("on") if isinstance(cmd.get("on"), bool) else None,
        "question": question if out["intent"] == "ask" and isinstance(question, str) and question.strip() else None})
    return out


def read_command(text, cmd, names, vocab=None, categories=()):
    """What /v1/command returns for the model's JSON `cmd`: cleaned (every
    key; an intent the caller did not offer is "unknown", a name outside
    its vocab null), then settled by the sentence when the settled intent
    is one the caller offers, and cleaned again (a question read as a panel
    keeps no question)."""
    cmd = clean_command(cmd, names, vocab, categories)
    settled = settle_command(text, cmd, categories)
    return clean_command(settled, names, vocab, categories) if settled.get("intent") in set(names) else cmd


def session_categories(objects):
    """The category values of the session's objects (each object's
    "categories": a list of labels, or a code -> label table)."""
    out = []
    for o in objects or ():
        values = o.get("categories") if isinstance(o, dict) else None
        if isinstance(values, dict):
            values = list(values.values())
        out += [str(v) for v in values if v not in (None, "")] if isinstance(values, (list, tuple)) else []
    return out


# what a panel of the application is, for the names that do not say it
_PANEL_GLOSS = {"welllog": ("les logs d'un puits", "a well's logs"),
                "reconcile": ("le log d'un puits face à la grille", "a well log against the grid"),
                "compare": ("des propriétés comparées entre elles", "properties compared together"),
                "health": ("la qualité des données", "the data's quality")}


def _vocab_value(word, values):
    """The vocab's own spelling of `word` ("inferno" -> "Inferno
    (matplotlib)"), or None when it has no such entry."""
    w = word.lower()
    return next((v for v in values if v.lower() == w), None) or next((v for v in values if w in v.lower()), None)


def _session_zones(objects):
    """The session's category values, each once, in order: (the label as
    the session spells it, the value as the schema enumerates it)."""
    zones = {}
    for label in session_categories(objects):
        value = _fold(label).strip()
        if value:
            zones.setdefault(value, " ".join(label.split()))
    return [(label, value) for value, label in zones.items()]


def _zone_example(text, out, zones, spare):
    """An example that names a zone, as the session can hear it: as it is
    when the session lists no zone or has that value; with the session's
    own spelling of the same zone ("huile" for oil); else said on another
    value of the session, taken in turn from `spare` -- the zone's words in
    the sentence replaced by its label ("le siltstone" -> "la zone
    Channel"), its lesson (a filter, an exclude, a question) unchanged. The
    prompt so never shows a category the schema of the same request
    refuses. (text, out), or None when the sentence names no word of its
    zone."""
    category = out.get("category")
    values = [value for _label, value in zones]
    if not category or not zones or category in values:
        return text, out
    same = next((value for value in values if canonical_category(value) == category), None)
    if same:
        return text, {**out, "category": same}
    folded = _fold(text)
    words = "|".join(re.escape(w) for w in sorted(_zone_words(category), key=len, reverse=True))
    m = re.search(r"\b(?:(?P<zone>(?:la|les)\s+zones?)\s+(?:a|d.|de)\s*|(?P<det>du|le|la|l.|d.)\s*)?"
                  r"(?:" + words + r")s?\b", folded)
    if m is None or len(folded) != len(text):
        return None
    label, value = next(spare)
    if m.group("zone"):
        said = f"{text[m.start('zone'):m.end('zone')]} {label}"
    elif m.group("det"):
        said = f"{'de la' if m.group('det').startswith('d') else 'la'} zone {label}"
    else:
        said = label
    return text[:m.start()] + said + text[m.end():], {**out, "category": value}


def _example(text, out, vocab):
    """An example line, its panel and colour table spelt as the vocab
    spells them (and left out when the vocab has none)."""
    out = dict(out)
    for key, values in (("panel", vocab.panels), ("preset", vocab.presets)):
        if key in out:
            value = _vocab_value(out[key], values)
            if value:
                out[key] = value
            else:
                del out[key]
    return f"« {text} » → {json.dumps(out, ensure_ascii=False)}"


def command_prompt(req, glossary):
    """The system prompt of /v1/command, in the order of what changes: the
    catalogue, the rules (with the caller's vocab) and the examples that
    name no zone, the same for every session; then the examples that name a
    zone, said on the session's own values; then the session's objects;
    then the glossary read for the sentence's domain words. llama-server's
    prefix cache (cache_prompt) keeps everything before the first line that
    differs: a change of session re-reads its zone examples and its objects
    only, a new sentence its glossary only."""
    fr = req.lang == "fr"
    vocab = _vocab(req.vocab)
    lines = ["Tu traduis UNE phrase d'utilisateur en UNE commande du visualiseur fespp_on_trame. "
             "Réponds uniquement par le JSON demandé." if fr else
             "You turn ONE user sentence into ONE command of the fespp_on_trame viewer. "
             "Answer only with the JSON asked for."]
    lines.append("Commandes :" if fr else "Commands:")
    for c in req.catalogue:
        desc = c.get("fr" if fr else "en") or c.get("fr") or ""
        lines.append(f"- {c.get('name')} : {desc}")
    lines.append("- ask : une question sur le métier ou l'application, pas sur la réponse précédente "
                 "(met la question dans question)" if fr else
                 "- ask: a question on the domain or the app, not on the previous reply (the question goes in "
                 "question)")
    lines.append("- unknown : rien de tout cela" if fr else "- unknown: none of these")
    kinds = ", ".join(vocab.kinds or DEFAULT_KINDS)
    panels = ", ".join(f"{p} ({_PANEL_GLOSS[p][0 if fr else 1]})" if p in _PANEL_GLOSS else p for p in vocab.panels)
    presets = ", ".join(vocab.presets)
    if fr:
        lines += [
            "Règles : n'écris que les clés que la phrase remplit.",
            f"- kind : le type de propriété nommé, parmi {kinds} ; jamais un titre d'objet ni une statistique.",
            "- category : une valeur des propriétés catégorielles de la session (listées à la fin), quels que soient "
            "les mots (pétrole → oil, argile → shale) ; une zone que la phrase nomme, pas un mot du kind (« saturation "
            "en gaz » est un kind). exclude : true quand la phrase cache cette zone et garde le reste.",
            "- min et max : les nombres de la phrase (« au-dessus de 0,2 » → min 0.2 ; « moins de 12 » → max 12) ; un "
            "pourcentage de porosité, de saturation ou de net to gross est une fraction (15 % → 0.15).",
            "- objects : seulement les titres que la phrase nomme, sinon [].",
            "- well_filter (seulement pour well_cells) : keep_crossing = seuls les puits qui traversent la zone "
            "restent — « isole ceux qui la traversent », « enlève ceux qui restent à l'écart de la zone, qui ne la "
            "touchent pas », « vire tous les autres », « des puits sont encore hors de la zone » ; hide_crossing = les "
            "puits qui traversent partent. Sans verbe qui enlève ou garde des puits (« des puits y passent ? », "
            "« combien ? »), pas de well_filter.",
            (f"- panel (open_panel) : parmi {panels}" if panels else "- panel (open_panel) : le panneau nommé")
            + (f" ; preset (colormap) : parmi {presets}" if presets
               else " ; preset (colormap) : la table de couleurs nommée")
            + " ; axis (slice) : i, j ou k ; factor (z_scale) : le facteur ; on (hide_nan, flat_colors) : true pour "
              "activer, false pour désactiver.",
            "- question : seulement pour ask."]
    else:
        lines += [
            "Rules: write only the keys the sentence fills.",
            f"- kind: the property kind named, among {kinds}; never an object's title nor a statistic.",
            "- category: a value of the session's categorical properties (listed at the end), whatever the words "
            "(petroleum → oil, clay → shale); a zone the sentence names, not a word of the kind ('gas saturation' is "
            "a kind). exclude: true when the sentence hides that zone and keeps the rest.",
            "- min and max: the numbers of the sentence ('above 0.2' → min 0.2; 'less than 12' → max 12); a "
            "percentage of porosity, saturation or net to gross is a fraction (15 % → 0.15).",
            "- objects: only the titles the sentence names, otherwise [].",
            "- well_filter (well_cells only): keep_crossing = only the wells crossing the zone stay — 'isolate those "
            "that cross it', 'remove those staying away from the zone, not touching it', 'get rid of all the others', "
            "'some wells are still outside the zone'; hide_crossing = the crossing wells go. With no verb that "
            "removes or keeps wells ('do wells cross it?', 'how many?'), no well_filter.",
            (f"- panel (open_panel): among {panels}" if panels else "- panel (open_panel): the panel named")
            + (f"; preset (colormap): among {presets}" if presets else "; preset (colormap): the colour table named")
            + "; axis (slice): i, j or k; factor (z_scale): the factor; on (hide_nan, flat_colors): true to turn "
              "on, false to turn off.",
            "- question: ask only."]
    lines.append("Exemples :" if fr else "Examples:")
    zones = _session_zones(req.objects)
    spare = itertools.cycle(zones)
    examples = (_zone_example(text, out, zones, spare) for text, out in _COMMAND_EXAMPLES)
    lines += [_example(text, out, vocab) for text, out in filter(None, examples)]
    if req.objects:
        lines.append("Objets de la session :" if fr else "Objects of the session:")
        for o in req.objects[:60]:
            extra = []
            if o.get("kind"):
                extra.append(str(o["kind"]))
            values = session_categories([o])
            if values:
                extra.append(("valeurs : " if fr else "values: ") + ", ".join(values))
            lines.append(f"- {o.get('title')} ({o.get('type')}" + (", " + "; ".join(extra) if extra else "") + ")")
    if glossary:
        lines.append("Glossaire (extraits de la documentation, pour les mots du métier) :" if fr else
                     "Glossary (documentation extracts, for the domain words):")
        for _score, c in glossary:
            lines.append(f"- {c.get('title')} : {c.get('text', '')[:GLOSSARY_CHARS]}")
    return "\n".join(lines)


def load_index(index_dir, embed_dir, say=print):
    """The RAG index when both folders are there, else None (said once)."""
    if not (index_dir and embed_dir and os.path.isdir(index_dir) and os.path.isdir(embed_dir)):
        say(f"[fespp_ia] no RAG index ({index_dir}) or embedding model ({embed_dir}): /v1/ask is off", flush=True)
        return None
    try:
        from fespp_ia.rag import Index
        idx = Index.load(index_dir, embed_dir)
        say(f"[fespp_ia] RAG index: {idx.meta}", flush=True)
        return idx
    except Exception as exc:
        say(f"[fespp_ia] RAG index unusable: {exc}", flush=True)
        return None


def create_app(client=None, llama=None, parallel=None, queue_timeout=None, index=None, load_rag=True):
    """The FastAPI app of the /v1 contract.

    `client` speaks to llama-server (a fake in the tests); `llama` is the
    child process, started with the app when given; `index` a loaded RAG
    index (a fake in the tests), else loaded from the environment when
    `load_rag`. `parallel` and `queue_timeout` default to FESPP_IA_PARALLEL
    and FESPP_IA_QUEUE_TIMEOUT."""
    parallel = parallel or int(os.environ.get("FESPP_IA_PARALLEL", "1"))
    queue_timeout = (queue_timeout if queue_timeout is not None
                     else float(os.environ.get("FESPP_IA_QUEUE_TIMEOUT", "30")))
    gate = asyncio.Semaphore(parallel)
    counts = {"busy": 0, "waiting": 0}
    http = client or httpx.AsyncClient(base_url=f"http://127.0.0.1:{LLAMA_PORT}",
                                       timeout=httpx.Timeout(600.0, connect=5.0))
    rag = {"index": index}

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        if llama is not None:
            llama.start()
        if rag["index"] is None and load_rag:
            rag["index"] = await asyncio.to_thread(load_index, os.environ.get("FESPP_IA_INDEX"),
                                                   os.environ.get("FESPP_IA_EMBED"))
        try:
            yield
        finally:
            if llama is not None:
                llama.stop()
            if client is None:
                await http.aclose()

    app = FastAPI(title="fespp_ia", version=API_VERSION, lifespan=lifespan)

    def model_name():
        return llama.model.stem if llama is not None and llama.model else "unknown"

    async def complete(messages, schema=None, max_tokens=512, temperature=0.2):
        """ONE generation through the gate: {text, model, tokens, seconds, tokens_per_second}.
        A 503 when no slot frees within the queue timeout or the model does
        not answer, a 502 when it refuses."""
        counts["waiting"] += 1
        try:
            await asyncio.wait_for(gate.acquire(), timeout=queue_timeout)
        except asyncio.TimeoutError:
            raise HTTPException(503, "busy: every slot is taken, try again")
        finally:
            counts["waiting"] -= 1
        counts["busy"] += 1
        try:
            body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                    "cache_prompt": True}
            if schema is not None:
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
            t0 = time.monotonic()
            try:
                r = await http.post("/v1/chat/completions", json=body)
            except httpx.HTTPError as exc:
                raise HTTPException(503, f"the model does not answer: {exc}")
            if r.status_code != 200:
                raise HTTPException(502, f"the model refused: {r.status_code} {r.text[:300]}")
            data = r.json()
            seconds = time.monotonic() - t0
            tokens = int((data.get("usage") or {}).get("completion_tokens") or 0)
            return {"text": data["choices"][0]["message"]["content"], "model": model_name(),
                    "tokens": tokens, "seconds": round(seconds, 3),
                    "tokens_per_second": round(tokens / seconds, 1) if seconds > 0 else 0.0}
        finally:
            counts["busy"] -= 1
            gate.release()

    @app.get("/v1/health")
    async def health():
        idx = rag["index"]
        out = {"api": API_VERSION, "model": model_name(), **counts,
               "rag": (idx.meta if idx is not None and getattr(idx, "meta", None) else None)}
        if llama is not None and llama.model is None:
            return {**out, "status": "no_model", "error": llama.error}
        if llama is not None and not llama.alive():
            return {**out, "status": "error", "error": "llama-server stopped"}
        try:
            r = await http.get("/health")
        except httpx.HTTPError:
            return {**out, "status": "loading"}
        return {**out, "status": "ok" if r.status_code == 200 else "loading"}

    @app.post("/v1/chat")
    async def chat(req: ChatRequest):
        return await complete([m.model_dump() for m in req.messages], req.schema_, req.max_tokens, req.temperature)

    @app.post("/v1/ask")
    async def ask(req: AskRequest):
        idx = rag["index"]
        if idx is None:
            raise HTTPException(503, "no index: the RAG is not built (ia/build-index.ps1)")
        hits = await asyncio.to_thread(idx.search, req.question, req.k, req.sources)
        # each extract capped (EXTRACT_CHARS): on a CPU the length of the
        # prompt sets the response time, and an answer sits in an extract's
        # first lines
        extracts = "\n\n".join(f"[{c.get('title')}] ({c.get('source')}, {c.get('path')})\n"
                               f"{c.get('text', '')[:EXTRACT_CHARS]}" for _s, c in hits)
        user = (f"Question : {req.question}\n\nExtraits :\n{extracts}" if req.lang == "fr"
                else f"Question: {req.question}\n\nExtracts:\n{extracts}")
        out = await complete([{"role": "system", "content": _ASK_SYSTEM[req.lang]},
                              {"role": "user", "content": user}], None, req.max_tokens, 0.1)
        out["sources"] = [{"title": c.get("title"), "source": c.get("source"), "path": c.get("path"),
                           "score": round(s, 3)} for s, c in hits]
        return out

    @app.post("/v1/command")
    async def command(req: CommandRequest):
        names = [str(c.get("name")) for c in req.catalogue if c.get("name")]
        if not names:
            raise HTTPException(422, "an empty catalogue")
        # the glossary only when the sentence names a notion the prompt
        # itself does not: it is the one part of the prompt that changes
        # per call, hence the one part paid for
        glossary = []
        idx = rag["index"]
        if idx is not None and req.k and new_words(req.text, command_prompt(req, [])):
            glossary = await asyncio.to_thread(idx.search, req.text, req.k, GLOSSARY_SOURCES)
        categories = session_categories(req.objects)
        out = await complete([{"role": "system", "content": command_prompt(req, glossary)},
                              {"role": "user", "content": req.text}],
                             command_schema(names, req.vocab, categories), req.max_tokens, 0.0)
        try:
            cmd = json.loads(out["text"])
        except ValueError:
            cmd = {"intent": "unknown"}
        out["command"] = read_command(req.text, cmd, names, req.vocab, categories)
        out["glossary"] = [c.get("title") for _s, c in glossary]
        return out

    return app


def main():
    import uvicorn
    uvicorn.run(create_app(llama=LlamaProcess()), host="0.0.0.0",
                port=int(os.environ.get("FESPP_IA_PORT", "8000")))


if __name__ == "__main__":
    main()
