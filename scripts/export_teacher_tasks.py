"""Prepares, for each document, exactly what the student will see:
for each field, the BM25 passages and the full messages.

    uv run python scripts/export_teacher_tasks.py            # whole corpus
    -> data/teacher/tasks/<paper_id>.json

A task file works for the teacher whatever its interface: the API
(scripts/teacher_label.py) or a Claude session that reads these files and
writes data/teacher/labels/<paper_id>.json. Either way, for a given field the
teacher only sees that field's passages.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import pipeline as P  # noqa: E402
from app.retrieval import Retriever  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/corpus_manifest.csv")
    ap.add_argument("--out", default="data/teacher/tasks")
    args = ap.parse_args()
    mode = P.CFG["distill"].get("retrieval_mode", "bm25")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in csv.DictReader(open(args.manifest, encoding="utf-8")):
        pid = d["paper_id"]
        md_path = Path(d.get("markdown") or f"data/papers/md/{pid}.md")
        if not md_path.exists():
            continue
        md = md_path.read_text(encoding="utf-8", errors="replace")
        retriever = Retriever(P.parse(md, pid), P.CFG["retrieval"])
        chunks, fields = {}, {}
        for field in P.QUERIES:
            hits = P.retrieve(retriever, field, mode=mode)
            msgs, _ = P.extract_messages(field, hits)
            for c, _ in hits:
                chunks[c.id] = c.text
            fields[field] = {"chunk_ids": [c.id for c, _ in hits], "messages": msgs}
        (out / f"{pid}.json").write_text(json.dumps(
            {"paper_id": pid, "mode": getattr(retriever, "last_mode", mode),
             "chunks": chunks, "fields": fields}, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
    print(f"{n} task files in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
