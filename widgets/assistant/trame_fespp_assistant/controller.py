"""Server side of the Assistant: the conversation, and nothing of what a
command does, which is the application's business.

A sentence comes in; the controller gets the command it names from the
host, asks back when the sentence is unclear, runs the command, and keeps
what it did so that it can be undone.

The application hands over a HOST adapter, the only place that knows its
data and its controllers::

    class Host:
        def parse(self, text) -> dict: ...            # the command, below
        def readonly(self, intent) -> bool: ...       # a question, not a gesture
        def answer(self, cmd, lang) -> dict: ...      # {"ok", "text", "rows": [[k, v], ...]}
        def execute(self, cmd, lang) -> dict: ...     # {"ok", "text", "undo": token | None,
                                                      #  optionally "follow": [{"label", "cmd"}]}
        def undo(self, token, lang) -> dict: ...      # {"ok", "text"}
        def label(self, intent, lang) -> str: ...     # a few words for a button
        def missing(self, cmd) -> list: ...           # what the command still lacks
        def targets(self, cmd) -> list: ...           # every candidate object ({"path", ...})
        def ask_missing(self, cmd, lang) -> dict: ... # {"text", "choices": [{"id", "label"}]}
        def examples(self, lang) -> list: ...         # sentences that work on the data

and, optionally::

    examples_watch = ("assembly_xml", ...)            # state vars after which the
                                                      # examples are asked again
    def objects(self) -> list: ...                    # every object of the data now
                                                      # ({"path", ...}): a "target:"
                                                      # choice is checked against it
    def choice_label(self, cmd, intent, lang) -> str: ...  # a button's words for THIS command
    def instead_label(self, cmd, intent, lang) -> str: ...  # "Highlight instead" (a run_first offer)
    def with_category(self, cmd, label) -> dict: ...  # cmd with a "category:" value placed
    def with_intent(self, cmd, intent) -> dict: ...   # cmd read again for an "intent:" chosen
    def parse_next(self, text) -> dict: ...           # a later request of the sentence, read
                                                      # when its turn comes (else parse)
    def slow(self, intent) -> bool: ...               # answered in a thread (local AI)
    def llm_available(self) -> bool: ...              # a local AI can read what parse missed
    def llm_problem(self) -> str: ...                 # why it cannot now ("" when it can)
    def llm_reason(self, why, lang) -> str: ...       # that reason, or a failed call's, in words
    llm_wait_s = 90.0                                 # the longest the AI's reading is waited for
    def llm_prepare(self, text, lang) -> callable: ...  # on the loop: the call to make (a thread)
    def llm_finish(self, text, answer, lang) -> dict: ...  # on the loop: the call's answer as a command
    def llm_command(self, text, lang) -> dict: ...    # the AI's command in one go, in a thread,
                                                      # for a host without prepare / finish

A command is ``{"intent": str | None, "confidence": float, "alternatives":
[(intent, p), ...], "slots": {...}, "targets": [{"path", "title", ...}],
"missing": [str], "sure": bool, "text": str}``, optionally with ``"then":
[str | command, ...]`` (the further requests of the same sentence: their
words, parsed by the host when their turn comes — the request before has
run by then — or commands already parsed) and ``"choose_between": [intent,
...]`` (gestures the sentence itself leaves open) — with ``"run_first":
True``, the first of them runs at once instead of being asked about, and
its reply offers each other one as an ``"instead:<name>"`` button (its own
gesture undone, that one run with the same words) beside ``"undo"``. A
local AI's command whose call failed is ``{"intent": None, "error": str}``.
The host's parser proposes, this controller asks back or runs, the host
acts. The host's choices have the ids ``"target:<path>"`` (an object),
``"category:<value>"`` and ``"exclude:true"`` / ``"exclude:false"`` (the
values the command names hidden, or kept: its ``slots["exclude"]``); the
controller adds ``"intent:<name>"``, ``"instead:<name>"``, ``"then:<n>"``
(the n-th next step of a gesture's ``follow`` — "keep only these cells"
after a highlight —, its command run after that gesture, which stays),
``"none"``, ``"undo"`` and ``"cancel"``.

Wiring::

    ctl = AssistantController(server, host, prefix="ui_assistant", lang="fr",
                              journal=None)
    AssistantPanel(data=(ctl.data_var,), ask=(ctl.ask, "[$event]"),
                   choose=(ctl.choose, "[$event]"), undo=(ctl.undo, "[$event]"),
                   clear=ctl.clear)

The Undo button sends the id of the reply it sits on.

`journal` (optional) is a callable taking one event dict per step: the
sentence and what it was taken for ("said"), the reply ("reply"), the
button clicked ("choose"), the undo ("undo_asked", "undone"), the clear,
and the learning steps ("rephrase", "learned", "unlearned", "complain",
"expected", "llm"). Each event carries the `turn` (the id of the
sentence's message) it belongs to. The application keeps them to learn
from; the widget never writes a file.

Every reply is in the language of the sentence that asked for it, French or
English (`detect_language`); a sentence that says neither keeps the
language of the conversation. Unless `reply_lang` fixes it: an application
whose interface is in one language ("en" for fespp_on_trame, the PO 15/10)
answers, labels its buttons and gives its examples in that language, and
still understands a request in the other one (the parse never depended on
the language).

A command runs with the busy bar up. Inside a trame event the state only
reaches the browser once the handler has returned, so when an event loop
runs, a gesture raises the bar, pushes it, and the host's work follows as
a task one loop turn later (`YIELD_S`, as `_defer` does in app/boot.py);
slow work (the local AI) runs in a thread. `ask`, `choose` and `undo`
therefore return before the reply exists, and a caller that needs it
awaits `idle()` or polls the state. Without a running loop (a script, a
unit test) they run through and the reply is there on return. Gestures
that arrive while a command runs (a double click, a click that crossed the
busy state on the wire) are ignored, and the log says so.
"""
import asyncio
import re

