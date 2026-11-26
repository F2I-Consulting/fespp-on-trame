"""The parameters of a sentence, and the sentence without them.

`spans(tokens, objects)` finds, in the normalised tokens, what the lexicon
and the session name: property kinds, panels, colour tables, axes, groups,
category values, numbers, and the objects of the session by their title.
Each span is ``(start, end, type, value, score)``; spans never overlap, and
the longest phrase wins.

`delex(tokens, spans)` puts a placeholder in their place — "montre la
porosite de hugin au dessus de 0.2" becomes "montre la <kind> de <obj> au
dessus de <num>": the classifier learns the SHAPE of the sentence, not the
names, and a grid it never saw reads like one it did.

`read(tokens, spans)` gives the command's parameters: object candidates,
kind, bounds (min / max, from "above", "between … and …", "10-20", "min =
3"), free numbers, panel, preset, axis, group, category values, on/off.

Two numbers joined by a hyphen are a range ("0,1-0,3", "10-20") unless
they name an object of the session: "9-19 A" is the end of `15/9-19 A`,
"le puits 11-15" the well `25/11-15`.
"""
import re

from fespp_on_trame.ia.nlu import bilingual, lexicon
from fespp_on_trame.ia.nlu.text import normalize

_NUM = re.compile(r"^-?\d+(?:\.\d+)?%?$")
# two numbers joined by a hyphen: a range, or a piece of a name
RANGE = re.compile(r"^(-?\d+(?:\.\d+)?)(%?)-(\d+(?:\.\d+)?)(%?)$")
# what may follow a number as its unit
UNITS = frozenset("""
% pourcent percent pct m ft feet metres meters metre meter md mdarcy darcy darcys mdarcys d
mm cm km s ms us gapi api ohm ohmm ohm.m kg g bar psi kpa mpa pa degc degf deg c f
m3 m3/m3 v/v frac fraction fractions unites unite units unit gcc g/cc g/cm3 kg/m3 us/ft
""".split())
_TIMES = re.compile(r"^(?:x(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)x)$")

# words that never make an object mention on their own: articles,
# pronouns, the little words of both languages — "it" is not the end of
# PHIT, "ne" not of "Draupne fine", "voir" not of "Top Reservoir"
STOP = frozenset("""
le la les l un une des de du d a au aux en et ou sur dans pour par avec sans ce cet cette ces
mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs qui que quoi quel quelle quels
quelles est sont the a an of in on for to and or with without this that these those my your
its their is are be what which show me moi puis stp svp please peux tu peut on can you could
grille grid puits well wellbore log logs surface horizon propriete property vue view
ne n il ils elle elles j je t te s c qu y se si nous vous lui ca cela ceci pas plus moins tres
dit dis voir vois es suis ai as avait avais etait tout tous toute toutes aussi encore deja
it at so i im we us do does did don doesn isn aren not no yes as by from into onto up out off
all any some just only also too very if then than but been was were has have had get got let
lets ll re ve m o
""".split())
# the sorts of things a sentence names in general ("the zones", "the
# model", "the blocks of the wells"): alone they name an object only by
# its exact title — "zone" is not Volve_SGrid_OilZone, "blocks" not
# fault_blocks, "model" not Sw_model
GENERIC = frozenset("""
zone zones bloc blocs block blocks modele modeles model models maillage reservoir reservoirs grille grilles grid
grids puits puit well wells wellbore wellbores forage forages faille failles fault faults horizon horizons surface
surfaces couche couches layer layers log logs maille mailles cellule cellules cell cells propriete proprietes
property properties trajectoire trajectoires trajectory trajectories
""".split())


def _phrases(table):
    """{canonical: (phrase, …)} -> [(tokens, canonical)], longest first."""
    out = [(tuple(normalize(p).split()), c) for c, ps in table.items() for p in ps]
    return sorted((o for o in out if o[0]), key=lambda o: -len(o[0]))


_KIND_PHRASES = _phrases({k: v["say"] for k, v in lexicon.KINDS.items()})
_PANEL_PHRASES = _phrases(lexicon.PANELS)
_PRESET_PHRASES = _phrases(lexicon.PRESETS)
_AXIS_PHRASES = _phrases(lexicon.AXES)
_GROUP_PHRASES = _phrases(lexicon.GROUPS)
# the words of the view's gestures, read where they are said (never a span:
# "nord" may end a title, "points" sits in "nuage de points", "log" names a
# well log) — the classifier sees them as they are
_DIRECTION_PHRASES = _phrases(lexicon.DIRECTIONS)
_ZOOM_OUT_PHRASES = _phrases({"out": lexicon.ZOOM["out"]})
_STEP_PHRASES = _phrases(lexicon.STEPS)
_STYLE_PHRASES = _phrases(lexicon.STYLES)
_SCALE_PHRASES = _phrases(lexicon.SCALES)
_TOOL_PHRASES = _phrases(lexicon.TOOLS)
_TOOL_IF_OPENED = _phrases(lexicon.TOOLS_IF_OPENED)
_ORDINAL_WORDS = {normalize(w): n for n, ws in lexicon.ORDINALS.items() for w in ws}
# "3e", "3eme", "1er", "2nd", "3rd", "4th": a rank written with its number
_ORDINAL = re.compile(r"^(\d+)(?:e|er|ere|re|eme|nd|rd|st|th)$")
# a date a time step may be named by ("2020-01-01", "01/01/2020", "06/2020"):
# kept as said, the adapter matches it against the time labels
_DATE = re.compile(r"^(?:\d{4}-\d{1,2}(?:-\d{1,2})?|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{4})$")
_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
_TOWARD = frozenset(("vers", "towards", "toward", "facing", "face"))
# … which, alone, name an object only by its exact title: "nord" is not the
# end of "Faille nord", "final" not of PHIT_final, "points" no title
_GESTURE_WORDS = frozenset(w for table in (lexicon.DIRECTIONS, lexicon.ZOOM, lexicon.STEPS, lexicon.STYLES,
                                           lexicon.SCALES, lexicon.TOOLS, lexicon.TOOLS_IF_OPENED)
                           for ps in table.values() for p in ps for w in normalize(p).split())
