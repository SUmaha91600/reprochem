#!/usr/bin/env bash
# Chunk size, measured: the LoRA student on the gold set with sections of
# 200 words (production) and 400 words, back to back, same session.
#
#   bash scripts/mac_chunks.sh      # ~10 min on a 16 GB Mac
#
# Writes eval/report_student-lora-{200w,400w}.json and docs/chunks_400.{md,json}.
# config.yaml is not touched: REPROCHEM_MAX_WORDS overrides max_words per run.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
mkdir -p logs
exec > >(tee -a logs/chunks.log) 2>&1
echo "=== $(date) · chunk size 200 vs 400 ==="

# One model in memory at a time, and nothing else competing for the GPU:
# otherwise the timing compares two different machines.
if pgrep -f "streamlit run|eval/eval.py|weight_edit.py|mlx_lm" >/dev/null; then
  echo "Another model process is running (demo, benchmark or weight edit):"
  pgrep -fl "streamlit run|eval/eval.py|weight_edit.py|mlx_lm" || true
  echo "Stop it first (Ctrl-C in its terminal), then rerun. Nothing was started."
  exit 1
fi

BASE=$(cat adapters/BASE_MODEL 2>/dev/null || echo "Qwen/Qwen3-1.7B")
export REPROCHEM_BASE_URL=mlx REPROCHEM_MODEL="$BASE" REPROCHEM_API_KEY_ENV=none
export REPROCHEM_ADAPTER=adapters/qwen3-1.7b-reprochem

for W in 200 400; do
  echo "--- sections of at most $W words ---"
  REPROCHEM_MAX_WORDS=$W uv run python eval/eval.py --mode bm25 \
    --label "student-lora-${W}w" --out "eval/report_student-lora-${W}w.json"
done

uv run python scripts/chunks_compare.py
echo "=== $(date) · done: docs/chunks_400.md ==="
