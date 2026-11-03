#!/usr/bin/env bash
# La nuit, sans surveillance : entraînement corrigé, puis benchmark complet.
#
#   nohup caffeinate -i bash scripts/mac_overnight.sh > /dev/null 2>&1 &
#
# Le benchmark lit le jeu d'or (gold_review_edited.xlsx + gold_corrections.xlsx)
# au moment où il démarre, c'est-à-dire après l'entraînement : les corrections
# enregistrées d'ici là sont prises en compte.
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
mkdir -p logs

bash scripts/mac_train.sh

# Si le nouvel entraînement n'a produit aucun checkpoint sain, on revient au
# checkpoint 100 du premier run, vérifié sans NaN le 2 novembre.
if ! uv run python scripts/check_adapter.py adapters/qwen3-1.7b-reprochem; then
  echo "=== $(date) · nouvel entraînement inutilisable : retour au checkpoint 100 du run 1" | tee -a logs/train.log
  cp adapters/run1-nan-after-it100/0000100_adapters.safetensors \
     adapters/qwen3-1.7b-reprochem/adapters.safetensors
fi

bash scripts/mac_bench.sh
echo "=== $(date) · nuit terminée" | tee -a logs/bench.log
