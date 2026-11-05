"""ReproChem S4 agent: a reflection loop over the MCP tools of server.py.

    uv run python agentic/S4_strategy_memory/agent.py data/papers/md/2202.02370.md \
        --smiles O --heavy-atoms 1 --charge 0 --multiplicity 1 --yes --gold

1. parse_document and extract_method_card (MCP, read tools).
2. Reflection: the agent model reviews the card with lessons.md and the
   journal, and corrects fields. A correction needs a quote found in the paper.
3. Approval, then compile_and_validate_job (MCP, write tool, runs PySCF).
4. On an error, back to 2 with the error in the journal. 3 attempts at most.
5. At the end, the failures that were fixed become lessons in lessons.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reflect as R  # noqa: E402
from memory import Journal, Lessons, card_key  # noqa: E402
from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from openai import APIError  # noqa: E402
from fastmcp.client.transports import PythonStdioTransport  # noqa: E402

P, ROOT = R.P, R.ROOT
REQUIRED = ("functional", "basis", "charge", "multiplicity")


def norm(v) -> str:
    return "".join(ch for ch in str(v).upper() if ch.isalnum())


def gold_for(paper_id: str) -> dict | None:
    for line in (ROOT / "eval/testset.jsonl").read_text(encoding="utf-8").splitlines():
        t = json.loads(line) if line.strip() else {}
        if t.get("paper_id") == paper_id:
            return t["fields"]
    return None


def apply(card: dict, fixes: list[dict], markdown: str, journal: Journal,
          locked: set[str] = frozenset()) -> list[str]:
    """Applies the corrections whose quote is really in the paper."""
    changed = []
    for f in fixes:
        name, value, quote = f["field"], str(f["value"])[:60], str(f.get("quote", ""))
        if name in locked:                      # given by the user: the paper's molecule is not theirs
            continue
        if not P.quote_in_paper(quote, markdown):
            journal.add("review", False, f"correction of {name} to {value!r} refused: quote not in the paper",
                        quote=quote[:300])
            continue
        if name != "task" and norm(value) not in norm(quote):
            journal.add("review", False, f"correction of {name} to {value!r} refused: value not in the quote")
            continue
        old = card[name] if name == "task" else card[name]["value"]
        if norm(old) == norm(value):
            continue
        if name == "task":
            card["task"] = value
        else:
            card[name] = {"value": value, "citation": {"chunk_id": "agent", "quote": quote[:400],
                                                        "score": 0.0, "verified": True}}
        journal.add("review", True, f"{name}: {old!r} -> {value!r} ({f.get('reason', '')[:120]})",
                    field=name, old=old, new=value)
        changed.append(name)
    return changed


def ask_user(card: dict, journal: Journal, args) -> bool:
    """Charge and multiplicity of the user's molecule. Returns False if still missing."""
    for name in ("charge", "multiplicity"):
        given = getattr(args, name)
        if given is None and card[name]["value"] == "NOT_FOUND" and not args.yes and sys.stdin.isatty():
            given = input(f"The paper does not give the {name} of your molecule. Value? ").strip() or None
        if given is not None:
            card[name] = {"value": str(given), "citation": None}
            journal.add("user", True, f"{name} = {given} (given by the user)")
    return all(card[f]["value"] != "NOT_FOUND" for f in REQUIRED)


def approved(card: dict, args) -> bool:
    if args.yes:
        return True
    shown = {k: (v["value"] if isinstance(v, dict) else v) for k, v in card.items() if k != "paper_id"}
    print(json.dumps(shown, indent=1, ensure_ascii=False))
    return input("Run PySCF with this card? [y/N] ").strip().lower() == "y"


def compile_failed(out: dict) -> str | None:
    """The error message of a compile result, or None if it passed."""
    if out.get("spec") is None:
        return out.get("compile_note", "compile failed")
    v = out.get("validation") or {}
    if not v.get("accepted", True):
        return v.get("reason", "job refused")
    if v.get("converged") is False:
        return "PySCF did not run or converge: " + (v.get("log") or "")[-300:]
    return None


