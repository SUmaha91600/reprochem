#!/usr/bin/env bash
# The 3 November demo: the local student (Qwen3-1.7B + LoRA) in the browser.
set -euo pipefail
cd "$(dirname "$0")/.."
export REPROCHEM_BASE_URL=mlx REPROCHEM_API_KEY_ENV=none
export REPROCHEM_MODEL="$(cat adapters/BASE_MODEL 2>/dev/null || echo Qwen/Qwen3-1.7B)"
export REPROCHEM_ADAPTER="${REPROCHEM_ADAPTER-adapters/qwen3-1.7b-reprochem}"
uv run --extra train streamlit run app/ui.py
