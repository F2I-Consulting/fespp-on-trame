"""The index of the RAG and its search — numpy at query time, the
embedding model only to turn a text into a vector.

    build_index(chunks.jsonl, index_dir, model_dir)   at install time
    Index.load(index_dir, model_dir).search("what is a pillar?", k=6)

The index is two files: `vectors.npy` (float16, unit length, one row per
chunk) and `chunks.jsonl` (the chunks in the same order), plus `meta.json`
(the model's name, the count). Search = cosine similarity re-ranked by the
notions a chunk names and by its source (Index.search), top k, with an
optional filter on the source.

The embedding model is a sentence-transformers folder (the service never
downloads: ia/get-model.ps1 brings it): bilingual-embedding-small by La
Javaness (Paris, Apache-2.0) — French and English in one space, 384
dimensions, fast on a CPU.
"""
import json
import os
import re
import time
import unicodedata

import numpy as np

DEFAULT_MODEL = "Lajavaness/bilingual-embedding-small"

# the search is HYBRID: the vectors say what a chunk is about, the words
# say whether it names the notion asked — "pilier" must find "pillar" in
# an English Doxygen block. A small bridge between the two languages of
# the corpus, for the trade's notions.
BRIDGE = {
    "pilier": "pillar", "piliers": "pillars", "chenal": "channel", "chenaux": "channels", "faille": "fault",
    "failles": "faults", "maille": "cell", "mailles": "cells", "puits": "well wellbore", "grille": "grid",
    "grilles": "grids", "couche": "layer", "couches": "layers", "colonne": "column", "colonnes": "columns",
    "propriete": "property", "proprietes": "properties", "seuil": "threshold", "coupe": "slice",
    "realisation": "realization", "realisations": "realizations", "marqueur": "marker", "marqueurs": "markers",
    "trajectoire": "trajectory", "trajectoires": "trajectories", "sous": "sub", "representation": "representation",
    "surface": "surface", "horizon": "horizon", "porosite": "porosity", "permeabilite": "permeability",
    "saturation": "saturation", "categorielle": "categorical", "continue": "continuous", "discrete": "discrete",
    "temps": "time", "serie": "series", "contact": "contact", "sommet": "corner", "coin": "corner",
    "noeud": "node", "geometrie": "geometry", "explicite": "explicit", "parametrique": "parametric",
    "structuree": "structured", "volumetrie": "volumetrics", "calculatrice": "calculator", "derivee": "derived",
    "legende": "legend", "camera": "camera", "vue": "view", "session": "session", "fichier": "file",
    "reseau": "network", "unites": "units", "unite": "unit", "profondeur": "depth", "epaisseur": "thickness",
}
# the lead a chunk gets in the ranking, by source (fespp_ia.corpus.source_of)
SOURCE_BOOST = {"docs": 0.12, "energistics": 0.12, "geologie": 0.12, "pwls": 0.12}
# A question about the application itself -- a tool, a panel, a button,
# the assistant -- is answered by the application's own documentation,
# not by the geology wikis, which may describe another tool of the same
# name ("Volumetrics"). When the question names the application, its
# documentation gets this lead on top of the source's.
APP_TERMS = ("fespp", "application", "assistant", "volumetric", "volumetrie", "compare", "comparaison",
             "statistic", "statistique", "stats", "calculator", "calculatrice", "data health", "sante des donnees",
             "xml explorer", "log view", "vue log", "import", "session", "panel", "panneau", "tool", "outil",
             "button", "bouton", "widget", "3d view", "vue 3d", "camera", "palette", "colormap", "slicer",
             "reload", "recharge")
APP_BOOST = 0.15
APP_SOURCES = ("fespp_on_trame", "docs")
STOP = set("""
a an the of in on at to for and or is are be what which how does do it its this that with from by as un une le la
les des du de d l et ou est sont ce cette ces que qui quoi quel quelle quels quelles comment dans sur pour par avec
au aux se sa son ses il elle on nous vous ils elles ne pas plus fait faire veut dire signifie sert servent
""".split())


