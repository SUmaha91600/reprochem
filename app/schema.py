"""The schema is the domain boundary.

Whoever maintains this file and the validator does not need to know what a
hybrid functional is. They need to know why `charge` is required and why
`solvent` is allowed to be NOT_FOUND.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

NOT_FOUND = "NOT_FOUND"

# Values known in v1. The compiler rejects anything else, which turns a
# hallucination into a visible error instead of a wrong calculation.
KNOWN_FUNCTIONALS = {
    "B3LYP", "PBE", "PBE0", "M06-2X", "wB97X-D", "TPSS", "CAM-B3LYP", "BP86",
}
KNOWN_BASIS = {
    "STO-3G", "6-31G*", "6-31+G*", "6-311++G**", "def2-SVP", "def2-TZVP",
    "def2-TZVPP", "cc-pVDZ", "cc-pVTZ", "aug-cc-pVDZ",
}


class Citation(BaseModel):
    """Where the value comes from. Without it, an extracted field is worthless."""

    chunk_id: str
    quote: str = Field(min_length=10, max_length=400)
    score: float = 0.0
    # Set at extraction: is the quote really in the passages, and the value in
    # the quote? False is shown to the user as an unverified citation (B3).
    verified: Optional[bool] = None


class Field_(BaseModel):
    """A value, or the admission that it is missing."""

    value: str
    citation: Optional[Citation] = None

    @property
    def found(self) -> bool:
        return self.value != NOT_FOUND


class MethodCard(BaseModel):
    """What gets extracted from a paper. Step B of the project."""

    paper_id: str
    task: Literal["single_point", "geometry_optimisation", "frequency", NOT_FOUND]
    functional: Field_
    basis: Field_
    dispersion: Field_
    solvation: Field_
    charge: Field_
    multiplicity: Field_
    software: Field_

    def missing(self) -> list[str]:
        return [n for n in ("functional", "basis", "dispersion", "solvation",
                            "charge", "multiplicity", "software")
                if not getattr(self, n).found]


# ── SAFEGUARD S10 · typed schema, whitelists and bounds (LLM05) ── tested by: C1
#    Only known functionals and basis sets compile; charge and multiplicity are bounded integers; anything else is refused.
class JobSpec(BaseModel):
    """What gets run. Step A of the project. Nothing optional here."""

    molecule_smiles: str
    task: Literal["single_point", "geometry_optimisation"]
    functional: str
    basis: str
    # C1: bounds, so that an absurd extracted number cannot reach the script.
    charge: int = Field(ge=-20, le=20)
    multiplicity: int = Field(ge=1, le=20)
    dispersion: Optional[str] = None
    solvent: Optional[str] = None

    @field_validator("functional")
    @classmethod
    def _known_functional(cls, v: str) -> str:
        if v.upper() not in {f.upper() for f in KNOWN_FUNCTIONALS}:
            raise ValueError(f"functional not supported in v1: {v}")
        return v

    @field_validator("basis")
    @classmethod
    def _known_basis(cls, v: str) -> str:
        if v.upper() not in {b.upper() for b in KNOWN_BASIS}:
            raise ValueError(f"basis set not supported in v1: {v}")
        return v
