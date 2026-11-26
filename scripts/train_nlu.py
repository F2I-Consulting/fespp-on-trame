"""Train the command engine's intent classifier (fespp_on_trame/ia/nlu) into
``fespp_on_trame/assets/nlu_intents.npz``.

    docker run --rm -v "${PWD}:/repo" -w /repo --entrypoint /deploy/server/venv/bin/python \
        fespp_on_trame:local scripts/train_nlu.py [--quiet] [--heldout] [--confusions]

The training sentences come from two sources, both delexicalised
(slots.delex: object names replaced by placeholders):

- generated from the catalogue's patterns (ia/nlu/generate.py): every
  command in every shape the patterns know, with the trade's words;
- the corpus (ia/nlu/data/corpus_*.jsonl): sentences written by people
  given the catalogue and a persona, the shape of real requests. A fixed
  tenth of it, the same every run, is held out and never trained on.

The model is numpy only and trains on a CPU in a few minutes. It keeps the
words it was trained on (the engine tells an unknown sentence by them). The
script then scores it (ia/nlu/evaluation.py) on the held-out corpus — the
command read whole and as the application reads it (cut into its requests
by multi.split), and the parameters the sentences state — on the
hand-written sets of tests/unit/data (nlu_eval, never tuned on; nlu_dev_*
and nlu_journal, open for tuning) and, with --heldout, on the sealed sets,
printing their score only and never a sentence. Each line also counts the
readings the engine is sure of and gets wrong: the application carries
those out without asking.

--quiet hides the per-command corpus counts and the open sets' misses;
--confusions lists the command pairs most confused on the held-out corpus,
and its misses.
"""
import collections
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fespp_on_trame.ia.nlu import catalogue, corpus, evaluation, generate, slots  # noqa: E402
from fespp_on_trame.ia.nlu.engine import MODEL_PATH  # noqa: E402
from fespp_on_trame.ia.nlu.model import IntentModel, source_signature  # noqa: E402
from fespp_on_trame.ia.nlu.text import tokens  # noqa: E402

EVAL = os.path.join(evaluation.DATA_DIR, "nlu_eval.jsonl")
# the session objects the hand-written sentences are read against (kept
# under this name for the scripts that score with this module)
EVAL_OBJECTS = evaluation.EVAL_OBJECTS

#: Weight of a corpus sentence against a generated one, and the number of
#: training epochs. Both are tuned on the held-out corpus, together with 400
#: generated sentences per command: fewer epochs, a lower weight or fewer
#: generated sentences each score lower there.
CORPUS_WEIGHT = 4.0
EPOCHS = 60
#: The most sentences of one command the corpus weighs in full: past it, its
#: sentences weigh proportionally less, so a command the corpus covers
#: heavily carries the mass of a well-covered one, no more. It is 1.5 x the
#: median per-command count of the corpus the weights were tuned on — a
#: constant, so the commands that come with a small corpus of their own do
#: not lower the mass of the others.
CORPUS_CAP = 187.5


def _delex(text, objs):
    """The tokens of ``text`` with every slot found in it (``objs`` for the
    object names) replaced by its placeholder, as the engine sees them."""
    toks = tokens(text)
    return slots.delex(toks, slots.spans(toks, objs))


def vocabulary(texts):
    """The words of the training sentences, numbers apart: what the model
    has seen, so a sentence of none of them is not understood."""
    return {t for s in texts for t in tokens(s) if not any(c.isdigit() for c in t)}


