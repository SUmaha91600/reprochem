"""The teacher labels the documents: the raw material for distillation.

    uv run python scripts/teacher_label.py --dry               # estimated tokens, no paid call
    uv run python scripts/teacher_label.py --limit 20          # 20 papers from the public corpus
    uv run python scripts/teacher_label.py --internal          # internal documents (authorisation required)

Two outputs, in data/teacher/:

  doc_cards.jsonl   one card per document, with the teacher reading the whole
                    document. This is the reference for student agreement.
  passages.jsonl    one answer per (document, field), with the teacher seeing
                    EXACTLY the messages the student will see in production:
                    same retrieved passages, same prompt. This is the raw
                    training set that make_sft.py filters.

Every call is cached (data/teacher/cache/) on a hash of the model and the
messages: a rerun pays nothing again, and an interrupted run resumes where it
stopped.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import pipeline as P  # noqa: E402
from app.retrieval import Retriever  # noqa: E402


def cached_chat(messages: list[dict], c: dict, cache: Path) -> tuple[str, dict, bool]:
    key = hashlib.sha256((c["name"] + json.dumps(messages, ensure_ascii=False)).encode()).hexdigest()
    f = cache / f"{key}.json"
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        return d["text"], d.get("usage", {}), True
    text, usage = P.chat(messages, c)
    f.write_text(json.dumps({"model": c["name"], "text": text, "usage": usage},
                            ensure_ascii=False), encoding="utf-8")
    return text, usage, False


def load_keys(path: Path, key) -> set:
    if not path.exists():
        return set()
    return {key(json.loads(l)) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--internal", action="store_true", help="data/internal/manifest.csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", nargs="*", default=None, help="only these paper_id values")
    ap.add_argument("--cards-only", action="store_true", help="document cards only")
    ap.add_argument("--dry", action="store_true", help="estimate tokens without calling the teacher")
    args = ap.parse_args()

    T = P.TCFG
    if args.internal and not T.get("allow_internal"):
        print("Refused: teacher.allow_internal is false in config.yaml.\n"
              "Internal documents go to the API only with written authorisation, "
              "and after reading the data retention policy.",
              file=sys.stderr)
        return 2
    manifest = Path(args.manifest or ("data/internal/manifest.csv" if args.internal
                                      else "data/corpus_manifest.csv"))
    docs = [r for r in csv.DictReader(manifest.open(encoding="utf-8"))]
    if args.ids:
        docs = [d for d in docs if d["paper_id"] in set(args.ids)]
    if args.limit:
        docs = docs[:args.limit]

    dcfg = P.CFG["distill"]
    out = Path(dcfg["labels_dir"])
    cache = out / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    cards_f, pass_f = out / "doc_cards.jsonl", out / "passages.jsonl"
    done_cards = load_keys(cards_f, lambda d: (d["paper_id"], d["model"]))
    done_pass = load_keys(pass_f, lambda d: (d["paper_id"], d["field"], d["model"]))
    mode = dcfg.get("retrieval_mode", "hybrid")

    tok_in = tok_out = n_calls = n_cached = 0
    for i, d in enumerate(docs, 1):
        pid = d["paper_id"]
        md_path = Path(d.get("markdown") or f"data/papers/md/{pid}.md")
        if not md_path.exists():
            print(f"[{i}/{len(docs)}] {pid}: no markdown, skipped", file=sys.stderr)
            continue
        md = md_path.read_text(encoding="utf-8", errors="replace")
        if T.get("anonymize", True):
            # Nothing personal leaves the machine: authors, affiliations, e-mails,
            # phones, URLs and titled names are pseudonymised first (app/anonymize.py).
            from app.anonymize import anonymize
            md, _ = anonymize(md)

        if args.dry:
            chunks = P.parse(md, pid)
            r = Retriever(chunks, {**P.CFG["retrieval"], "embedder_backend": "none"})
            est = len(md) // 4
            if not args.cards_only:
                for field in P.QUERIES:
                    msgs, _ = P.extract_messages(field, r.search(P.QUERIES[field], mode="bm25"),
                                                 for_teacher=True)
                    est += sum(len(m["content"]) for m in msgs) // 4
            tok_in += est
            print(f"[{i}/{len(docs)}] {pid}: ~{est} input tokens")
            continue

        try:
            if (pid, T["name"]) not in done_cards:
                if len(md) // 4 > T.get("max_context_tokens", 150_000):
                    raise ValueError("document longer than max_context_tokens")
                text, u, hit = cached_chat(P.fullpaper_messages(md), T, cache)
                card = P.card_from_fullpaper(P._json_block(text), pid)
                with cards_f.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"paper_id": pid, "source": d.get("source", ""),
                                         "model": T["name"], "card": card.model_dump(),
                                         "usage": u}, ensure_ascii=False) + "\n")
                n_calls += 1; n_cached += hit
                tok_in += u.get("prompt_tokens") or 0; tok_out += u.get("completion_tokens") or 0

            if not args.cards_only:
                retriever = Retriever(P.parse(md, pid), P.CFG["retrieval"])
                for field in P.QUERIES:
                    if (pid, field, T["name"]) in done_pass:
                        continue
                    hits = P.retrieve(retriever, field, mode=mode)
                    student_msgs, _ = P.extract_messages(field, hits)
                    teacher_msgs, _ = P.extract_messages(field, hits, for_teacher=True)
                    text, u, hit = cached_chat(teacher_msgs, T, cache)
                    with pass_f.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({
                            "paper_id": pid, "field": field, "model": T["name"],
                            "mode": getattr(retriever, "last_mode", mode),
                            "messages": student_msgs, "teacher_text": text,
                            "teacher": P._json_block(text), "hit_ids": [c.id for c, _ in hits],
                            "usage": u}, ensure_ascii=False) + "\n")
                    n_calls += 1; n_cached += hit
                    tok_in += u.get("prompt_tokens") or 0; tok_out += u.get("completion_tokens") or 0
        except Exception as err:                                   # noqa: BLE001
            print(f"[{i}/{len(docs)}] {pid}: FAILED, {type(err).__name__}: {str(err)[:200]}",
                  file=sys.stderr)
            continue
        print(f"[{i}/{len(docs)}] {pid}: ok", file=sys.stderr)

    if args.dry:
        print(f"\n{len(docs)} documents, ~{tok_in:,} input tokens in total "
              f"(+ ~{len(docs) * 8 * 150:,} output). Multiply by the price "
              f"of {T['name']} to get the cost.".replace(",", " "))
    else:
        print(f"\n{n_calls} calls ({n_cached} from cache) · {tok_in:,} input tokens · "
              f"{tok_out:,} output".replace(",", " "))
        print(f"{cards_f} · {pass_f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
