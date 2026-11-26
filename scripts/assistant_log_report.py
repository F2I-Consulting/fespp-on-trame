"""Report what the assistant's dialogue journal shows needs work.

    python scripts/assistant_log_report.py <journal folder> [--candidates out.jsonl]

The journal is the one fespp_on_trame/ia/journal.py writes. Each exchange
(a sentence, the command the engine read in it, the replies, what the
reader did next) is sorted into one of these groups:

- NOT UNDERSTOOD: the engine named no command;
- ASKED BACK: the assistant asked "did you mean...?" or "which one?"; a
  command the reader then chose labels the sentence with what they meant;
- UNDONE: an action the reader took back, the likeliest misreadings;
- REFUSED: understood but not doable (nothing found, a grid property
  needed...), often a word of the trade the lexicon lacks;
- REPHRASED: the reader answered "none of these", then made the same
  request in other words that worked; the first wording and what it meant
  make a labelled example;
- EXPECTED: rephrased and still not understood; the result the reader
  described, to be added to the vocabulary by hand;
- DONE: everything else, counted per command.

``--candidates`` writes one JSON line per sentence worth reviewing:
{"text", "engine_intent", "confidence", "intent" (the reader's choice, or
null), "source"}, plus "slots" and "rephrased_as" for a rephrasing and
"expected" for a described result. Once reviewed by hand, they feed the
patterns, the lexicon or the tuning sets (tests/unit/data/nlu_dev_*.jsonl),
never the sealed evaluation sets.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fespp_on_trame.ia.journal import read  # noqa: E402


def _empty():
    """A blank exchange: the opening sentence and one list per follow-up kind."""
    return {"said": None, "replies": [], "choices": [], "undone": [], "learned": [], "expected": [],
            "unlearned": [], "complained": []}


def exchanges(events):
    """Group journal events into exchanges keyed by (session, turn), in order.

    "said", "reply" and "choose" events belong to their own turn; the
    follow-ups (undone, learned, expected, unlearned, complain) name the
    turn they refer to in ``of_turn`` and join that exchange.
    """
    out = collections.OrderedDict()
    for e in events:
        key = (e.get("session"), e.get("turn"))
        x = out.setdefault(key, _empty())
        kind = e.get("event")
        if kind == "said":
            x["said"] = e
        elif kind == "reply":
            x["replies"].append(e)
        elif kind == "choose":
            x["choices"].append(e)
        elif kind == "undone":
            out.setdefault((e.get("session"), e.get("of_turn")), _empty())["undone"].append(e)
        elif kind in ("learned", "expected", "unlearned"):
            out.setdefault((e.get("session"), e.get("of_turn")), _empty())[kind].append(e)
        elif kind == "complain":
            out.setdefault((e.get("session"), e.get("of_turn")), _empty())["complained"].append(e)
    return out


def sort(xs):
    """Sort exchanges into the report's groups.

    "learned" and "expected" collect follow-ups whatever the exchange's own
    outcome. Every other exchange lands in exactly one group, the first that
    matches: undone, not understood, asked back, refused, done. An "undo"
    sentence is the reader's correction, not a request, and is not sorted.
    """
    groups = {"learned": [], "expected": [], "not_understood": [], "asked": [], "undone": [],
              "refused": [], "done": []}
    for x in xs.values():
        said = x["said"]
        # a learned rephrasing that was withdrawn ("unlearned") is no example
        if x["learned"] and not x["unlearned"]:
            groups["learned"].append(x)
        if x["expected"]:
            groups["expected"].append(x)
        if not said or said.get("intent") == "undo":
            continue
        levels = [r.get("level") for r in x["replies"]]
        if x["undone"]:
            groups["undone"].append(x)
        elif said.get("intent") is None:
            groups["not_understood"].append(x)
        elif any(r.get("choices") for r in x["replies"]):
            groups["asked"].append(x)
        elif "error" in levels:
            groups["refused"].append(x)
        else:
            groups["done"].append(x)
    return groups


def _line(x):
    """One exchange as the report prints it: the sentence and how the engine
    read it, then the replies and what the reader did next."""
    s = x["said"]
    conf = s.get("confidence")
    head = f"« {s.get('text')} » → {s.get('intent')}" + (f" ({conf:.2f})" if isinstance(conf, float) else "")
    alts = ", ".join(f"{a[0]} {a[1]:.2f}" for a in s.get("alternatives") or () if len(a) == 2)
    parts = [head]
    if alts:
        parts.append(f"   autres lectures : {alts}")
    if s.get("slots"):
        parts.append(f"   paramètres : {s['slots']}")
    if s.get("n_targets"):
        more = f" (+{s['n_targets'] - len(s['targets'])})" if s["n_targets"] > len(s.get("targets") or ()) else ""
        parts.append(f"   objets visés : {', '.join(map(str, s.get('targets') or ()))}{more}")
    for r in x["replies"]:
        parts.append(f"   [{r.get('level')}] {r.get('text')}")
    for c in x["choices"]:
        parts.append(f"   ↳ choisi : {c.get('label')} ({c.get('choice')})")
    for _c in x["complained"]:
        parts.append("   ✗ le lecteur a dit que la réponse ne convenait pas")
    for u in x["undone"]:
        parts.append(f"   ↺ annulé{' (refusé)' if u.get('refused') else ''}")
    return "\n".join(parts)


def candidates(groups):
    """The rows ``--candidates`` writes, one per sentence worth reviewing.

    For a sorted exchange, the label ("intent") is the last command the
    reader chose from the assistant's offer (a choice ``intent:<name>``),
    or None when they chose none.
    """
    out = []
    for x in groups["learned"]:
        for e in x["learned"]:
            out.append({"text": e.get("original"), "engine_intent": (x["said"] or {}).get("intent"),
                        "confidence": (x["said"] or {}).get("confidence"), "intent": e.get("intent"),
                        "slots": e.get("slots"), "rephrased_as": e.get("text"), "source": "rephrased"})
    for x in groups["expected"]:
        for e in x["expected"]:
            out.append({"text": e.get("original"), "engine_intent": (x["said"] or {}).get("intent"),
                        "confidence": (x["said"] or {}).get("confidence"), "intent": None,
                        "expected": e.get("text"), "source": "expected"})
    for source in ("not_understood", "asked", "undone", "refused"):
        for x in groups[source]:
            s = x["said"]
            chosen = None
            for c in x["choices"]:
                if str(c.get("choice", "")).startswith("intent:"):
                    chosen = c["choice"][len("intent:"):]
            out.append({"text": s.get("text"), "engine_intent": s.get("intent"),
                        "confidence": s.get("confidence"), "intent": chosen, "source": source})
    return out


def main(argv):
    """Print the report for the journal folder ``argv[0]``; with no argument,
    print the usage."""
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    folder = argv[0]
    events = read(folder)
    xs = exchanges(events)
    groups = sort(xs)
    total = sum(len(groups[k]) for k in ("not_understood", "asked", "undone", "refused", "done"))
    print(f"{len(events)} événements, {total} phrases, dans {folder}\n")
    titles = {"learned": "REFORMULÉES (exemples étiquetés : ce que la phrase voulait dire)",
              "expected": "RÉSULTAT ATTENDU DÉCRIT (à ajouter au vocabulaire)",
              "not_understood": "NON COMPRIS", "asked": "QUESTIONS POSÉES (et la réponse du lecteur)",
              "undone": "ANNULÉS (lectures probablement fausses)", "refused": "REFUSÉS (compris, pas faisable)",
              "done": "FAITS"}
    for key in ("learned", "expected"):
        print(f"== {titles[key]} : {len(groups[key])}")
        for x in groups[key]:
            for e in x[key]:
                if key == "learned":
                    print(f"« {e.get('original')} » = « {e.get('text')} » → {e.get('intent')} {e.get('slots') or ''}")
                else:
                    print(f"« {e.get('original')} » : attendu « {e.get('text')} »")
        print()
    for key in ("not_understood", "asked", "undone", "refused"):
        print(f"== {titles[key]} : {len(groups[key])}")
        for x in groups[key]:
            print(_line(x))
        print()
    print(f"== {titles['done']} : {len(groups['done'])}")
    by = collections.Counter(x["said"].get("intent") for x in groups["done"])
    print("   " + ", ".join(f"{k} {v}" for k, v in by.most_common()))
    if "--candidates" in argv:
        path = argv[argv.index("--candidates") + 1]
        rows = candidates(groups)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n{len(rows)} phrases à revoir écrites dans {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
