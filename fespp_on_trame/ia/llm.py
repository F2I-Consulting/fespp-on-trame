"""The application's client of the local AI service (fespp_ia: a Mistral
model behind llama.cpp, and the RAG index of the documentation).

Off unless FESPP_IA_URL names the service's base URL (http://ia:8000 in
compose.yaml, http://127.0.0.1:8000 on a workstation). Everything here is
a plain HTTP call with a timeout: on a CPU an answer takes tens of seconds,
so the callers run it OFF the event loop. Nothing leaves the machine: the
service runs without outbound network.

    ia = LocalIA.from_env()           # None when off
    ia.command(text, catalogue, objects, lang)  -> {"intent", "category", ...} or None
    ia.ask(question, lang)                      -> {"text", "sources"} or None
"""
import json
import os
import urllib.error
import urllib.request

TIMEOUT_S = 240.0   # a RAG question on a CPU: up to a minute or two
# How long the assistant waits for a sentence read as a command: the reader
# is in front of the panel, and a reading that takes longer has stalled (a
# queue full, a model still loading) — saying so beats waiting as long as a
# question to the documentation may take.
COMMAND_TIMEOUT_S = 90.0
HEALTH_TIMEOUT_S = 5.0

# Why a call failed or the service is out, as the reader is told it: the
# words a reason holds (urllib's, the service's 503 detail, the status of
# /v1/health), then the French and the English. The first that matches
# wins: the service's own detail before the bare 503 it comes with.
_REASONS = (
    (("timed out", "timeout"), "délai d'attente dépassé", "it took too long"),
    (("connection refused", "actively refused", "10061", "errno 111"), "connexion refusée, le service n'est pas lancé",
     "connection refused, the service is not running"),
    # the service went away during the call (restarted, stopped): Windows
    # gives its own text, sometimes in the system's language, with the code
    (("connection reset", "remote end closed", "forcibly closed", "connection aborted", "broken pipe", "10054",
      "10053", "errno 104", "errno 32"), "connexion interrompue", "connection lost"),
    (("the model refused", "502"), "le modèle a refusé la demande", "the model refused the request"),
    (("getaddrinfo", "name or service not known", "nodename nor servname", "no address associated"),
     "adresse du service introuvable", "the service's address is unknown"),
    (("busy",), "le service est occupé, sa file d'attente est pleine", "the service is busy, its queue is full"),
    (("does not answer", "llama-server stopped"), "le modèle ne répond pas", "the model does not answer"),
    (("no_model",), "aucun modèle n'est installé", "no model is installed"),
    (("no index",), "l'index de la documentation n'est pas construit", "the documentation's index is not built"),
    (("loading",), "le modèle est encore en chargement", "the model is still loading"),
    (("503",), "le service est indisponible pour l'instant", "the service is unavailable for now"),
    # a path the service does not serve: FESPP_IA_URL names another service,
    # or a version without that call
    (("404 ",), "le service ne connaît pas cette adresse (404) : vérifiez FESPP_IA_URL",
     "the service does not know this address (404): check FESPP_IA_URL"),
    (("500 ", "internal server error"), "le service a rencontré une erreur interne (500)",
     "the service failed on an internal error (500)"),
    # a reply that is not JSON (json.JSONDecodeError's own words)
    (("expecting value", "extra data", "unterminated string", "invalid control character", "jsondecodeerror"),
     "sa réponse est illisible (ce n'est pas du JSON)", "its reply cannot be read (it is not JSON)"),
    (("no command",), "sa réponse ne contient aucune commande", "its reply holds no command"),
)


def reason_words(why, lang="fr"):
    """`why` — the reason a call failed (`LocalIA.last_error`) or the
    service is out (its health status) — in the reader's words; a reason
    none of the known ones matches is given as it came."""
    text = str(why or "").strip()
    low = text.lower()
    for keys, fr, en in _REASONS:
        if any(k in low for k in keys):
            return en if lang == "en" else fr
    if not text:
        return "an empty reply" if lang == "en" else "réponse vide"
    return text


def vocabulary():
    """The canonical words a command's slots take, sent with /v1/command
    ("vocab") so the service can hold the model to them: the property
    kinds, the panels and the colour tables of the engine's lexicon."""
    from fespp_on_trame.ia.nlu import lexicon
    return {"kinds": list(lexicon.KINDS), "panels": list(lexicon.PANELS), "presets": list(lexicon.PRESETS)}


