"""ReproChem MCP server (FastMCP): the three agent tools of app/tool_schemas.py over MCP.

    uv run python server.py                 # stdio (what an MCP client launches)
    uv run python server.py --http          # Streamable HTTP on http://127.0.0.1:8765/mcp

Tools (same names, descriptions and Pydantic models as app/tool_schemas.py):

    parse_document            read   Markdown -> section-based passages (no model call)
    extract_method_card       read   Markdown -> cited method card (calls the LLM of config.yaml)
    compile_and_validate_job  write  method card + molecule -> PySCF job spec + runnability test

Every result is validated against its Pydantic output model before it leaves
the server, so the client always receives the structured output declared in S2.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp_types import ToolAnnotations
from pydantic import Field

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import app.pipeline as P  # noqa: E402
from app.retrieval import Retriever  # noqa: E402
from app.schema import MethodCard  # noqa: E402
from app.tool_schemas import (  # noqa: E402
    TOOLS,
    ChunkOutput,
    CompileAndValidateOutput,
    ExtractMethodCardOutput,
    ParsedDocumentOutput,
    ValidationOutput,
)

DESCRIPTIONS = {t["name"]: t["description"] for t in TOOLS}
ACCESS = {t["name"]: t["access"] for t in TOOLS}

Markdown = Annotated[str, Field(min_length=1, description="Document content in Markdown.")]
PaperId = Annotated[str, Field(min_length=1, description="Document identifier.")]

mcp = FastMCP(
    name="reprochem",
    instructions=(
        "ReproChem turns a published computational chemistry protocol into a "
        "runnable PySCF job. Call parse_document to inspect a paper, "
        "extract_method_card to get the cited settings, then "
        "compile_and_validate_job. Never invent a setting reported as NOT_FOUND."
    ),
)


def _annotations(name: str) -> ToolAnnotations:
    read = ACCESS[name] == "read"
    return ToolAnnotations(read_only_hint=read, destructive_hint=False,
                           idempotent_hint=read, open_world_hint=False)


@mcp.tool(name="parse_document", description=DESCRIPTIONS["parse_document"],
          annotations=_annotations("parse_document"))
def parse_document(markdown: Markdown, paper_id: PaperId) -> ParsedDocumentOutput:
    chunks = P.parse(markdown, paper_id)
    return ParsedDocumentOutput(
        paper_id=paper_id,
        chunks=[ChunkOutput(id=c.id, text=c.text, section=c.meta.get("section")) for c in chunks],
    )


@mcp.tool(name="extract_method_card", description=DESCRIPTIONS["extract_method_card"],
          annotations=_annotations("extract_method_card"))
def extract_method_card(
    markdown: Markdown,
    paper_id: PaperId,
    mode: Literal["bm25", "dense", "hybrid", "rerank"] = "rerank",
) -> ExtractMethodCardOutput:
    retriever = Retriever(P.parse(markdown, paper_id), P.CFG["retrieval"])
    card = P.extract(retriever, paper_id, mode=mode)
    return ExtractMethodCardOutput(
        card=card, missing=card.missing(),
        effective_mode=getattr(retriever, "last_mode", mode),
    )


@mcp.tool(name="compile_and_validate_job", description=DESCRIPTIONS["compile_and_validate_job"],
          annotations=_annotations("compile_and_validate_job"))
def compile_and_validate_job(
    card: MethodCard,
    molecule_smiles: Annotated[str, Field(min_length=1)],
    n_heavy_atoms: Annotated[int, Field(ge=0)],
) -> CompileAndValidateOutput:
    spec, note = P.compile_spec(card, molecule_smiles)
    validation = ValidationOutput(**P.validate(spec, n_heavy_atoms)) if spec else None
    return CompileAndValidateOutput(spec=spec, compile_note=note, validation=validation)


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="http", host="127.0.0.1", port=8765)
    else:
        mcp.run()
