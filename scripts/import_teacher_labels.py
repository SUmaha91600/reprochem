"""Teacher labels (data/teacher/labels/*.json) -> passages.jsonl + doc_cards.jsonl.

    uv run python scripts/import_teacher_labels.py

The labels come from Claude, which read data/teacher/tasks/<id>.json: for each
field, exactly the passages the student will receive. This script puts each
label back next to the student messages, in the format make_sft.py reads, and
builds one card per document (all 7 fields) so the teacher can be scored on
the gold set with eval.py --cards.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOT_FOUND = "NOT_FOUND"


def main() -> int:
    tasks, labels = ROOT / "data/teacher/tasks", ROOT / "data/teacher/labels"
    pas, cards = [], []
    for lf in sorted(labels.glob("*.json")):
        lab = json.loads(lf.read_text(encoding="utf-8"))
        pid, model = lab["paper_id"], lab.get("teacher", "claude")
        task = json.loads((tasks / f"{pid}.json").read_text(encoding="utf-8"))
        card = {"paper_id": pid, "task": "geometry_optimisation"}
        for field, t in task["fields"].items():
            ans = lab["fields"].get(field) or {}
            value = str(ans.get("value") or NOT_FOUND).strip() or NOT_FOUND
            quote = str(ans.get("quote") or "").strip()
            cid = str(ans.get("chunk_id") or "").strip()
            pas.append({"paper_id": pid, "field": field, "model": model, "mode": task["mode"],
                        "messages": t["messages"], "teacher": {"value": value, "chunk_id": cid, "quote": quote},
                        "hit_ids": t["chunk_ids"]})
            card[field] = {"value": value,
                           "citation": ({"chunk_id": cid, "quote": quote, "score": 1.0}
                                        if value != NOT_FOUND and len(quote) >= 10 else None)}
        cards.append({"paper_id": pid, "source": "arxiv", "model": model, "card": card})
    (ROOT / "data/teacher/passages.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pas), encoding="utf-8")
    (ROOT / "data/teacher/doc_cards.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    pos = sum(1 for p in pas if p["teacher"]["value"] != NOT_FOUND)
    print(f"{len(cards)} documents · {len(pas)} teacher answers · {pos} values, {len(pas) - pos} NOT_FOUND")
    return 0


if __name__ == "__main__":
    sys.exit(main())
