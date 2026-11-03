#!/usr/bin/env bash
# Weight-edit experiment: the student with and without a targeted weight edit.
#
#   bash scripts/mac_weight_edit.sh          # LoRA student only, ~40 min
#   FAST=1 bash scripts/mac_weight_edit.sh   # smaller sets, ~20 min
#   bash scripts/mac_weight_edit.sh both     # also the base model
#
# For each model: find the direction (training data) -> choose layers and beta
# (validation data) -> score once on the gold set -> eval/report_<label>-edit.json.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
mkdir -p logs
exec > >(tee -a logs/weight_edit.log) 2>&1
echo "=== $(date) · weight edit ==="

# One model in memory at a time. The demo (Streamlit) or another benchmark
# also holds a copy of the model: two copies plus this run do not fit in 16 GB.
if pgrep -f "streamlit run|eval/eval.py|weight_edit.py find|weight_edit.py sweep|mlx_lm" >/dev/null; then
  echo "Another model process is running (demo, benchmark or a previous run):"
  pgrep -fl "streamlit run|eval/eval.py|weight_edit.py|mlx_lm" || true
  echo "Stop it first (Ctrl-C in its terminal), then rerun. Nothing was started."
  exit 1
fi
export REPROCHEM_MLX_GB="${REPROCHEM_MLX_GB:-6}"   # MLX memory cap for find and sweep

BASE=$(cat adapters/BASE_MODEL 2>/dev/null || echo "Qwen/Qwen3-1.7B")
export REPROCHEM_BASE_URL=mlx REPROCHEM_MODEL="$BASE" REPROCHEM_API_KEY_ENV=none
LORA=adapters/qwen3-1.7b-reprochem

if [[ -n "${FAST:-}" ]]; then FIND_ARGS="--n 40"; SWEEP_ARGS="--n-valid 30 --betas 0 0.25 0.5"
else FIND_ARGS="--n 80"; SWEEP_ARGS="--n-valid 50"; fi

run() {  # $1 label, $2 adapter ("" for the base model)
  uv run python scripts/weight_edit.py find  --label "$1" --adapter "$2" $FIND_ARGS
  uv run python scripts/weight_edit.py sweep --label "$1" --adapter "$2" $SWEEP_ARGS
  REPROCHEM_ADAPTER="$2" REPROCHEM_EDIT="eval/weight_edit/$1.json" \
    uv run python eval/eval.py --mode bm25 --label "$1-edit" --out "eval/report_$1-edit.json"
}

run student-lora "$LORA"
[[ "${1:-}" == "both" ]] && run student-base ""

REPORTS="eval/report_student-base.json eval/report_student-lora.json eval/report_student-lora-edit.json"
[[ -f eval/report_student-base-edit.json ]] && REPORTS="eval/report_student-base.json eval/report_student-base-edit.json eval/report_student-lora.json eval/report_student-lora-edit.json"
uv run python eval/compare.py $REPORTS | tee eval/weight_edit/benchmark.txt
echo "=== $(date) · done ==="