def _fold(s):
    """Lower case without accents: the form every word match compares."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def keywords(query):
    """The words of a question worth matching: folded, no stop word, four
    letters or more, each with its bridge to the other language."""
    out = []
    for w in re.findall(r"[a-zA-ZÀ-ɏ][a-zA-ZÀ-ɏ0-9]+", query):
        f = _fold(w)
        if len(f) < 4 or f in STOP:
            continue
        group = {f, f[:-1] if f.endswith("s") else f}
        group.update(BRIDGE.get(f, "").split())
        out.append(tuple(sorted(x for x in group if x)))
    return out


def keyword_score(chunk, terms):
    """The share of the question's notions the chunk names — in its title
    (counted twice) or its text — 0..1."""
    if not terms:
        return 0.0
    title = _fold(chunk.get("title", ""))
    text = _fold(chunk.get("text", ""))
    score = 0.0
    for group in terms:
        if any(t in title for t in group):
            score += 1.0
        elif any(t in text for t in group):
            score += 0.6
    return score / len(terms)


class Embedder:
    """Texts -> unit vectors, through sentence-transformers."""

    def __init__(self, model_dir):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(str(model_dir), device="cpu", trust_remote_code=True)
        self.name = os.path.basename(str(model_dir).rstrip("/\\"))

    def encode(self, texts, batch_size=32):
        v = self.model.encode(list(texts), batch_size=batch_size, normalize_embeddings=True,
                              convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(v, dtype=np.float32)


def read_chunks(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_index(chunks_path, index_dir, model_dir, say=print):
    """Embed every chunk (its title and its text) and write the index."""
    chunks = read_chunks(chunks_path)
    emb = Embedder(model_dir)
    t0 = time.monotonic()
    vectors = np.zeros((len(chunks), 0), dtype=np.float16)
    parts = []
    for i in range(0, len(chunks), 256):
        batch = chunks[i:i + 256]
        parts.append(emb.encode([f"{c.get('title', '')}\n{c['text']}" for c in batch]).astype(np.float16))
        say(f"[rag] {min(i + 256, len(chunks))}/{len(chunks)} chunks embedded", flush=True)
    if parts:
        vectors = np.concatenate(parts)
    os.makedirs(index_dir, exist_ok=True)
    np.save(os.path.join(index_dir, "vectors.npy"), vectors)
    with open(os.path.join(index_dir, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    meta = {"model": emb.name, "count": len(chunks), "dim": int(vectors.shape[1]) if len(chunks) else 0,
            "seconds": round(time.monotonic() - t0, 1)}
    with open(os.path.join(index_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    say(f"[rag] index written: {meta}", flush=True)
    return meta


class Index:
    """The index in memory: vectors, chunks, the embedder for the queries."""

    def __init__(self, vectors, chunks, embedder, meta):
        self.vectors = vectors.astype(np.float32)
        self.chunks = chunks
        self.embedder = embedder
        self.meta = meta

    @classmethod
    def load(cls, index_dir, model_dir):
        vectors = np.load(os.path.join(index_dir, "vectors.npy"))
        chunks = read_chunks(os.path.join(index_dir, "chunks.jsonl"))
        with open(os.path.join(index_dir, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        return cls(vectors, chunks, Embedder(model_dir), meta)

    def search(self, query, k=6, sources=None, min_score=0.0, pool=60):
        """[(score, chunk)] of the `k` chunks that best answer `query`, the
        best first: the `pool` nearest by vector and the `pool` that name
        the most notions of the question, re-ranked by the notions they name
        (keyword_score, weighted 0.3) plus the lead of their source
        (SOURCE_BOOST, APP_BOOST); `sources` limits to those source names."""
        if not self.chunks:
            return []
        q = self.embedder.encode([query])[0]
        scores = self.vectors @ q
        if sources:
            allowed = np.array([c.get("source") in set(sources) for c in self.chunks])
            scores = np.where(allowed, scores, -1.0)
        terms = keywords(query)
        # the candidates: the nearest by vector, AND every chunk that names
        # a notion of the question (a French question sits far, by vector,
        # from an English Doxygen block that holds the answer)
        cand = set(int(i) for i in np.argsort(-scores)[:max(int(k), int(pool))])
        if terms:
            kw = np.array([keyword_score(c, terms) for c in self.chunks])
            cand.update(int(i) for i in np.argsort(-kw)[:pool] if kw[i] > 0)
        else:
            kw = np.zeros(len(self.chunks))
        # the documents of reference define (the glossary and guides, the
        # official Energistics documentation, the geology wikis); an API line
        # only names -- a small lead for them (SOURCE_BOOST). ETP, the
        # protocol, gets none: its many chunks would push the glossary's
        # definition out of a question like "what is ETP?".
        boost = dict(SOURCE_BOOST)
        if about_the_app(query):
            # a question about the application is not a geology question:
            # the wikis lose their lead, the application's documents gain one
            boost["geologie"] = 0.0
            for s in APP_SOURCES:
                boost[s] = boost.get(s, 0.0) + APP_BOOST
        ranked = sorted(((float(scores[i]) + 0.3 * float(kw[i])
                          + boost.get(self.chunks[i].get("source"), 0.0), i)
                         for i in cand if scores[i] >= min_score), reverse=True)
        return [(round(s, 4), self.chunks[i]) for s, i in ranked[:max(1, int(k))]]


def about_the_app(query):
    """Whether the question names the application (APP_TERMS)."""
    folded = " " + _fold(query) + " "
    return any((" " + t) in folded for t in APP_TERMS)


def extend_index(base_dir, chunks_path, index_dir, model_dir, say=print):
    """A new index = the index of `base_dir` + the chunks of `chunks_path`,
    embedding only the new chunks (the base vectors are reused as they
    are: same embedding model, same vectors). Adding a folder of documents
    then costs only its own embedding, and the base chunks stay exactly the
    same, so the two indexes compare fairly."""
    base_vectors = np.load(os.path.join(base_dir, "vectors.npy"))
    base_chunks = read_chunks(os.path.join(base_dir, "chunks.jsonl"))
    with open(os.path.join(base_dir, "meta.json"), encoding="utf-8") as f:
        base_meta = json.load(f)
    emb = Embedder(model_dir)
    if base_meta.get("model") and base_meta["model"] != emb.name:
        raise SystemExit(f"[rag] the base index was embedded with {base_meta['model']}, not {emb.name}")
    new = read_chunks(chunks_path)
    t0 = time.monotonic()
    parts = []
    for i in range(0, len(new), 256):
        batch = new[i:i + 256]
        parts.append(emb.encode([f"{c.get('title', '')}\n{c['text']}" for c in batch]).astype(np.float16))
        say(f"[rag] {min(i + 256, len(new))}/{len(new)} new chunks embedded", flush=True)
    vectors = np.concatenate([base_vectors.astype(np.float16)] + parts) if parts else base_vectors
    chunks = base_chunks + new
    for n, c in enumerate(chunks, 1):
        c["id"] = n
    os.makedirs(index_dir, exist_ok=True)
    np.save(os.path.join(index_dir, "vectors.npy"), vectors)
    with open(os.path.join(index_dir, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    meta = {"model": emb.name, "count": len(chunks), "dim": int(vectors.shape[1]),
            "seconds": round(time.monotonic() - t0, 1), "base": os.path.basename(base_dir.rstrip("/\\")),
            "added": len(new)}
    with open(os.path.join(index_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    say(f"[rag] index written: {meta}", flush=True)
    return meta


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Build the RAG index from a chunks.jsonl.")
    ap.add_argument("--chunks", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--model", required=True, help="the sentence-transformers model folder")
    ap.add_argument("--base", help="an existing index to extend: only the chunks of --chunks are embedded")
    a = ap.parse_args(argv)
    if a.base:
        extend_index(a.base, a.chunks, a.index, a.model)
    else:
        build_index(a.chunks, a.index, a.model)


if __name__ == "__main__":
    main()