# a lone i / j / k is an axis only where a slice is spoken of: the "j" of
# "j'aime" is not one
_AXIS_CONTEXT = frozenset(("selon", "suivant", "en", "along", "axe", "axis", "direction", "coupe",
                           "slice", "cut", "section", "tranche", "la", "the", "in", "on", "by", "sur", "de",
                           "plan", "plane"))
# … or before a word that makes it one: "a J section", "i direction", "an I
# cut", "k = 10", "où k vaut 12", "where k equals 12" — but the English "I"
# of "I cut the grid" is no axis: an "i" needs a word before it that says so
_AXIS_AFTER = frozenset(("section", "sections", "direction", "slice", "slices", "coupe", "coupes", "plane",
                         "planes", "plan", "axis", "index", "indice", "cut", "cuts", "=", "vaut", "egal", "egale",
                         "equals", "equal"))
_I_BEFORE = _AXIS_CONTEXT | {"a", "an", "une", "un", "le"}
# … and never the "I" of "in I want a slice", "by I mean": the pronoun
# before its verb
_I_VERBS = frozenset("""
want wanted wanna think thought mean meant need needed would will can could should shall am m d ll ve have
had guess see saw said say asked ask believe wish like know don do did just really also hope feel prefer told
tell get got love only still
""".split())
# the words of a slice: there, "k 1" is a layer, not a title K1
_SLICE_WORDS = frozenset(("coupe", "coupes", "couper", "slice", "slices", "cut", "cuts", "tranche", "trancher",
                          "section", "sections", "plan", "plane", "couche", "couches", "layer", "layers", "selon",
                          "along", "axe", "axis"))
_ABOVE = [tuple(normalize(p).split()) for p in lexicon.ABOVE]
_BELOW = [tuple(normalize(p).split()) for p in lexicon.BELOW]
_EQUAL = [tuple(normalize(p).split()) for p in lexicon.EQUAL]
# every bound phrase, longest first: "pas plus de" is a maximum though
# "plus de" is a minimum, "superieur ou egal a" a minimum though "egal a"
# is a value
_BOUNDS = sorted([(p, "min") for p in _ABOVE] + [(p, "max") for p in _BELOW] + [(p, "eq") for p in _EQUAL],
                 key=lambda b: -len(b[0]))
_ON = [tuple(p.split()) for p in lexicon.ON]
_OFF = [tuple(p.split()) for p in lexicon.OFF]


# the names of sorts of objects, and what their RESQML type contains
NOUNS = {"puits": "well", "puit": "well", "well": "well", "wells": "well", "wellbore": "well",
         "wellbores": "well", "forage": "well", "forages": "well", "borehole": "well", "boreholes": "well",
         "trajectoire": "well", "trajectoires": "well", "trajectory": "well", "trajectories": "well",
         "faille": "fault", "fault": "fault", "horizon": "horizon", "surface": "horizon",
         "zone": "zone", "grille": "grid", "grid": "grid"}
# the app's types are FESPP's short names (IjkGrid, Grid2d, Wellbore,
# TriangulatedSet…): a Grid2d is a surface, not a grid; a fault is a
# triangulated set whose title says so
_FAMILY_TYPES = {"well": ("wellbore",), "fault": ("fault",),
                 "horizon": ("horizon", "grid2d", "triangulated", "surface"),
                 "zone": ("zone", "stratigraphic"), "grid": ("ijkgrid", "unstructuredgrid")}
_FAULT_WORDS = ("fault", "faille", "flt")
# the sort of object a noun says when it is said WITHOUT a name
FAMILY_NOUNS = {"grille": "grid", "grid": "grid", "modele": "grid", "model": "grid", "maillage": "grid",
                "puits": "well", "puit": "well", "well": "well", "wells": "well", "wellbore": "well",
                "wellbores": "well", "forage": "well", "forages": "well", "borehole": "well", "boreholes": "well",
                "trajectoire": "well", "trajectoires": "well", "trajectory": "well", "trajectories": "well",
                "horizon": "horizon", "surface": "horizon", "faille": "fault", "fault": "fault"}
_TRAILING = re.compile(r"(\d+)\s*[a-z]?\s*$")


def _trailing_number(title):
    """The number a title ends with, without leading zeros ("Well 07" ->
    "7", "15/9-F-11 A" -> "11"), or None."""
    m = _TRAILING.search(normalize(title))
    return m.group(1).lstrip("0") or "0" if m else None


def _family_ok(fam, obj):
    """An object of that sort: by its type when the session gives one (a
    well is a Wellbore…), any object otherwise."""
    t = (obj.get("type") or "").lower()
    if not t:
        return True
    faulty = any(w in normalize(obj.get("title", "")) for w in _FAULT_WORDS)
    if fam == "fault":
        return "fault" in t or (faulty and ("triangulated" in t or "polyline" in t))
    if fam == "horizon" and faulty:
        return False
    return any(k in t for k in _FAMILY_TYPES[fam])


def _compact(s):
    return re.sub(r"[^a-z0-9]", "", normalize(s))


