"""Builds the annotation sheet from the corpus manifest.

    uv run python scripts/make_sheet.py --sample 20

Writes `data/annotation_sheet.csv`, to open in a spreadsheet. One row per
paper, two columns per field: the value, and the copied sentence that
contains it. Nothing to invent, everything to copy.

The sheet is **additive**: rerunning with a larger `--sample` adds the new
rows without touching the ones already filled in.
"""
from __future__ import annotations

import argparse
import csv
import random
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

COLUMNS = (["paper_id", "title", "licence", "annotateur", "task",
            "smiles", "n_heavy_atoms"]
           + [c for f in FIELDS for c in (f, f"{f}_quote")]
           + ["notes"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/corpus_manifest.csv")
    ap.add_argument("--sheet", default="data/annotation_sheet.csv")
    ap.add_argument("--sample", type=int, default=20,
                    help="number of papers to annotate")
    ap.add_argument("--seed", type=int, default=0,
                    help="reproducible draw: the same seed gives the same sample")
    args = ap.parse_args()

    manifest = ROOT / args.manifest
    if not manifest.exists():
        print(f"manifest not found: {manifest}\n"
              "Run this first: uv run python scripts/fetch_corpus.py", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
    sheet = ROOT / args.sheet
    existing: dict[str, dict] = {}
    if sheet.exists():
        existing = {r["paper_id"]: r for r in csv.DictReader(sheet.open(encoding="utf-8"))}

    pool = [r for r in rows if r["paper_id"] not in existing]
    random.Random(args.seed).shuffle(pool)
    need = max(0, args.sample - len(existing))

    out = list(existing.values())
    for r in pool[:need]:
        blank = {c: "" for c in COLUMNS}
        blank.update(paper_id=r["paper_id"], title=r["title"][:120],
                     licence=r.get("licence", ""))
        out.append(blank)

    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    print(f"{rel(sheet)}: {len(out)} rows "
          f"({len(existing)} already there, {len(out) - len(existing)} added)")
    print("Fill it in a spreadsheet, then: uv run python scripts/build_testset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