class LocalIA:
    """The HTTP client of one fespp_ia service. A failed call returns None
    and leaves its reason in `last_error`."""

    def __init__(self, url, timeout=TIMEOUT_S):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.last_error = ""

    @classmethod
    def from_env(cls, env=None):
        """The client FESPP_IA_URL names, or None when it is unset."""
        url = (env or os.environ).get("FESPP_IA_URL", "").strip()
        return cls(url) if url else None

    def _post(self, path, body, timeout=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout if timeout is None else timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # the service says why in its body ({"detail": "busy: …"}): a
            # full queue and a model that does not answer are both a 503
            self.last_error = f"{exc.code} {self._detail(exc) or exc.reason}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            self.last_error = str(exc)
        print(f"[assistant] local AI {path}: {self.last_error}", flush=True)
        return None

    @staticmethod
    def _detail(exc):
        """The `detail` of an HTTP error's JSON body, "" when there is none."""
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except (OSError, ValueError, AttributeError) as err:
            print("[assistant] local AI: an error without a readable body:", err, flush=True)
            return ""
        detail = body.get("detail") if isinstance(body, dict) else None
        return str(detail).strip() if detail else ""

    def health(self, timeout=HEALTH_TIMEOUT_S):
        """The service's /v1/health answer, or None when it does not answer
        within `timeout` seconds."""
        try:
            with urllib.request.urlopen(self.url + "/v1/health", timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            self.last_error = str(exc)
            print(f"[assistant] local AI health: {exc}", flush=True)
            return None

    def command(self, text, catalogue, objects, lang="fr", vocab=None, timeout=None):
        """The service's reading of `text` as a command of `catalogue`
        ([{name, fr, en}]) given `objects` ([{title, type, kind, parent,
        categories}]) and the slots' words `vocab` (`vocabulary()` when
        None): the command dict, plus the service's `_seconds` and the
        glossary entries it used (`_glossary`), or None when the call
        failed. `timeout` overrides the client's for this call."""
        out = self._post("/v1/command", {"text": text, "catalogue": catalogue, "objects": objects,
                                         "lang": lang, "vocab": vocabulary() if vocab is None else vocab},
                         timeout)
        if not out or not isinstance(out.get("command"), dict):
            return None
        cmd = dict(out["command"])
        cmd["_seconds"] = out.get("seconds")
        cmd["_glossary"] = out.get("glossary") or []
        return cmd

    def ask(self, question, lang="fr", k=6):
        """An answer from the documentation: {"text", "sources": [{title,
        source, path, score}], "seconds"}, or None."""
        out = self._post("/v1/ask", {"question": question, "lang": lang, "k": k})
        if not out or not out.get("text"):
            return None
        return {"text": out["text"], "sources": out.get("sources") or [], "seconds": out.get("seconds")}


# What the local model is told on top of the short description of each
# command, for the intents it tends to confuse. The descriptions
# (catalogue.INTENTS[...]["fr"]) stay short and untouched: they are also the
# help table the user reads, and part of the built-in model's signature.
# The show / hide / threshold rule is stated ONCE, under threshold (a fluid
# or facies zone shown or hidden is a threshold with category); show and
# hide only point at it. A number in the sentence does not make a
# threshold: "make ... stand out > 0.8" is a highlight. The complain hint
# covers the short questions about the last reply ("which grid?"), which
# the model cannot settle without the history and would otherwise read as
# ask. The examples quoted are made up for these hints, never sentences of
# an evaluation set: a test sentence quoted here would measure the prompt,
# not the model. Each entry is (French, English).
LLM_HINTS = {
    "show": ("un objet nommé, une propriété ou un nom donné seul, sans verbe (« les failles », « ntg ») ; seule une "
             "zone de fluide ou de faciès montrée (« fais voir le calcaire ») est threshold",
             "a named object, a property or a bare name with no verb ('the faults', 'ntg'); only a fluid or facies "
             "zone shown ('let me see the limestone') is threshold"),
    "hide": ("un objet nommé ou une propriété (« masque le net sur brut » → hide, kind) ; seule une zone de fluide "
             "ou de faciès cachée (« vire le grès de la grille ») est threshold, avec exclude",
             "a named object or a property ('take the net to gross away' → hide, kind); only a fluid or facies "
             "zone hidden ('remove the sandstone') is threshold, with exclude"),
    "isolate": ("« rien que X », « montre X et masque tout le reste », « isole X » : isolate, objects [X] ou kind — "
                "sans zone de fluide ni puits qui traversent (ce serait well_cells keep_crossing)",
                "'nothing but X', 'show X and hide everything else', 'isolate X': isolate, objects [X] or kind — "
                "no fluid zone nor crossing wells (that would be well_cells keep_crossing)"),
    "threshold": ("par valeur (min/max) ou par catégorie : une zone de fluide ou de faciès montrée, gardée ou cachée "
                  "est un seuil avec category (cachée : exclude, les autres valeurs restent) ; les mailles hors "
                  "condition disparaissent",
                  "by value (min/max) or by category: a fluid or facies zone shown, kept or hidden is a threshold "
                  "with category (hidden: exclude, the other values stay); the cells outside the condition "
                  "disappear"),
    "highlight": ("« mets en évidence », « signale », « emphasize », « flag » : highlight même avec un nombre "
                  "(min/max lus) ou une catégorie, rien ne disparaît ; threshold seulement quand des mailles doivent "
                  "partir ; avec des puits qui traversent, well_cells",
                  "'emphasize', 'flag', 'mark in colour': highlight even with a number (min/max read) or a "
                  "category, nothing disappears; threshold only when cells must go; with wells crossing, well_cells"),
    "well_cells": ("les mailles de la grille que traversent les puits (blocked wellbores, blocks des puits), y compris "
                   "une question sur le nombre ou les noms des puits qui atteignent une zone : un calcul sur la vue, "
                   "pas ask ; les mailles des puits là où une propriété vérifie une valeur (« les blocks des forages "
                   "où la perméabilité passe 300 ») : well_cells avec kind, min/max, pas threshold",
                   "the grid cells the wells go through (blocked wellbores, well blocks), including a question on "
                   "the number or the names of the wells that reach a zone: a computation on the view, not ask; the "
                   "wells' cells where a property meets a value ('the borehole blocks where permeability passes "
                   "300'): well_cells with kind, min/max, not threshold"),
    "color_range": ("les bornes min et max de l'échelle de couleurs, sans filtrer les mailles ni changer la palette",
                    "the min and max bounds of the colour scale, without filtering cells or changing the palette"),
    "open_panel": ("quand la phrase demande un panneau ou un outil (statistiques, histogramme, cross-plot, vue des "
                   "logs, explorateur XML…) : open_panel avec panel",
                   "when the sentence asks for a panel or a tool (statistics, histogram, cross-plot, log view, XML "
                   "explorer…): open_panel with panel"),
    "describe": ("une question sur ce qu'est un objet de la session (sa nature, son type, son origine) : describe, "
                 "objects [X] ; ask seulement pour une notion qui n'est pas un objet chargé",
                 "a question on what an object of the session is (its nature, its type, its origin): describe, "
                 "objects [X]; ask only for a notion that is not a loaded object"),
    "value": ("un chiffre demandé tout de suite (moyenne, min, max, médiane), sans ouvrir de panneau, même le long des "
              "puits (« la perméabilité médiane le long des forages » → value, kind permeability)",
              "a number asked for right away (mean, min, max, median), without opening a panel, even along the "
              "wells ('median permeability along the boreholes' → value, kind permeability)"),
    "open_tool": ("une carte outil de la vue 3D (explorateur de données, attributs, couleurs, coupes, seuils, "
                  "volumétrie, temps et réalisations, navigation, synchronisation des caméras) : open_tool avec "
                  "tool ; un panneau d'analyse (statistiques, cross-plot, logs, XML…) est open_panel",
                  "a tool card of the 3D view (data explorer, attributes, colormap, slicers, thresholds, "
                  "volumetrics, time and realizations, navigation, camera sync): open_tool with tool; an analysis "
                  "panel (statistics, cross-plot, logs, XML…) is open_panel"),
    "close_panel": ("fermer un panneau d'analyse ouvert : close_panel avec panel ; défaire le dernier geste est undo",
                    "closing an open analysis panel: close_panel with panel; taking back the last gesture is undo"),
    "camera_view": ("la caméra tournée vers une direction (dessus, dessous, nord, sud, est, ouest) ; recadrer sans "
                    "direction est reset_camera, avancer ou reculer est zoom",
                    "the camera turned to a direction (top, bottom, north, south, east, west); framing with no "
                    "direction is reset_camera, moving in or out is zoom"),
    "rep_style": ("le mode de dessin de toute la vue (surface, arêtes, fil de fer, points, contour) ; un nuage de "
                  "points qui croise deux propriétés est le cross-plot (open_panel)",
                  "the drawing style of the whole view (surface, edges, wireframe, points, outline); a scatter of "
                  "two properties is the cross-plot (open_panel)"),
    "color_scale": ("l'échelle des couleurs logarithmique ou linéaire ; « log » seul, sans mot de couleur ni "
                    "d'échelle, est un log de puits (open_panel welllog)",
                    "the colour scale made logarithmic or linear; 'log' alone, with no colour or scale word, is a "
                    "well log (open_panel welllog)"),
    "realization": ("une autre réalisation d'une propriété qui en a plusieurs ; un pas de temps ou une date est "
                    "time_step",
                    "another realization of a property that has several; a time step or a date is time_step"),
    "hide_all": ("tout masquer sans rien nommer ; masquer un objet nommé est hide",
                 "hide everything, nothing named; hiding a named object is hide"),
    "unsupported": ("une demande que l'application ne fait pas (capture d'écran, couleur du fond…) ou une "
                    "salutation : unsupported ; une question sur une notion est ask",
                    "a request the application does not do (a screenshot, the background colour…) or a greeting: "
                    "unsupported; a question about a notion is ask"),
    "complain": ("l'utilisateur se plaint, corrige ou demande ce que la réponse voulait dire : « l'écran reste vide », "
                 "« faux, recommence », « ce résultat ne me va pas… » (même si la phrase redit ce qui était voulu), "
                 "et une question courte sur ce que l'assistant vient de dire, sans objet de la session nommé : "
                 "« quelle grille ? », « des valeurs de quelle propriété ? », « lesquels, au juste ? »",
                 "the user complains, corrects or asks what the reply meant: 'the screen stays empty', 'wrong, try "
                 "again', 'this result does not suit me…' (even when the sentence repeats what was wanted), and a "
                 "short question about what the assistant just said, no session object named: 'which grid?', "
                 "'values of which property?', 'which ones, exactly?'"),
}
