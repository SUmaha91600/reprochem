"""Converts a folder of internal documents to markdown, with a manifest.

    uv run python scripts/ingest_docs.py                      # data/internal/raw -> data/internal/md
    uv run python scripts/ingest_docs.py --src ~/Documents/rapports

Formats: PDF, DOCX, XLSX, CSV, IPYNB, MD, TXT. The manifest has the same
columns as the public corpus one: make_sheet.py, build_testset.py and
teacher_label.py read it unchanged.

Everything under data/internal/ is ignored by git: internal documents,
markdown, annotation sheet and test set do not leave the machine that way.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ingest import SUPPORTED, to_markdown  # noqa: E402

COLUMNS = ["paper_id", "source", "title", "published", "licence", "licence_url",
           "categories", "pdf", "markdown", "sha256"]


def slug(p: Path) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", p.stem).strip("_")[:60]
    return f"int-{s}-{hashlib.sha256(str(p).encode()).hexdigest()[:6]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/internal/raw")
    ap.add_argument("--out", default="data/internal/md")
    ap.add_argument("--manifest", default="data/internal/manifest.csv")
    args = ap.parse_args()

    src, out, man = (ROOT / args.src).expanduser(), ROOT / args.out, ROOT / args.manifest
    if not src.exists():
        print(f"folder not found: {src}\nPut the documents there, then rerun.", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    known = {}
    if man.exists():
        known = {r["paper_id"]: r for r in csv.DictReader(man.open(encoding="utf-8"))}

    rows, failed, skipped = dict(known), [], 0
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        if f.name.startswith((".", "~$")):
            continue
        if f.suffix.lower() not in SUPPORTED:
            skipped += 1
            continue
        pid = slug(f.relative_to(src))
        digest = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        if pid in known and known[pid]["sha256"] == digest:
            continue                                    # already converted, unchanged
        try:
            md = to_markdown(f)
        except Exception as err:                        # noqa: BLE001
            failed.append(f"{f.name}: {type(err).__name__}: {err}")
            continue
        target = out / f"{pid}.md"
        target.write_text(md, encoding="utf-8")
        rows[pid] = {"paper_id": pid, "source": "internal", "title": f.name,
                     "published": "", "licence": "internal", "licence_url": "",
                     "categories": f.suffix.lower().lstrip("."),
                     "pdf": str(f), "markdown": str(target.relative_to(ROOT)),
                     "sha256": digest}
        print(f"  {f.name} -> {target.name} ({len(md)} characters)")

    man.parent.mkdir(parents=True, exist_ok=True)
    with man.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows.values())
    print(f"\n{len(rows)} documents in {man.relative_to(ROOT)}"
          + (f" · {skipped} files in an unsupported format" if skipped else ""))
    for x in failed:
        print(f"  failed · {x}", file=sys.stderr)
    print("Read three markdown files at random before going further: a badly "
          "converted table shows up straight away.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