def _pieces(s):
    """Letters and digits apart, and the words of a name written in camel
    case: "15/9-F-1_A" -> 15, 9, f, 1, a; "TopVolantis" -> top, volantis."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s or ""))
    return [p for p in re.split(r"[^a-z0-9]+|(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])", normalize(s)) if p]


def _has_run(pieces, run):
    """Are the pieces of `run` among `pieces`, whole, in order and side by
    side (numbers compared without their leading zeros)?"""
    def norm(p):
        return p.lstrip("0") or "0" if p.isdigit() else p
    have, want = [norm(p) for p in pieces], [norm(p) for p in run]
    return any(have[k:k + len(want)] == want for k in range(len(have) - len(want) + 1))


def _trigrams(s):
    s = f"  {s} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def object_score(mention_tokens, title):
    """How well a few words of the sentence name `title`: 1 the same, 0.85
    the end of it ("f-4" for "15/9-F-4"), else the trigram overlap."""
    m, t = _compact(" ".join(mention_tokens)), _compact(title)
    if not m or not t:
        return 0.0
    if m == t:
        return 1.0
    # the same name in the other language ("modèle structural" is
    # `Structural model`, "lithologie" is `Lithology1`): bilingual.py
    if bilingual.same_name(mention_tokens, title):
        return 0.9
    # the end of the name, from one of its pieces on: "f-4" ends "15/9-F-4"
    # (15, 9, f, 4), "hugin" ends "Top Hugin", "volantis" TopVolantis — a
    # word that only ends with the same letters does not ("it" and PHIT,
    # "ne" and "Draupne fine")
    if len(m) >= 2 and not m.isdigit():
        tp = _pieces(title)
        if any("".join(tp[k:]) == m for k in range(1, len(tp))):
            return 0.85
    # the mention's pieces, whole and in order, among the title's pieces:
    # "F-1 A" in "well_feature_NO_15_9-F-1_A_84B691" (f, 1, a) — not inside
    # "F-11" (f, 11), not "F1 fault" (f1). A digit, several pieces or a long
    # word, so "top" alone does not name every Top-something; digits alone
    # only as several pieces ("33-1" is the end of 55/33-1, "2500" nothing)
    mp, tp = _pieces(" ".join(mention_tokens)), _pieces(title)
    if mp and (any(c.isdigit() for c in m) or len(mp) > 1 or len(m) >= 5) and (not m.isdigit() or len(mp) > 1):
        for k in range(len(tp) - len(mp) + 1):
            if tp[k:k + len(mp)] == mp:
                return 0.85
    # the start of a name, with a digit in it: "F1" for "F1 fault"
    if len(m) >= 2 and t.startswith(m) and any(c.isdigit() for c in m) and not m.isdigit() \
            and not t[len(m):len(m) + 1].isdigit():
        return 0.8
    # a piece of a long generated name: "F-1 A" in "well_feature_NO_15_9-F-1_A_84B691";
    # letters AND digits, so a plain word never hits by chance, and less sure
    # when a digit follows ("f1" inside "f11")
    if len(m) >= 3 and any(c.isdigit() for c in m) and any(c.isalpha() for c in m):
        at = t.find(m)
        if at >= 0:
            after = t[at + len(m):at + len(m) + 1]
            return 0.65 if after.isdigit() else 0.75
    a, b = _trigrams(m), _trigrams(t)
    return len(a & b) / len(a | b)


def edit_distance(a, b, cap=3):
    """Letters added, dropped, changed or swapped to go from `a` to `b`
    (optimal string alignment); anything above `cap` is `cap + 1`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return min(prev[-1], cap + 1)


_KNOWN = None

# real words close to a word of the lexicon, that the patterns do not use
_ALSO_KNOWN = ("session", "sessions", "range", "ranger", "state", "states", "ferme", "fermer",
               "coche", "cocher", "presse", "position", "passion", "station", "stable", "rangs",
               "lignee", "couche", "linge", "totale", "total", "persil", "donnees", "donnee",
               "think", "thinks", "thinking", "thought", "thin", "thing", "things")
# the words the engine reads as cues (engine.py, multi.py: verbs, crossing,
# highlighting, hiding, statistics…) that the patterns do not use — a cue is
# said on purpose, never a slip of a word of the lexicon ("perce" is not
# "perme", "calcule" not "calcul"); tests/unit/test_nlu.py checks the list
# against the engine's
_CUE_WORDS = """
affichages affiches affichez allumer annuler apparaitre appliquer arreter arretez atteignent atteindre atteint
blocked bloque bloques bring brille briller cachez calcule calculer calcules cancel cesse cessez change changer changes
clear coches colore colores colories coloriez comment compute conserve conserver coupent couper croise croisee
croisees croisent croises cross crossed crosses crossing cutoff decrire degager degage desactivee desactiver
desactives desactivez desurligne disable display drilled dropped efface effacer effaces effacez enleves enlevez
eteindre eteint exceed exceeding exceeds excede exclude exclus exclure existe filtres filtrez flag flagged garde
gardes gardez glow go goes going highlite hilight hit intersect intersected intersection intersections
intersects isole isolez keeps light lit marque marquer marquez mask masks masques masquez mettre montres
montrez outline outlined passe passes pass passing penetrate penetrated penetrates perce percee percees
percent pointe pop recadrer recentre recentrez recoupe recoupees recoupent remets remettez remettre remove
removed rencontre rencontrees rencontrent rentre rentrent repere reperer retires retirez scales see seen shade
shown signale signaler spotlight stand stays supprimes supprimez surlignage surligne surlignee surlignees
surligner surlignes surlignez surbrillance throw touch touche touchent touches traverse traversed traversee
traversees traversent traverses unhide unhighlight vire virer vires virez visible voit
""".split()

# the short mnemonics of the lexicon ("rdeep", "gassat"): a slip toward one
# of them is more likely a real word ("deep") than a mistyped kind
_NO_SLIP = frozenset(("rdeep", "resis", "gassat", "vshale", "litho", "swat", "soil", "sgas", "rhob", "nphi",
                      "tnph", "vclay", "permx", "klogh", "watsat"))
