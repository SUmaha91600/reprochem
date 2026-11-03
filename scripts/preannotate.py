"""Rule-based pre-annotation of the gold set, independent of any LLM.

    uv run python scripts/preannotate.py --ids 2202.02370 2110.03421 ...
    -> data/gold_review.xlsx, to validate by hand

Why rules and not a model: the project's teacher is Claude. If Claude also
pre-annotated the gold set, the gold set would resemble the teacher and score
it too high. A regex extractor has no such bias: it proposes candidates and
the sentences that contain them, and a human decides. The human decision is
the only thing that enters the gold set.

For each field, candidate sentences are ranked: first those about geometry
optimisation (the project's annotation rule), then the rest, in document
order.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FUNCTIONALS = (r"ωB97X-D3\(BJ\)|ωB97X-D3|ωB97X-D|ωB97XD|ωB97M-V|ωB97M-D3\(BJ\)|ωB97X-V|ωB97X|"
               r"wB97X-D3|wB97X-D|wB97XD|wB97M-V|wB97X|CAM-B3LYP|B3LYP|X3LYP|PBE0|PBE1PBE|revPBE|"
               r"PBE|M06-2X|M06-L|M06|M11|BP86|BLYP|TPSSh|TPSS|r2SCAN-3c|r2SCAN|SCAN|B97-3c|B97-D3|"
               r"B97-D|BHLYP|BHandHLYP|B2PLYP|PW6B95|PW91|APFD|LDA|HSE06")
BASIS = (r"aug-cc-pV[DTQ5]Z|cc-pV[DTQ5]Z(?:-DK)?|def2-?[A-Z]{2,6}(?:/[A-Z])?|"
         r"6-31\+?\+?G\*{0,2}(?:\([0-9a-z,+]+\))?|6-311\+?\+?G\*{0,2}(?:\([0-9a-z,+]+\))?|"
         r"STO-[36]G|LANL2DZ|POB-TZVP|SVP|TZVP")
FIELDS = {
    "functional": rf"(?<![A-Za-z0-9])({FUNCTIONALS})(?![A-Za-z0-9])",
    "basis": rf"(?<![A-Za-z0-9])({BASIS})(?![A-Za-z0-9])",
    "dispersion": r"(?<![A-Za-z0-9])(GD3BJ|BJD3|D3\(BJ\)|D3BJ|D3|D4|Grimme(?:'s)? dispersion)(?![A-Za-z0-9])",
    "solvation": r"(?<![A-Za-z0-9])((?:C-?PCM|IEF-?PCM|SMD|COSMO(?:-RS)?|PCM)(?:\s*\(?\s*(?:water|acetonitrile|toluene|DMSO|methanol|ethanol|benzene|chloroform|dichloromethane|THF)\)?)?)(?![A-Za-z0-9])",
    "charge": r"((?:total |net )?charge (?:of |is |=\s*)?[-+−]?\d|\b(?:anion|anionic|cation|cationic|dianion|neutral)\b)",
    "multiplicity": r"(\b(?:spin )?multiplicity (?:of |is |=\s*)?\d|\b(?:singlet|doublet|triplet|quartet|quintet)\b)",
    "software": r"(?<![A-Za-z0-9])((?:Gaussian|ORCA|PySCF|Psi4|Q-Chem|Turbomole|TURBOMOLE|NWChem|CP2K|VASP|GAMESS|Molpro|MOLPRO|ADF|xtb|Quantum ESPRESSO|FHI-aims|CFOUR)(?:\s*(?:\d{2}|\d+(?:\.\d+){0,2})(?:\s*rev(?:ision)?\.?\s*[A-Z]\.?\d+)?)?)(?![A-Za-z])",
}
OPT = re.compile(r"optimi[sz]|geometr|relax", re.I)


def sentences(md: str) -> list[str]:
    flat = " ".join(re.sub(r"<[^>]+>", " ", md).split())
    return [s for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z(\[])", flat) if 15 < len(s) < 700]


def candidates(md: str, field: str, n: int = 3) -> list[tuple[str, str]]:
    pat = re.compile(FIELDS[field], re.I if field in ("charge", "multiplicity", "solvation") else 0)
    hits = []
    for i, s in enumerate(sentences(md)):
        m = pat.search(s)
        if m:
            hits.append((0 if OPT.search(s) else 1, i, m.group(1).strip(), s))
    hits.sort()
    seen, out = set(), []
    for _, _, v, s in hits:
        if s not in seen:
            seen.add(s)
            out.append((v, s))
        if len(out) == n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--out", default="data/gold_review.xlsx")
    args = ap.parse_args()

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    titles = {r["paper_id"]: r["title"] for r in csv.DictReader((ROOT / "data/corpus_manifest.csv").open(encoding="utf-8"))}
    wb = Workbook()
    guide = wb.active
    guide.title = "Instructions"
    lines = [
        "Validate the gold set, field by field",
        "",
        "One row = one field of one paper. The rule-based script proposes a value and the sentence that contains it.",
        "\"Decision\" column: OK if the proposal is right; Corriger if the value or the sentence is wrong",
        "(then fill in \"Corrected value\" and \"Corrected sentence\", copied word for word from the paper);",
        "NOT_FOUND if the paper does not give this field for the geometry optimisation; Hors périmètre if",
        "the authors ran no geometry optimisation of their own (set it on all 7 rows of the paper).",
        "",
        "Rules (eval/gold/README.md): annotate the authors' geometry optimisation, the last one if there are",
        "several; copy the value as written; a charge or multiplicity that is obvious but not written = NOT_FOUND.",
        "",
        "The other candidate sentences (column G) help you correct without reopening the paper.",
        "Each paper's markdown is in data/papers/md/<paper_id>.md.",
    ]
    for i, l in enumerate(lines, 1):
        guide.cell(row=i, column=1, value=l).font = Font(bold=(i == 1), size=13 if i == 1 else 11)
    guide.column_dimensions["A"].width = 120

    ws = wb.create_sheet("Validation")
    head = ["paper_id", "title", "field", "proposed value", "proposed sentence", "Decision",
            "other candidates", "Corrected value", "Corrected sentence", "Note"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="44475A")
    dv = DataValidation(type="list", formula1='"OK,Corriger,NOT_FOUND,Hors périmètre"', allow_blank=True)
    ws.add_data_validation(dv)
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for pid in args.ids:
        md = (ROOT / f"data/papers/md/{pid}.md").read_text(encoding="utf-8", errors="replace")
        for field in FIELDS:
            c = candidates(md, field)
            val, quote = (c[0] if c else ("NOT_FOUND", ""))
            others = "\n\n".join(f"[{v}] {s}" for v, s in c[1:])
            ws.append([pid, titles.get(pid, ""), field, val, quote, "", others, "", "", ""])
            r = ws.max_row
            dv.add(ws.cell(row=r, column=6))
            ws.cell(row=r, column=6).fill = yellow
    widths = [12, 30, 13, 18, 70, 14, 70, 18, 50, 25]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "D2"
    out = ROOT / args.out
    wb.save(out)
    print(f"{out.relative_to(ROOT)}: {len(args.ids)} papers, {len(args.ids) * len(FIELDS)} rows to validate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
