"""Pseudonymisation before a document leaves the machine.

    from app.anonymize import anonymize
    text, report = anonymize(markdown)      # report: what was removed, and the local mapping

Used by scripts/teacher_label.py before any call to an external teacher
(config.yaml, teacher.anonymize). The student runs locally and never needs it.

What is replaced, and by what:
  - e-mail addresses            -> [EMAIL_n]
  - phone and fax numbers       -> [PHONE_n]
  - ORCID identifiers           -> [ORCID_n]
  - web addresses               -> [URL_n]
  - the author and affiliation block between the title and the abstract
                                -> [AUTHORS_AND_AFFILIATIONS]
  - "Dr / Prof / Mr / Ms Name" anywhere (acknowledgements)  -> [PERSON_n]

The chemistry is never touched: scripts/security_eval.py checks that every
gold value is still in the text and that retrieval recall is unchanged.
The mapping (pseudonym -> original) stays on the machine and is never sent.
"""
from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
ORCID = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")
URL = re.compile(r"https?://[^\s)\]>]+")
# Only labelled numbers: a bare "+2.000 8.85 3.23" is a coordinate table, not a phone.
PHONE = re.compile(r"(?i)\b(?:tel|phone|fax|mobile)\.?\s*:?\s*\+?[\d ()./-]{7,}\d")
TITLED = re.compile(r"\b(?:Dr|Prof|Professor|Mr|Mrs|Ms)\.?\s+(?:[A-Z]\.\s*)*[A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+)?")
HEADING = re.compile(r"^#{1,6}\s*(.*)$")
FIRST_SECTION = re.compile(r"(?i)\b(abstract|introduction|summary|keywords|résumé)\b")


def _author_block(lines: list[str]) -> tuple[int, int] | None:
    """Line range between the title (first heading) and the first Abstract /
    Introduction heading, within the first 80 lines. None if not found."""
    title = next((i for i, l in enumerate(lines[:80]) if HEADING.match(l)), None)
    if title is None:
        return None
    for j in range(title + 1, min(len(lines), 80)):
        m = HEADING.match(lines[j])
        if m and FIRST_SECTION.search(re.sub(r"[*_#\d.]", " ", m.group(1))):
            return (title + 1, j) if j > title + 1 else None
    return None


def anonymize(markdown: str) -> tuple[str, dict]:
    mapping: dict[str, str] = {}
    counts = {"email": 0, "phone": 0, "orcid": 0, "url": 0, "person": 0, "author_block_lines": 0}

    def sub(pattern, kind, text):
        def repl(m):
            orig = m.group(0)
            key = next((k for k, v in mapping.items() if v == orig), None)
            if key is None:
                counts[kind] += 1
                key = f"[{kind.upper()}_{counts[kind]}]"
                mapping[key] = orig
            return key
        return pattern.sub(repl, text)

    lines = markdown.splitlines()
    block = _author_block(lines)
    if block:
        a, b = block
        removed = [l for l in lines[a:b] if l.strip()]
        counts["author_block_lines"] = len(removed)
        mapping["[AUTHORS_AND_AFFILIATIONS]"] = "\n".join(lines[a:b])
        lines = lines[:a] + ["[AUTHORS_AND_AFFILIATIONS]", ""] + lines[b:]
    text = "\n".join(lines)
    for pattern, kind in ((EMAIL, "email"), (ORCID, "orcid"), (URL, "url"),
                          (PHONE, "phone"), (TITLED, "person")):
        text = sub(pattern, kind, text)
    return text, {"counts": counts, "mapping": mapping, "author_block_found": bool(block)}