# ------------------------------------------------------------------ language
# Words that only one of the two languages uses. Words both use stay out
# ("a", "on", "me", "i/j/k" for the axes, "min", "max", "stats", "surface",
# "zone", "palette", "change", "reset", "table", "zoom", "vertical"), so a
# sentence made of them alone keeps the language of the conversation.
_FR_WORDS = frozenset("""
    le la les un une des du de au aux et est sont ou où sur dans pour avec sans
    par entre que qui quoi quel quelle quels quelles ce cet cette ces je tu il
    elle nous vous ils elles ne pas plus moins mon ma mes ton ta tes son sa ses
    leur leurs moi toi en tout tous toute toutes seulement aussi très trop peu
    combien comment pourquoi quand svp stp merci bonjour oui non
    montre montrer montrez affiche afficher affichez cache cacher cachez
    masque masquer masquez filtre filtrer filtrez ouvre ouvrir ouvrez ferme
    fermer décris décrire décrivez liste lister listez enlève enlever enlevez
    supprime supprimer retire retirer efface effacer surligne surligner
    surlignez annule annuler annulez remets remettre isole isoler coupe couper
    donne donner donnez mets mettre recadre recadrer applique appliquer garde
    garder enregistre enregistrer sauvegarde sauvegarder aide fais faire peux
    peut voir veux voudrais dépasse dépassent supérieur supérieure supérieurs
    supérieures inférieur inférieure inférieurs inférieures dessus dessous
    moyenne moyen médiane valeur valeurs maille mailles grille grilles puits
    couleur couleurs vue vues nouvelle nouveau propriété propriétés porosité
    perméabilité statistique statistiques chargé chargée chargés chargées
    exagération verticale surbrillance caméra seuil faille failles tranche
    ombrage objet objets absentes manquantes
""".split())
_EN_WORDS = frozenset("""
    the an of and is are or in at to for with without by between that which
    what who where when how this these those it its my your you we they not
    all every only just please yes from into whose there here
    show display hide filter open close describe list remove delete highlight
    undo put set give apply keep clear save help can could would want make
    tell above below over under greater less than exceeds exceed exceeding
    isolate rescale exclude drop enable disable cut
    more mean average median value values cell cells grid grids well wells
    colour color colours colors view views new property properties porosity
    permeability statistic statistics loaded exaggeration camera
    range threshold fault faults slice shading missing
""".split())
_WORD = re.compile(r"[a-zàâäçéèêëîïôöùûüÿœ]+")
_ACCENTED = re.compile(r"[àâäçéèêëîïôöùûüÿœ]")
# French elision: "qu" or one of c d j l m n s t, starting its word, then a
# straight or curly apostrophe and a letter. The prefix must start the word,
# so English "let's", "don't" and "it's" do not match.
_ELISION = re.compile(r"(?<![a-zàâäçéèêëîïôöùûüÿœ])(?:qu|[cdjlmnst])['’](?=[a-zàâäçéèêëîïôöùûüÿœ])")


def detect_language(text, default="fr"):
    """Return "fr" or "en", the language most words of `text` belong to.

    A word counts when only one of the two languages uses it; an accented
    letter and a French elision count for French. A sentence that says
    neither ("xqzt", "Geogrid") gets `default` ("fr" when `default` is
    neither language)."""
    t = str(text or "").lower()
    fr = len(_ELISION.findall(t))
    en = 0
    for w in _WORD.findall(t):
        if w in _FR_WORDS:
            fr += 1
        elif w in _EN_WORDS:
            en += 1
        elif _ACCENTED.search(w):
            fr += 1
    if fr > en:
        return "fr"
    if en > fr:
        return "en"
    return default if default in ("fr", "en") else "fr"


# ------------------------------------------------------------------ replies
# The controller's own messages and button labels, in both languages.
_T = {
    "not_understood_bare": {"fr": "Je n'ai pas compris.", "en": "I did not understand."},
    "try": {"fr": "Essayez par exemple : ", "en": "Try for instance: "},
    "did_you_mean": {"fr": "Voulez-vous dire… ?", "en": "Did you mean…?"},
    "which_gesture": {"fr": "Que voulez-vous faire ?", "en": "What do you want to do?"},
    "cancel": {"fr": "Annuler", "en": "Cancel"},
    "none": {"fr": "Rien de tout ça — je précise", "en": "None of these — let me rephrase"},
    "instead": {"fr": "{label} plutôt", "en": "{label} instead"},
    "rephrase": {"fr": "Dites-le autrement, avec vos mots : je retiendrai ce que vous vouliez dire.",
                 "en": "Say it another way, in your own words: I will learn what you meant."},
    "describe": {"fr": "Toujours pas. Décrivez le résultat que vous attendiez : il sera ajouté à mon"
                       " apprentissage.",
                 "en": "Still not. Describe the result you expected: it will be added to what I learn."},
    "noted": {"fr": "Merci, c'est noté pour l'apprentissage.", "en": "Thank you, noted for learning."},
    "chain_dropped": {"fr": "Le reste de la phrase n'a pas été fait.", "en": "The rest of the sentence was not done."},
    "part_not_understood": {"fr": "Je n'ai pas compris « {part} » : le reste de la phrase n'a pas été fait.",
                            "en": "I did not understand “{part}”: the rest of the sentence was not done."},
    "sorry": {"fr": "Désolé. Dites-moi autrement ce que vous vouliez : je retiendrai la bonne réponse.",
              "en": "Sorry. Tell me another way what you wanted: I will learn the right answer."},
    "undo_it": {"fr": "Annuler ce que je viens de faire", "en": "Undo what I just did"},
    "cancelled": {"fr": "D'accord, rien n'est fait.", "en": "OK, nothing done."},
    "nothing_to_undo": {"fr": "Rien à annuler.", "en": "Nothing to undo."},
    "failed": {"fr": "Une erreur est survenue : ", "en": "Something went wrong: "},
    # A model on a CPU takes from seconds to a minute or more: the message
    # says how long the reader may wait, the host's own wait when it says it.
    "asking_ai": {"fr": "Je demande à l'IA locale : sa réponse peut prendre jusqu'à {wait}…",
                  "en": "Asking the local AI: its answer may take up to {wait}…"},
    "asking_ai_open": {"fr": "Je demande à l'IA locale : sa réponse peut prendre une minute ou plus…",
                       "en": "Asking the local AI: its answer may take a minute or more…"},
    "asking_ai_question": {"fr": "Je pose la question à l'IA locale : la réponse peut prendre une à deux minutes…",
                           "en": "Asking the local AI: the answer may take a minute or two…"},
    "ai_failed": {"fr": "L'IA locale n'a pas répondu ({why}) : je n'ai pas compris la phrase.",
                  "en": "The local AI did not answer ({why}): I did not understand the sentence."},
    "ai_down": {"fr": " (L'IA locale ne répond pas : {why}.)", "en": " (The local AI does not answer: {why}.)"},
    "undo_asked": {"fr": "Annuler la dernière action", "en": "Undo the last action"},
    "need_more": {"fr": "Il me manque une précision.", "en": "I need one more detail."},
    "done": {"fr": "C'est fait.", "en": "Done."},
    "undone": {"fr": "C'est annulé.", "en": "Undone."},
    "gone": {"fr": "« {label} » n'est plus disponible : rien n'est fait.",
             "en": "“{label}” is no longer available: nothing done."},
    "too_long": {"fr": "Cette demande est trop longue (plus de {n} caractères) :"
                       " une commande tient en une phrase.",
                 "en": "That request is too long (over {n} characters):"
                       " a command fits in one sentence."},
}

