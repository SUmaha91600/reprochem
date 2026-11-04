"""Workflow or agent? A decision helper for the S1 agent sheet.

The five questions come from Dr. Yaacoub's S1 deck, slide "When not to build an agent"
(Agentic AI, aivancity, 4 Nov 2026), itself based on Anthropic's "Building effective
agents" (2024). The helper does not decide for you: it applies the checklist to your
answers, compares the result with the decision you wrote, and flags disagreements.

Usage
-----
    from workflow_or_agent import Request, review, to_markdown
    rows = review(REQUESTS)
    print(to_markdown(rows))
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The five questions of the lecture, in the deck's order.
QUESTIONS = {
    "steps_unknown":  "Are the steps unknown until you see the task?",
    "needs_tools":    "Does it need fresh data or actions in other systems?",
    "cheap_mistakes": "Is a wrong step cheap and easy to undo?",
    "afford_cost":    "Can you afford 10x the cost and latency of one call?",
    "auto_check":     "Can you check success automatically?",
}


@dataclass
class Request:
    """One real request a user would send, with the student's answers and decision."""
    text: str
    steps_unknown: bool
    needs_tools: bool
    cheap_mistakes: bool
    afford_cost: bool
    auto_check: bool
    decision: str                      # "workflow" or "agent"
    justification: str                 # one sentence
    pattern: str = ""                  # optional: chaining, routing, parallelisation, ...
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.decision = self.decision.strip().lower()
        if self.decision not in {"workflow", "agent"}:
            raise ValueError(f"decision must be 'workflow' or 'agent', got {self.decision!r}")


def recommend(r: Request) -> tuple[str, str, list[str]]:
    """Apply the lecture checklist. Returns (decision, autonomy level, safeguards)."""
    safeguards: list[str] = []
    if not r.cheap_mistakes:
        safeguards.append("human approval before write or costly actions")
    if not r.auto_check:
        safeguards.append("keep a human in the loop to judge success")

    if not r.steps_unknown:
        level = "1 · Workflow" if r.needs_tools or r.auto_check else "0 · Single call"
        return "workflow", level, safeguards
    if not r.afford_cost:
        safeguards.append("budget too tight for a loop: fixed workflow with a fallback to a human")
        return "workflow", "1 · Workflow", safeguards
    return "agent", "3 · Agent loop", safeguards


def review(requests: list[Request]) -> list[dict]:
    """Run the checklist on every request and flag where it disagrees with the student."""
    rows = []
    for i, r in enumerate(requests, 1):
        dec, level, safe = recommend(r)
        rows.append({
            "n": i, "request": r.text, "decision": r.decision, "justification": r.justification,
            "pattern": r.pattern, "checklist": dec, "level": level,
            "safeguards": "; ".join(safe) or "none",
            "agrees": dec == r.decision,
            "answers": {k: getattr(r, k) for k in QUESTIONS},
        })
    return rows


def to_markdown(rows: list[dict], title: str = "Workflow or agent? Five real requests") -> str:
    """Render the deliverable: one table plus the checklist answers per request."""
    yn = lambda b: "yes" if b else "no"
    out = [f"# {title}", "",
           "| # | Request | Decision | Justification (one sentence) | Level | Safeguards | Checklist agrees |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        dec = r["decision"].capitalize() + (f" ({r['pattern']})" if r["pattern"] else "")
        out.append(f"| {r['n']} | {r['request']} | **{dec}** | {r['justification']} | {r['level']} | "
                   f"{r['safeguards']} | {'yes' if r['agrees'] else '**no, review**'} |")
    out += ["", "## Checklist answers (S1 deck, \"When not to build an agent\")", "",
            "| # | " + " | ".join(QUESTIONS.values()) + " |",
            "|---|" + "---|" * len(QUESTIONS)]
    for r in rows:
        out.append(f"| {r['n']} | " + " | ".join(yn(v) for v in r["answers"].values()) + " |")
    return "\n".join(out) + "\n"
