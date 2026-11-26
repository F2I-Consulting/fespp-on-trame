"""Benchmark a model on the two jobs of fespp_ia, through the running
service: questions (RAG) and commands (natural-language test sentences).

    python -m fespp_ia.bench --url http://127.0.0.1:8000 --commands commands.json --catalogue catalogue.json --out bench-<model>.json
    python -m fespp_ia.bench --rescore bench-a.json bench-b.json --questions bench-questions-metier.json

Questions: a dozen built-in domain questions, each with the notions a right
answer should hold. The score is a rough grade; the answers are stored in
full for a human to read. A question file (--questions, repeatable) is a
JSON list of {"q": question, "words": [notion, ...]}; a notion is a string,
or a list of strings that are its wordings in the two languages
(["colonne", "column"]). A notion counts once when any of its wordings
starts a word of the answer, case and accents folded ("porosit" matches
"porosité" and "Porosity"), so a French answer is not penalized for not
also saying the English word.

--rescore re-judges the answers stored in earlier reports against the
current lists, without any generation, and writes <name>-rescored.json next
to each report, so reports from different runs stay comparable under the
same judge. The stored hit rate was computed on the answer at run time; the
re-judged ones on the answer as the report stores it.

Commands (run only when both --commands and --catalogue are given): a JSON
list of {"text", "intent", "category"?, "well_filter"?, ...}, or a list of
groups {"lang", "items": [...]} whose items without a "context" are kept.
An item's intent is a name, or a list of the names a right reading may give
(a bare "the wells" is shown or listed). A command passes when its intent,
and its category and well_filter when the item states them, match the
label. The other slots an item states (SLOT_KEYS: kind, min, max, exclude,
panel, preset) are judged apart, each counted on its own: a miss there does
not fail the command, so the accuracy stays comparable with earlier reports.
The report keeps the time, the output tokens and the full command produced,
so a miss can be diagnosed. --vocab sends the application's canonical kinds,
panels and colour tables ({"kinds", "panels", "presets"}), as the
application does.

--rescore with --commands re-judges the commands stored in earlier reports
against that file's labels (matched by text), the same way, without any
generation: the stored verdict stays beside the new one (ok_stored).
"""
import argparse
import functools
import glob
import json
import os
import re
import statistics
import time
import unicodedata
import urllib.request

# the built-in questions, (question, expected notions): see the module docstring
QUESTIONS = [
    ("c'est quoi un pilier dans une grille IJK ?", ["k", ["colonne", "column"], ["coin", "corner"], "ligne"]),
    ("qu'est-ce qu'un chenal ?", [["chenal", "channel"], ["sable", "sand"], "fluvi", "corps"]),
    ("what is a sub-representation in RESQML?", [["subset", "sous"], "element", "cell", "representation"]),
    ("à quoi sert une blocked wellbore representation ?", [["cell", "maille"], ["grid", "grille"], ["trajectoire", "trajectory"]]),
    ("quelle est la différence entre une propriété continue et une propriété catégorielle ?", [["catég", "categor"], ["valeur", "value"], "continu"]),
    ("comment fonctionne un seuil (threshold) dans fespp_on_trame ?", [["maille", "cell"], ["plage", "range"], ["garde", "keep"], ["valeur", "value"]]),
    ("what does the Volumetrics tool compute?", ["volume", ["porosity", "porosité"], "saturation", "contact"]),
    ("qu'est-ce qu'une réalisation dans une propriété multi-réalisations ?", [["réalisation", "realization"], "stochast", "simulation", "version"]),
    ("what is ETP?", ["transfer", "protocol", "energistics", "websocket", "server"]),
    ("comment la caméra est-elle recadrée dans une vue 3D ?", [["camera", "caméra"], "reset", "recadr", ["bounds", "boîte"], "frame"]),
    ("what is a wellbore marker?", [["marker", "marqueur"], ["depth", "profondeur"], "horizon", "md"]),
    ("qu'est-ce que le net to gross ?", ["net", "gross", "ratio", ["réservoir", "reservoir"], ["épaisseur", "thickness"], "fraction"]),
]


def fold(s):
    """Lower-case and strip accents, so the judge reads "résistivité" and "Resistivity" alike."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def notions(words):
    """The expected list as folded notions, [[wording, ...], ...]: a string
    is a notion with one wording, a list is one notion with several."""
    return [[fold(w) for w in (item if isinstance(item, (list, tuple)) else [item])] for item in words]


@functools.lru_cache(maxsize=None)
def _starts_a_word(wording):
    """The pattern that finds `wording` at the start of a word (cached: the
    same wordings are searched in every answer)."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(wording))


