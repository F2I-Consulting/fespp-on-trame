"""The corpus: sentences written by people — independent writers given the
catalogue and a persona — in `data/corpus_<lang>-<writer>.jsonl`: what the
classifier learns the SHAPE of real requests from, next to the generated
sentences of `generate.py`, which only know their patterns.

One JSON object per line: {"text", "intent"} plus the slots the sentence
states (kind, category, panel, preset, axis, min, max, factor, on, object,
direction, step, style, scale, tool) — the same keys the evaluation sets use
(tests/unit/data/nlu_*.jsonl).

`load()` reads every file, drops what is not a sentence of the catalogue,
the duplicates, and — so the measures stay honest — every sentence that
also sits in an evaluation set (compared normalised: the sealed sets are
read by this code, never by a person). `split()` keeps a tenth aside, by a
hash of the text, so the same sentences are held out at every run: the
score on them says how the model does on people's words it never saw.
"""
import glob
import json
import os
import zlib

from fespp_on_trame.ia.nlu import catalogue
from fespp_on_trame.ia.nlu.text import normalize

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "tests", "unit", "data")

SLOT_KEYS = ("kind", "category", "panel", "preset", "axis", "min", "max", "factor", "on", "object",
             "direction", "step", "style", "scale", "tool")


def _rows(path):
    """(line number, row) for each JSON line of `path`; a bad line is
    reported and skipped."""
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                print(f"[nlu corpus] {os.path.basename(path)}:{n} is not JSON, skipped: {exc}", flush=True)
                continue
            yield n, row


def eval_texts(eval_dir=EVAL_DIR):
    """The normalised texts of every evaluation set, sealed ones included —
    read by the machine to keep them OUT of the training, never shown."""
    out = set()
    for path in glob.glob(os.path.join(eval_dir, "nlu_*.jsonl")):
        for _n, row in _rows(path):
            if row.get("text"):
                out.add(normalize(row["text"]))
    return out


def load(data_dir=DATA_DIR, eval_dir=EVAL_DIR, say=print):
    """[{text, intent, lang, source, slots…}] — clean, unique, none of them
    in an evaluation set. `source` is the file name after "corpus_"
    ("fr-geol"), `lang` its first part."""
    banned = eval_texts(eval_dir)
    seen, out, dropped = set(), [], {"bad": 0, "dup": 0, "eval": 0}
    for path in sorted(glob.glob(os.path.join(data_dir, "corpus_*.jsonl"))):
        source = os.path.basename(path)[len("corpus_"):-len(".jsonl")]
        lang = source.split("-")[0]
        for n, row in _rows(path):
            text = str(row.get("text") or "").strip()
            intent = row.get("intent")
            if not text or intent not in catalogue.INTENTS:
                dropped["bad"] += 1
                continue
            key = normalize(text)
            if not key or key in seen:
                dropped["dup"] += 1
                continue
            if key in banned:
                dropped["eval"] += 1
                continue
            seen.add(key)
            item = {"text": text, "intent": intent, "lang": lang, "source": source}
            for k in SLOT_KEYS:
                if k in row and row[k] not in (None, ""):
                    item[k] = row[k]
            out.append(item)
    if say:
        say(f"[nlu corpus] {len(out)} sentences kept, dropped: {dropped['bad']} not of the catalogue,"
            f" {dropped['dup']} duplicates, {dropped['eval']} also in an evaluation set")
    return out


def split(items, holdout=0.1):
    """(train, held_out): the tenth held out chosen by a hash of the text,
    the same at every run, whatever the order or the number of files."""
    train, held = [], []
    for it in items:
        h = zlib.crc32(normalize(it["text"]).encode("utf-8")) % 1000
        (held if h < holdout * 1000 else train).append(it)
    return train, held
