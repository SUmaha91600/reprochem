"""The test set drives the project. Run it after every change.

    python eval/eval.py                      # full system (retrieval + reranker)
    python eval/eval.py --mode bm25          # one ablation
    python eval/eval.py --baseline           # strong baseline: a strong model reads the whole paper
    python eval/eval.py --baseline --limit 5 # the week-1 test, on 5 papers
    python eval/eval.py --dry                # no model call: checks the plumbing
    python eval/eval.py --cards data/teacher/doc_cards.jsonl --label teacher
                                             # scores the teacher cards already paid for, no call
    python eval/eval.py --label student-lora --out eval/report_student-lora.json
                                             # the student served by mlx_lm.server (see RUN.md)
    python eval/compare.py eval/report_*.json  # every report, side by side

With --teacher-cards (defaults to the ones in config.yaml, if the file exists),
a sixth measure is added: teacher agreement, the share of fields where the
model gives the same value as the teacher. Read it next to accuracy: a student
that faithfully copies a wrong teacher is wrong too.

Five metrics, from easiest to hardest:
  1. field_accuracy      the extracted field equals the annotated value
  2. citation_verified   the value appears verbatim in the returned quote
  3. quote_in_paper      the quote really exists in the paper
  4. abstention          NOT_FOUND where the paper says nothing (hallucination = the opposite)
  5. runnable            the compiled script converges on the toy molecule
Every rate comes with a bootstrap confidence interval: on 20 papers, a number
without an error bar proves nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schema import NOT_FOUND  # noqa: E402

FIELDS = ("functional", "basis", "dispersion", "solvation", "charge",
          "multiplicity", "software")


def ci(values: list[float], samples: int = 2000):
    """Mean and 95 % bootstrap interval. None when there is nothing to measure."""
    if not values:
        return None
    mean = sum(values) / len(values)
    rng = random.Random(0)
    means = sorted(
        sum(rng.choices(values, k=len(values))) / len(values) for _ in range(samples))
    return round(mean, 3), round(means[int(0.025 * samples)], 3), round(means[int(0.975 * samples)], 3)


# Two spellings of the same setting must not count as an error: the
# annotation copies the paper as written, the model may normalise it.
EQUIV = [
    ("(D,P)", "**"), ("(D)", "*"),
    ("GD3BJ", "D3BJ"), ("BJD3", "D3BJ"), ("D3(BJ)", "D3BJ"), ("GD3", "D3"),
    ("Ω", "W"), ("ω", "W"),
]


def normalise(v: str) -> str:
    s = str(v).strip().upper().replace(" ", "").replace("-", "")
    for a, b in EQUIV:
        s = s.replace(a.upper(), b)
    return s


def score_card(pred: dict, gold: dict, markdown: str | None) -> dict:
    from app.pipeline import quote_in_paper

    rows = {}
    for f in FIELDS:
        p = pred.get(f, {}) or {}
        want = gold["fields"][f]
        got = p.get("value", NOT_FOUND)
        unanswerable = want == NOT_FOUND
        quote = (p.get("citation") or {}).get("quote", "")
        found = got != NOT_FOUND
        rows[f] = {
            "value": got,
            "gold": want,
            "correct": normalise(got) == normalise(want),
            "abstained_ok": (not found) if unanswerable else None,
            "cited": (normalise(got) in normalise(quote)) if found else None,
            "quote_in_paper": (quote_in_paper(quote, markdown)
                               if found and markdown is not None else None),
            "hallucinated": found if unanswerable else None,
        }
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="rerank",
                    choices=["bm25", "dense", "hybrid", "rerank"])
    ap.add_argument("--baseline", action="store_true",
                    help="a strong model reads the whole paper (baseline section of config.yaml)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N papers")
    ap.add_argument("--out", default=None, help="report file")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--testset", default=None, help="gold set (default: config.yaml)")
    ap.add_argument("--cards", default=None,
                    help="score cards produced earlier (jsonl from teacher_label.py), no model call")
    ap.add_argument("--teacher-cards", default=None, help="teacher cards for the agreement metric")
    ap.add_argument("--label", default=None, help="row name in compare.py")
    args = ap.parse_args()

    import yaml
    root = os.path.join(os.path.dirname(__file__), "..")
    cfg = yaml.safe_load(open(os.path.join(root, "config.yaml")))
    tests = [json.loads(l) for l in open(args.testset or cfg["evaluation"]["testset"]) if l.strip()]
    tc_path = args.teacher_cards or cfg["evaluation"].get("teacher_cards")
    teacher = {}
    if tc_path and os.path.exists(tc_path):
        for l in open(tc_path, encoding="utf-8"):
            if l.strip():
                c = json.loads(l)
                teacher[c["paper_id"]] = c["card"]
    given = {}
    if args.cards:
        for l in open(args.cards, encoding="utf-8"):
            if l.strip():
                c = json.loads(l)
                given[c["paper_id"]] = c
    if args.limit:
        tests = tests[:args.limit]
    out_path = args.out or (
        cfg["evaluation"]["report"].replace(".json", "_baseline.json") if args.baseline else
        cfg["evaluation"]["report"].replace(".json", f"_{args.label}.json") if args.label else
        cfg["evaluation"]["report"])

    results, runnable, seconds, effective, failed, usage = [], [], [], set(), [], []
    model_name = None
    for n, t in enumerate(tests, 1):
        md = open(t["markdown_path"]).read()
        try:
            if args.dry:
                pred = {f: {"value": t["fields"][f], "citation": None} for f in FIELDS}
                out = {"card": pred, "validation": {"converged": None}, "seconds": 0.0}
            elif args.cards:
                if t["paper_id"] not in given:
                    raise KeyError("no card for this document in --cards")
                g = given[t["paper_id"]]
                out = {"card": g["card"], "seconds": 0.0, "model": g.get("model"),
                       "effective_mode": "fiches", "usage": g.get("usage")}
            elif args.baseline:
                from app.pipeline import answer_fullpaper
                out = answer_fullpaper(md, t["paper_id"], t["smiles"], t["n_heavy_atoms"])
            else:
                from app.pipeline import answer
                out = answer(md, t["paper_id"], t["smiles"], t["n_heavy_atoms"],
                             mode=args.mode)
        except Exception as err:                               # noqa: BLE001
            # A rejected paper (too long, quota, network) must not kill the run:
            # it is left out of the scores and the report says so.
            msg = f"{type(err).__name__}: {str(err)[:300]}"
            failed.append({"paper_id": t["paper_id"], "error": msg})
            print(f"[{n}/{len(tests)}] {t['paper_id']}: FAILED, {msg}", file=sys.stderr)
            continue
        print(f"[{n}/{len(tests)}] {t['paper_id']}: {out['seconds']} s", file=sys.stderr)
        model_name = out.get("model", model_name)
        effective.add(out.get("effective_mode", args.mode))
        rows = score_card(out["card"], t, None if args.dry else md)
        ref = teacher.get(t["paper_id"])
        for f in FIELDS:
            rows[f]["teacher_agree"] = (
                normalise(rows[f]["value"]) == normalise((ref.get(f) or {}).get("value", NOT_FOUND))
                if ref else None)
        results.append((t, rows))
        seconds.append(out["seconds"])
        if out.get("usage"):
            usage.append(out["usage"])
        conv = (out.get("validation") or {}).get("converged")
        if conv is not None:
            runnable.append(1.0 if conv else 0.0)

    def collect(key):
        return [1.0 if r[f][key] else 0.0
                for _, r in results for f in FIELDS if r[f][key] is not None]

    # The report states what actually ran, not what was requested.
    mode = ("baseline (article entier)" if args.baseline else
            "fiches existantes" if args.cards else args.mode)
    ran = ", ".join(sorted(effective))
    if ran and not (args.baseline or args.cards) and ran != mode:
        mode = f"{mode} (repli : {ran})"

    b = cfg["evaluation"]["bootstrap_samples"]
    invented = [{"paper_id": t["paper_id"], "field": f, "value": r[f]["value"]}
                for t, r in results for f in FIELDS if r[f]["hallucinated"]]
    fake_quotes = [{"paper_id": t["paper_id"], "field": f, "value": r[f]["value"]}
                   for t, r in results for f in FIELDS if r[f]["quote_in_paper"] is False]
    tokens_in = [u.get("prompt_tokens") or u.get("approx_input_tokens") for u in usage]
    report = {
        "label": args.label or ("baseline" if args.baseline else mode),
        "n_papers": len(results),
        "n_failed": len(failed),
        "mode": mode,
        "model": model_name or (cfg.get("baseline", {}).get("name") if args.baseline
                                else os.environ.get("REPROCHEM_MODEL", cfg["model"]["name"])),
        "field_accuracy": ci(collect("correct"), b),
        "citation_verified": ci(collect("cited"), b),
        "quote_in_paper": ci(collect("quote_in_paper"), b),
        "abstention": ci(collect("abstained_ok"), b),
        "hallucination": ci(collect("hallucinated"), b),
        "runnable": ci(runnable, b),
        "teacher_agreement": ci(collect("teacher_agree"), b),
        "n_absent_fields": len(collect("abstained_ok")),
        "median_seconds": statistics.median(seconds) if seconds else None,
        "median_input_tokens": statistics.median(tokens_in) if tokens_in and all(tokens_in) else None,
        "invented_values": invented,
        "quotes_not_in_paper": fake_quotes,
        "failed": failed,
        "config": cfg,
        "per_paper": [{"paper_id": t["paper_id"], "seconds": sec, "fields": r}
                      for (t, r), sec in zip(results, seconds)],
        "max_words": int(os.environ.get("REPROCHEM_MAX_WORDS") or cfg["retrieval"]["max_words"]),
    }
    json.dump(report, open(out_path, "w"), indent=2, ensure_ascii=False)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("config", "per_paper")}, indent=2, ensure_ascii=False))
    print(f"\nreport written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
