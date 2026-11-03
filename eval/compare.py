"""All reports side by side, on one page.

    python eval/compare.py                              # report.json against report_baseline.json
    python eval/compare.py eval/report_*.json           # the full benchmark

Each cell: mean [95% interval]. With two reports, the last column says which
one wins. Two overlapping intervals mean "no proven difference", a valid
conclusion that goes into the report as it stands.
"""
from __future__ import annotations

import glob
import json
import sys

METRICS = [
    ("field_accuracy", "correct field (gold set)", True),
    ("hallucination", "invented value if absent", False),
    ("abstention", "NOT_FOUND if absent", True),
    ("quote_in_paper", "quote in the document", True),
    ("citation_verified", "value in the quote", True),
    ("teacher_agreement", "agreement with the teacher", True),
    ("runnable", "script that converges", True),
]


def fmt(v) -> str:
    return "—" if v is None else f"{v[0]:.2f} [{v[1]:.2f}–{v[2]:.2f}]"


def verdict(a, b, higher_better: bool, na: str, nb: str) -> str:
    if a is None or b is None:
        return ""
    if a[1] > b[2]:
        return na if higher_better else nb
    if b[1] > a[2]:
        return nb if higher_better else na
    return "no proven difference"


def main() -> None:
    paths = []
    for a in sys.argv[1:]:
        paths += sorted(glob.glob(a)) or [a]
    if not paths:
        paths = ["eval/report.json", "eval/report_baseline.json"]
    reps = [json.load(open(p)) for p in paths]
    names = [r.get("label") or r.get("mode") or p for r, p in zip(reps, paths)]
    for n, r in zip(names, reps):
        extra = f" · {r['n_failed']} failed" if r.get("n_failed") else ""
        print(f"{n:<22} {r.get('model')} · {r.get('mode')} · {r['n_papers']} documents{extra}")
    print()
    w = max(len(l) for _, l, _ in METRICS)
    cw = 20
    print(f"{'':{w}}  " + "".join(f"{n[:cw - 1]:<{cw}}" for n in names)
          + ("best" if len(reps) == 2 else ""))
    for key, lbl, hb in METRICS:
        row = f"{lbl:{w}}  " + "".join(f"{fmt(r.get(key)):<{cw}}" for r in reps)
        if len(reps) == 2:
            row += verdict(reps[0].get(key), reps[1].get(key), hb, names[0], names[1])
        print(row)
    print(f"{'seconds per document':{w}}  "
          + "".join(f"{str(r.get('median_seconds')):<{cw}}" for r in reps))
    for n, r in zip(names, reps):
        inv = r.get("invented_values") or []
        if inv:
            print(f"\ninvented values · {n}:")
            for x in inv:
                print(f"  {x['paper_id']:<16} {x['field']:<13} {x['value']}")


if __name__ == "__main__":
    main()
