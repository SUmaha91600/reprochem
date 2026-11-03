"""Three guardrails, each testable on its own.

1. Abstention: a reranking score that is too low means NOT_FOUND.
2. Cost: a job that is too large is refused before it starts.
3. Injection: retrieved text is data, never an instruction.
"""
from __future__ import annotations

import re

from .schema import NOT_FOUND, Field_

# Patterns from the 6 Oct lab (slide "prompt injection in one example")
INJECTION_PATTERNS = [
    r"ignore\s+(the\s+)?(previous|above|prior)\s+instructions",
    r"ignorez?\s+les\s+instructions",
    r"system\s*:",
    r"tu\s+es\s+maintenant",
    r"you\s+are\s+now",
    r"disregard\s+the\s+(system|rules)",
    r"print\s+your\s+(system\s+)?prompt",
]

# Basis functions per heavy atom; the order of magnitude is enough to refuse a job.
BASIS_SIZE = {
    "STO-3G": 5, "6-31G*": 15, "6-31+G*": 19, "6-311++G**": 27,
    "DEF2-SVP": 14, "DEF2-TZVP": 31, "DEF2-TZVPP": 43,
    "CC-PVDZ": 14, "CC-PVTZ": 30, "AUG-CC-PVDZ": 23,
}


def scrub(text: str) -> tuple[str, list[str]]:
    """Neutralises injection attempts and reports which ones were seen."""
    hits = []
    out = text
    for pat in INJECTION_PATTERNS:
        for m in re.finditer(pat, out, flags=re.I):
            hits.append(m.group(0))
        out = re.sub(pat, "[instruction neutralisée]", out, flags=re.I)
    return out, hits


def abstain(field: Field_, threshold: float) -> Field_:
    """Below the threshold, admitting ignorance beats guessing."""
    if field.citation is None or field.citation.score < threshold:
        return Field_(value=NOT_FOUND, citation=None)
    return field


def estimate_basis_functions(n_heavy_atoms: int, basis: str) -> int:
    return n_heavy_atoms * BASIS_SIZE.get(basis.upper(), 20)


def cost_gate(n_heavy_atoms: int, basis: str, limit: int) -> tuple[bool, str]:
    n = estimate_basis_functions(n_heavy_atoms, basis)
    if n > limit:
        return False, (f"job refused: ~{n} basis functions estimated, "
                       f"limit {limit}. Use a smaller basis or molecule.")
    return True, f"~{n} basis functions estimated"
