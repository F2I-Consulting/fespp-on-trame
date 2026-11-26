"""Several commands in one sentence: "montre la porosité de Hugin et passe
en viridis", "filter porosity above 0.2 then highlight the gas cells".

`split(text)` cuts on the joints that separate two REQUESTS — "puis",
"ensuite", "then", "and then", "après", "also"… — and on a bare "et" /
"and" / "mais" / "but" only when what follows starts like a command (a
verb of the catalogue): "entre 0,1 et 0,3", "l'huile et le gaz", "tous les
puits mais pas F-4" stay whole, and so does what a sentence says of the
rest ("…et garde les autres", "…mais laisse le reste"); "cache le gaz mais
garde l'huile" is two requests. A verb
said once for two things ("enlève le surlignage et le filtre", "filtre la
porosité au-dessus de 0,2 et la perméabilité au-dessus de 100", "cache les
failles et les horizons") is said again for the second — never an isolation
("isole la grille et les puits" isolates both at once); a request without
a verb ("montre la porosité puis la perméabilité") takes the verb of the
one before. Each part is then parsed on its own; the assistant runs them in
order, each with its own reply and its own undo.
"""
import re

from fespp_on_trame.ia.nlu import lexicon
from fespp_on_trame.ia.nlu.text import normalize

# joints that always separate two requests (on the normalised text)
_HARD = re.compile(
    r"\s*(?:,\s*)?\b(?:puis|ensuite|et puis|et ensuite|apres ca|apres cela|apres quoi|then|and then|"
    r"after that|afterwards|en meme temps|at the same time)\b\s*|\s*;\s*")
# "et", "and", "aussi", "also"…: a joint only before a verb of the catalogue
# ("montre aussi la porosite" stays whole, "montre X et passe en viridis" cuts)
_SOFT = re.compile(r"\s+(?:et aussi|and also|et|and|aussi|also|de plus|en plus|mais|but)\s+")
_BARE_AND = re.compile(r"\s+(?:et|and)\s+")
# "quels puis traversent…": after a determiner or a question word, "puis"
# is a slipped "puits" (a well), not "then" — unless a verb follows it
# ("cache-les puis montre Hugin"), or the "les" / "le" is a pronoun: a verb
# right before it ("masque-les puis la grille", "fais le puis le filtre")
_PUIS = re.compile(r"\b(?:(\S+)\s+)?(les|des|ces|mes|tes|ses|nos|vos|leurs|quels|quel|quelles|quelle|du|le|un|"
                   r"aux|au|combien de|ce|cet|chaque)\s+puis\b(?:\s+(\S+))?")
# a pronoun joined to its verb: "masque-les puis…"
_HYPHENED_PRONOUN = re.compile(r"-\s*(?:les|le)\s+puis\b", re.IGNORECASE)
_PRONOUNS = frozenset(("les", "le"))
# … but "les puis qui traversent": a noun, whatever comes before
_NOUN_NEXT = frozenset(("qui", "qu", "dont", "traversant", "traversants"))

_HAND_VERBS = """
montre montrer affiche afficher visualise visualiser cache cacher masque masquer enleve enlever retire retirer
isole isoler filtre filtrer seuille seuiller garde garder surligne surligner allume allumer eteins eteindre
coupe couper tranche trancher passe passer mets mettre change changer utilise utiliser applique appliquer
recale recaler recadre recadrer centre centrer zoome zoomer reinitialise reinitialiser ouvre ouvrir lance lancer
decris decrire liste lister donne donner calcule calculer annule annuler enregistre enregistrer sauvegarde sauvegarder
exagere exagerer multiplie multiplier etire etirer fais faire
recentre recentrer remets vire virer supprime supprimer efface effacer desactive desactiver active activer
show display hide remove uncheck isolate keep filter threshold highlight mark light cut slice switch set change
use apply rescale reset recenter zoom center centre open launch describe list give compute undo save export
exaggerate stretch multiply make put turn clear drop colour color mask bring get take
ferme fermer dezoome dezoomer joue jouer anime animer arrete arreter avance avancer recule reculer vide vider
oriente orienter tourne tourner close play pause stop animate unload decharge
""".split()
# first words of the patterns that are not verbs: they never start a
# request of their own after "et" / "and" — nor does "leave", which mostly
# says what becomes of the rest ("…and leave everything else visible")
_NOT_VERBS = frozenset("""
aide another auto average bonjour cells colorbar colormap colors combien comment couleurs ctrl def definition
detail details deuxieme difference documentation ecart echelle exact exageration facteur flat grid guide hello
help hi how info information instructions intersection intersections jusqu just juste legend legende mailles
manuel mauvaise max maximum mean median mediane min minimum mode moyenne nan no non not nothing notice nouvelle
only palette panneau pas plage plain plus point range retour salut second section seuil seulement solid
standard statistic statistique table tutoriel valeur value values vertical whats where who wrong z
leave laisse laissez pourquoi why
aerial arriere attributes back barre bird birds black book bottom camera carte dark date done east empty fait first
fond instant last lecture linear logarithmic look looking lower map met navigation next north opacite opacity order
outil overhead plan points previous realisation realization rendu representation see slicers south step style
thresholds time timestep tirage top transparence transparency uniquement va volumetrics west white wireframe
""".split())
# what a sentence says of the rest, after "et" / "and": not a request of
# its own ("masque les mailles sous 0,1 et garde les autres")
_THE_REST = re.compile(r"^(?:garde|gardez|garder|keep|keeping)\s+(?:tout\s+)?(?:les autres|le reste|the others?|the rest"
                       r"|everything else|all the rest|the other)\b")