def count_hits(folded_text, expected):
    """How many notions of `expected` (from notions()) the folded text
    holds: a notion counts once, whichever of its wordings starts a word."""
    return sum(1 for n in expected if any(_starts_a_word(w).search(folded_text) for w in n))


def judge(text, words):
    """{"hits", "of", "missing"} of an answer against the expected notions;
    the missing ones are written as the question file gives them (wordings
    joined by "/")."""
    folded = fold(text)
    found = [any(_starts_a_word(w).search(folded) for w in n) for n in notions(words)]
    return {"hits": sum(found), "of": len(found),
            "missing": ["/".join(item) if isinstance(item, (list, tuple)) else item
                        for item, ok in zip(words, found) if not ok]}


def _word_hits(text, words):
    """(hits, of) under the plain word rule: every wording counted on its
    own, found anywhere in the lower-cased answer. The rescore table shows
    it next to the stored and the notion rates: stored against words
    isolates the difference between the answer judged at run time and the
    stored one, words against notions isolates the effect of the judge."""
    flat = [w for item in words for w in (item if isinstance(item, (list, tuple)) else [item])]
    return sum(1 for w in flat if w.lower() in text.lower()), len(flat)


def _hit_rate(rows, hits, of):
    """Mean of row[hits] / row[of] over the rows, rounded to 2 decimals;
    None without rows."""
    return round(sum(r[hits] / r[of] for r in rows) / len(rows), 2) if rows else None


def rescore(report, expected):
    """A copy of an earlier report, re-judged on its stored answers against
    `expected` ({question: words}).

    Each row gets the new notion hits next to the stored ones (hits_stored,
    of_stored) and the word-rule hits (hits_words, of_words, see
    _word_hits); the summary gets the three rates: hit_rate_stored,
    hit_rate_words and hit_rate (notions). A row whose question is not in
    `expected` is left unchanged and counted as "unknown"."""
    out = json.loads(json.dumps(report))
    rows, unknown = [], 0
    for row in out.get("questions", []):
        if "answer" not in row:
            continue
        if row["q"] not in expected:
            unknown += 1
            continue
        words = expected[row["q"]]
        row["hits_words"], row["of_words"] = _word_hits(row["answer"], words)
        row.update({"hits_stored": row["hits"], "of_stored": row["of"], **judge(row["answer"], words)})
        rows.append(row)
    out.setdefault("summary", {})["questions"] = {
        **out.get("summary", {}).get("questions", {}), "n": len(rows), "judge": "notions",
        "hit_rate_stored": _hit_rate(rows, "hits_stored", "of_stored"),
        "hit_rate_words": _hit_rate(rows, "hits_words", "of_words"),
        "hit_rate": _hit_rate(rows, "hits", "of"), "unknown": unknown}
    return out


# the session the commands are read in: a grid with a fluid and a facies
# property, three continuous properties and two wells
BENCH_OBJECTS = [
    {"title": "Volve_SGrid", "type": "IjkGrid"},
    {"title": "Fluids", "type": "CategoricalProperty", "categories": ["water", "oil", "gas"]},
    {"title": "Lithology1", "type": "CategoricalProperty",
     "categories": ["Shale", "Sandstone", "Siltstone", "Limestone"]},
    {"title": "WatSat", "type": "ContinuousProperty", "kind": "water saturation"},
    {"title": "Porosity", "type": "ContinuousProperty", "kind": "porosity"},
    {"title": "PERMX", "type": "ContinuousProperty", "kind": "permeability"},
    {"title": "well_feature_NO_15_9-F-1_ABC", "type": "Wellbore"},
    {"title": "well_feature_NO_15_9-F-12_ABC", "type": "Wellbore"}]

# what makes a command pass, and the slots judged apart (see the docstring)
GATE_KEYS = ("intent", "category", "well_filter")
SLOT_KEYS = ("kind", "min", "max", "exclude", "panel", "preset")


def command_items(doc):
    """The labelled sentences of a commands file: a list of items, or a
    list of groups {"lang", "items"} whose items without a "context" are
    kept, each with its group's language (as the application sends the
    reader's language: guessing from accents would send unaccented French
    to the English prompt)."""
    res = doc.get("result", doc) if isinstance(doc, dict) else doc
    if isinstance(res, str):
        res = json.loads(res)
    if res and isinstance(res[0], dict) and "items" in res[0]:
        return [dict(it, lang=it.get("lang") or b.get("lang")) for b in res for it in b.get("items", [])
                if not it.get("context")]
    return res


def expected_of(item):
    """The labels an item states: the intent (a name or a list of names),
    the category and well_filter when given, and every slot of SLOT_KEYS it
    sets (0 and false are labels too)."""
    out = {k: item[k] for k in GATE_KEYS if item.get(k)}
    out.update({k: item[k] for k in SLOT_KEYS if item.get(k) is not None})
    return out


