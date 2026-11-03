"""Supply chain check (OWASP LLM03): are the model, the adapter and the prompts
the files we evaluated, byte for byte?

    uv run python scripts/integrity.py --write   # once, after the evaluation: writes INTEGRITY.sha256
    uv run python scripts/integrity.py           # before a demo or a run: exit 1 if any file changed

A swapped adapter (a "fine-tuned" file from elsewhere), an edited prompt or a
modified weight file changes the SHA-256 and is refused before anything runs.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "INTEGRITY.sha256"
WATCHED = [
    "models/qwen3-1.7b-4bit/model.safetensors",
    "models/qwen3-1.7b-4bit/config.json",
    "models/qwen3-1.7b-4bit/tokenizer.json",
    "adapters/qwen3-1.7b-reprochem/adapters.safetensors",
    "adapters/qwen3-1.7b-reprochem/adapter_config.json",
    "prompts/extract_v2.txt",
    "config.yaml",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write(root: Path = ROOT, files=WATCHED, manifest: Path = MANIFEST) -> int:
    lines = [f"{sha256(root / f)}  {f}" for f in files if (root / f).exists()]
    manifest.write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} files recorded in {manifest.name}")
    return 0


# ── SAFEGUARD S18 · integrity of model, adapter and prompts (LLM03) ── tested by: F1
#    SHA-256 of the evaluated files; a swapped adapter or an edited prompt is reported and the run should stop.
def check(root: Path = ROOT, manifest: Path = MANIFEST) -> list[str]:
    """Returns the files that changed or disappeared (empty list: all intact)."""
    bad = []
    for line in manifest.read_text().splitlines():
        digest, name = line.split("  ", 1)
        p = root / name
        if not p.exists() or sha256(p) != digest:
            bad.append(name)
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if args.write:
        return write()
    if not MANIFEST.exists():
        print("no INTEGRITY.sha256 yet: run with --write after the evaluation")
        return 2
    bad = check()
    if bad:
        print("CHANGED since the evaluation, do not run:", *bad, sep="\n  ")
        return 1
    print("all watched files match the evaluated version")
    return 0


if __name__ == "__main__":
    sys.exit(main())
