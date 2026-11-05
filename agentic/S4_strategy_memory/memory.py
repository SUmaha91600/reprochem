"""The two memories of the S4 agent.

Journal  short-term: what the agent tried during ONE request. It lives in the
         process and is lost when the request ends.
Lessons  long-term, procedural: lessons.md, a skill file injected in the
         agent prompt at the start of each request. It keeps how to use the
         tools and how to read a paper, never the content of a paper.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

LESSONS_FILE = Path(__file__).with_name("lessons.md")
SECTIONS = ("Tool lessons", "Reading lessons", "To review")
MAX_LESSON_CHARS = 220


# ------------------------------------------------------------- short-term
@dataclass
class Journal:
    """One entry per step: the step, what was sent, what came back."""

    entries: list[dict] = field(default_factory=list)
    first: dict = field(default_factory=dict)      # the card as extracted, before any correction

    def add(self, step: str, ok: bool, detail: str, **data) -> None:
        self.entries.append({"n": len(self.entries) + 1, "step": step, "ok": ok,
                             "detail": detail[:400], **data})

    def render(self) -> str:
        if not self.entries:
            return "(no step yet)"
        return "\n".join(f"{e['n']}. [{e['step']}] {'OK' if e['ok'] else 'FAILED'}: {e['detail']}"
                         for e in self.entries)

    def failures(self) -> list[dict]:
        return [e for e in self.entries if not e["ok"]]

    def tried(self, key: str) -> bool:
        """Was this exact card already sent to the compiler?"""
        return any(e.get("card_key") == key for e in self.entries)


def card_key(card: dict) -> str:
    return json.dumps({k: (v["value"] if isinstance(v, dict) else v) for k, v in card.items()},
                      sort_keys=True)


# -------------------------------------------------------------- long-term
class Lessons:
    """lessons.md, read and written by section. A lesson is one bullet line."""

    def __init__(self, path: Path = LESSONS_FILE, max_per_section: int = 20):
        self.path = path
        self.max = max_per_section
        self.head, self.items = self._read()

    def _read(self) -> tuple[str, dict[str, list[str]]]:
        text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        head, items, current = [], {s: [] for s in SECTIONS}, None
        for line in text.splitlines():
            m = re.match(r"^##\s+(.+?)\s*$", line)
            if m and m.group(1) in SECTIONS:
                current = m.group(1)
            elif current and line.startswith("- "):
                items[current].append(line[2:].strip())
            elif current is None:
                head.append(line)
        return "\n".join(head).rstrip() + "\n", items

    def prompt_block(self) -> str:
        """What the agent sees: validated lessons only, never 'To review'."""
        lines = [f"- [tool] {t}" for t in self.items["Tool lessons"]]
        lines += [f"- [reading] {t}" for t in self.items["Reading lessons"]]
        return "\n".join(lines) or "(no lesson yet)"

    def add(self, section: str, text: str) -> bool:
        """Adds a lesson unless it is too long, a near duplicate, or the
        section is full. Returns True when the lesson was added."""
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) > MAX_LESSON_CHARS or len(self.items[section]) >= self.max:
            return False
        for s in SECTIONS:
            for old in self.items[s]:
                if difflib.SequenceMatcher(None, old.lower(), text.lower()).ratio() > 0.8:
                    return False
        self.items[section].append(text)
        return True

    def save(self) -> None:
        out = [self.head]
        for s in SECTIONS:
            out.append(f"## {s}\n")
            out += [f"- {t}" for t in self.items[s]]
            out.append("")
        self.path.write_text("\n".join(out), encoding="utf-8")
