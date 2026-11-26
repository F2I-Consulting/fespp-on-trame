"""The intent classifier: hashed n-grams and a softmax regression, numpy only
— it trains in under a minute on a CPU and answers in well under a
millisecond.

Features of a sentence already delexicalised (slots.delex):
    - the words and the pairs of words ("au dessus", "dessus <num>");
    - the letter trigrams to 5-grams of each word, which is what survives a
      typo ("porosiet") and a missing accent.
Each feature is hashed (crc32, stable across runs, unlike hash()) into DIM
columns; the vector is L2-normalised. A sentence has a hundred or so
features, so it is kept SPARSE (its columns and values): the training
gathers the rows of the weights it needs rather than building a dense
matrix of every sentence, which is what lets DIM be large enough for the
corpus without collisions — and the model stay a few MB.

The trained model is one .npz: the weights, the intent names, the words of
the sentences it was trained on (a sentence of none of them is not
understood, engine.parse), and the signature of the sources it was trained
from (see `source_signature`), so a test can say when the model is older
than its catalogue or its corpus.
"""
import zlib

import numpy as np

DIM = 1 << 16


def features(tokens):
    feats = []
    padded = ["<s>"] + list(tokens) + ["</s>"]
    for i, w in enumerate(padded):
        feats.append("w:" + w)
        if i + 1 < len(padded):
            feats.append("b:" + w + " " + padded[i + 1])
        if not w.startswith("<"):
            ww = f"#{w}#"
            for n in (3, 4, 5):
                for j in range(len(ww) - n + 1):
                    feats.append(f"c{n}:" + ww[j:j + n])
    return feats


def _columns(tokens):
    cols = {}
    for f in features(tokens):
        c = zlib.crc32(f.encode("utf-8")) & (DIM - 1)
        cols[c] = cols.get(c, 0.0) + 1.0
    idx = np.fromiter(cols.keys(), dtype=np.int64, count=len(cols))
    val = np.fromiter(cols.values(), dtype=np.float32, count=len(cols))
    val /= max(float(np.linalg.norm(val)), 1e-9)
    return idx, val


def sparse_rows(token_lists):
    """The sentences as one padded block: (idx, val) of shape (n, width),
    the padding pointing at column 0 with a value of 0 — a gather-friendly
    sparse matrix."""
    rows = [_columns(t) for t in token_lists]
    width = max((len(i) for i, _ in rows), default=1)
    idx = np.zeros((len(rows), width), dtype=np.int64)
    val = np.zeros((len(rows), width), dtype=np.float32)
    for r, (i, v) in enumerate(rows):
        idx[r, :len(i)] = i
        val[r, :len(v)] = v
    return idx, val


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


class IntentModel:
    """A softmax regression over the hashed features: weights (DIM x
    intents), biases, the training vocabulary and the source signature it
    was trained from."""

    def __init__(self, intents, w=None, b=None, signature="", vocab=()):
        self.intents = list(intents)
        self.w = w if w is not None else np.zeros((DIM, len(self.intents)), dtype=np.float32)
        self.b = b if b is not None else np.zeros(len(self.intents), dtype=np.float32)
        self.signature = signature
        self.vocab = frozenset(vocab)

    # ------------------------------------------------------------ training
    def fit(self, token_lists, labels, epochs=30, lr=8.0, l2=1e-6, batch=128, seed=0,
            weights=None):
        """Minibatch gradient descent on the cross-entropy, sparse: a batch
        gathers the weight rows of its features and scatters its gradient
        back. `weights` (one per sentence, default 1) lets the people's
        sentences count more than the generated ones. Returns the loss of
        each epoch."""
        y = np.array([self.intents.index(lab) for lab in labels])
        rng = np.random.default_rng(seed)
        idx_all, val_all = sparse_rows(token_lists)
        sw = (np.ones(len(y), dtype=np.float32) if weights is None
              else np.asarray(weights, dtype=np.float32))
        onehot = np.eye(len(self.intents), dtype=np.float32)[y]
        losses = []
        for _ in range(epochs):
            order = rng.permutation(len(y))
            total = 0.0
            for s in range(0, len(y), batch):
                i = order[s:s + batch]
                idx, val, t = idx_all[i], val_all[i], onehot[i]
                # z = x @ w, with x sparse: gather the rows, weight, sum
                z = np.einsum("bf,bfk->bk", val, self.w[idx]) + self.b
                p = _softmax(z)
                total += float((-np.log(np.maximum((p * t).sum(axis=1), 1e-12)) * sw[i]).sum())
                g = (p - t) * (sw[i] / len(i))[:, None]
                # scatter x.T @ g back on the rows the batch touched
                np.add.at(self.w, idx.ravel(), -lr * (val[:, :, None] * g[:, None, :]).reshape(-1, g.shape[1]))
                self.b -= lr * g.sum(axis=0)
            # the L2 decay, once per epoch on the whole table (cheap)
            self.w *= 1.0 - lr * l2 * (len(y) / batch)
            losses.append(total / float(sw.sum()))
        return losses

    # ------------------------------------------------------------ use
    def proba(self, tokens):
        """The probability of each intent, in the order of `intents`."""
        idx, val = _columns(tokens)
        z = val @ self.w[idx].astype(np.float32) + self.b
        return _softmax(z[None, :])[0]

    def ranked(self, tokens, top=3):
        """The `top` most likely intents, as (name, probability), best first."""
        p = self.proba(tokens)
        order = np.argsort(-p)[:top]
        return [(self.intents[i], float(p[i])) for i in order]

    # ------------------------------------------------------------ file
    def save(self, path):
        """One compressed .npz; the weights are stored as float16 to keep
        the file small."""
        np.savez_compressed(path, w=self.w.astype(np.float16), b=self.b,
                            intents=np.array(self.intents), signature=np.array(self.signature),
                            vocab=np.array(sorted(self.vocab), dtype=str))

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as z:
            # a model saved without its vocabulary loads with none
            vocab = [str(s) for s in z["vocab"]] if "vocab" in z.files else ()
            return cls([str(s) for s in z["intents"]], z["w"].astype(np.float32),
                       z["b"].astype(np.float32), str(z["signature"]), vocab)


def source_signature():
    """What the model is made of: the catalogue, the lexicon, the patterns,
    the corpus files, the features. A model whose signature differs is out
    of date.

    The whole source text of those modules is hashed, comments and
    docstrings included: any edit to catalogue, lexicon, generate, slots,
    bilingual (a French word naming an English title decides what becomes
    an object placeholder), text or corpus asks for a retrain
    (scripts/train_nlu.py)."""
    import glob
    import hashlib
    import inspect
    import os

    from fespp_on_trame.ia.nlu import bilingual, catalogue, corpus, generate, lexicon, slots, text
    h = hashlib.sha1()
    for mod in (catalogue, lexicon, generate, slots, bilingual, text, corpus):
        # the line endings a Windows checkout gives must not age the model
        h.update(inspect.getsource(mod).replace("\r\n", "\n").encode("utf-8"))
    h.update(inspect.getsource(features).replace("\r\n", "\n").encode("utf-8"))
    h.update(str(DIM).encode())
    for path in sorted(glob.glob(os.path.join(corpus.DATA_DIR, "corpus_*.jsonl"))):
        with open(path, "rb") as f:
            h.update(os.path.basename(path).encode())
            h.update(f.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]
