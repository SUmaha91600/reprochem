"""Validation sheet -> gold set (eval/testset.jsonl).

    uv run python scripts/gold_from_review.py   # validated sheet + data/gold_corrections.xlsx

Only the human decision counts: a row with no decision holds back its paper
(it stays out of the gold set until every field is settled).
Accepted decisions (case-insensitive):
  OK or 1        the proposal is right;
  2 or 3         the right choice is the 2nd or 3rd candidate, i.e. the 1st or
                 2nd block of the "other candidates" column (also "Candidat 2");
  Corriger       fill in the corrected value. The corrected sentence is
                 optional: if empty, the script takes the candidate sentence
                 that contains the value, then the paper's sentence (and flags it);
  NOT_FOUND      the paper does not give this field;
  Hors périmètre the paper leaves the gold set and is counted separately.

The runnability test uses a toy molecule (water), as set in config.yaml
(compiler.dry_run_molecule): it checks that an extracted protocol compiles
and converges; the paper's own molecule plays no part here.
"""
from __future__ import annotations

import argparse
import collections
import re
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
NOT_FOUND = "NOT_FOUND"
FIELDS = ("functional", "basis", "dispersion", "solvation", "charge", "multiplicity", "software")


def norm(s: str) -> str:
    return str(s).strip().upper().replace(" ", "").replace("-", "")


def cell(x) -> str:
    """Excel turns "2" into 2.0: bring everything back to clean text."""
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return str(x or "").strip()


def decision(dec: str):
    """'nf', a candidate number (1 = the proposal), or 'corriger'."""
    d = dec.lower().replace("candidat", "").replace("n°", "").strip()
    if d in ("ok", "1"):
        return 1
    if d in ("2", "3", "4"):
        return int(d)
    if d.replace(" ", "").replace("_", "") in ("notfound", "nf", "absent"):
        return "nf"
    return "corriger"


def parse_others(text) -> list[tuple[str, str]]:
    """The "other candidates" column: "[value] sentence" blocks separated
    by a blank line, in order (2nd candidate, 3rd candidate)."""
    out = []
    for block in str(text or "").split("\n\n"):
        m = re.match(r"\s*\[(.+?)\]\s*(.*)", block, re.S)
        if m:
            out.append((m.group(1).strip(), " ".join(m.group(2).split())))
    return out


def find_quote(value: str, cands, md: str) -> str:
    """The sentence that contains the value: first among the candidates, then in
    the paper, preferring sentences about geometry optimisation."""
    from preannotate import OPT, sentences

    core = r"[\s\-]*".join(re.escape(ch) for ch in re.sub(r"[\s\-]", "", value))
    pat = re.compile(r"(?<![A-Za-z0-9])" + core + r"(?![A-Za-z0-9])", re.I)
    for _, s in cands:
        if s and pat.search(s):
            return s
    hits = [s for s in sentences(md) if pat.search(s)]
    hits.sort(key=lambda s: 0 if OPT.search(s) else 1)
    return hits[0] if hits else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default=None,
                    help="default: data/gold_review_edited.xlsx if it exists, else data/gold_review.xlsx")
    ap.add_argument("--corrections", default="data/gold_corrections.xlsx",
                    help="second pass (scripts/corrections_sheet.py), applied on top if the file exists")
    ap.add_argument("--out", default="eval/testset.jsonl")
    args = ap.parse_args()
    from openpyxl import load_workbook

    if args.review is None:
        args.review = ("data/gold_review_edited.xlsx"
                       if (ROOT / "data/gold_review_edited.xlsx").exists() else "data/gold_review.xlsx")
    print(f"sheet: {args.review}")
    ws = load_workbook(ROOT / args.review, data_only=True)["Validation"]
    rows = collections.defaultdict(dict)
    titles = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        pid, title, field, val, quote, dec, _others, cval, cquote, note = (list(r) + [None] * 10)[:10]
        if not pid:
            continue
        titles[pid] = title
        rows[str(pid)][field] = (cell(dec), val, quote, cval, cquote, _others)

    corr = ROOT / args.corrections
    if corr.exists():
        n = 0
        for r in load_workbook(corr, data_only=True)["Corrections"].iter_rows(min_row=2, values_only=True):
            pid, field, _why, choice, cval, cquote = (list(r) + [None] * 6)[:6]
            choice = cell(choice)
            if not pid or not choice or field not in rows.get(str(pid), {}):
                continue
            _d, val, quote, _cv, _cq, others = rows[str(pid)][field]
            if choice.lower().startswith("autre"):
                rows[str(pid)][field] = ("Corriger", val, quote, cval, cquote, others)
            else:
                rows[str(pid)][field] = (choice, val, quote, None, None, others)
            n += 1
        print(f"corrections: {n} rows taken from {args.corrections}")

    kept, pending, out_of_scope, warns = [], [], [], []
    for pid, fields in rows.items():
        decs = {f: v[0] for f, v in fields.items()}
        if any(d.lower().startswith("hors") for d in decs.values()):
            out_of_scope.append(pid)
            continue
        if any(not d for d in decs.values()) or set(fields) != set(FIELDS):
            pending.append(pid)
            continue
        gold, quotes = {}, {}
        md = None
        for f in FIELDS:
            dec, val, quote, cval, cquote, others = fields[f]
            cands = [(val, quote)] + parse_others(others)
            k = decision(dec)
            if k == "nf":
                v, q = NOT_FOUND, ""
            elif isinstance(k, int):
                if k > len(cands):
                    warns.append(f"{pid} · {f}: candidate {k} requested, only {len(cands)} available")
                    pending.append(pid)
                    break
                v, q = cands[k - 1]
            else:                                            # Corriger
                v, q = cval, cquote
                if v in (None, ""):
                    warns.append(f"{pid} · {f}: decision \"{dec}\" with no corrected value, paper set aside")
                    pending.append(pid)
                    break
                if not str(q or "").strip():
                    if md is None:
                        md = (ROOT / f"data/papers/md/{pid}.md").read_text(encoding="utf-8", errors="replace")
                    q = find_quote(str(v), cands, md)
                    warns.append(f"{pid} · {f}: sentence found automatically for \"{v}\""
                                 + ("" if q else ": NONE, fill in by hand"))
            v = str(v).strip() if v not in (None, "") else NOT_FOUND
            q = str(q or "").strip()
            if v != NOT_FOUND and norm(v) not in norm(q):
                warns.append(f"{pid} · {f}: \"{v}\" not in the selected sentence")
            gold[f], quotes[f] = v, q
        else:
            kept.append({"paper_id": pid, "markdown_path": f"data/papers/md/{pid}.md",
                         "smiles": "O", "n_heavy_atoms": 1, "task": "geometry_optimisation",
                         "annotateur": "humain, sur pré-annotation par règles",
                         "tags": ["corpus", "gold"] + (["incomplet"] if NOT_FOUND in gold.values() else []),
                         "fields": gold, "quotes": quotes})

    out = ROOT / args.out
    out.write_text("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in kept), encoding="utf-8")
    n = len(kept) * len(FIELDS)
    absent = sum(1 for k in kept for f in FIELDS if k["fields"][f] == NOT_FOUND)
    print(f"{args.out}: {len(kept)} papers, {n} fields, {absent} of them NOT_FOUND"
          + (f" ({100 * absent / n:.0f} %)" if n else ""))
    if out_of_scope:
        print(f"out of scope ({len(out_of_scope)}): " + ", ".join(out_of_scope))
    if pending:
        print(f"not yet decided ({len(pending)}): " + ", ".join(pending))
    for w in warns:
        print("  warning · " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