def training_set(per_intent=400, seed=7, say=print):
    """Return (sentences, intents, weights, held-out corpus items, vocabulary).

    ``per_intent`` sentences are generated per command from a fixed
    ``seed``, so two runs train on the same set; ``say`` receives the
    progress lines, or None for silence.
    """
    objs = generate.objects()
    xs, ys, ws, texts = [], [], [], []
    for s, intent in generate.sentences(per_intent, seed):
        xs.append(_delex(s, objs))
        ys.append(intent)
        ws.append(1.0)
        texts.append(s)
    items = corpus.load(say=say)
    train, held = corpus.split(items)
    # a command the corpus covers heavily must not outweigh the others: past
    # CORPUS_CAP sentences, its sentences weigh proportionally less
    counts = collections.Counter(it["intent"] for it in train)
    for it in train:
        xs.append(_delex(it["text"], objs))
        ys.append(it["intent"])
        ws.append(CORPUS_WEIGHT * min(1.0, CORPUS_CAP / counts[it["intent"]]))
        texts.append(it["text"])
    if say:
        by = collections.Counter(it["intent"] for it in train)
        say(f"[nlu corpus] {len(train)} sentences to train on, {len(held)} held out; per command:"
            + " ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return xs, ys, ws, held, vocabulary(texts)


def train(quiet=False):
    """(the trained model, the held-out corpus items)."""
    t0 = time.time()
    xs, ys, ws, held, vocab = training_set(say=None if quiet else print)
    m = IntentModel(catalogue.NAMES, signature=source_signature(), vocab=vocab)
    losses = m.fit(xs, ys, weights=ws, epochs=EPOCHS)
    print(f"trained on {len(xs)} sentences in {time.time() - t0:.1f} s, loss {losses[0]:.3f} -> {losses[-1]:.3f}")
    return m, held


def evaluate(m, path=EVAL, objects=None):
    """Score the model on a hand-written set: (row count, misses), a miss
    being (text, wanted, got, confidence). Rows are read as the application
    reads them (evaluation.readings)."""
    res = evaluation.score(evaluation.rows(os.path.basename(path), os.path.dirname(path)),
                           objects or EVAL_OBJECTS, m)
    return res["n"], [mi[:4] for mi in res["misses"]]


def _line(name, res):
    n, ok = res["n"], res["right"]
    return (f"{name}: {ok}/{n} right ({100 * ok / max(n, 1):.1f} %), sure and wrong {res['sure_wrong']}"
            f" of {res['sure']} sure")


def report(m, held, heldout=False, quiet=False, confusions=False, say=print):
    """Print the scores of `m` on every evaluation set."""
    if held:
        objs = generate.objects()
        whole = evaluation.score(held, objs, m, split=False)
        cut = evaluation.score(held, objs, m, split=True)
        say(_line("corpus held out (whole sentence)", whole))
        say(_line("corpus held out (cut as the application does)", cut))
        say("  parameters, among the right commands: " + evaluation.slot_line(whole))
        wrong = collections.Counter((want, got) for _t, want, got, _c, _s in whole["misses"])
        total = collections.Counter(it["intent"] for it in held)
        right = total - collections.Counter(want for _t, want, _g, _c, _s in whole["misses"])
        weak = sorted(total, key=lambda k: right[k] / total[k])[:6]
        say("  weakest commands: " + ", ".join(f"{k} {right[k]}/{total[k]}" for k in weak))
        if confusions:
            for (want, got), c in wrong.most_common(12):
                say(f"  {want} read as {got}: {c}")
            for text, want, got, conf, sure in whole["misses"][:40]:
                say(f"  MISS {text!r}: want {want}, got {got} ({conf:.2f}{', sure' if sure else ''})")
    for name, objs in evaluation.OPEN_SETS:
        items = evaluation.rows(name)
        if not items:
            continue
        res = evaluation.score(items, objs, m)
        say(_line(name, res))
        say("  parameters: " + evaluation.slot_line(res))
        if not quiet:
            for text, want, got, conf, sure in res["misses"]:
                say(f"  MISS {text!r}: want {want}, got {got} ({conf:.2f}{', sure' if sure else ''})")
    # sealed: scored only with --heldout, and only the score is printed,
    # never a sentence: a sentence read is a sentence tuned on
    if heldout:
        for name, objs in evaluation.SEALED_SETS:
            items = evaluation.rows(name)
            if items:
                say(_line(name, evaluation.score(items, objs, m)))


def main():
    """Train and save the model, then print its score on every evaluation set."""
    quiet = "--quiet" in sys.argv
    m, held = train(quiet)
    m.save(MODEL_PATH)
    print("saved", MODEL_PATH, f"{os.path.getsize(MODEL_PATH) / 1024:.0f} KB")
    report(m, held, heldout="--heldout" in sys.argv, quiet=quiet, confusions="--confusions" in sys.argv)


if __name__ == "__main__":
    main()