def _first_words():
    """The first word of every pattern of the catalogue (generate.py) — the
    verbs a request starts with — minus the words that are no verbs."""
    from fespp_on_trame.ia.nlu import generate, slots
    out = set()
    for pats in generate.PATTERNS.values():
        for pat in pats:
            s = re.sub(r"^\d+\*", "", pat).strip()
            if s.startswith("("):
                depth = 0
                for end, ch in enumerate(s):
                    depth += (ch == "(") - (ch == ")")
                    if depth == 0:
                        break
                alts = s[1:end].split("|")
            else:
                alts = s.split()[0].split("|") if s and s[0] not in "[{" else []
            for a in alts:
                w = normalize(re.sub(r"[\[\]()|{}]", " ", a)).split()
                if w and w[0] not in slots.STOP and w[0] not in _NOT_VERBS and len(w[0]) > 1:
                    out.add(w[0])
    return out


def _verbs():
    words = set(_HAND_VERBS) | _first_words()
    # the French forms a hurried reader types for the imperative: "enlèves",
    # "enlevez" for "enlève"
    for w in list(words):
        if w.endswith("e") and len(w) > 3 and not w.endswith("ee"):
            words |= {w + "s", w[:-1] + "ez"}
    return frozenset(words)


VERBS = _verbs()
_LEAD = re.compile(r"^(?:peux tu|pouvez vous|tu peux|can you|could you|please|stp|svp|merci de|je veux|je voudrais"
                   r"|j aimerais|i want to|i d like to|i would like to|now|maintenant|aussi|also|et|and)\s+")
_ARTICLES = frozenset("le la les l du des de d un une ce cet cette ces mon ma mes the a an this that these those my"
                      .split())
# the verbs of an isolation (`_elided`)
_ISOLATING = frozenset(("isole", "isoler", "isolez", "isoles", "isolate", "isolates"))
# the gestures said by their noun: "enlève le surlignage et LE FILTRE"
_GESTURE_NOUNS = frozenset("""
filtre filtres seuil seuils surlignage surbrillance coupe coupes nan nans ombrage eclairage selection cutoff
filter filters threshold thresholds highlight highlighting highlights cut cuts slice slices shading lighting
""".split())


def _words(part):
    return _LEAD.sub("", normalize(part)).split()


def _starts_like_a_command(part):
    words = _words(part)
    return bool(words) and words[0] in VERBS and not _THE_REST.match(" ".join(words))


def _kind_at(words, i):
    """The length of the kind phrase that starts at words[i], or 0."""
    from fespp_on_trame.ia.nlu import slots
    for p, _c in slots._KIND_PHRASES:
        if tuple(words[i:i + len(p)]) == p:
            return len(p)
    return 0


def _object_start(words):
    """Does a verbless request start with what a verb acts on: an article
    and a kind, a value, a gesture's noun, a sort of object, a group ("la
    perméabilité", "the gas", "le puits F-4", "les failles")?"""
    from fespp_on_trame.ia.nlu import slots
    i = 1 if words and words[0] in _ARTICLES else 0
    if i >= len(words):
        return False
    w = words[i]
    return bool(_kind_at(words, i)) or w in _GESTURE_NOUNS or w in slots.NOUNS or w in slots.FAMILY_NOUNS \
        or w in _VALUE_WORDS or any(tuple(words[:len(p)]) == p for p, _c in slots._GROUP_PHRASES)


_VALUE_WORDS = frozenset(normalize(w) for ws in lexicon.CATEGORIES.values() for w in ws if " " not in w)


def _has_number(words):
    return any(re.match(r"^-?\d+(?:\.\d+)?%?(?:-\d+(?:\.\d+)?%?)?$", w) for w in words)


def _has_preset(words):
    from fespp_on_trame.ia.nlu import slots
    return any(tuple(words[i:i + len(p)]) == p for i in range(len(words)) for p, _c in slots._PRESET_PHRASES)


