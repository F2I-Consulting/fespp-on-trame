"""Retrieval only, no generation: does the hybrid search put a chunk that
answers the question among what /v1/ask reads? For each question of the
bench (the built-in set of fespp_ia.bench, plus the question files),
Index.search as /v1/ask calls it, asked for the top `--k` of its ranking
(the candidates are the same whatever k <= the search's pool); a chunk
is GOOD when its title and text hold at least half the expected notions
(the judge of fespp_ia.bench). Per bench: hit@1/3/4/6 (k=4 is /v1/ask's
default, k=6 the bench's), MRR, good_in_pool (a good chunk among the
ranked candidates: the ceiling a reranker can reach), good_in_corpus
(a good chunk anywhere in the index: the ceiling of the first stage),
the search seconds.

    docker run --rm -v "${root}:/repo:ro" -v "${root}/ia/models:/models:ro" -v "${out}:/out" `
        -w /repo/ia --entrypoint python3 fespp_ia:cpu -m fespp_ia.bench_retrieval `
        --index /models/index --model /models/embed/bilingual-embedding-small --json /out/retrieval.json
"""
import argparse
import json
import statistics
import time

from fespp_ia.bench import QUESTIONS, bench_name, count_hits, fold, load_questions, notions, question_files
from fespp_ia.rag import Index

GOOD = 0.5
KS = (1, 3, 4, 6)


def chunk_text(chunk):
    return fold(chunk.get("title", "") + "\n" + chunk.get("text", ""))


def share(folded_chunk, expected):
    """The share of the expected notions (from notions()) the chunk names, 0..1."""
    return count_hits(folded_chunk, expected) / len(expected) if expected else 0.0


def first_good(shares, good=GOOD):
    """The 1-based rank of the first chunk graded GOOD, None when none."""
    return next((r for r, s in enumerate(shares, 1) if s >= good), None)


def summary(rows, good=GOOD):
    """The figures of one bench: hit@k for each k of KS, good_in_pool,
    good_in_corpus, the MRR and the median search seconds."""
    ranks = [r["rank"] for r in rows]
    return {"n": len(rows), "good": good,
            **{f"hit@{k}": sum(1 for r in ranks if r and r <= k) for k in KS},
            "good_in_pool": sum(1 for r in ranks if r),
            "good_in_corpus": sum(1 for r in rows if r["good_in_corpus"]),
            "mrr": round(statistics.mean(1.0 / r if r else 0.0 for r in ranks), 3) if rows else None,
            "median_seconds": round(statistics.median(r["seconds"] for r in rows), 3) if rows else None}


def run(idx, benches, k=60, good=GOOD, say=print):
    """{bench: {"summary", "rows"}} for {bench: [(question, words)]} against the loaded index."""
    folded = [chunk_text(c) for c in idx.chunks]
    out = {}
    for name, items in benches.items():
        rows = []
        for q, words in items:
            expected = notions(words)
            t0 = time.perf_counter()
            ranked = idx.search(q, k=k)
            seconds = time.perf_counter() - t0
            shares = [share(chunk_text(c), expected) for _s, c in ranked]
            corpus = [share(f, expected) for f in folded]
            rows.append({"q": q, "rank": first_good(shares, good),
                         "best_share_pool": round(max(shares), 2) if shares else 0.0,
                         "best_share_corpus": round(max(corpus), 2) if corpus else 0.0,
                         "good_in_corpus": sum(1 for s in corpus if s >= good),
                         "top": [f"{c.get('source')}:{c.get('title', '')[:60]}" for _s, c in ranked[:6]],
                         "top_shares": [round(s, 2) for s in shares[:6]], "seconds": round(seconds, 3)})
        out[name] = {"summary": summary(rows, good), "rows": rows}
        say(f"[retrieval] {name} {json.dumps(out[name]['summary'])}", flush=True)
        say("   rank best_pool best_corpus n_good  question")
        for r in rows:
            say(f"   {str(r['rank']):>4} {r['best_share_pool']:>9} {r['best_share_corpus']:>11} {r['good_in_corpus']:>6}  {r['q'][:70]}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Retrieval-only bench of the RAG index, no generation.")
    ap.add_argument("--index", required=True, help="the index folder (vectors.npy, chunks.jsonl, meta.json)")
    ap.add_argument("--model", required=True, help="the embedding model folder")
    ap.add_argument("--questions", action="append", default=[],
                    help="a question file, repeatable; default: the bench-questions-*.json of ia/")
    ap.add_argument("--k", type=int, default=60, help="how deep the ranking is read (default 60, the search's pool)")
    ap.add_argument("--json", help="write the summaries and rows there")
    a = ap.parse_args(argv)
    idx = Index.load(a.index, a.model)
    print(f"[retrieval] index {a.index} {idx.meta}", flush=True)
    benches = {"builtin": QUESTIONS}
    for path in question_files(a.questions):
        benches[bench_name(path)] = load_questions(path)
    out = {"index": a.index, "meta": idx.meta, "k": a.k, "good": GOOD, "benches": run(idx, benches, a.k)}
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
