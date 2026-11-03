"""Turns the annotation sheet into the test set, checking it along the way.

    uv run python scripts/build_testset.py
    uv run python scripts/build_testset.py --strict   # fails on any warning

Three checks, because a wrong annotation costs more than a missing one:

1. The quote contains the annotated value. If not, one of the two is wrong.
2. A filled field with no quote is rejected, except NOT_FOUND, which needs none.
3. charge and multiplicity must be integers, multiplicity ≥ 1.

Incomplete rows are skipped with a message, so the test set can be built at
any time, even half-annotated.

A row whose notes column starts with "HORS PÉRIMÈTRE" (a benchmark of ten
functionals, geometries taken from another paper, and so on) leaves the test
set and is counted separately: that count is one of the project's results.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def rel(p: Path) -> str:
    """Readable path, even when the file is outside the repo (tests)."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)

FIELDS = ("functional", "basis", "dispersion", "solvation", "charge",
          "multiplicity", "software")
NOT_FOUND = "NOT_FOUND"


def norm(s: str) -> str:
    return s.strip().upper().replace(" ", "").replace("-", "")


def check(row: dict) -> tuple[list[str], list[str]]:
    """Returns (blocking errors, warnings)."""
    errs, warns = [], []
    pid = row.get("paper_id", "?")

    for f in FIELDS:
        value = (row.get(f) or "").strip()
        quote = (row.get(f"{f}_quote") or "").strip()
        if not value:
            errs.append(f"{pid} · {f}: empty (enter a value or {NOT_FOUND})")
            continue
        if value == NOT_FOUND:
            if quote:
                warns.append(f"{pid} · {f}: {NOT_FOUND} with a quote, "
                             "one of the two should go")
            continue
        if not quote:
            errs.append(f"{pid} · {f}: value without a quote")
        elif norm(value) not in norm(quote):
            warns.append(f"{pid} · {f}: \"{value}\" not in the copied quote")

    for f in ("charge", "multiplicity"):
        v = (row.get(f) or "").strip()
        if v and v != NOT_FOUND:
            try:
                n = int(v)
                if f == "multiplicity" and n < 1:
                    errs.append(f"{pid} · multiplicity: {n} < 1")
            except ValueError:
                errs.append(f"{pid} · {f}: \"{v}\" is not an integer")

    if not (row.get("smiles") or "").strip():
        errs.append(f"{pid} · smiles: empty")
    if not (row.get("n_heavy_atoms") or "").strip().isdigit():
        errs.append(f"{pid} · n_heavy_atoms: empty or not an integer")
    task = (row.get("task") or "").strip()
    if task not in ("single_point", "geometry_optimisation", "frequency", NOT_FOUND):
        errs.append(f"{pid} · task: \"{task}\" not in the allowed list")
    return errs, warns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="data/annotation_sheet.csv")
    ap.add_argument("--manifest", default="data/corpus_manifest.csv")
    ap.add_argument("--out", default="eval/testset.jsonl")
    ap.add_argument("--keep-synthetic", action="store_true",
                    help="keep the three synthetic papers at the top of the file")
    ap.add_argument("--strict", action="store_true",
                    help="exit with an error if any warning remains")
    args = ap.parse_args()

    sheet = ROOT / args.sheet
    if not sheet.exists():
        print(f"sheet not found: {sheet}\n"
              "Run this first: uv run python scripts/make_sheet.py", file=sys.stderr)
        return 1

    md_by_id = {}
    manifest = ROOT / args.manifest
    if manifest.exists():
        md_by_id = {r["paper_id"]: r.get("markdown", "")
                    for r in csv.DictReader(manifest.open(encoding="utf-8"))}

    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    kept, skipped, all_warns, out_of_scope = [], 0, [], []

    for row in rows:
        note = (row.get("notes") or "").strip().upper()
        if note.startswith(("HORS PÉRIMÈTRE", "HORS PERIMETRE")):
            out_of_scope.append(row.get("paper_id", "?"))
            continue
        if not any((row.get(f) or "").strip() for f in FIELDS):
            skipped += 1                      # row not touched yet
            continue
        errs, warns = check(row)
        all_warns += warns
        if errs:
            skipped += 1
            for e in errs:
                print(f"  skipped · {e}", file=sys.stderr)
            continue
        pid = row["paper_id"]
        kept.append({
            "paper_id": pid,
            "markdown_path": md_by_id.get(pid, f"data/papers/md/{pid}.md"),
            "smiles": row["smiles"].strip(),
            "n_heavy_atoms": int(row["n_heavy_atoms"]),
            "task": row["task"].strip(),
            "annotateur": (row.get("annotateur") or "").strip(),
            "tags": ["corpus"] + (["incomplet"] if any(
                (row.get(f) or "").strip() == NOT_FOUND for f in FIELDS) else []),
            "fields": {f: row[f].strip() for f in FIELDS},
            "quotes": {f: (row.get(f"{f}_quote") or "").strip() for f in FIELDS},
        })

    out = ROOT / args.out
    head = []
    if args.keep_synthetic and out.exists():
        head = [l for l in out.read_text(encoding="utf-8").splitlines()
                if '"synth' in l]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + [json.dumps(r, ensure_ascii=False)
                                     for r in kept]) + "\n", encoding="utf-8")

    for w in all_warns:
        print(f"  warning · {w}", file=sys.stderr)

    n_fields = len(kept) * len(FIELDS)
    n_absent = sum(1 for r in kept for f in FIELDS if r["fields"][f] == NOT_FOUND)
    print(f"\n{rel(out)}: {len(kept)} papers, {n_fields} fields, "
          f"{n_absent} of them absent from the paper "
          f"({100 * n_absent / n_fields:.0f} %)." if n_fields else "empty set")
    if skipped:
        print(f"{skipped} rows skipped (empty or incomplete).")
    if out_of_scope:
        print(f"{len(out_of_scope)} papers out of scope, to report: "
              + ", ".join(out_of_scope))
    if all_warns:
        print(f"{len(all_warns)} warnings to review.")
    return 1 if (args.strict and all_warns) else 0


if __name__ == "__main__":
    sys.exit(main())
