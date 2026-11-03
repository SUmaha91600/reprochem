#!/usr/bin/env bash
# ReproChem in one HTML page: extraction with its RAG passages, Lens, and the attacks.
#
#   bash scripts/web.sh          # opens http://127.0.0.1:8600 (or the next free port)
#
# Same model as scripts/demo.sh (Qwen3-1.7B + LoRA with MLX). Listens on 127.0.0.1 only.
set -euo pipefail
cd "$(dirname "$0")/.."
export REPROCHEM_BASE_URL=mlx REPROCHEM_API_KEY_ENV=none
export REPROCHEM_MODEL="$(cat adapters/BASE_MODEL 2>/dev/null || echo Qwen/Qwen3-1.7B)"
export REPROCHEM_ADAPTER="${REPROCHEM_ADAPTER-adapters/qwen3-1.7b-reprochem}"
export PYTHONUNBUFFERED=1
uv run --extra train python -m app.server