# mnemonics that are everyday words too ("so", "près", "à côté"): a kind
# only right before what is said of it — a bound or a number ("So above
# 0.5", "so > 0.5"), never "so show me…"
_SHARED = {"so": "oil saturation", "pres": "pressure", "cote": "depth"}


def known_words():
    """Every word the patterns, the lexicon, the stop list and the engine's
    cues use: a word a reader types ON PURPOSE. Only an unknown word can be
    a slip — "session" is a word, not a mistyped "pression"."""
    global _KNOWN
    if _KNOWN is None:
        from fespp_on_trame.ia.nlu import generate
        words = set(STOP) | set(GENERIC) | set(_ALSO_KNOWN) | set(_CUE_WORDS)
        # the words of the view's gestures are said on purpose too ("arete"
        # is no slipped verb, "filaire" no slipped kind)
        for table in (lexicon.DIRECTIONS, lexicon.ZOOM, lexicon.STEPS, lexicon.STYLES, lexicon.SCALES,
                      lexicon.TOOLS, lexicon.TOOLS_IF_OPENED):
            for ps in table.values():
                for p in ps:
                    words.update(normalize(p).split())
        words.update(w for ws in lexicon.ORDINALS.values() for w in ws)
        for pats in generate.PATTERNS.values():
            for pat in pats:
                words.update(normalize(re.sub(r"^\d+\*|[\[\]()|{}]", " ", pat)).split())
        _KNOWN = frozenset(words)
    return _KNOWN


def typo_budget(word):
    """How many slips a word of the lexicon forgives: none under 5 letters
    ("gamma" must not catch "grand", "sw" nothing), one up to 7, two beyond."""
    return 0 if len(word) < 5 else 1 if len(word) <= 7 else 2


_CATEGORY_SAY = {normalize(w): c for c, ws in lexicon.CATEGORIES.items() for w in ws}


def category_of(label):
    """The canonical value a category label stands for: "Oil", "huile" ->
    "oil"; a label the lexicon does not know stands for itself (normalised)."""
    n = normalize(label)
    return _CATEGORY_SAY.get(n, n)


def _category_phrases(objects):
    """[(tokens, canonical)] for the category values the session holds —
    every label of every categorical property, and the lexicon's ways of
    saying the ones it knows ("huile" for oil). Empty without categories:
    no word is ever a category value in a session that has none."""
    have = set()
    for o in objects or ():
        for label in (o.get("categories") or {}).values():
            if label not in (None, ""):
                have.add(category_of(str(label)))
    if not have:
        return []
    table = {c: [c] + [w for w, cc in _CATEGORY_SAY.items() if cc == c] for c in have}
    return _phrases(table)


def _match_at(tokens, i, phrases, fuzzy=False):
    """(length, canonical) of the phrase that starts at token `i`, or
    (0, None); `fuzzy` forgives slipped letters, the fewest winning."""
    if not fuzzy:
        for p, c in phrases:
            if tuple(tokens[i:i + len(p)]) == p:
                return len(p), c
        return 0, None
    # a slipped letter in ONE word of a phrase ("permeabilte", "saturaton de
    # l eau"): the other words exact, the slip within the word's budget
    best = None
    for p, c in phrases:
        win = tokens[i:i + len(p)]
        if len(win) < len(p):
            continue
        slips = 0
        for w, q in zip(win, p):
            if w == q:
                continue
            if w in known_words() or len(w) < 4 or _NUM.match(w) or q in _NO_SLIP:
                slips = None
                break
            d = edit_distance(w, q, cap=2)
            if d > typo_budget(q):
                slips = None
                break
            slips += d
        if slips and (best is None or (slips, -len(p)) < best[0]):
            best = ((slips, -len(p)), len(p), c)
    return (best[1], best[2]) if best else (0, None)


def _is_axis_letter(tokens, i):
    """Is the lone letter at `i` an axis? Only where a slice is spoken of:
    a word before it that says so ("selon k", "on J"), or a number or a
    slice word after it ("k 10", "a J section") — for "i" a word before it
    all the same: the English "I" of "I cut the grid" is no axis."""
    before = tokens[i - 1] if i else ""
    after = tokens[i + 1] if i + 1 < len(tokens) else ""
    if tokens[i] == "i" and after in _I_VERBS:
        return False
    if before in _AXIS_CONTEXT:
        return True
    if tokens[i] == "i" and before not in _I_BEFORE:
        return False
    return bool(_NUM.match(after)) or after in _AXIS_AFTER


def capitals(text):
    """The words of `text` typed in capitals ("SO", "J"), normalised: there
    a little word or a lone letter may be a name. None in a sentence typed
    all in capitals, nor a lone letter that starts it ("J'aimerais")."""
    raw = str(text or "")
    letters = [c for c in raw if c.isalpha()]
    if not letters or all(c.isupper() for c in letters):
        return frozenset()
    words = re.findall(r"[^\W_]+", raw)
    return frozenset(normalize(w) for k, w in enumerate(words)
                     if w.isupper() and not (k == 0 and len(w) == 1))


def _said_as_name(tokens, i, caps):
    """Is the little word at `i` said as a name: typed in capitals, the
    sentence's last word, or right before a number or a bound ("so > 0.5")?"""
    if tokens[i] in caps:
        return True
    if i == len(tokens) - 1:
        return i > 0
    return bool(_NUM.match(tokens[i + 1])) or any(tuple(tokens[i + 1:i + 1 + len(p)]) == p for p, _s in _BOUNDS)


