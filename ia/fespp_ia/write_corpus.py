"""Generate the training corpus of the home-made NLU engine with the
service's LLM (Mistral).

For each command of the catalogue, the model writes many ways a person
would ask for it. The label is KNOWN by construction (the command is
given) and only the wording comes from the model, so a wrong label cannot
slip in. The domain vocabulary comes from the RAG index (notions retrieved
for the command's description) and from the personas.

    python -m fespp_ia.write_corpus --url http://127.0.0.1:8000 --catalogue catalogue.json \\
        --out corpus_fr-mistral.jsonl --lang fr --per-call 12 --personas 4

`catalogue.json` is what the app's `catalogue_for_llm()` returns:
[{"name", "fr", "en", "slots"}]. The evaluation sentences of
tests/unit/data are NEVER shown to the model, so the measure stays honest;
the corpus loader also drops any sentence found in an evaluation set.

Output: one JSON object per line, {"text", "intent", "persona", ...the
slots the model states (category, kind, min, max)}, the shape of
ia/nlu/data/corpus_*.jsonl. Run once at install time against the service:
hours on a CPU, minutes on a GPU. An interrupted run resumes: a (command,
persona) pair already in the output is skipped.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

# (key, description) per language: the description goes into the prompt,
# the key onto every row written (a rerun skips the pairs already done)
PERSONAS = {
    "fr": [
        ("geologue", "un géologue de réservoir : faciès, chenaux, piliers, zones à huile, contacts, horizons, failles"),
        ("petrophysicien", "un pétrophysicien : PHIT, Sw, NTG, PERMX, saturations, seuils chiffrés, unités"),
        ("ingenieur", "un ingénieur réservoir : complétions, intervalles, puits producteurs, zones productrices, pas de temps, réalisations"),
        ("presse", "un utilisateur pressé qui tape vite, avec des fautes de frappe et d'accord, sans articles, des abréviations"),
        ("debutant", "un débutant qui découvre l'application et utilise des mots courants (la carte, les tuyaux, les couleurs)"),
        ("etudiant", "un étudiant en géosciences, poli, phrases longues, parfois hésitant"),
    ],
    "en": [
        ("geologist", "a reservoir geologist: facies, channels, pillars, oil zones, contacts, horizons, faults"),
        ("petrophysicist", "a petrophysicist: PHIT, Sw, NTG, PERMX, saturations, numeric cutoffs, units"),
        ("engineer", "a reservoir engineer: completions, intervals, producing wells, pay zones, time steps, realizations"),
        ("hurried", "a hurried user typing fast, with typos, no articles, abbreviations"),
        ("beginner", "a beginner discovering the application, everyday words (the map, the pipes, the colours)"),
        ("student", "a geoscience student, polite, long sentences, sometimes hesitant"),
    ],
}

# the object names, category values and property kinds the sentences may
# use; a category or kind slot is kept only when it is one of these
OBJECTS = ("Hugin", "Volve_SGrid", "Geogrid", "Drogon", "15/9-F-4", "15/9-F-11 A", "F-1 C", "Well 7",
           "Top Hugin", "PHIT", "PERMX", "NTG", "Fluids", "Lithology1", "WatSat", "Facies")
CATEGORIES = ("oil", "gas", "water", "sandstone", "shale", "siltstone", "limestone", "coal")
KINDS = ("porosity", "permeability", "water saturation", "net to gross", "facies", "gamma ray", "depth",
         "bulk density")

# the JSON schema the reply is constrained to
SCHEMA = {"type": "object",
          "properties": {"sentences": {"type": "array", "items": {"type": "object", "properties": {
              "text": {"type": "string"}, "category": {"type": ["string", "null"]},
              "kind": {"type": ["string", "null"]}, "min": {"type": ["number", "null"]},
              "max": {"type": ["number", "null"]}}, "required": ["text"]}}},
          "required": ["sentences"]}


def prompt(command, persona, lang, n, glossary):
    """The user prompt in `lang`: `n` sentences asking for `command`, in the
    voice of `persona`, using the domain notions of `glossary` when they fit."""
    fr = lang == "fr"
    desc = command.get("fr" if fr else "en") or command.get("fr") or command["name"]
    head = (f"Tu écris {n} phrases DIFFÉRENTES qu'une personne taperait à l'assistant d'un visualiseur de "
            f"réservoirs RESQML pour demander UNE chose : « {desc} » (commande {command['name']}). "
            f"La personne est {persona}. Varie les tournures (impératif, question, « je veux », fragment), "
            f"mets des noms d'objets parmi : {', '.join(OBJECTS)} quand la commande en prend un, des valeurs "
            f"de catégorie parmi : {', '.join(CATEGORIES)} (dis-les avec les mots du métier : huile, pétrole, "
            f"grès, argile…), des genres de propriété parmi : {', '.join(KINDS)}, des nombres quand il faut "
            f"une borne. Pour chaque phrase, donne category (mot canonique de la liste, ou null), kind (de la "
            f"liste, ou null), min et max (nombres, ou null) tels que la phrase les dit. Pas de phrase qui "
            f"demanderait une AUTRE commande. Réponds uniquement par le JSON demandé." if fr else
            f"You write {n} DIFFERENT sentences a person would type to the assistant of a RESQML reservoir "
            f"viewer to ask for ONE thing: \"{desc}\" (command {command['name']}). The person is {persona}. "
            f"Vary the shapes (imperative, question, 'I want', fragment), use object names among: "
            f"{', '.join(OBJECTS)} when the command takes one, category values among: {', '.join(CATEGORIES)} "
            f"(said with the trade's words), property kinds among: {', '.join(KINDS)}, numbers when a bound is "
            f"needed. For each sentence give category (a canonical word of the list, or null), kind (of the "
            f"list, or null), min and max (numbers, or null) as the sentence states them. No sentence that "
            f"would ask for ANOTHER command. Answer only with the JSON asked for.")
    if glossary:
        head += ("\nNotions du métier à employer quand elles conviennent : " if fr else
                 "\nDomain notions to use when they fit: ") + "; ".join(glossary)
    return head


def post(url, path, body, timeout=900):
    """POST `body` as JSON to url + path and return the decoded JSON reply.
    The default timeout is generous: a generation on a CPU takes minutes."""
    req = urllib.request.Request(url + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def glossary_for(url, command, lang, k=4):
    """A few domain notions retrieved from the index for the command's
    description: the titles of the best sources of a /v1/ask call with
    max_tokens 1, so that only the retrieval runs. [] when the call fails."""
    try:
        out = post(url, "/v1/ask", {"question": command.get("fr") or command["name"], "k": k, "lang": lang,
                                    "max_tokens": 1})
    except Exception:
        return []
    return [s.get("title", "").split(":")[0] for s in (out or {}).get("sources") or []][:k]


def main(argv=None):
    """Append the generated sentences to --out, command by command and
    persona by persona."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--catalogue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="fr", choices=("fr", "en"))
    ap.add_argument("--per-call", type=int, default=6)
    ap.add_argument("--personas", type=int, default=4)
    ap.add_argument("--only", help="comma-separated command names")
    ap.add_argument("--no-glossary", action="store_true")
    a = ap.parse_args(argv)
    catalogue = [c for c in json.load(open(a.catalogue, encoding="utf-8"))
                 if not a.only or c["name"] in a.only.split(",")]
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out, encoding="utf-8"):
            if line.strip():
                row = json.loads(line)
                done.add((row.get("intent"), row.get("persona")))
    written = 0
    with open(a.out, "a", encoding="utf-8") as out:
        for c in catalogue:
            glossary = [] if a.no_glossary else glossary_for(a.url, c, a.lang)
            for key, persona in PERSONAS[a.lang][:a.personas]:
                if (c["name"], key) in done:
                    continue
                t0 = time.monotonic()
                try:
                    # the language is stated in the system prompt too (a small
                    # model drifts to English), and the token budget is wide: a
                    # JSON reply cut short loses the whole batch
                    system = ("Tu écris UNIQUEMENT en français, comme un utilisateur francophone." if a.lang == "fr"
                              else "You write ONLY in English.")
                    reply = post(a.url, "/v1/chat", {
                        "messages": [{"role": "system", "content": system},
                                     {"role": "user", "content": prompt(c, persona, a.lang, a.per_call, glossary)}],
                        "schema": SCHEMA, "max_tokens": 110 * a.per_call + 150, "temperature": 0.8})
                    rows = json.loads(reply["text"]).get("sentences") or []
                except Exception as exc:
                    print(f"[write_corpus] {c['name']}/{key}: {exc}", file=sys.stderr, flush=True)
                    continue
                n = 0
                for r in rows:
                    text = str(r.get("text") or "").strip()
                    if len(text) < 4:
                        continue
                    row = {"text": text, "intent": c["name"], "persona": key}
                    for k in ("category", "kind"):
                        if r.get(k) and str(r[k]).lower() in (CATEGORIES if k == "category" else KINDS):
                            row[k] = str(r[k]).lower()
                    for k in ("min", "max"):
                        if isinstance(r.get(k), (int, float)):
                            row[k] = r[k]
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n += 1
                out.flush()
                written += n
                print(f"[write_corpus] {c['name']}/{key}: {n} sentences in {time.monotonic() - t0:.0f} s",
                      flush=True)
    print(f"[write_corpus] {written} sentences written to {a.out}")


if __name__ == "__main__":
    main()
