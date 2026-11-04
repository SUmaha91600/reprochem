"""Pydantic schemas for ReproChem's three main agent tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .schema import JobSpec, MethodCard


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Tool parameters ────────────────────────────────────────────────

class ParseDocumentParams(StrictModel):
    markdown: str = Field(min_length=1, description="Document content in Markdown.")
    paper_id: str = Field(min_length=1, description="Document identifier.")


class ExtractMethodCardParams(ParseDocumentParams):
    mode: Literal["bm25", "dense", "hybrid", "rerank"] = "rerank"


class CompileAndValidateParams(StrictModel):
    card: MethodCard
    molecule_smiles: str = Field(min_length=1)
    n_heavy_atoms: int = Field(ge=0)


# ── Structured outputs ─────────────────────────────────────────────

class ChunkOutput(StrictModel):
    id: str
    text: str
    section: str | None = None


class ParsedDocumentOutput(StrictModel):
    paper_id: str
    chunks: list[ChunkOutput]


class ExtractMethodCardOutput(StrictModel):
    card: MethodCard
    missing: list[str]
    effective_mode: str


class ValidationOutput(StrictModel):
    accepted: bool
    reason: str | None = None
    note: str | None = None
    converged: bool | None = None
    script: str | None = None
    log: str | None = None


class CompileAndValidateOutput(StrictModel):
    spec: JobSpec | None
    compile_note: str
    validation: ValidationOutput | None = None


# ── JSON tool schemas ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "parse_document",
        "access": "read",
        "description": (
            "Split a Markdown chemistry document into section-based passages "
            "for retrieval."
        ),
        "parameters": ParseDocumentParams.model_json_schema(),
        "output": ParsedDocumentOutput.model_json_schema(),
    },
    {
        "name": "extract_method_card",
        "access": "read",
        "description": (
            "Extract the seven computational chemistry settings with citations. "
            "Use NOT_FOUND rather than guessing when a setting is absent."
        ),
        "parameters": ExtractMethodCardParams.model_json_schema(),
        "output": ExtractMethodCardOutput.model_json_schema(),
    },
    {
        "name": "compile_and_validate_job",
        "access": "write",
        "description": (
            "Compile a cited method card into a validated PySCF job specification "
            "and check whether the calculation runs. Missing or unsupported "
            "required settings must block compilation."
        ),
        "parameters": CompileAndValidateParams.model_json_schema(),
        "output": CompileAndValidateOutput.model_json_schema(),
    },
]


OUTPUT_MODELS = {
    "parse_document": ParsedDocumentOutput,
    "extract_method_card": ExtractMethodCardOutput,
    "compile_and_validate_job": CompileAndValidateOutput,
}


def validate_tool_output(tool_name: str, payload: dict) -> BaseModel:
    """Validate a tool result against its Pydantic output model."""
    try:
        model = OUTPUT_MODELS[tool_name]
    except KeyError as exc:
        raise ValueError(f"Unknown tool: {tool_name}") from exc
    return model.model_validate(payload)