async def run(markdown: str, paper_id: str, args) -> dict:
    journal, lessons = Journal(), Lessons(args.lessons, max_per_section=P.CFG.get("agent", {}).get("max_lessons", 20))
    max_attempts = P.CFG.get("agent", {}).get("max_attempts", 3)
    server = PythonStdioTransport(str(ROOT / "server.py"), env=dict(os.environ), cwd=str(ROOT),
                                  log_file=ROOT / "logs" / "agent_server.log")
    status, out, card = "failed", None, None
    try:
        async with Client(server) as mcp:
            status, out, card = await loop(mcp, markdown, paper_id, args, journal, lessons, max_attempts)
    except (ToolError, APIError) as err:       # a tool or a model is down: stop, do not crash
        status = "tool_error"
        journal.add("stop", False, f"{type(err).__name__}: {str(err)[:300]}")
    learned = []
    if card is not None:
        learned = remember(journal, lessons, card, journal.first, gold_for(paper_id) if args.gold else None)
    return {"status": status, "card": card, "result": out, "journal": journal.entries, "learned": learned}


async def loop(mcp, markdown, paper_id, args, journal, lessons, max_attempts):
    status, out = "failed", None
    chunks = (await mcp.call_tool("parse_document", {"markdown": markdown, "paper_id": paper_id})
              ).structured_content["chunks"]
    ext = (await mcp.call_tool("extract_method_card", {"markdown": markdown, "paper_id": paper_id,
                                                        "mode": args.mode})).structured_content
    card = ext["card"]
    journal.first = {k: (v["value"] if isinstance(v, dict) else v) for k, v in card.items()}
    journal.add("extract", True, f"{len(chunks)} passages, missing: {', '.join(ext['missing']) or 'none'}")
    for attempt in range(1, max_attempts + 1):
        passages = R.method_passages(chunks, card)
        rev = R.review(card, passages, journal.render(), lessons.prompt_block())
        locked = {n for n in ("charge", "multiplicity") if getattr(args, n) is not None}
        apply(card, rev["corrections"], markdown, journal, locked)
        if not ask_user(card, journal, args):
            status = "needs_user"
            journal.add("stop", False, "a required field is missing: ask the user")
            break
        key = card_key(card)
        if journal.tried(key):
            journal.add("stop", False, "no new correction after the last error")
            break
        if not approved(card, args):
            status = "refused"
            break
        out = (await mcp.call_tool("compile_and_validate_job", {
            "card": card, "molecule_smiles": args.smiles,
            "n_heavy_atoms": args.heavy_atoms})).structured_content
        error = compile_failed(out)
        journal.add("compile", error is None, error or (out.get("validation") or {}).get("note", "ok"),
                    card_key=key, attempt=attempt)
        if error is None:
            status = "done"
            break
    return status, out, card


def remember(journal: Journal, lessons: Lessons, card: dict, first: dict, gold: dict | None) -> list[dict]:
    """Long-term memory: only a failure that was then fixed teaches something."""
    compiles = [e["ok"] for e in journal.entries if e["step"] == "compile"]
    recovered = False in compiles and compiles[-1]           # a compile error, then a success
    fixed = any(e["step"] == "review" and e["ok"] for e in journal.entries)
    if not (fixed or recovered):
        return []
    added = []
    known = "\n".join([lessons.prompt_block(), *lessons.items["To review"]])
    for les in R.learn(journal.render(), known):
        f = les.get("field")
        if les["kind"] == "tool":
            section = "Tool lessons" if recovered else "To review"
        elif gold and f in gold and norm(gold[f]) == norm(card[f]["value"]) != norm(first.get(f)):
            section = "Reading lessons"        # the correction is confirmed by the gold set
        else:
            section = "To review"
        if lessons.add(section, les["text"]):
            added.append({**les, "section": section})
    lessons.save()
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown", type=Path)
    ap.add_argument("--paper-id", help="default: the file name without .md")
    ap.add_argument("--smiles", default="O")
    ap.add_argument("--heavy-atoms", type=int, default=1)
    ap.add_argument("--charge")
    ap.add_argument("--multiplicity")
    ap.add_argument("--mode", default="bm25", choices=["bm25", "dense", "hybrid", "rerank"])
    ap.add_argument("--yes", action="store_true", help="approve the PySCF run without asking")
    ap.add_argument("--gold", action="store_true", help="confirm reading lessons with eval/testset.jsonl")
    ap.add_argument("--lessons", type=Path, default=HERE / "lessons.md", help="the skill file")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args()
    paper_id = args.paper_id or args.markdown.stem
    result = asyncio.run(run(args.markdown.read_text(encoding="utf-8"), paper_id, args))
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    else:
        print(Journal(result["journal"]).render())
        print(f"\nstatus: {result['status']}")
        for les in result["learned"]:
            print(f"learned ({les['section']}): {les['text']}")
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