def _same(key, got, want):
    """One slot against its label: a switch counts null as false, a number
    is equal to rounding, a name is equal case and accents aside."""
    if key == "exclude" or isinstance(want, bool):
        return bool(got) == bool(want)
    if isinstance(want, (int, float)):
        return (isinstance(got, (int, float)) and not isinstance(got, bool)
                and abs(got - want) <= 1e-6 * max(1.0, abs(want)))
    if isinstance(want, str):
        return isinstance(got, str) and fold(got).strip() == fold(want).strip()
    return got == want


def judge_command(cmd, expected):
    """{"ok", "slots"} of a command against expected_of(item): ok when the
    intent is the label's (or one of its names) and the category and
    well_filter stated match; slots maps each other slot stated to whether
    it matches."""
    cmd = cmd or {}
    want = expected.get("intent")
    ok = cmd.get("intent") in want if isinstance(want, list) else cmd.get("intent") == want
    ok = ok and all(cmd.get(k) == expected[k] for k in GATE_KEYS[1:] if k in expected)
    return {"ok": bool(ok), "slots": {k: _same(k, cmd.get(k), expected[k]) for k in SLOT_KEYS if k in expected}}


def command_summary(rows):
    """The summary of judged command rows: n, the accuracy (the gate), the
    median seconds and output tokens, and per slot the labelled rows and
    the right ones."""
    cs = [c for c in rows if "command" in c]
    slots = {}
    for c in cs:
        for k, v in (c.get("slots") or {}).items():
            s = slots.setdefault(k, {"n": 0, "ok": 0})
            s["n"] += 1
            s["ok"] += bool(v)
    seconds = [c["seconds"] for c in cs if c.get("seconds") is not None]
    tokens = [c["tokens"] for c in cs if c.get("tokens")]
    return {"n": len(cs), "accuracy": round(sum(1 for c in cs if c["ok"]) / len(cs), 2) if cs else None,
            "median_seconds": statistics.median(seconds) if seconds else None,
            "median_tokens": statistics.median(tokens) if tokens else None,
            "slots": {k: slots[k] for k in SLOT_KEYS if k in slots}}


def rescore_commands(report, items):
    """A copy of an earlier report whose stored commands are re-judged
    against `items` (labelled sentences, matched by text): each row gets
    ok (the stored verdict kept as ok_stored), expected and slots, and the
    summary is recomputed; a row whose text no item has is counted as
    "unknown" and left out of the summary."""
    out = json.loads(json.dumps(report))
    by_text = {it["text"]: it for it in items}
    rows, unknown = [], 0
    for row in out.get("commands", []):
        it = by_text.get(row.get("text"))
        if it is None or "command" not in row:
            unknown += 1
            continue
        expected = expected_of(it)
        row.update({"ok_stored": row.get("ok"), "expected": expected, "want": it["intent"],
                    **judge_command(row["command"], expected)})
        rows.append(row)
    out.setdefault("summary", {})["commands"] = {**command_summary(rows), "unknown": unknown}
    return out


def question_files(paths):
    """The question files to read: those given, else every bench-questions-*.json next to the package (in ia/)."""
    return paths or sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench-questions-*.json")))


def load_questions(path):
    """[(question, words)] of a question file."""
    with open(path, encoding="utf-8") as f:
        return [(x["q"], x["words"]) for x in json.load(f)]


def bench_name(path):
    """bench-questions-metier.json -> metier."""
    name = os.path.basename(path)
    name = name[:-5] if name.endswith(".json") else name
    return name[len("bench-questions-"):] if name.startswith("bench-questions-") else name


