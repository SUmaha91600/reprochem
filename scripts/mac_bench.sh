#!/usr/bin/env bash
# Final benchmark, on the hand-validated gold set. Apple Silicon Mac.
#
#   bash scripts/mac_bench.sh          # ~20 to 30 min
#
# Writes eval/report_<row>.json for each row, and eval/benchmark.txt.
set -euo pipefail
cd "$(dirname "$0")/.."
# Without this, Python buffers its output when piped through tee:
# the terminal and the log stay silent for the whole run.
export PYTHONUNBUFFERED=1
mkdir -p logs
exec > >(tee -a logs/bench.log) 2>&1
echo "=== $(date) · benchmark ==="

# 1. The gold set, from the sheet you validated.
uv run python scripts/gold_from_review.py

# PySCF and RDKit for the runnable metric. Without them the column stays empty
# and the rest of the benchmark still runs.
uv sync --extra train --extra chem || { echo "chemistry unavailable: runnable will stay empty"; uv sync --extra train; }

BASE=$(cat adapters/BASE_MODEL 2>/dev/null || echo "Qwen/Qwen3-1.7B")
export REPROCHEM_BASE_URL=mlx REPROCHEM_MODEL="$BASE" REPROCHEM_API_KEY_ENV=none

# 2. Teacher: its labels on the same passages as the student (no model call).
uv run python eval/eval.py --cards data/teacher/doc_cards.jsonl --label teacher --mode bm25

# 3. Student without LoRA, then with it. "bash scripts/mac_bench.sh lora" reruns
#    only the LoRA row (after a new training run): teacher and base do not change.
uv run python scripts/check_adapter.py adapters/qwen3-1.7b-reprochem
if [[ "${1:-}" != "lora" || ! -f eval/report_student-base.json ]]; then
  REPROCHEM_ADAPTER= uv run python eval/eval.py --mode bm25 --label student-base
fi
REPROCHEM_ADAPTER=adapters/qwen3-1.7b-reprochem uv run python eval/eval.py --mode bm25 --label student-lora

# 4. The red team replayed against the LoRA student (docs/red_team_results.md).
REPROCHEM_ADAPTER=adapters/qwen3-1.7b-reprochem uv run python scripts/red_team.py || echo "red team failed, carrying on"

# 5. The table.
uv run python eval/compare.py eval/report_teacher.json eval/report_student-base.json eval/report_student-lora.json \
  | tee eval/benchmark.txt

# 6. The report tables (docs/results.md), with no copying by hand.
uv run python scripts/results_md.py > /dev/null
echo "=== $(date) · done ==="
