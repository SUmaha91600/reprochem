"""ReproChem tools for the LangGraph agent.

Each tool calls the MCP server of S3 (server.py). The documents and the method
cards stay in this process (short-term memory of one run): the model only
sends a paper_id, never the whole paper.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agentic/S4_strategy_memory"))

import reflect as R  # noqa: E402  (S4: passage filter, pipeline helpers)

P = R.P
DOCS: dict[str, str] = {}          # paper_id -> markdown; "request" is the user's message
CARDS: dict[str, dict] = {}        # paper_id -> method card
ATTEMPTS: dict[str, int] = {}      # paper_id -> compile attempts
USER: dict[str, str] = {}          # charge and multiplicity of the user's molecule
MAX_ATTEMPTS = 3
FIELDS = ("task", "functional", "basis", "dispersion", "solvation", "charge",
          "multiplicity", "software")


def reset(request_text: str) -> None:
    """Clears the short-term memory and registers the user's message as a document."""
    DOCS.clear()
    CARDS.clear()
    ATTEMPTS.clear()
    USER.clear()
    DOCS["request"] = request_text


def doc(paper_id: str) -> str:
    if paper_id not in DOCS:
        path = ROOT / "data/papers/md" / f"{paper_id}.md"
        if not path.exists():
            raise ValueError(f"unknown paper_id {paper_id!r}")
        DOCS[paper_id] = path.read_text(encoding="utf-8")
    return DOCS[paper_id]


def mcp(name: str, args: dict) -> dict:
    """One MCP call. A tool error comes back as {"error": ...} for the model to read."""
    async def call():
        server = PythonStdioTransport(str(ROOT / "server.py"), env=dict(os.environ), cwd=str(ROOT),
                                      log_file=ROOT / "logs" / "agent_server.log")
        async with Client(server) as c:
            return (await c.call_tool(name, args)).structured_content
    try:
        return asyncio.run(call())
    except Exception as err:                                    # noqa: BLE001
        return {"error": f"{type(err).__name__}: {str(err)[:300]}"}


def values(card: dict) -> dict:
    return {k: (card[k]["value"] if isinstance(card[k], dict) else card[k]) for k in FIELDS}


def apply_user(paper_id: str) -> None:
    """The user's values win over the paper: the molecule of the paper is not theirs."""
    for k, v in USER.items():
        CARDS[paper_id][k] = {"value": v, "citation": None}


@tool
def extract_method_card(paper_id: str) -> str:
    """Read tool. Extract the computational settings of a paper (or of the user's
    message, paper_id "request") with cited quotes. NOT_FOUND means the text does
    not give the value."""
    out = mcp("extract_method_card", {"markdown": doc(paper_id), "paper_id": paper_id, "mode": "bm25"})
    if "error" in out:
        return f"ERROR: {out['error']}"
    CARDS[paper_id] = out["card"]
    apply_user(paper_id)
    return json.dumps({"card": values(out["card"]), "missing": out["missing"]})


@tool
def read_method_passages(paper_id: str) -> str:
    """Read tool. Return the passages of a paper that talk about the calculation
    settings (functional, basis, dispersion, solvation, charge, software)."""
    out = mcp("parse_document", {"markdown": doc(paper_id), "paper_id": paper_id})
    if "error" in out:
        return f"ERROR: {out['error']}"
    chunks = out["chunks"]
    return R.method_passages(chunks, CARDS.get(paper_id, {}), max_words=1200) or "(no method passage)"


@tool
def correct_field(paper_id: str, field: str, value: str, quote: str) -> str:
    """Correct one field of the extracted card. quote must be a sentence copied
    word for word from the paper, and it must contain the value (except for task)."""
    if paper_id not in CARDS:
        return "ERROR: call extract_method_card first"
    if field not in FIELDS:
        return f"ERROR: unknown field {field}"
    if field in ("charge", "multiplicity"):
        return "ERROR: charge and multiplicity come from the user: use set_user_molecule"
    if field == "task" and value not in ("single_point", "geometry_optimisation"):
        return "ERROR: task is single_point or geometry_optimisation"
    if not P.quote_in_paper(quote, doc(paper_id)):
        return "ERROR: quote not found in the paper"
    norm = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())  # noqa: E731
    if field != "task" and norm(value) not in norm(quote):
        return "ERROR: the value is not in the quote"
    card = CARDS[paper_id]
    if field == "task":
        card["task"] = value
    else:
        card[field] = {"value": value, "citation": {"chunk_id": "agent", "quote": quote[:400],
                                                    "score": 0.0, "verified": True}}
    return f"OK: {field} = {value}"


@tool
def set_user_molecule(paper_id: str, charge: int, multiplicity: int) -> str:
    """Set the charge and multiplicity of the USER's molecule, only when the user
    gave them (a singlet is multiplicity 1). Never take them from the paper."""
    USER.update(charge=str(charge), multiplicity=str(multiplicity))
    if paper_id in CARDS:
        apply_user(paper_id)
    return "OK: kept for this request"


@tool
def compile_and_validate_job(paper_id: str, molecule_smiles: str, n_heavy_atoms: int) -> str:
    """WRITE tool: compile the card of paper_id into a PySCF job and run it on the
    molecule. 3 attempts per paper at most."""
    if paper_id not in CARDS:
        return "ERROR: call extract_method_card first"
    ATTEMPTS[paper_id] = ATTEMPTS.get(paper_id, 0) + 1
    if ATTEMPTS[paper_id] > MAX_ATTEMPTS:
        return "ERROR: no attempt left. Stop and explain the problem to the user."
    out = mcp("compile_and_validate_job", {"card": CARDS[paper_id], "molecule_smiles": molecule_smiles,
                                           "n_heavy_atoms": n_heavy_atoms})
    if "error" in out:
        return f"ERROR: {out['error']}"
    if out.get("spec") is None:
        return f"ERROR: compile failed: {out.get('compile_note')}"
    v = out.get("validation") or {}
    if not v.get("accepted", True):
        return f"ERROR: job refused: {v.get('reason')}"
    if v.get("converged") is False:
        return f"ERROR: PySCF did not converge: {(v.get('log') or '')[-300:]}"
    return json.dumps({"spec": out["spec"], "converged": v.get("converged"), "note": v.get("note")})


TOOLS = [extract_method_card, read_method_passages, correct_field, set_user_molecule,
         compile_and_validate_job]
