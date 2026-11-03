"""Second validation pass: only the "Corriger" rows still missing a value.

    uv run python scripts/corrections_sheet.py      # -> data/gold_corrections.xlsx

Each row shows the numbered candidates side by side. "Choice" column:
1, 2 or 3 (that candidate's value and sentence), NOT_FOUND, or Autre (then
fill in "Value" and, if possible, "Sentence"). gold_from_review.py applies
this file on top of the main sheet.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gold_from_review import cell, parse_others  # noqa: E402

# Rows validated OK whose value deserves a second look, with the reason.
RECHECK = {
    ("2602.15700", "software"): "\"54\" is the footnote marker <sup>54</sup>, not a version. "
                                "The text: calculations run with Gellan, except SA-CASSCF (OpenMolcas) "
                                "and SF-TDDFT (ORCA).",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default="data/gold_review_edited.xlsx")
    ap.add_argument("--out", default="data/gold_corrections.xlsx")
    args = ap.parse_args()
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    src = load_workbook(ROOT / args.review, data_only=True)["Validation"]
    todo = []
    for r in src.iter_rows(min_row=2, values_only=True):
        pid, _t, f, val, q, dec, oth, cval, _cq, _n = (list(r) + [None] * 10)[:10]
        if not pid:
            continue
        why = None
        if cell(dec).lower().startswith("corr") and not cell(cval):
            why = "marked Corriger, no value"
        elif (str(pid), f) in RECHECK:
            why = RECHECK[(str(pid), f)]
        if why:
            todo.append((str(pid), f, [(val, q)] + parse_others(oth), why))

    wb = Workbook()
    ws = wb.active
    ws.title = "Corrections"
    head = ["paper_id", "field", "why", "Choice", "Value (if Autre)", "Sentence (if Autre)",
            "1 · value", "1 · sentence", "2 · value", "2 · sentence", "3 · value", "3 · sentence"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="44475A")
    dv = DataValidation(type="list", formula1='"1,2,3,NOT_FOUND,Autre"', allow_blank=True)
    ws.add_data_validation(dv)
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for pid, f, cands, why in todo:
        row = [pid, f, why, "", "", ""]
        for k in range(3):
            v, s = cands[k] if k < len(cands) else ("", "")
            row += [v or "", s or ""]
        ws.append(row)
        dv.add(ws.cell(row=ws.max_row, column=4))
        ws.cell(row=ws.max_row, column=4).fill = yellow
    for i, w in enumerate([11, 12, 22, 10, 16, 30, 14, 55, 14, 55, 14, 55], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "E2"
    wb.save(ROOT / args.out)
    print(f"{args.out}: {len(todo)} rows to decide")
    return 0


if __name__ == "__main__":
    sys.exit(main())