def _sort_at(words, i):
    """Does a sort of object or a group start at words[i] ("les puits", "la
    grille", "the horizons", "le puits F-4")?"""
    from fespp_on_trame.ia.nlu import slots
    if i < len(words) and words[i] in _ARTICLES and i + 1 < len(words) and (
            words[i + 1] in slots.NOUNS or words[i + 1] in slots.FAMILY_NOUNS):
        return True
    return any(tuple(words[i:i + len(p)]) == p for p, _c in slots._GROUP_PHRASES)


def _acts_on_a_thing(hw):
    """Does the verb `hw[0]` act on a gesture, a kind or a sort of object,
    said right after it ("enlève le filtre", "show me the porosity", "cache
    les failles") — not on cells of a crossing ("surligne les mailles
    traversées par les puits")?"""
    i = 1
    while i < len(hw) and hw[i] in ("moi", "me", "nous", "us"):
        i += 1
    if i >= len(hw):
        return False
    if _sort_at(hw, i):
        return True
    return hw[i] in _ARTICLES and i + 1 < len(hw) and (hw[i + 1] in _GESTURE_NOUNS or bool(_kind_at(hw, i + 1)))


def _elided(head, tail):
    """The verb of `head` when `tail` is a second thing it acts on, said
    without the verb: an article and a gesture's noun ("le filtre"), an
    article and a kind with its own bound or colour table when the head has
    one ("la perméabilité au-dessus de 100", "la perméabilité en jet"), or
    a sort of object after the thing the verb acted on ("enlève le filtre
    et les puits", "cache les failles et les horizons"). None otherwise
    ("l'huile et le gaz", "entre 0,1 et 0,3", "Hugin et le puits 7" stay
    whole) — and never for an isolation: "isole la grille et les puits"
    keeps both, said again it would keep the second alone."""
    hw, tw = _words(head), normalize(tail).split()
    if not hw or hw[0] not in VERBS or hw[0] in _ISOLATING or len(tw) < 2 or tw[0] not in _ARTICLES:
        return None
    if tw[1] in _GESTURE_NOUNS:
        return hw[0]
    if _kind_at(tw, 1) and ((_has_number(tw) and _has_number(hw)) or (_has_preset(tw) and _has_preset(hw))):
        return hw[0]
    if _sort_at(tw, 0) and _acts_on_a_thing(hw):
        return hw[0]
    return None


def mend(text):
    """`text` normalised, a "puis" that follows a determiner or a question
    word read "puits" ("quels puis traversent la zone d'huile") — unless a
    verb follows it ("cache-les puis montre Hugin"), or the "les" / "le" is
    a pronoun: joined to its verb by a hyphen, or right after a verb
    ("masque-les puis la grille", "fais le puis le filtre")."""
    hyphened = bool(_HYPHENED_PRONOUN.search(str(text or "")))

    def well(m):
        before, det, nxt = m.group(1), m.group(2), m.group(3)
        if nxt in VERBS:
            return m.group(0)
        if det in _PRONOUNS and (hyphened or before in VERBS) and nxt not in _NOUN_NEXT:
            return m.group(0)
        return (before + " " if before else "") + det + " puits" + (" " + nxt if nxt else "")
    return _PUIS.sub(well, normalize(text))


def split(text):
    """The requests of `text`, in order; [text] when it holds one."""
    # ";" separates requests too — cut before normalising, which drops it
    parts = [p for raw in re.split(r"\s*;\s*", str(text or ""))
             for p in _HARD.split(mend(raw)) if p and p.strip()]
    out = []
    for p in parts:
        # a bare et/and: cut where a command starts, keep the rest whole
        pieces, last = [], 0
        for m in _SOFT.finditer(p):
            tail = p[m.end():]
            if _starts_like_a_command(tail):
                pieces.append(p[last:m.start()])
                last = m.end()
        pieces.append(p[last:])
        pieces = [x.strip(" ,;") for x in pieces if x.strip(" ,;")]
        # the verb said once for two things: "enleve le surlignage et le filtre"
        cut = []
        for piece in pieces:
            for m in _BARE_AND.finditer(piece):
                verb = _elided(piece[:m.start()], piece[m.end():])
                if verb:
                    cut += [piece[:m.start()], verb + " " + piece[m.end():]]
                    break
            else:
                cut.append(piece)
        # a request without a verb takes the one of the request before:
        # "montre la porosite puis la permeabilite"
        for piece in cut:
            words = _words(piece)
            if out and words and words[0] not in VERBS and _object_start(words):
                prev = _words(out[-1])
                if prev and prev[0] in VERBS:
                    piece = prev[0] + " " + piece
            out.append(piece)
    return out or [normalize(text)]