def _name_like(tokens, i, objects, min_score):
    """Is the hyphened pair of whole numbers at `i` a piece of a name rather
    than a range: after the name of a well or a fault ("le puits 11-15"),
    before a lone letter ("9-19 A"), or naming an object of the session on
    its own or with the word after it? A decimal is never a name, nor the
    numbers after a grid ("coupe la grille 10-20 en k": its layers)."""
    t = tokens[i]
    if "." in t:
        return False
    if i and NOUNS.get(tokens[i - 1]) in ("well", "fault"):
        return True
    nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
    if len(nxt) == 1 and nxt.isalpha() and nxt not in UNITS:
        return True
    wins = [[t]] + ([[t, nxt]] if nxt else [])
    return any(object_score(w, o.get("title", "")) >= min_score for o in objects or () for w in wins)


def spans(tokens, objects=(), min_object_score=0.6, caps=()):
    """The spans of `tokens`, sorted by position. `objects`: [{"path",
    "title", …}] — the session's, or the generator's; an object is a
    candidate from `min_object_score` up (see `object_score`). `caps`: the
    words typed in capitals (`capitals`)."""
    taken = [False] * len(tokens)
    found = []

    def add(i, n, typ, val, score=1.0):
        for k in range(i, i + n):
            taken[k] = True
        found.append((i, i + n, typ, val, score))

    # 0. "le puits 7", "fault 3": a whole number after the name of a sort of
    # object is that object ("Well 7", "15/9-F-7"), not a bound — and "le
    # puits 19 A" the one whose name holds 19 and A side by side
    for i, t in enumerate(tokens[:-1]):
        fam = NOUNS.get(t)
        nxt = tokens[i + 1]
        if fam is None or not nxt.isdigit() or taken[i + 1]:
            continue
        letter = tokens[i + 2] if i + 2 < len(tokens) else ""
        if len(letter) == 1 and letter.isalpha():
            lettered = [o for o in objects or ()
                        if _family_ok(fam, o) and _has_run(_pieces(o.get("title", "")), [nxt, letter])]
            if lettered:
                add(i + 1, 2, "obj", [dict(o, score=0.8) for o in lettered], 0.8)
                continue
        cands = [o for o in objects or ()
                 if _trailing_number(o.get("title", "")) == (nxt.lstrip("0") or "0")
                 and _family_ok(fam, o)]
        if cands:
            add(i + 1, 1, "obj", [dict(o, score=0.8) for o in cands], 0.8)
    # … and "zoome sur 19 A" without the sort: a number and a letter typed in
    # capitals that sit side by side in the name of ONE well (the "à" of "de
    # 1 à 5" is no capital, and a letter before a number is a range's)
    for i, t in enumerate(tokens[:-1]):
        letter = tokens[i + 1]
        if (not t.isdigit() or taken[i] or taken[i + 1] or len(letter) != 1 or not letter.isalpha()
                or letter not in caps or (i + 2 < len(tokens) and _NUM.match(tokens[i + 2]))):
            continue
        wells = [o for o in objects or ()
                 if _family_ok("well", o) and (o.get("type") or "") and _has_run(_pieces(o.get("title", "")),
                                                                                  [t, letter])]
        if len(wells) == 1:
            add(i, 2, "obj", [dict(wells[0], score=0.8)], 0.8)
    # 0b. a title said exactly, a mnemonic joined to a number ("NTG_2024",
    # "GM09_FACIES"): the object — not a kind and a bound. A title of plain
    # words and a number ("Layer 12") reads like the sentence's own words
    # ("just layer 12" is a slice): step 0 and the lexicon decide there
    titled = {}
    for o in objects or ():
        title = str(o.get("title", ""))
        c = _compact(title)
        if any(ch.isdigit() for ch in c) and re.search(r"[_./-]|[a-zA-Z]\d|\d[a-zA-Z]", title):
            titled.setdefault(c, []).append(o)
    if titled:
        # where a slice is spoken of, "k 1" is a layer, not the title K1
        slicing = any(t in _SLICE_WORDS for t in tokens)
        for n in (4, 3, 2):
            for i in range(len(tokens) - n + 1):
                win = tokens[i:i + n]
                if any(taken[i:i + n]) or not any(ch.isdigit() for w in win for ch in w):
                    continue
                if slicing and n == 2 and win[0] in ("i", "j", "k") and _NUM.match(win[1]):
                    continue
                hit = titled.get(_compact(" ".join(win)))
                if hit:
                    add(i, n, "obj", [dict(o, score=1.0) for o in hit], 1.0)

    # 1. numbers ("0.2", "20%", "20 %", "x5") and ranges ("0.1-0.3", "10-20")
    def percent_after(i):
        return i + 1 < len(tokens) and tokens[i + 1] in ("%", "pourcent", "percent", "pct")

    for i, t in enumerate(tokens):
        if taken[i]:
            continue
        rng = RANGE.match(t)
        if _NUM.match(t):
            add(i, 1, "num", (float(t.rstrip("%")), t.endswith("%") or percent_after(i)))
        elif rng and not _name_like(tokens, i, objects, min_object_score):
            pct = bool(rng.group(2) or rng.group(4)) or percent_after(i)
            add(i, 1, "range", ((float(rng.group(1)), pct), (float(rng.group(3)), pct)))
        elif _TIMES.match(t):
            g = _TIMES.match(t)
            add(i, 1, "times", float(g.group(1) or g.group(2)))
            continue
        else:
            continue
        # "100 mD", "2500 m", "35 gAPI": the unit is the number's, not a
        # word to match objects or kinds against ("m" is no well "M")
        if i + 1 < len(tokens) and tokens[i + 1] in UNITS:
            taken[i + 1] = True

    cat_phrases = _category_phrases(objects)
    one_word_values = {p[0] for p, _c in cat_phrases if len(p) == 1}
    # 2. the lexicon: kinds, panels, colour tables, axes (longest phrase
    # first); every exact match before any forgiven slip, so a slip never
    # takes a word another table names exactly
    for fuzzy, phrases, typ in [(f, p, t) for f in (False, True)
                                for p, t in ((_GROUP_PHRASES, "group"), (_PANEL_PHRASES, "panel"),
                                             (_PRESET_PHRASES, "preset"), (_KIND_PHRASES, "kind"),
                                             (_AXIS_PHRASES, "axis"))]:
        i = 0
        while i < len(tokens):
            if not taken[i]:
                n, c = _match_at(tokens, i, phrases, fuzzy=fuzzy)
                # "shale" where a property lists Shale: the value, not the
                # kind shale volume — a ONE-word kind never takes a value's
                # word ("saturation en eau" stays a kind: three words)
                if n == 1 and typ == "kind" and tokens[i] in one_word_values:
                    n = 0
                if n and typ == "axis" and len(tokens[i]) == 1 and n == 1 and not _is_axis_letter(tokens, i):
                    n = 0
                if n and not any(taken[i:i + n]):
                    add(i, n, typ, c)
                    i += n
                    continue
            i += 1
    for i, t in enumerate(tokens):
        j = i + 2 if tokens[i + 1:i + 2] in (["is"], ["est"], ["are"]) else i + 1   # "So is over 0.3"
        if t in _SHARED and not taken[i] and j < len(tokens) and (
                _NUM.match(tokens[j]) or any(tuple(tokens[j:j + len(p)]) == p for p, _s in _BOUNDS)):
            add(i, 1, "kind", _SHARED[t])
    # 2b. values of the session's categorical properties ("huile" where a
    # property lists oil), after the kinds: "saturation en eau" stays a kind
    if cat_phrases:
        for fuzzy in (False, True):
            i = 0
            while i < len(tokens):
                if not taken[i]:
                    n, c = _match_at(tokens, i, cat_phrases, fuzzy=fuzzy)
                    if n and not any(taken[i:i + n]):
                        add(i, n, "category", c)
                        i += n
                        continue
                i += 1

    # 3. the session's objects, by their title: the best window per object
    # (step 4 below: a sort of object said without a name). A lone letter
    # names an object only after the name of its sort ("la faille J"); a
    # word of a sort ("zone", "model") alone only by the exact title; a
    # little word or a lone letter only by an exact title it is said as a
    # name of ("montre SO", "cache J": in capitals, last, before its bound)
    best = []
    # a window may run one word past the title's words ("top of volantis"
    # for TopVolantis: its camel-case pieces count)
    titled = [(o, max(len(normalize(o.get("title", "")).split()), len(_pieces(o.get("title", ""))), 1))
              for o in objects or ()]
    exact = {}
    for o in objects or ():
        exact.setdefault(normalize(o.get("title", "")), []).append(o)
    for i in range(len(tokens)):
        if taken[i]:
            continue
        letter = len(tokens[i]) == 1 and not tokens[i].isdigit()
        if (letter or tokens[i] in STOP) and tokens[i] in exact and _said_as_name(tokens, i, caps):
            best += [(1.0, 1, i, o) for o in exact[tokens[i]]]
            continue
        if letter:
            if not i or tokens[i - 1] not in NOUNS:
                continue
        elif tokens[i] in STOP:
            continue
        for n in range(1, 5):
            win = tokens[i:i + n]
            if len(win) < n or any(taken[i:i + n]):
                break
            # "top of reservoir": go on to "reservoir" — but the lone letter
            # after a numbered name is part of it ("F-1 A", not "à")
            if n > 1 and win[-1] in STOP and not (len(win[-1]) == 1 and any(c.isdigit() for c in win[-2])):
                continue
            if letter and n > 1:
                break
            exact_only = n == 1 and (win[0] in GENERIC or win[0] in _GESTURE_WORDS)
            for o, tn in titled:
                if n > tn + 1:
                    continue
                s = object_score(win, o.get("title", ""))
                if s >= min_object_score and (s >= 1.0 or not exact_only):
                    best.append((s, n, i, o))
    best.sort(key=lambda b: (-b[0], -b[1]))
    groups = {}
    for s, n, i, o in best:
        groups.setdefault((i, n), []).append((o, s))
    for (i, n), cands in sorted(groups.items(),
                                key=lambda g: (-max(s for _, s in g[1]), -g[0][1])):
        if any(taken[i:i + n]):
            continue
        # "la faille F1": the sort of object said before the name decides
        # between a fault and a well that both answer to F1
        fam = NOUNS.get(tokens[i - 1]) if i else None
        if fam:
            kept = [(o, s) for o, s in cands if _family_ok(fam, o)]
            cands = kept or cands
        top = max(s for _, s in cands)
        add(i, n, "obj", [dict(o, score=round(s, 3)) for o, s in cands if s >= top - 1e-9], top)

    # 4. "the grid", "the well" said without a name: the top-level objects
    # of that sort the session holds ("show the grid" names its only grid)
    # — never the whole catalogue. `by_sort`: the engine asks which one when
    # a singular sort has several answers
    if not any(f[2] in ("obj", "group") for f in found):
        for i, t in enumerate(tokens):
            fam = FAMILY_NOUNS.get(t)
            if fam is None or taken[i]:
                continue
            same = [dict(o, score=0.9, by_sort=True) for o in objects or ()
                    if not o.get("parent") and _family_ok(fam, o)]
            if same:
                add(i, 1, "obj", same, 0.9)
            break

    return sorted(found)


