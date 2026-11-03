"""Checks the LoRA weights and keeps the last checkpoint free of NaN.

    uv run python scripts/check_adapter.py [adapters/qwen3-1.7b-reprochem]

Why: on 2 November, the first training run hit a NaN loss around iteration
105. Four examples had a prompt longer than 3,072 tokens: once truncated to
--max-seq-length, they had no answer token left, the loss was 0/0, and a
single NaN is enough to poison every weight through Adam.
This script reads each .safetensors file (with no MLX dependency), finds the
ones holding non-finite values, and copies the last healthy checkpoint to
adapters.safetensors, the file the benchmark and the demo load.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np


def finite(path: Path) -> bool:
    b = path.read_bytes()
    n = struct.unpack("<Q", b[:8])[0]
    header, base = json.loads(b[8:8 + n]), 8 + n
    for k, v in header.items():
        if k == "__metadata__":
            continue
        s, e = v["data_offsets"]
        raw = b[base + s:base + e]
        if v["dtype"] == "F32":
            a = np.frombuffer(raw, np.float32)
        elif v["dtype"] == "F16":
            a = np.frombuffer(raw, np.float16)
        elif v["dtype"] == "BF16":
            a = (np.frombuffer(raw, np.uint16).astype(np.uint32) << 16).view(np.float32)
        else:
            continue
        if not np.isfinite(a).all():
            return False
    return True


def main() -> int:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "adapters/qwen3-1.7b-reprochem")
    ckpts = sorted(d.glob("[0-9]*_adapters.safetensors"))
    final = d / "adapters.safetensors"
    status = {p.name: finite(p) for p in ckpts}
    for name, ok in status.items():
        print(f"  {name:<32} {'healthy' if ok else 'NaN'}")
    if final.exists() and finite(final):
        print(f"{final}: healthy, kept")
        return 0
    good = [p for p in ckpts if status[p.name]]
    if not good:
        print("no healthy checkpoint: rerun training", file=sys.stderr)
        return 1
    shutil.copyfile(good[-1], final)
    print(f"{final} contained NaN: replaced with {good[-1].name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