# Confidence at which the intent of a command the parser is not sure of
# counts as clear when the command only lacks a parameter: it is asked for
# that parameter directly. Below this, the reader is first asked which
# command was meant.
CONFIDENT = 0.6
# The conversation keeps the newest MAX_MESSAGES messages, the undo stack the
# newest MAX_UNDO actions; a "did you mean" question offers at most
# MAX_INTENT_CHOICES commands.
MAX_MESSAGES = 200
MAX_UNDO = 20
MAX_INTENT_CHOICES = 3
# A command is one sentence. The parser's cost grows with the number of
# words times the number of objects in the data, so a long paste would block
# the event loop: a longer text is refused unparsed. The panel's field has
# the same maxlength (MAX_TEXT in AssistantPanel.vue).
MAX_TEXT = 500
# The journal keeps a reply up to this many characters: enough for the wells
# a filter hid or the cells a highlight lit, what a contested result is
# diagnosed from.
REPLY_LOG_CHARS = 2000
# Delay, in seconds, that lets the busy state reach the browser before the
# host's work blocks the loop: wslink only queues a flush (call_later(0),
# then a send task), so a bare sleep(0) would resume the work first.
YIELD_S = 0.02
# whether _running_loop has said, once per process, that no loop runs
_NO_LOOP_SAID = []


def _running_loop():
    """Return the event loop running this call (a trame event, a scenario),
    or None (a script, a unit test)."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        # Never the case inside the application, whose events all run on the
        # loop; a script or a test runs every command this way, and one line
        # says so for all of them.
        if not _NO_LOOP_SAID:
            _NO_LOOP_SAID.append(True)
            print("[assistant] no event loop running: commands run at once", flush=True)
        return None


def _as_id(v):
    """Return a message id sent back by the browser as an int, or None.

    The browser may send the number as a float or a string; a bool is never
    an id."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v)
    return None


def _plain(v):
    """Return `v` when the state can carry it as it is, else its text."""
    return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)


def _rows(rows):
    """Return the host's table rows as [label, value] pairs the state can
    carry; a row with fewer than two cells is dropped."""
    out = []
    for r in rows or []:
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            out.append([str(r[0]), _plain(r[1])])
    return out


def _choices(choices):
    """Return the buttons as {"id", "label"} dicts of text; a choice without
    an id is dropped, one without a label shows its id."""
    out = []
    for c in choices or []:
        if isinstance(c, dict) and c.get("id") not in (None, ""):
            out.append({"id": str(c["id"]), "label": str(c.get("label") or c["id"])})
    return out


def _quote(sentence, lang):
    return f"« {sentence} »" if lang == "fr" else f"“{sentence}”"


def _duration(seconds, lang):
    """A wait in words: "90 secondes", "4 minutes"."""
    if seconds < 120:
        n = int(round(seconds))
        return f"{n} {'seconds' if lang == 'en' else 'secondes'}"
    n = int(round(seconds / 60.0))
    return f"{n} minutes"


def _with_category(cmd, label):
    """Fallback for a host without `with_category`: put the category value,
    lower-cased, in the slots and clear any min/max range."""
    cmd = dict(cmd)
    cmd["slots"] = dict(cmd.get("slots") or {}, category=str(label).strip().lower(), min=None, max=None)
    return cmd


def _summary(cmd):
    """Return what the parser took a sentence for, for the journal.

    The command, how sure the parser was, the other readings, the
    parameters, the objects the sentence named and the ones the command
    would act on (titles, not paths, at most ten of each)."""
    sl = cmd.get("slots") or {}
    named = [o.get("title") for cands in sl.get("objects") or () for o in cands or ()]
    targets = [t.get("title") for t in cmd.get("targets") or ()]
    keep = ("kind", "category", "categories", "exclude", "well_filter", "min", "max", "numbers", "factor", "panel",
            "preset", "axis", "on", "group", "direction", "step", "style", "scale", "tool")
    return {"intent": cmd.get("intent"), "confidence": cmd.get("confidence"),
            "sure": cmd.get("sure"),
            "alternatives": [list(a) for a in cmd.get("alternatives") or ()],
            "missing": list(cmd.get("missing") or ()),
            "slots": {k: sl.get(k) for k in keep if sl.get(k) not in (None, [], "")},
            "named": named[:10], "targets": targets[:10], "n_targets": len(targets)}