PLACEHOLDER = {"num": "<num>", "times": "<times>", "obj": "<obj>", "kind": "<kind>",
               "panel": "<panel>", "preset": "<preset>", "axis": "<axis>", "group": "<group>",
               "category": "<category>"}


def delex(tokens, found):
    """`tokens` with each span replaced by its placeholder (`PLACEHOLDER`);
    a range reads as its two numbers ("<num> - <num>")."""
    out, i = [], 0
    for s, e, typ, _v, _sc in found:
        out += tokens[i:s]
        if typ == "range":
            out += ["<num>", "-", "<num>"]
            i = e
            continue
        out.append(PLACEHOLDER[typ])
        # the panel IS the command's word ("stats"): its name is kept next
        # to the placeholder so "stats" and "crossplot" stay apart
        if typ in ("panel",):
            out.append("<panel_" + _v + ">")
        i = e
    return out + tokens[i:]


def _bound_phrase_before(tokens, idx):
    """(side, length) of the bound phrase that ends right before token
    `idx` (the longest one): side "min", "max" or "eq"; (None, 0) when
    none does."""
    for p, side in _BOUNDS:
        n = len(p)
        if idx - n >= 0 and tuple(tokens[idx - n:idx]) == p:
            return side, n
    return None, 0


def bound_before(tokens, idx):
    """"min", "max" or "eq" for the bound phrase that ends right before
    token `idx` (the longest one), or None."""
    return _bound_phrase_before(tokens, idx)[0]


