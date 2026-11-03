"""Teacher answers -> filtered LoRA training set.

    uv run python scripts/make_sft.py
    uv run python scripts/make_sft.py --keep-disagreements   # skip the consistency filter

Output: data/sft/train.jsonl and data/sft/valid.jsonl, in mlx-lm chat format
({"messages": [system, user, assistant]}). The system and user messages are
the ones the student will get in production; the answer is the teacher's.

Three rules, in this order:

1. No test-set document goes into training. The train / valid split is done
   per DOCUMENT: seven examples from the same paper on both sides would make
   validation look better than it is.
2. An answer that cannot be checked is dropped: invalid JSON, a quote missing
   from the given passages, or a value missing from its own quote.
3. The teacher must agree with itself: its answer on the passages is compared
   with its card on the whole document. A disagreement is dropped, except a
   NOT_FOUND when the value is not in the passages (the student has to learn
   to abstain when retrieval missed).

This is the rejection filtering from the 6 October lecture (R1: rejection
sampling, then SFT), applied to extraction. The count for each rejection
reason is printed, and goes into the report.

Two adjustments follow, also printed:

- Augmentation (--augment k): every example where the teacher found a value
  is copied k times, with other passages from the same document as
  distractors, in shuffled order. The cited passage is always there, so the
  teacher's answer stays correct; only the context changes.
- Balancing (--nf-share): NOT_FOUND examples are sampled at random so they
  make up this share of the set. Without it, 88 % NOT_FOUND would teach the
  student to always abstain.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from eval.eval import normalise  # noqa: E402

NOT_FOUND = "NOT_FOUND"


def flat(t: str) -> str:
    t = re.sub(r"\[[^\]]*#[^\]]*\]", " ", t)
    t = re.sub(r"[*_`#>]", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()


# ── SAFEGUARD S19 · poisoned training labels rejected (LLM04) ── tested by: B4
#    A teacher answer is kept only if its quote is in the passages and its value in its quote.
def label_check(value: str, quote: str, sources: str) -> str | None:
    """Rejection filter for one teacher answer (also replayed by
    scripts/security_eval.py, attack B4: a poisoned label). None = kept."""
    if value == NOT_FOUND:
        return None
    if len(quote) < 10 or flat(quote) not in flat(sources):
        return "quote not in the passages"
    if normalise(value) not in normalise(quote):
        return "value not in its own quote"
    return None


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testsets", nargs="*",
                    default=["eval/testset.jsonl", "data/internal/testset.jsonl"],
                    help="documents excluded from training")
    ap.add_argument("--keep-disagreements", action="store_true")
    ap.add_argument("--exclude", default="data/gold_ids.txt", help="IDs reserved for the gold set")
    ap.add_argument("--augment", type=int, default=3)
    ap.add_argument("--nf-share", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    d = cfg["distill"]
    labels, out = ROOT / d["labels_dir"], ROOT / d["out_dir"]
    passages = read_jsonl(labels / "passages.jsonl")
    if not passages:
        print("No labels: run scripts/teacher_label.py first", file=sys.stderr)
        return 1
    cards = {(c["paper_id"], c["model"]): c["card"] for c in read_jsonl(labels / "doc_cards.jsonl")}

    # ── SAFEGUARD S19 · gold papers never trained on (LLM04) ── tested by: gold set integrity
    #    Every gold-set paper is excluded from the training data, so the score measures generalisation.
    test_ids = set()
    for t in args.testsets:
        test_ids |= {r["paper_id"] for r in read_jsonl(ROOT / t)}
    if (ROOT / args.exclude).exists():
        test_ids |= {l.strip() for l in (ROOT / args.exclude).read_text().splitlines() if l.strip()}

    kept, why = [], collections.Counter()
    for p in passages:
        if p["paper_id"] in test_ids:
            why["test-set document"] += 1
            continue
        t = p.get("teacher") or {}
        if "value" not in t:
            why["invalid JSON"] += 1
            continue
        value = str(t.get("value", "")).strip() or NOT_FOUND
        quote = str(t.get("quote", "")).strip()
        sources = p["messages"][1]["content"]
        reason = label_check(value, quote, sources)
        if reason:
            why[reason] += 1
            continue
        card = cards.get((p["paper_id"], p["model"]))
        if card and not args.keep_disagreements:
            ref = (card.get(p["field"]) or {}).get("value", NOT_FOUND)
            if value != NOT_FOUND and ref != NOT_FOUND and normalise(value) != normalise(ref):
                why["disagrees with the document card"] += 1
                continue
            if value == NOT_FOUND and ref != NOT_FOUND and normalise(ref) in normalise(sources):
                why["NOT_FOUND although the value is in the passages"] += 1
                continue
            if value != NOT_FOUND and ref == NOT_FOUND:
                why["value found in passages, missing from the card"] += 1
                continue
        answer = {"value": value,
                  "chunk_id": str(t.get("chunk_id", "")) if value != NOT_FOUND else "",
                  "quote": quote if value != NOT_FOUND else ""}
        kept.append((p["paper_id"], {"messages": p["messages"] + [
            {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}]},
            value == NOT_FOUND, p["field"]))

    # Augment positive examples (the cited passage stays in the context).
    rng = random.Random(args.seed)
    n_aug = 0
    if args.augment > 0:
        sys.path.insert(0, str(ROOT))
        from app import pipeline as P
        chunks_by_doc = {}
        for pid, ex, isnf, field in list(kept):
            if isnf:
                continue
            ans = json.loads(ex["messages"][2]["content"])
            if pid not in chunks_by_doc:
                md = (ROOT / f"data/papers/md/{pid}.md").read_text(encoding="utf-8", errors="replace")
                chunks_by_doc[pid] = P.parse(md, pid)
            chunks = chunks_by_doc[pid]
            cited = [c for c in chunks if c.id == ans["chunk_id"]]
            others = [c for c in chunks if c.id != ans["chunk_id"]]
            if not cited or len(others) < 2:
                continue
            for _ in range(args.augment):
                hits = cited + rng.sample(others, 2)
                rng.shuffle(hits)
                msgs, _ = P.extract_messages(field, [(c, 0.0) for c in hits])
                kept.append((pid, {"messages": msgs + [ex["messages"][2]]}, False, field))
                n_aug += 1

    # Balancing: the NOT_FOUND share is set by sampling.
    pos = [k for k in kept if not k[2]]
    nfs = [k for k in kept if k[2]]
    n_nf_raw = len(nfs)
    if 0 < args.nf_share < 1 and nfs:
        target = int(round(len(pos) * args.nf_share / (1 - args.nf_share)))
        if target < len(nfs):
            nfs = rng.sample(nfs, target)
    kept = pos + nfs

    docs = sorted({pid for pid, *_ in kept})
    random.Random(args.seed).shuffle(docs)
    n_valid = max(1, round(len(docs) * d.get("valid_fraction", 0.1))) if len(docs) > 1 else 0
    valid_docs = set(docs[:n_valid])
    out.mkdir(parents=True, exist_ok=True)
    tr = [ex for pid, ex, *_ in kept if pid not in valid_docs]
    va = [ex for pid, ex, *_ in kept if pid in valid_docs]
    for name, rows in (("train", tr), ("valid", va)):
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    nf = sum(1 for *_, isnf, _f in kept if isnf)
    print(f"augmentation: +{n_aug} positive examples · NOT_FOUND kept: {len(nfs)} of {n_nf_raw}")
    n_filtered = sum(why.values())
    print(f"{len(passages)} teacher answers · {len(passages) - n_filtered} pass the filters · "
          f"{n_filtered} dropped")
    for k, v in why.most_common():
        print(f"  dropped · {k}: {v}")
    print(f"\ntrain: {len(tr)} examples ({len(docs) - n_valid} documents) · "
          f"valid: {len(va)} examples ({n_valid} documents)")
    print(f"NOT_FOUND share: {nf / max(1, len(kept)):.0%}")
    by_field = collections.Counter(f for *_, f in kept)
    print("per field: " + " · ".join(f"{f} {n}" for f, n in sorted(by_field.items())))
    if len(tr) < 500:
        print(f"\nWarning: only {len(tr)} training examples. The course recommends 500+ "
              "for a LoRA; label more documents before training.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
