"""A French word and the English name of an object: "perméabilité
horizontale" is `Horizontal Permeability`, "fluides" is `Fluids`,
"lithologie" is `Lithology1` — the data is often named in English, the
reader may speak French.

No translator (a machine-translation library weighs ~100 MB a language pair
and translates sentences, not the words of the trade). Two light means:

- COGNATES, by suffix: -ité/-ity (porosité, porosity), -ie/-y (lithologie,
  lithology), -ique/-ic, -ale/-al (horizontale, horizontal), plurals — most
  words of the trade cross that way;
- a small bilingual DICTIONARY of the trade for the ones that do not (eau
  water, huile oil, toit top, mur base, grès sandstone…).

`same_name(words, title)`: every word of the title answered by a word said,
and every word said answered by one of the title — in either language, in
any order. "porosité" is not `Total Porosity` (nothing said answers
"total"): that is the kind's business, not a name. Nor is "zone" `Zone 3`,
or "the wells" `Well 7`: a sort of thing said alone names no object whose
title is that sort and a number or a code — the number is the name. A
title made of sorts only is named by them, in either language: "blocs de
faille" is `fault_blocks`.
"""
import functools
import re

from fespp_on_trame.ia.nlu.text import normalize

# French <-> English words of the trade that are not cognates (normalised:
# lower case, no accents); a word may have several partners
DICTIONARY = (
    ("eau", "water"), ("huile", "oil"), ("petrole", "oil"), ("gaz", "gas"), ("brut", "gross"),
    ("toit", "top"), ("sommet", "top"), ("mur", "base"), ("faille", "fault"), ("puits", "well"),
    ("forage", "well"), ("couche", "layer"), ("niveau", "level"), ("bloc", "block"),
    ("gres", "sandstone"), ("sable", "sand"), ("argile", "shale"), ("argile", "clay"),
    ("calcaire", "limestone"), ("charbon", "coal"), ("profondeur", "depth"), ("epaisseur", "thickness"),
    ("vitesse", "velocity"), ("rapport", "ratio"), ("taux", "rate"), ("moyenne", "mean"),
    ("maillage", "grid"), ("grille", "grid"), ("modele", "model"), ("indice", "index"),
    ("cellule", "cell"), ("maille", "cell"), ("actif", "active"), ("active", "active"),
    ("marqueur", "marker"), ("trajectoire", "trajectory"), ("unite", "unit"), ("fluide", "fluid"),
    ("sismique", "seismic"), ("temps", "time"), ("reservoir", "reservoir"), ("roche", "rock"),
    ("pression", "pressure"), ("densite", "density"), ("vert", "vertical"), ("horiz", "horizontal"),
)

# French ending -> English ending, cognates; applied both ways
SUFFIXES = (
    ("ites", "ities"), ("ite", "ity"), ("ies", "ies"), ("ie", "y"), ("iques", "ics"), ("ique", "ic"),
    ("iques", "ical"), ("ique", "ical"), ("ales", "al"), ("ale", "al"), ("aux", "al"), ("elles", "al"),
    ("elle", "al"), ("eux", "ous"), ("euse", "ous"), ("ees", "ed"), ("ee", "ed"), ("ure", "ure"),
    ("ion", "ion"),
)

_PAIRS = {}
for _fr, _en in DICTIONARY:
    _PAIRS.setdefault(_fr, set()).add(_en)
    _PAIRS.setdefault(_en, set()).add(_fr)


def _singular(w):
    """A plural made singular: -aux -> -al, a final s or x dropped (not
    -ss)."""
    if len(w) > 4 and w.endswith("aux"):
        return w[:-3] + "al"
    if len(w) > 3 and w[-1] in "sx" and not w.endswith("ss"):
        return w[:-1]
    return w


@functools.lru_cache(maxsize=8192)
def variants(word):
    """The forms a word may take in the other language (and its own
    singular): "horizontale" -> horizontale, horizontal; "fluides" ->
    fluides, fluide, fluid; "eau" -> eau, water."""
    w = normalize(word)
    out = {w, _singular(w)}
    for base in list(out):
        out |= _PAIRS.get(base, set())
        for fr, en in SUFFIXES:
            if base.endswith(fr) and len(base) - len(fr) >= 3:
                out.add(base[: len(base) - len(fr)] + en)
            if base.endswith(en) and len(base) - len(en) >= 3:
                out.add(base[: len(base) - len(en)] + fr)
        # a French final e dropped: "fluide" -> "fluid" (the suffix table
        # already gives "horizontale" -> "horizontal")
        if base.endswith("e") and len(base) > 4:
            out.add(base[:-1])
    return frozenset(v for v in out if v)


@functools.lru_cache(maxsize=8192)
def words(title):
    """The content words of a title: camel case split ("WatSat" -> wat sat,
    "HorizontalPermeability"), digits and separators dropped, short words
    and articles left out."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(title or ""))
    s = re.sub(r"[\d_\-/().]+", " ", s)
    return tuple(w for w in normalize(s).split() if len(w) >= 3 and w not in _ARTICLES)


_ARTICLES = frozenset("les des une the and for with sur par pour dans aux".split())
# the words of a sort of thing (singular forms; variants() gives the
# plurals and the other language)
SORTS = frozenset("""
zone well puits forage wellbore trajectory trajectoire grid grille model modele maillage mesh fault faille
horizon surface layer couche block bloc cell maille cellule log property propriete reservoir
""".split())


def _answers(a, b):
    """Does a word `a` answer a word `b` (one of their forms in common)?"""
    return bool(variants(a) & variants(b))


# the little words a title may hold between its words ("Blocs de faille")
_LITTLE = frozenset("de du d la le l of to a an en et in on at by".split())


@functools.lru_cache(maxsize=8192)
def _coded(title):
    """Does the title hold a number or a short code next to its words
    ("Zone 3", "Fault F1", "Sw_model") — what names it among its sort?"""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(title or ""))
    return any(p and (any(c.isdigit() for c in p) or (len(p) < 3 and p not in _LITTLE))
               for p in re.split(r"[^a-z0-9]+", normalize(s)))


@functools.lru_cache(maxsize=8192)
def forms(title):
    """Every form of every word of a title, for a quick first check."""
    out = set()
    for w in words(title):
        out |= variants(w)
    return frozenset(out)


def same_name(said, title):
    """`said` (words of the sentence) and `title` name the same thing: every
    content word of each answered by the other, in either language."""
    tw = words(title)
    sw = [w for w in (normalize(x) for x in said) if len(w) >= 3 and w not in _ARTICLES]
    if not tw or not sw or (all(variants(s) & SORTS for s in sw) and _coded(title)):
        return False
    tf = forms(title)
    # most titles fail here, on a set lookup: a word said the title lacks
    if not all(variants(s) & tf for s in sw):
        return False
    return (all(any(_answers(t, s) for s in sw) for t in tw)
            and all(any(_answers(s, t) for t in tw) for s in sw))