# an equal sign after one of these words gives that bound: "min = 10",
# "max = 300", "cutoff = 0.08" (a cutoff is the lowest value kept)
_EQ_MIN = frozenset(w for w in lexicon.MIN_WORDS if " " not in w)
_EQ_MAX = frozenset(w for w in lexicon.MAX_WORDS if " " not in w)
_EQ_CUTOFF = frozenset(("seuil", "seuils", "cutoff", "cutoffs", "threshold", "thresholds", "coupure"))
# the kinds whose values are codes: there "facies = 2" is that one code
_CODED_KINDS = frozenset(("facies", "fluids"))


def _coded(found):
    """Does the sentence speak of a property of codes (a category value, a
    facies, a categorical or discrete property named)?"""
    for _s, _e, typ, v, _sc in found:
        if typ == "category" or (typ == "kind" and v in _CODED_KINDS):
            return True
        if typ == "obj" and any(t in (o.get("type") or "").lower() for o in v for t in ("categorical", "discrete")):
            return True
    return False


def _free(tokens, found):
    """Which tokens no span holds — a sort of object said without a name
    ("le maillage" of "maillage visible", "surface pleine") stays free."""
    free = [True] * len(tokens)
    for s, e, typ, v, _sc in found:
        if typ == "obj" and all(o.get("by_sort") for o in v):
            continue
        for k in range(s, e):
            free[k] = False
    return free


def _said_at(tokens, free, phrases):
    """[(start, length, canonical)] of every phrase of `phrases` said on free
    tokens, in order — the longest one at each place."""
    out, i = [], 0
    while i < len(tokens):
        hit = None
        if free[i]:
            hit = next(((len(p), c) for p, c in phrases
                        if tuple(tokens[i:i + len(p)]) == p and all(free[i:i + len(p)])), None)
        if hit:
            out.append((i, hit[0], hit[1]))
            i += hit[0]
        else:
            i += 1
    return out


def _direction(tokens, free):
    """Where the camera stands: "top", "bottom", "north"… — a cardinal
    point said after "vers" / "towards" / "facing" is where it looks, so it
    stands on the other side ("regarde vers le nord" is from the south)."""
    said = _said_at(tokens, free, _DIRECTION_PHRASES)
    if not said:
        return None
    i, _n, d = said[0]
    if d in _OPPOSITE:
        j = i - 1
        while j >= 0 and tokens[j] in ("le", "la", "the"):
            j -= 1
        if j >= 0 and (tokens[j] in _TOWARD or (tokens[j] == "au" and j and tokens[j - 1] == "face")):
            return _OPPOSITE[d]
    return d


def zoom_direction(tokens):
    """"out" when the zoom is said back ("dézoome", "zoom out", "plus
    loin"), else "in"."""
    return "out" if _said_at(tokens, [True] * len(tokens), _ZOOM_OUT_PHRASES) else "in"


def _step(tokens, free):
    """A time step or a realization said by its place ("next", "previous",
    "first", "last"), by its rank in words or written ("troisième", "3e":
    3), or by a date ("2020-01-01", kept as said); None otherwise — a number
    said alone is taken by the engine, which knows the command."""
    said = _said_at(tokens, free, _STEP_PHRASES)
    if said:
        return said[0][2]
    for i, t in enumerate(tokens):
        if not free[i]:
            continue
        m = _ORDINAL.match(t)
        if m:
            return int(m.group(1))
        if t in _ORDINAL_WORDS:
            return _ORDINAL_WORDS[t]
        if _DATE.match(t):
            return t
    return None


def _scale(tokens, free):
    """"log" or "linear": "logarithmique", "linéaire" — and "log" alone only
    with a word of the colours or of a scale said, or right after "en" /
    "in" / "to": alone it is a well log."""
    scaled = any(t in lexicon.SCALE_WORDS for k, t in enumerate(tokens) if free[k])
    for i, n, c in _said_at(tokens, free, _SCALE_PHRASES):
        if tokens[i:i + n] != ["log"] or scaled or (i and tokens[i - 1] in ("en", "in", "to")):
            return c
    return None