class AssistantController:
    """The conversation of one Assistant panel, published in the state var
    `prefix` (see the module docstring for the host and the wiring)."""

    def __init__(self, server, host, prefix="ui_assistant", lang="fr", journal=None,
                 reply_lang=None):
        self.server = server
        # Optional callable receiving one event dict per step of the dialogue,
        # kept by the application to learn from (see the module docstring).
        self._journal = journal
        # The user message that started the current exchange, and the turn
        # each reply belongs to (an undo names the turn it undoes).
        self._turn = None
        self._turn_of = {}
        self.state = server.state
        self.host = host
        self.data_var = prefix
        # the interface language when the application fixes one (see the
        # module docstring); None: each reply in the language of its sentence
        self.reply_lang = reply_lang if reply_lang in ("fr", "en") else None
        self.lang = self.reply_lang or (lang if lang in ("fr", "en") else "fr")
        self._messages = []
        self._next_id = 1
        # The command waiting for the reader's button: (cmd, lang).
        self._pending = None
        # Undo stack: [(token, cmd, id of the reply)], newest last.
        self._undo = []
        self._busy = False
        # After "none of these": the sentence said again in other words, or
        # the result it should have given described, as {of_turn, original,
        # level, turn}; the journal keeps it as a labelled example.
        self._rephrase = None
        # The reader's own words of each sentence, by turn.
        self._said = {}
        # Each learned rephrasing, its turn -> the turn it rephrased: undone
        # or complained about later, it is unlearned.
        self._learned_turns = {}
        # The commands still to run of a sentence that held several.
        self._chain = []
        # The command's work scheduled on the event loop (see _work).
        self._task = None
        self._examples = []
        self._refresh_examples(self.lang)
        self.state.setdefault(self.data_var, self._data())

        # Examples built from the data are worth asking for again once the
        # data changed: the host may name the state vars that signal it.
        watch = tuple(getattr(host, "examples_watch", ()) or ())
        if watch:
            @self.state.change(*watch)
            def _on_data(**_):
                # a host may build them only while its panel is shown
                # (`examples_wanted`); the door then asks refresh_examples
                wanted = getattr(self.host, "examples_wanted", None)
                if wanted is not None and not wanted():
                    return
                self._refresh_examples(self.lang)
                self._publish()

    # ---------------------------------------------------------------- events
    def ask(self, text):
        """Handle a sentence of the reader: parse it, then run it or ask back."""
        text = str(text or "").strip()
        if not text:
            return
        if self._ignored_while_busy("the sentence " + repr(text[:80])):
            return
        too_long = len(text) > MAX_TEXT
        if too_long:
            text = text[:MAX_TEXT].rstrip() + "…"
        lang = said = detect_language(text, self.lang)
        if self.reply_lang:
            lang = self.reply_lang        # understood whatever it says, answered in this
        if lang != self.lang:
            self.lang = lang
            self._refresh_examples(lang)
        # A new sentence replaces any question left unanswered.
        self._pending = None
        if too_long:
            # Never parsed, and only its beginning kept in the conversation.
            self._turn = self._say_user(text, publish=False)["id"]
            self._log("said", text=text, lang=said, too_long=True)
            self._say(_T["too_long"][lang].format(n=MAX_TEXT), "error")
            return
        self._turn = self._say_user(text)["id"]
        self._said[self._turn] = text
        # A sentence typed after "none of these" is the same request in other
        # words or, the second time, a description of the expected result.
        if self._rephrase is not None:
            r = self._rephrase
            if r["level"] >= 2:
                self._rephrase = None
                self._log("expected", of_turn=r["of_turn"], original=r["original"], text=text)
                self._say(_T["noted"][lang], "info")
                return
            r["turn"] = self._turn
            self._log("rephrase", of_turn=r["of_turn"], original=r["original"])
        try:
            cmd = dict(self.host.parse(text) or {})
        except Exception as exc:
            self._log("said", text=text, lang=said, parse_error=str(exc))
            self._failed(exc, lang, "parse")
            return
        self._log("said", text=text, lang=said, **_summary(cmd))
        # A sentence holding several requests ("show X and switch to
        # viridis"): the ones after the first wait in the chain, each run
        # after the previous one succeeded, or asked about. The host gives
        # their words, parsed when their turn comes ("…then the wells that
        # cross them" knows the zone just kept), or commands already parsed.
        self._chain = [c if isinstance(c, str) else dict(c) for c in cmd.pop("then", None) or ()
                       if isinstance(c, (str, dict))]
        self._route(cmd, lang, first=True)

    def _route(self, cmd, lang, first=False):
        """Run `cmd` or ask about it — the one decision for a sentence, for
        each further request of it, and for what the local AI read. A
        request the parser did not read goes to the local AI when there is
        one (that request alone: the rest of the sentence waits for it)."""
        if cmd.get("intent") is None:
            if first and self._rephrase is not None and self._rephrase.get("turn") == self._turn:
                self._chain = []
                self._ask_expected(lang)
            elif self._llm_on():
                self._ask_llm(str(cmd.get("text") or self._said.get(self._turn, "")), lang)
            elif first:
                rest = bool(self._chain)
                self._chain = []
                self._not_understood(lang)
                if rest:
                    self._say(_T["chain_dropped"][lang], "info")
            else:
                self._chain = []
                self._say(_T["part_not_understood"][lang].format(part=cmd.get("text") or ""), "error")
            return
        # Sure: the parser says so. Not sure but with something missing: the
        # intent itself may still be clear, which its confidence tells.
        said_missing = list(cmd.get("missing") or [])
        confident = bool(cmd.get("sure")) or (
            bool(said_missing) and float(cmd.get("confidence") or 0.0) >= CONFIDENT)
        # The host has the last word on what is missing: it knows the data
        # (one property asked for, three found on the grid).
        try:
            cmd["missing"] = list(self.host.missing(cmd) or [])
        except Exception as exc:
            self._chain = []
            self._failed(exc, lang, "missing")
            return
        if not confident:
            if not (cmd.get("run_first") and self._run_first(cmd, lang)):
                self._did_you_mean(cmd, lang)
        elif cmd["missing"]:
            self._ask_missing(cmd, lang)
        else:
            self._run(cmd, lang)

    def _ask_llm(self, text, lang):
        """Have the local AI read `text`, then run or ask about its command.

        What it is told is read from the application on the event loop
        (`host.llm_prepare`); only the HTTP call runs in a thread (it takes
        seconds); its answer becomes a command back on the loop
        (`host.llm_finish`). A host without that pair is called in one go
        in the thread (`host.llm_command`)."""
        self._say(self._asking_ai(lang), "info")
        prepare = getattr(self.host, "llm_prepare", None)
        finish = getattr(self.host, "llm_finish", None)
        if not (callable(prepare) and callable(finish)):
            self._work_threaded(lambda: self.host.llm_command(text, lang),
                                lambda got: self._after_llm(got, text, lang), lang, "the local AI")
            return
        try:
            call = prepare(text, lang)
        except Exception as exc:
            self._chain = []
            self._failed(exc, lang, "llm_prepare")
            return
        if call is None:
            self._after_llm(None, text, lang)
            return
        self._work_threaded(call, lambda answer: self._after_llm(finish(text, answer, lang), text, lang),
                            lang, "the local AI")

    def choose(self, choice_id):
        """Handle a button of the LAST message, for the command it asked
        about; an id that is not on that message is ignored."""
        choice_id = str(choice_id or "")
        if self._ignored_while_busy("the choice " + repr(choice_id)):
            return
        if self._pending is None or not self._messages:
            return
        last = self._messages[-1]
        live = ({c["id"]: c["label"] for c in last.get("choices") or []}
                if last.get("role") == "assistant" else {})
        if choice_id not in live:
            return
        if not (choice_id in ("cancel", "none", "undo", "exclude:true", "exclude:false")
                or choice_id.startswith("intent:") or choice_id.startswith("target:")
                or choice_id.startswith("category:") or choice_id.startswith("instead:")
                or choice_id.startswith("then:")):
            print("[assistant] a choice this controller does not know, ignored:",
                  choice_id, flush=True)
            return
        cmd, lang = self._pending
        cmd = dict(cmd)
        self._pending = None
        self._log("choose", choice=choice_id, label=live[choice_id], intent=cmd.get("intent"))
        self._say_user(live[choice_id])
        if choice_id == "cancel":
            self._rephrase = None
            self._chain = []
            self._say(_T["cancelled"][lang], "info")
            return
        if choice_id == "undo":
            # Offered after a complaint: the action is undone and the
            # rephrasing still awaited, so what the reader says next is
            # learned for the sentence that went wrong.
            self._work(lambda: self._undo_last(lang), lang, "the undo")
            return
        if choice_id == "none":
            r = self._rephrase
            if r is not None and r.get("turn") == self._turn:
                # The rephrasing missed too: ask for the expected result.
                self._ask_expected(lang)
            else:
                self._rephrase = {"of_turn": self._turn, "level": 1,
                                  "original": self._said.get(self._turn, "")}
                self._say(_T["rephrase"][lang], "ask")
            return
        if choice_id.startswith("intent:"):
            cmd = self._chosen(cmd, choice_id[len("intent:"):], lang)
            if cmd is None:
                return
            if cmd["missing"]:
                self._ask_missing(cmd, lang)
            else:
                self._run(cmd, lang)
            return
        if choice_id.startswith("instead:"):
            # Offered on the reply of a gesture run by default: that gesture
            # is undone, then this one runs with the same words.
            self._work(lambda: self._instead(cmd, choice_id[len("instead:"):], last["id"], lang),
                       lang, "the gesture instead")
            return
        if choice_id.startswith("then:"):
            # A next step the reply offered ("keep only these cells"): its
            # command runs after the gesture, which stays.
            try:
                nxt = dict(cmd["follow"][int(choice_id[len("then:"):])])
            except (KeyError, IndexError, TypeError, ValueError):
                return
            self._route(nxt, lang)
            return
        if choice_id.startswith("category:"):
            # A value of a categorical property offered by the host's
            # question ("which cells of Fluids?"): the command takes that
            # value, placed by the host's `with_category` when it has one.
            label = choice_id[len("category:"):]
            try:
                with_cat = getattr(self.host, "with_category", None)
                cmd = with_cat(cmd, label) if callable(with_cat) else _with_category(cmd, label)
                cmd["missing"] = list(self.host.missing(cmd) or [])
            except Exception as exc:
                self._failed(exc, lang, "category")
                return
            cmd["sure"] = True
            if cmd["missing"]:
                self._ask_missing(cmd, lang)
            else:
                self._run(cmd, lang)
            return
        if choice_id.startswith("exclude:"):
            # Hide the values the command names, or keep only them: the
            # host asked because nothing said which.
            cmd["slots"] = dict(cmd.get("slots") or {}, exclude=choice_id == "exclude:true")
            cmd["sure"] = True
            try:
                cmd["missing"] = list(self.host.missing(cmd) or [])
            except Exception as exc:
                self._failed(exc, lang, "missing")
                return
            if cmd["missing"]:
                self._ask_missing(cmd, lang)
            else:
                self._run(cmd, lang)
            return
        path = choice_id[len("target:"):]
        chosen = self._target(cmd, path, lang)
        if chosen is False:
            return
        if chosen is None:
            # Never run without a target: the host would read "nothing named"
            # and act on every object, or on the view's active property.
            print("[assistant] a target choice no longer available, not run:", path, flush=True)
            self._say(_T["gone"][lang].format(label=live[choice_id]), "error")
            self._ask_missing(cmd, lang)
            return
        cmd["targets"] = [chosen]
        cmd["missing"] = []
        self._run(cmd, lang)

    def undo(self, msg_id=None):
        """Undo the action of reply `msg_id`, only while it is still the last
        action done.

        A second click, or a click that crossed the reply to the first one,
        finds another action on top (or none) and is ignored. Without an id
        (a headless scenario, a panel wired without `$event`), the last
        action is undone, whichever it is."""
        if self._ignored_while_busy("the undo"):
            return
        if msg_id is not None:
            top = self._undo[-1][2] if self._undo else None
            if top is None or _as_id(msg_id) != top:
                print("[assistant] an Undo of message", msg_id, "ignored: the last action is",
                      "message " + str(top) if top is not None else "none", flush=True)
                return
        self._pending = None
        lang = self.lang
        self._log("undo_asked", msg=msg_id)
        self._say_user(_T["undo_asked"][lang], publish=False)
        self._work(lambda: self._undo_last(lang), lang, "the undo")

    def clear_undo(self):
        """Forget every action to undo, for when the views they acted on are
        gone (a session restored over them). Unlike `clear`, it is never
        refused while a command runs, and the conversation stays."""
        self._undo = []
        self._pending = None
        self._mark_undoable()
        self._publish()

    def clear(self):
        """Empty the conversation; what was done in the views stays."""
        if self._ignored_while_busy("the clear"):
            return
        self._log("clear", messages=len(self._messages))
        self._messages = []
        self._undo = []
        self._pending = None
        self._chain = []
        self._rephrase = None
        self._refresh_examples(self.lang)
        self._publish()

    def refresh_examples(self):
        """Ask the host for its examples again after the data changed, as
        `examples_watch` does automatically."""
        self._refresh_examples(self.lang)
        self._publish()

    async def idle(self):
        """Wait until the running command, if any, has replied — and the
        commands it started (the next requests of the sentence, the local
        AI): for a caller inside the event loop (a scenario) that reads the
        reply."""
        while self._task is not None and not self._task.done():
            # asyncio.wait does not raise the task's exception; _task_done logs it.
            await asyncio.wait({self._task})

    def _ignored_while_busy(self, what):
        """Return True, and log that `what` is ignored, while a command runs."""
        if not self._busy:
            return False
        print(f"[assistant] {what} ignored: a command is running", flush=True)
        return True

    def _target(self, cmd, path, lang):
        """Return the object a "target:<path>" button picked, as the data
        has it now.

        The object comes from the host's current candidates when it is
        still one. Otherwise, when the host can list its data (`objects()`),
        the object itself is taken if it still exists: the candidates are
        computed from live state (the view's active property narrows a
        grid's properties to itself), and the reader did click this one.
        Returns None when the object is gone or the host cannot tell, and
        False when the host failed (the error is already said)."""
        try:
            live = [t for t in (self.host.targets(cmd) or [])
                    if isinstance(t, dict) and t.get("path") == path]
        except Exception as exc:
            self._failed(exc, lang, "targets")
            return False
        chosen = dict(live[0]) if live else None
        objects = getattr(self.host, "objects", None)
        if not callable(objects):
            return chosen
        try:
            now = {o["path"]: o for o in (objects() or [])
                   if isinstance(o, dict) and o.get("path")}
        except Exception as exc:
            self._failed(exc, lang, "objects")
            return False
        if path not in now:
            return None
        return chosen if chosen is not None else dict(now[path])

    # ---------------------------------------------------------------- asking back
    def _not_understood(self, lang, head=None):
        """Say the sentence was not understood, with up to three of the
        host's examples — and, when the host's local AI is configured but
        out, why it could not help (`host.llm_problem`). `head` replaces
        the opening words."""
        examples = self._refresh_examples(lang)[:3]
        text = head or _T["not_understood_bare"][lang]
        fn = getattr(self.host, "llm_problem", None)
        if head is None and callable(fn):
            try:
                why = str(fn() or "")
            except Exception as exc:
                print("[assistant] llm_problem failed:", exc, flush=True)
                why = ""
            if why:
                text += _T["ai_down"][lang].format(why=self._ai_why(why, lang))
        if examples:
            text += " " + _T["try"][lang] + " · ".join(_quote(e, lang) for e in examples)
        self._say(text, "error")

    def _complain(self, lang):
        """Handle a complaint that the last answer missed.

        Say sorry, offer to undo its action, and tie what the reader says
        next to the sentence that went WRONG: its rephrasing is learned for
        that sentence, not for the complaint."""
        top = self._undo[-1] if self._undo else None
        bad = self._turn_of.get(top[2]) if top else max(
            (t for t in self._said if t < (self._turn or 0)), default=None)
        self._unlearn(bad)
        original = self._said.get(bad, "")
        self._log("complain", of_turn=bad, original=original)
        self._rephrase = {"of_turn": bad, "original": original, "level": 1}
        choices = [{"id": "undo", "label": _T["undo_it"][lang]}] if top else []
        # A complaint such as "I see nothing at all" may only mean that what
        # is shown is out of frame: offer to reset the camera.
        choices.append({"id": "intent:reset_camera", "label": self._label("reset_camera", lang)})
        choices.append({"id": "cancel", "label": _T["cancel"][lang]})
        self._pending = ({"intent": "complain"}, lang)
        self._say(_T["sorry"][lang], "ask", choices=choices)

    def _unlearn(self, turn):
        """Withdraw the rephrasing learned at `turn`, if any: its action was
        taken back, so it is not an example."""
        if turn in self._learned_turns:
            self._log("unlearned", of_turn=self._learned_turns.pop(turn), turn=turn)

    def _ask_expected(self, lang):
        """After a second miss, ask the reader to describe the expected
        result; the next sentence is noted, not run."""
        if self._rephrase is None:
            self._rephrase = {"of_turn": self._turn, "original": self._said.get(self._turn, "")}
        self._rephrase["level"] = 2
        self._say(_T["describe"][lang], "ask")

    def _learned(self, cmd):
        """Journal a rephrased request that worked: the first words and the
        command they meant, a labelled example for the vocabulary."""
        r = self._rephrase
        if r is None or r.get("turn") != self._turn:
            return
        self._rephrase = None
        self._learned_turns[self._turn] = r["of_turn"]
        self._log("learned", of_turn=r["of_turn"], original=r["original"],
                  text=self._said.get(self._turn, ""), **_summary(cmd))

    def _did_you_mean(self, cmd, lang):
        """Ask which command was meant.

        The choices are the parser's readings or, when the host says the
        sentence itself leaves a choice between gestures (`choose_between`:
        "show the oil zones" may keep only those cells, or highlight them),
        those gestures in the host's order, labelled for THIS command."""
        between = [n for n in cmd.get("choose_between") or () if isinstance(n, str) and n]
        names = list(between)
        if not names:
            for a in [cmd.get("intent")] + list(cmd.get("alternatives") or []):
                name = a[0] if isinstance(a, (list, tuple)) and a else a
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
        choices = [{"id": f"intent:{n}", "label": self._label(n, lang, cmd)}
                   for n in names[:MAX_INTENT_CHOICES]]
        choices.append({"id": "none", "label": _T["none"][lang]})
        choices.append({"id": "cancel", "label": _T["cancel"][lang]})
        self._pending = (cmd, lang)
        self._say(_T["which_gesture" if between else "did_you_mean"][lang], "ask", choices=choices)

    def _chosen(self, cmd, intent, lang):
        """Return `cmd` for the gesture `intent` — a button's, or the one run
        by default — read again by the host when it can (a hiding said stays
        a hiding under another intent), with what it lacks now; None when
        the host failed (the error is already said)."""
        cmd = dict(cmd, intent=intent, sure=True)
        try:
            with_intent = getattr(self.host, "with_intent", None)
            if callable(with_intent):
                cmd = dict(with_intent(cmd, intent) or cmd, sure=True)
            cmd["missing"] = list(self.host.missing(cmd) or [])
        except Exception as exc:
            self._failed(exc, lang, "missing")
            return None
        return cmd

    def _run_first(self, cmd, lang):
        """Run the first gesture of `choose_between` at once, its reply
        offering the others instead (`_offer`). Return False, nothing done,
        when that gesture lacks something: the choice is asked as usual."""
        between = [n for n in cmd.get("choose_between") or () if isinstance(n, str) and n]
        if not between:
            return False
        first = self._chosen(cmd, between[0], lang)
        if first is None:
            return True
        if first["missing"]:
            return False
        first["offer_instead"] = {"cmd": cmd, "intents": between[1:MAX_INTENT_CHOICES]}
        self._run(first, lang)
        return True

    def _offer(self, cmd, lang):
        """The buttons on the reply of a gesture run by default: each other
        gesture instead, then Cancel, which undoes it (`"undo"`)."""
        offer = cmd.get("offer_instead") or {}
        choices = []
        for n in offer.get("intents") or ():
            label = None
            fn = getattr(self.host, "instead_label", None)
            if callable(fn):
                try:
                    label = fn(offer.get("cmd"), n, lang)
                except Exception as exc:
                    print("[assistant] no instead label for", n, exc, flush=True)
            choices.append({"id": f"instead:{n}",
                            "label": label or _T["instead"][lang].format(label=self._label(n, lang))})
        if choices:
            choices.append({"id": "undo", "label": _T["cancel"][lang]})
        return choices

    @staticmethod
    def _follow(r):
        """The next steps a gesture's reply offers: its `follow`, each the
        words of a button and the command it runs."""
        return [f for f in r.get("follow") or ()
                if isinstance(f, dict) and f.get("label") and isinstance(f.get("cmd"), dict)]

    def _instead(self, cmd, intent, msg_id, lang):
        """Undo the gesture of reply `msg_id`, run by default, then run
        `intent` with the sentence's words (`cmd`, as it was read)."""
        if not self._undo or self._undo[-1][2] != msg_id:
            self._say(_T["gone"][lang].format(label=self._label(intent, lang)), "error", publish=False)
            return
        if not self._undo_last(lang):
            return
        other = self._chosen(cmd, intent, lang)
        if other is None:
            return
        if other["missing"]:
            self._ask_missing(other, lang)
        else:
            self._run(other, lang)

    def _ask_missing(self, cmd, lang):
        """Ask the host's question for what the command still lacks."""
        try:
            r = self.host.ask_missing(cmd, lang) or {}
        except Exception as exc:
            self._failed(exc, lang, "ask_missing")
            return
        choices = _choices(r.get("choices"))
        # A question with buttons can always be answered "none of these", and declined.
        if choices and not any(c["id"] == "none" for c in choices):
            at = next((i for i, c in enumerate(choices) if c["id"] == "cancel"), len(choices))
            choices.insert(at, {"id": "none", "label": _T["none"][lang]})
        if choices and not any(c["id"] == "cancel" for c in choices):
            choices.append({"id": "cancel", "label": _T["cancel"][lang]})
        self._pending = (cmd, lang)
        self._say(str(r.get("text") or _T["need_more"][lang]), "ask", choices=choices)

    def _label(self, intent, lang, cmd=None):
        """Return a button's words for `intent`: the host's words for this
        command when it has some (`choice_label(cmd, intent, lang)`, such as
        'Keep only the "oil" cells'), else its label for the command in
        general, else the intent's name."""
        try:
            if cmd is not None and hasattr(self.host, "choice_label"):
                label = self.host.choice_label(cmd, intent, lang)
                if label:
                    return str(label)
            return str(self.host.label(intent, lang) or intent)
        except Exception as exc:
            print("[assistant] no label for", intent, exc, flush=True)
            return intent

    # ---------------------------------------------------------------- running
    def _asking_ai(self, lang):
        """The waiting message: how long the reader may wait, the host's
        longest wait for the local AI (`host.llm_wait_s`) when it says it."""
        try:
            wait = float(getattr(self.host, "llm_wait_s", None) or 0.0)
        except (TypeError, ValueError) as exc:
            print("[assistant] the host's llm_wait_s is not a number:", exc, flush=True)
            wait = 0.0
        if wait > 0:
            return _T["asking_ai"][lang].format(wait=_duration(wait, lang))
        return _T["asking_ai_open"][lang]

    def _ai_why(self, why, lang):
        """Why the local AI failed or is out, in the reader's words when the
        host can say it (`host.llm_reason`), else as the host gave it."""
        fn = getattr(self.host, "llm_reason", None)
        if callable(fn):
            try:
                return str(fn(why, lang) or why)
            except Exception as exc:
                print("[assistant] llm_reason failed:", exc, flush=True)
        return str(why)

    def _llm_on(self):
        """Whether the host offers a local AI (`llm_available()`) and it is up."""
        fn = getattr(self.host, "llm_available", None)
        try:
            return bool(fn and fn())
        except Exception as exc:
            print("[assistant] llm_available failed:", exc, flush=True)
            return False

    def _after_llm(self, got, text, lang):
        """Go on with what the local AI made of a request the parser could
        not read: a call that failed says so, with the reason (a timeout, a
        full queue); no command is "not understood"; a command is run or
        asked about like the parser's, and the rest of the sentence follows
        it. A failure or no command drops the rest, and says so."""
        rest = bool(self._chain)
        if got and got.get("error"):
            self._chain = []
            self._log("llm", text=text, error=str(got["error"]))
            self._not_understood(lang, head=_T["ai_failed"][lang].format(why=self._ai_why(got["error"], lang)))
        elif not got or not got.get("intent"):
            self._chain = []
            self._log("llm", text=text, intent=None)
            self._not_understood(lang)
        else:
            cmd = dict(got)
            self._log("llm", text=text, seconds=cmd.get("seconds"), **_summary(cmd))
            self._route(cmd, lang)
            return
        if rest:
            self._say(_T["chain_dropped"][lang], "info")

    def _slow(self, intent):
        """Whether the host says `intent` is slow (a question to the local
        AI), so that it runs in a thread."""
        fn = getattr(self.host, "slow", None)
        try:
            return bool(fn and fn(intent))
        except Exception as exc:
            print("[assistant] slow failed:", exc, flush=True)
            return False

    def _run(self, cmd, lang):
        """Run a command that needs nothing more: a complaint, a slow
        question, an undo, or the host's command."""
        intent = cmd.get("intent")
        if intent == "complain":
            self._complain(lang)
            return
        if self._slow(intent):
            # A question to the local AI takes seconds: it runs in a thread.
            self._say(_T["asking_ai_question"][lang], "info")
            self._work_threaded(lambda: self.host.answer(cmd, lang) or {},
                                lambda r: self._answered(cmd, r, lang), lang, "the question")
            return
        if intent == "undo":
            # An undo typed as a sentence: the undo stack lives here, not in
            # the host; the rest of the sentence follows it
            def undo_then_go_on():
                self._undo_last(lang)
                self._continue(True, lang)
            self._work(undo_then_go_on, lang, "the undo")
        else:
            self._work(lambda: self._run_now(cmd, lang), lang, "the command " + str(intent))

    def _answered(self, cmd, r, lang):
        """Say a read-only command's reply, then go on with the chain."""
        self._say(str(r.get("text") or _T["done"][lang]),
                  "error" if r.get("ok") is False else "ok",
                  rows=r.get("rows"), publish=False)
        if r.get("ok") is not False:
            self._learned(cmd)
        self._continue(r.get("ok") is not False, lang)

    def _run_now(self, cmd, lang):
        """Run `cmd` through the host now: answer a read-only command,
        execute any other and push its undo token, then go on with the
        chain."""
        intent = cmd.get("intent")
        if self.host.readonly(intent):
            self._answered(cmd, self.host.answer(cmd, lang) or {}, lang)
            return
        r = self.host.execute(cmd, lang) or {}
        ok = r.get("ok") is not False
        token = r.get("undo") if ok else None
        # a gesture run by default offers the others instead — when nothing
        # of the sentence follows, so its reply stays the last message
        offer = self._offer(cmd, lang) if token is not None and not self._chain else []
        # else the next steps the host offers, the gesture kept ("keep only
        # these cells" after a highlight) — likewise when nothing follows
        follow = self._follow(r) if ok and not offer and not self._chain else []
        choices = offer or [{"id": f"then:{i}", "label": str(f["label"])} for i, f in enumerate(follow)]
        msg = self._say(str(r.get("text") or _T["done"][lang]), "ok" if ok else "error",
                        rows=r.get("rows"), choices=choices, publish=False)
        if offer:
            self._pending = (cmd["offer_instead"]["cmd"], lang)
        elif follow:
            self._pending = (dict(cmd, follow=[f["cmd"] for f in follow]), lang)
        if ok:
            self._learned(cmd)
        if token is not None:
            self._undo.append((token, cmd, msg["id"]))
            del self._undo[:-MAX_UNDO]
            self._mark_undoable()
        self._continue(ok, lang)

    def _continue(self, ok, lang):
        """Go on with the next request of the sentence, read now that the
        one before has run (what it showed or kept is the session's last
        command): run it, or ask about it — the chain then waits for the
        answer. A request not read goes to the local AI when there is one.
        After a failure the rest is dropped, and the reply says so."""
        if not self._chain:
            return
        if not ok:
            self._chain = []
            self._say(_T["chain_dropped"][lang], "info", publish=False)
            return
        nxt = self._chain.pop(0)
        if isinstance(nxt, str):
            words = nxt
            # a later request of the sentence: the host may read it as such
            # ("…then the gas" adds the gas to the values just filtered)
            parse = getattr(self.host, "parse_next", None)
            try:
                nxt = dict((parse if callable(parse) else self.host.parse)(words) or {})
            except Exception as exc:
                self._chain = []
                self._failed(exc, lang, "parse")
                return
            nxt["text"] = nxt.get("text") or words
            # a part is one request: the sentence was cut into its requests already
            nxt.pop("then", None)
            self._log("next", text=words, **_summary(nxt))
        self._route(nxt, lang)

    def _undo_last(self, lang):
        """Undo the action on top of the stack through the host; return
        whether it was undone."""
        if not self._undo:
            self._say(_T["nothing_to_undo"][lang], "info", publish=False)
            return False
        entry = self._undo.pop()
        self._mark_undoable()
        r = self.host.undo(entry[0], lang) or {}
        refused = r.get("ok") is False
        # The turn whose action is undone: what the parser took a sentence
        # for and the reader took back, the journal's best "misread" signal.
        self._log("undone", of_turn=self._turn_of.get(entry[2]),
                  intent=(entry[1] or {}).get("intent"), refused=refused)
        if not refused:
            self._unlearn(self._turn_of.get(entry[2]))
        if refused:
            # An undo the host refused (a Globe view, the grid gone) did not
            # happen: the action goes back on top, where a later undo reaches it.
            self._undo.append(entry)
        self._say(str(r.get("text") or _T["undone"][lang]),
                  "error" if refused else "ok", publish=False)
        if refused:
            self._mark_undoable()
        return not refused

    def _work(self, fn, lang, what):
        """Run `fn` (the host's work and the reply that says it) with the
        busy bar up.

        Inside a trame event the state goes out when the handler returns,
        after any work done in it. So with an event loop running, the bar
        is pushed, the handler returns, and `fn` runs as a task `YIELD_S`
        later, with the bar on screen. Without a loop, `fn` runs now."""
        self._busy = True
        self._publish()
        try:
            self.state.flush()
        except Exception as exc:
            print("[assistant] the busy state could not be pushed:", exc, flush=True)
        loop = _running_loop()
        if loop is None:
            self._finish(fn, lang, what, None)
            return

        async def _later():
            try:
                await asyncio.sleep(YIELD_S)
            except asyncio.CancelledError:
                print("[assistant] the command was cancelled before it ran", flush=True)
                self._busy = False
                raise
            with self.state:
                self._finish(fn, lang, what, task)

        task = loop.create_task(_later())
        self._task = task
        task.add_done_callback(self._task_done)

    def _work_threaded(self, blocking, then, lang, what):
        """Run `blocking`, a call that takes seconds (the local AI), in a
        THREAD with the busy bar up, then `then(result)` back on the loop,
        inside the state. Without a loop (a test, a headless call) both run
        now."""
        self._busy = True
        self._publish()
        try:
            self.state.flush()
        except Exception as exc:
            print("[assistant] the busy state could not be pushed:", exc, flush=True)
        loop = _running_loop()
        if loop is None:
            try:
                result = blocking()
            except Exception as exc:
                self._work_failed(exc, lang, what)
                self._busy = False
                self._publish()
                return
            self._then(then, result, lang, what, None)
            return

        async def _later():
            try:
                result = await asyncio.to_thread(blocking)
            except asyncio.CancelledError:
                print(f"[assistant] {what} was cancelled", flush=True)
                self._busy = False
                raise
            except Exception as exc:
                # the reply, the busy bar down and the rest of the sentence
                # dropped reach the browser together
                with self.state:
                    self._work_failed(exc, lang, what)
                    self._busy = False
                    self._publish()
                return
            with self.state:
                self._then(then, result, lang, what, task)

        task = loop.create_task(_later())
        self._task = task
        task.add_done_callback(self._task_done)

    def _then(self, then, result, lang, what, task):
        """Call `then(result)`. It may start another command (a task of its
        own): the busy bar then stays up for it, and comes down otherwise."""
        try:
            then(result)
        except Exception as exc:
            self._work_failed(exc, lang, what)
        finally:
            if self._task is task or self._task is None:
                self._busy = False
            self._publish()

    def _work_failed(self, exc, lang, what):
        """Say that `what` failed. The sentence stops there: its later
        requests waited for this one, and the reply says they were not done."""
        print(f"[assistant] {what} failed:", exc, flush=True)
        rest = bool(self._chain)
        self._chain = []
        self._say(_T["failed"][lang] + str(exc), "error", publish=False)
        if rest:
            self._say(_T["chain_dropped"][lang], "info", publish=False)

    def _finish(self, fn, lang, what, task):
        """Call `fn`, say its failure if any, then lower the busy bar — unless
        `fn` started another command of its own (the next request of the
        sentence, the local AI), which keeps the bar up until it is done."""
        try:
            fn()
        except Exception as exc:
            self._work_failed(exc, lang, what)
        finally:
            if self._task is task or self._task is None or self._task.done():
                self._busy = False
            self._publish()

    @staticmethod
    def _task_done(task):
        """Log the exception of a command's task that failed."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            print("[assistant] the command's task failed:", exc, flush=True)

    def _mark_undoable(self):
        """Only the message of the action on top of the stack carries the
        Undo button."""
        top = self._undo[-1][2] if self._undo else None
        for m in self._messages:
            if m.get("role") == "assistant":
                m["undoable"] = m["id"] == top

    def _failed(self, exc, lang, step):
        """Log and say that the host's `step` call failed."""
        print(f"[assistant] host.{step} failed:", exc, flush=True)
        self._say(_T["failed"][lang] + str(exc), "error")

    # ---------------------------------------------------------------- state
    def _refresh_examples(self, lang):
        """Fetch and return the host's examples in `lang` (none when the
        host fails)."""
        try:
            self._examples = [str(e) for e in (self.host.examples(lang) or []) if e]
        except Exception as exc:
            print("[assistant] host.examples failed:", exc, flush=True)
            self._examples = []
        return self._examples

    def _say_user(self, text, publish=True):
        return self._append({"role": "user", "text": str(text)}, publish)

    def _say(self, text, level, rows=None, choices=None, publish=True):
        """Append an assistant message (level info|ok|ask|error), tie it to
        the current turn and journal it."""
        msg = {"role": "assistant", "text": str(text), "level": level, "undoable": False}
        rows, choices = _rows(rows), _choices(choices)
        if rows:
            msg["rows"] = rows
        if choices:
            msg["choices"] = choices
        msg = self._append(msg, publish)
        self._turn_of[msg["id"]] = self._turn
        self._log("reply", level=level, text=str(text)[:REPLY_LOG_CHARS], rows=len(rows or ()),
                  choices=[c["label"] for c in choices or ()])
        return msg

    def _log(self, event, **fields):
        """Write one event to the dialogue journal, when there is one; a
        journal failure never breaks the conversation."""
        if self._journal is None:
            return
        try:
            self._journal(dict({"event": event, "turn": self._turn}, **fields))
        except Exception as exc:
            print("[assistant] the dialogue journal failed:", exc, flush=True)

    def _append(self, msg, publish):
        """Append `msg` with the next id, keeping the newest MAX_MESSAGES."""
        msg["id"] = self._next_id
        self._next_id += 1
        self._messages.append(msg)
        if len(self._messages) > MAX_MESSAGES:
            del self._messages[:-MAX_MESSAGES]
            # An action whose reply left the conversation cannot be undone:
            # no message could carry its Undo, and a typed undo would act on
            # something out of sight.
            first = self._messages[0]["id"]
            self._turn_of = {k: v for k, v in self._turn_of.items() if k >= first}
            self._said = {k: v for k, v in self._said.items() if k >= first}
            kept = [u for u in self._undo if u[2] >= first]
            if len(kept) != len(self._undo):
                self._undo = kept
                self._mark_undoable()
        if publish:
            self._publish()
        return msg

    def _data(self):
        # Fresh copies: the state compares the new value with the old one,
        # and a message changed in place would compare equal to itself.
        return {"messages": [dict(m) for m in self._messages], "busy": self._busy,
                "can_undo": bool(self._undo), "lang": self.lang,
                "examples": list(self._examples)}

    def _publish(self):
        self.state[self.data_var] = self._data()