def post(url, path, body, timeout=900):
    """POST `body` as JSON to url + path and return the decoded JSON reply.
    The default timeout is generous: a generation on a CPU takes minutes."""
    req = urllib.request.Request(url + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv=None):
    """Run the benchmark against the service and write the report, or
    re-judge stored reports (--rescore)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--commands", help="the PO-style items (json: [{'lang','who','items':[...]}] or a list)")
    ap.add_argument("--catalogue", help="catalogue.json for /v1/command")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--out", help="the report (required unless --rescore)")
    ap.add_argument("--skip-questions", action="store_true")
    ap.add_argument("--questions", action="append", default=[],
                    help="a question file, repeatable: instead of the built-in twelve (a run), beside them (--rescore)")
    ap.add_argument("--rescore", nargs="+", metavar="BENCH.json",
                    help="re-judge the answers stored in these reports with the current lists, no generation;"
                         " with --commands, their commands against that file's labels")
    ap.add_argument("--vocab", help="the application's names for /v1/command (json: {'kinds','panels','presets'})")
    a = ap.parse_args(argv)
    if a.rescore and a.commands:
        items = command_items(json.load(open(a.commands, encoding="utf-8")))
        print(f"[rescore] {'file':44} {'n':>3} {'stored':>7} {'ok':>6} {'unknown':>8}  slots")
        for path in a.rescore:
            with open(path, encoding="utf-8") as f:
                out = rescore_commands(json.load(f), items)
            name = path[:-5] if path.endswith(".json") else path
            with open(name + "-rescored.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            s = out["summary"]["commands"]
            stored = sum(1 for c in out["commands"] if c.get("ok_stored"))
            ok = sum(1 for c in out["commands"] if c.get("ok") and "ok_stored" in c)
            print(f"[rescore] {os.path.basename(path):44} {s['n']:>3} {stored:>7} {ok:>6} {s['unknown']:>8}  "
                  + ", ".join(f"{k} {v['ok']}/{v['n']}" for k, v in s["slots"].items()))
        return
    if a.rescore:
        expected = dict(QUESTIONS)
        for path in question_files(a.questions):
            expected.update(load_questions(path))
        print(f"[rescore] {'file':44} {'n':>3} {'stored':>7} {'words':>6} {'notions':>8} {'unknown':>8}")
        for path in a.rescore:
            with open(path, encoding="utf-8") as f:
                out = rescore(json.load(f), expected)
            name = path[:-5] if path.endswith(".json") else path
            with open(name + "-rescored.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            s = out["summary"]["questions"]
            print(f"[rescore] {os.path.basename(path):44} {s['n']:>3} {str(s['hit_rate_stored']):>7} "
                  f"{str(s['hit_rate_words']):>6} {str(s['hit_rate']):>8} {s['unknown']:>8}")
        return
    if not a.out:
        ap.error("--out is required")
    with urllib.request.urlopen(a.url + "/v1/health", timeout=10) as r:
        health = json.loads(r.read().decode("utf-8"))
    report = {"model": health.get("model"), "rag": health.get("rag"), "questions": [], "commands": []}
    if not a.skip_questions:
        questions = [x for path in a.questions for x in load_questions(path)] if a.questions else QUESTIONS
        for q, words in questions:
            t0 = time.monotonic()
            try:
                out = post(a.url, "/v1/ask", {"question": q, "k": 6, "lang": "fr" if any(c in q for c in "éèàç") or q.startswith(("c'", "qu", "à", "comment")) else "en"})
                text = out.get("text", "")
                report["questions"].append({"q": q, "seconds": round(time.monotonic() - t0, 1), **judge(text, words),
                                            "answer": text.strip(),
                                            "sources": [s.get("title") for s in out.get("sources", [])][:3]})
            except Exception as exc:
                report["questions"].append({"q": q, "error": str(exc)})
            print(f"[bench] q {report['questions'][-1].get('seconds')} s hits {report['questions'][-1].get('hits')}: {q}", flush=True)
    if a.commands and a.catalogue:
        items = command_items(json.load(open(a.commands, encoding="utf-8")))
        catalogue = json.load(open(a.catalogue, encoding="utf-8"))
        vocab = json.load(open(a.vocab, encoding="utf-8")) if a.vocab else None
        report["vocab"] = bool(vocab)
        for it in items[:a.limit]:
            t0 = time.monotonic()
            expected = expected_of(it)
            try:
                lang = it.get("lang") or ("fr" if any(c in it["text"] for c in "éèàçù") else "en")
                # no "k": the bench uses the service's default, as the application does
                body = {"text": it["text"], "catalogue": catalogue, "objects": BENCH_OBJECTS, "lang": lang}
                if vocab:
                    body["vocab"] = vocab
                out = post(a.url, "/v1/command", body)
                cmd = out.get("command") or {}
                report["commands"].append({"text": it["text"], "want": it["intent"], "got": cmd.get("intent"),
                                           **judge_command(cmd, expected),
                                           "seconds": round(time.monotonic() - t0, 1), "tokens": out.get("tokens"),
                                           "command": cmd, "expected": expected})
            except Exception as exc:
                report["commands"].append({"text": it["text"], "want": it["intent"], "error": str(exc), "expected": expected})
            print(f"[bench] cmd {report['commands'][-1].get('seconds')} s {'ok ' if report['commands'][-1].get('ok') else 'MISS'}: {it['text'][:60]}", flush=True)
    qs = [q for q in report["questions"] if "seconds" in q]
    report["summary"] = {
        "questions": {"n": len(qs), "hit_rate": _hit_rate(qs, "hits", "of"),
                      "median_seconds": statistics.median(q["seconds"] for q in qs) if qs else None},
        "commands": command_summary(report["commands"])}
    json.dump(report, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[bench]", report["model"], json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
