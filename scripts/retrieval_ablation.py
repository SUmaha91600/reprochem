"""Retrieval ablation on the gold set: the measurements behind two design choices.

    uv run python scripts/retrieval_ablation.py            # BM25 only, about 10 s, no model
    uv run python scripts/retrieval_ablation.py --dense    # + bge-m3 embeddings and hybrid (Ollama)

Question 1 · chunk size. Sections split at 50 to 400 words, unsplit sections,
and fixed windows. Bigger chunks raise the chance that the right sentence is
in the 3 passages, and also the length of the prompt the 1.7B student must
read. Both are measured.

Question 2 · retriever. BM25 against dense embeddings (bge-m3, the model named
in config.yaml) and their RRF fusion, on the production chunking.

Metric: recall@k = share of the fields present in the paper (48 in the gold
set) whose gold value appears, after normalisation, in the top-k passages.
No language model is called: retrieval is scored on its own, the way the
7 October lecture asks ("did we find the right page?").

Output: docs/retrieval_ablation.json (read by scripts/figures.py) and
docs/retrieval_ablation.md.
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from eval import FIELDS, ci, normalise  # noqa: E402

KMAX = 10
TOKENIZER = ROOT / "models/qwen3-1.7b-4bit/tokenizer.json"   # the student's own tokenizer, if present


def token_counter():
    """Counts tokens with the student's tokenizer when it is on disk (the Mac);
    otherwise returns None and the report gives words only."""
    try:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(TOKENIZER))
        return lambda s: len(tok.encode(s).ids)
    except Exception:
        return None
SECTION_SIZES = [50, 100, 150, 200, 300, 400, None]   # None = sections never split
FIXED_SIZES = [100, 200, 300]


def label(chunking: str, size) -> str:
    if chunking == "fixed":
        return f"fixed {size} w"
    return "sections, unsplit" if size is None else f"sections ≤ {size} w"


def run_config(P, R, testset, chunking, size, modes, base_cfg, count=None):
    rc = copy.deepcopy(base_cfg)
    rc["chunking"] = chunking
    if chunking == "fixed":
        rc["fixed_words"] = size
    else:
        rc["max_words"] = size
    rc["top_k"] = KMAX
    saved = P.CFG["retrieval"]
    P.CFG["retrieval"] = rc                      # parse() reads the global config
    try:
        out = {m: {"hits": [], "per_field": {f: [] for f in FIELDS}, "ctx_words": [], "ctx_tokens": []}
               for m in modes}
        n_chunks = []
        for t in testset:
            md = (ROOT / t["markdown_path"]).read_text(encoding="utf-8", errors="replace")
            chunks = P.parse(md, t["paper_id"])
            n_chunks.append(len(chunks))
            r = R.Retriever(chunks, rc)
            for f in FIELDS:
                want = t["fields"][f]
                for m in modes:
                    hits = r.search(P.QUERIES[f], mode=m) if m != "hybrid" else \
                        R.rrf([r.bm25.search(P.QUERIES[f], 20), r.dense.search(P.QUERIES[f], 20)],
                              k=rc["rrf_k"], top=KMAX)
                    texts = [c.text for c, _ in hits[:KMAX]]
                    out[m]["ctx_words"].append(sum(len(x.split()) for x in texts[:3]))
                    if count:
                        msgs, _ = P.extract_messages(f, hits[:3])
                        out[m]["ctx_tokens"].append(count(msgs[0]["content"]) + count(msgs[1]["content"]))
                    if want == "NOT_FOUND":
                        continue
                    w = normalise(want)
                    row = [w in normalise(" ".join(texts[:k])) for k in range(1, KMAX + 1)]
                    out[m]["hits"].append(row)
                    out[m]["per_field"][f].append(row[2])
    finally:
        P.CFG["retrieval"] = saved
    res = {}
    for m in modes:
        H = out[m]["hits"]
        res[m] = {
            "recall_at_k": [round(sum(h[k] for h in H) / len(H), 3) for k in range(KMAX)],
            "recall_at_3_ci": ci([1.0 if h[2] else 0.0 for h in H]),
            "hits_at_3": [bool(h[2]) for h in H],
            "n_fields": len(H),
            "per_field_recall_at_3": {f: [sum(v), len(v)] for f, v in out[m]["per_field"].items() if v},
            "median_context_words_top3": statistics.median(out[m]["ctx_words"]),
            "max_context_words_top3": max(out[m]["ctx_words"]),
            "median_prompt_tokens": statistics.median(out[m]["ctx_tokens"]) if out[m]["ctx_tokens"] else None,
            "max_prompt_tokens": max(out[m]["ctx_tokens"]) if out[m]["ctx_tokens"] else None,
        }
    return res, statistics.median(n_chunks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dense", action="store_true",
                    help="also run bge-m3 embeddings and hybrid fusion (needs Ollama + bge-m3)")
    ap.add_argument("--testset", default="eval/testset.jsonl")
    args = ap.parse_args()
    from app import pipeline as P
    from app import retrieval as R

    testset = [json.loads(l) for l in (ROOT / args.testset).open() if l.strip()]
    base_cfg = P.CFG["retrieval"]
    count = token_counter()
    print("prompt length in tokens: " + ("student tokenizer" if count else "tokenizer not found, words only"))
    rows = []
    t0 = time.time()
    for chunking, sizes in (("sections", SECTION_SIZES), ("fixed", FIXED_SIZES)):
        for s in sizes:
            res, nch = run_config(P, R, testset, chunking, s, ["bm25"], base_cfg, count)
            rows.append({"retriever": "bm25", "chunking": chunking, "size": s,
                         "label": label(chunking, s), "median_chunks_per_paper": nch, **res["bm25"]})
            print(f"bm25   {label(chunking, s):<20} recall@1 {res['bm25']['recall_at_k'][0]:.2f} "
                  f"@3 {res['bm25']['recall_at_k'][2]:.2f} @10 {res['bm25']['recall_at_k'][9]:.2f} "
                  f"· context {res['bm25']['median_context_words_top3']:.0f} words")
    if args.dense:
        prod = (base_cfg["chunking"], base_cfg.get("max_words"))
        for chunking, s in [prod]:
            res, nch = run_config(P, R, testset, chunking, s, ["dense", "hybrid"], base_cfg, count)
            for m in ("dense", "hybrid"):
                name = "bge-m3" if m == "dense" else "hybrid (BM25 + bge-m3, RRF)"
                rows.append({"retriever": m, "model": base_cfg.get("embedder"), "chunking": chunking,
                             "size": s, "label": label(chunking, s),
                             "median_chunks_per_paper": nch, **res[m]})
                print(f"{name:<28} {label(chunking, s)} recall@1 {res[m]['recall_at_k'][0]:.2f} "
                      f"@3 {res[m]['recall_at_k'][2]:.2f} @10 {res[m]['recall_at_k'][9]:.2f}")

    prod_label = label(base_cfg["chunking"], base_cfg.get("max_words"))
    out = {"testset": args.testset, "n_papers": len(testset), "kmax": KMAX,
           "production": {"retriever": "bm25", "label": prod_label, "top_k": base_cfg["top_k"]},
           "seconds": round(time.time() - t0, 1), "rows": rows}
    (ROOT / "docs/retrieval_ablation.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))

    L = ["# Retrieval ablation", "",
         f"*Generated by `scripts/retrieval_ablation.py`. Gold set: {len(testset)} papers, "
         f"{rows[0]['n_fields']} fields present in the paper. No language model involved.*", "",
         "recall@k: share of present fields whose gold value is inside the top-k passages. "
         "In brackets: 95% bootstrap interval over fields. Context: words in the 3 passages "
         "sent to the student (median / max); prompt: system + user message in student "
         "tokens (median / max), when the tokenizer is available.", "",
         "| Retriever | Chunking | recall@1 | recall@3 [95% CI] | recall@5 | recall@10 | context words | prompt tokens | chunks per paper |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ra = r["recall_at_k"]
        name = {"bm25": "BM25", "dense": f"dense ({r.get('model')})", "hybrid": "hybrid (RRF)"}[r["retriever"]]
        star = " **(production)**" if r["retriever"] == "bm25" and r["label"] == prod_label else ""
        c3 = r["recall_at_3_ci"]
        tok = (f"{r['median_prompt_tokens']:.0f} / {r['max_prompt_tokens']}"
               if r.get("median_prompt_tokens") else "—")
        L.append(f"| {name} | {r['label']}{star} | {ra[0]:.2f} | {ra[2]:.2f} [{c3[1]:.2f} – {c3[2]:.2f}] | "
                 f"{ra[4]:.2f} | {ra[9]:.2f} | {r['median_context_words_top3']:.0f} / "
                 f"{r['max_context_words_top3']} | {tok} | {r['median_chunks_per_paper']:.0f} |")
    L += ["", "Per field, recall@3 of the production setting:", "",
          "| Field | recall@3 |", "|---|---|"]
    prod_row = next(r for r in rows if r["retriever"] == "bm25" and r["label"] == prod_label)
    for f, (a, n) in prod_row["per_field_recall_at_3"].items():
        L.append(f"| {f} | {a}/{n} |")
    if not args.dense:
        L += ["", "Dense and hybrid rows: rerun with `--dense` (needs Ollama with `bge-m3`)."]
    (ROOT / "docs/retrieval_ablation.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\nwritten: docs/retrieval_ablation.json, docs/retrieval_ablation.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