def _tool(tokens, free):
    """The tool card named ("la carte des seuils", "l'explorateur de
    données", "navigation"); a word that names a card only when one is asked
    for ("seuils", "coupes", "pas de temps") counts after a word of opening
    or of a card ("ouvre les seuils", "open the slicers")."""
    said = _said_at(tokens, free, _TOOL_PHRASES)
    if said:
        return said[0][2]
    for i, _n, c in _said_at(tokens, free, _TOOL_IF_OPENED):
        if any(w in lexicon.OPENING for w in tokens[max(0, i - 3):i]):
            return c
    return None


def read(tokens, found):
    """The parameters: {"objects", "kind", "kinds", "min", "max", "numbers",
    "factor", "panel", "preset", "axis", "on", "percent", "group",
    "category", "categories", "conflict", "neq", "direction", "step",
    "style", "scale", "tool"}. "objects" holds one
    candidate list per object mention; "numbers" the numbers that are not a
    bound; "categories" every category value said, in order ("category" the
    first); "conflict" a second bound on the same side, left out ("porosity
    above 0.2 and permeability above 100" is two filters, not one); "neq" a
    value said NOT ("≠ 0"), which no bound gives.

    An equal sign gives the bound of the word before it ("min = 10", "max =
    300", "cutoff = 0.08" a minimum), that one value after an axis or z
    ("k = 15", "z = 3") or on a property of codes ("facies = 2"); said of a
    continuous property ("porosity equals 0.2") its number is a free one.

    The view's gestures are read from the words no span holds: the camera's
    "direction" (lexicon.DIRECTIONS; a zoom's in / out is the engine's),
    the "step" of a time series or a realization (next, previous, first,
    last, a rank, a date — a bare number is the engine's), the drawing
    "style" (a ParaView name), the colour "scale" (log / linear), the
    "tool" card."""
    out = {"objects": [], "kind": None, "kinds": [], "min": None, "max": None, "numbers": [],
           "factor": None, "panel": None, "preset": None, "axis": None, "on": None,
           "percent": False, "group": None, "category": None, "categories": [], "conflict": False,
           "neq": False}
    free = _free(tokens, found)
    out["direction"] = _direction(tokens, free)
    out["step"] = _step(tokens, free)
    styles = _said_at(tokens, free, _STYLE_PHRASES)
    out["style"] = styles[0][2] if styles else None
    out["scale"] = _scale(tokens, free)
    out["tool"] = _tool(tokens, free)
    nums = [(s, v) for s, _e, typ, v, _ in found if typ == "num"]
    used = set()

    def bound(key, v, pct):
        if out[key] is None:
            out[key] = v
            out["percent"] |= pct
        elif out[key] != v:
            out["conflict"] = True

    # "0.1-0.3", "10-20": a range said with a hyphen
    for _s, _e, typ, v, _sc in found:
        if typ == "range":
            (a, pa), (b, pb) = v
            bound("min", min(a, b), pa or pb)
            bound("max", max(a, b), pa or pb)
    # "entre A et B", "between A and B", "de A a B", "from A to B", "A - B"
    for k, (s, (v, pct)) in enumerate(nums[:-1]):
        s2, (v2, pct2) = nums[k + 1]
        pair = s2 == s + 2 and tokens[s + 1] == "-"
        for w1, w2 in lexicon.BETWEEN:
            pair = pair or (s >= 1 and tokens[s - 1] == w1 and w2 in tokens[s + 1:s2])
        if pair and s not in used and s2 not in used:
            bound("min", min(v, v2), pct or pct2)
            bound("max", max(v, v2), pct or pct2)
            used |= {s, s2}
    axes = {s for s, _e, typ, _v, _sc in found if typ == "axis"}
    coded = _coded(found)
    for s, (v, pct) in nums:
        if s in used:
            continue
        if s and tokens[s - 1] == "neq":
            out["neq"] = True
            continue
        side, n = _bound_phrase_before(tokens, s)
        if side == "eq":
            before = s - n - 1
            word = tokens[before] if before >= 0 else ""
            if word == "z" or before in axes:
                side = "eq"
            elif word in _EQ_MIN or word in _EQ_CUTOFF:
                side = "min"
            elif word in _EQ_MAX:
                side = "max"
            elif not coded:
                side = None
        if side is None:
            continue
        if side == "eq":
            # "facies = 2", "k = 15": that value, both bounds
            bound("min", v, pct)
            bound("max", v, pct)
        else:
            bound(side, v, pct)
        used.add(s)
    out["numbers"] = [v for s, (v, _p) in nums if s not in used]
    out["percent"] |= any(p for s, (_v, p) in nums if s not in used)
    for s, _e, typ, v, _ in found:
        if typ == "times":
            out["factor"] = v
        elif typ == "obj":
            out["objects"].append(v)
        elif typ in ("kind", "panel", "preset", "axis", "group", "category") and out[typ] is None:
            out[typ] = v
        if typ == "kind" and v not in out["kinds"]:
            out["kinds"].append(v)
        if typ == "category" and v not in out["categories"]:
            out["categories"].append(v)
    text = " " + " ".join(tokens) + " "
    # a well set against a grid is the Log <-> Grid panel, not Compare
    # (which sets properties against each other) nor the logs alone ("check
    # the logs against the grid values")
    against = out["panel"] == "compare" or (out["panel"] == "welllog" and any(
        f" {w} " in text for w in ("against", "versus", "vs", "match", "agree", "confronte", "confronter",
                                   "en regard", "compare", "comparer", "contre")))
    if against and any(w in text for w in (" puits ", " well ", " wells ", " log ", " logs ", " diagraphie ",
                                           " diagraphies ")) \
            and any(w in text for w in (" grille ", " grid ", " modele ", " model ")):
        out["panel"] = "reconcile"
    if any(f" {' '.join(p)} " in text for p in _OFF):
        out["on"] = False
    elif any(f" {' '.join(p)} " in text for p in _ON):
        out["on"] = True
    return out
