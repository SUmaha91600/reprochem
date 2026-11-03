"""Every document becomes markdown, so the rest of the pipeline sees one format.

    PDF            pymupdf4llm (extra `convert`)
    DOCX           paragraphs and tables in document order (extra `ingest`)
    XLSX / CSV     one markdown table per sheet (extra `ingest` for xlsx)
    IPYNB          markdown cells, code and text outputs
    MD / TXT       as is

Word headings become markdown headings, which the section-based chunking in
retrieval relies on.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".ipynb", ".md", ".txt"}
MAX_ROWS = 400          # beyond this, a spreadsheet is truncated and the markdown says so


def _cell(v) -> str:
    return "" if v is None else str(v).replace("|", "\\|").replace("\n", " ").strip()


def _table(rows: list[list]) -> str:
    rows = [r for r in rows if any(_cell(c) for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    head, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(_cell(c) for c in head) + " |",
             "|" + "---|" * width]
    lines += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in body[:MAX_ROWS]]
    if len(body) > MAX_ROWS:
        lines.append(f"\n*({len(body) - MAX_ROWS} lignes de plus non reprises)*")
    return "\n".join(lines)


def _pdf(path: Path) -> str:
    import pymupdf4llm
    return pymupdf4llm.to_markdown(str(path))


def _docx(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    out = []
    for el in doc.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "") if p.style is not None else ""
            if style.startswith("Heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                out.append("#" * min(int(level), 3) + " " + text)
            elif style == "Title":
                out.append("# " + text)
            else:
                out.append(text)
        elif tag == "tbl":
            t = Table(el, doc)
            out.append(_table([[c.text for c in row.cells] for row in t.rows]))
    return "\n\n".join(x for x in out if x)


def _xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        table = _table([list(r) for r in ws.iter_rows(values_only=True)])
        if table:
            parts.append(f"## Feuille : {ws.title}\n\n{table}")
    return "\n\n".join(parts)


def _csv(path: Path) -> str:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return f"## {path.stem}\n\n" + _table(list(csv.reader(fh, dialect)))


def _ipynb(path: Path) -> str:
    nb = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for cell in nb.get("cells", []):
        src = "".join(cell.get("source", []))
        if not src.strip():
            continue
        if cell.get("cell_type") == "markdown":
            out.append(src)
        elif cell.get("cell_type") == "code":
            out.append(f"```\n{src}\n```")
            for o in cell.get("outputs", []):
                text = "".join(o.get("text", []) or o.get("data", {}).get("text/plain", []))
                if text.strip():
                    out.append("Sortie :\n```\n" + text[:2000] + "\n```")
    return "\n\n".join(out)


def to_markdown(path: str | Path) -> str:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"unsupported format: {ext}")
    if ext == ".pdf":
        return _pdf(path)
    if ext == ".docx":
        return _docx(path)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx(path)
    if ext == ".csv":
        return _csv(path)
    if ext == ".ipynb":
        return _ipynb(path)
    return path.read_text(encoding="utf-8", errors="replace")
