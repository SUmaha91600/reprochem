#!/usr/bin/env bash
# Entraîne le student (Qwen3-1.7B + LoRA) sur data/sft avec MLX. Mac Apple Silicon.
#
#   bash scripts/mac_train.sh            # ~30 à 60 min selon le Mac
#
# Tout est écrit dans logs/train.log ; l'adaptateur dans adapters/qwen3-1.7b-reprochem/.
set -euo pipefail
cd "$(dirname "$0")/.."
# Sans ça, Python garde sa sortie en mémoire quand elle passe par tee :
# le terminal et le log restent muets pendant tout l'entraînement.
export PYTHONUNBUFFERED=1
mkdir -p logs adapters
exec > >(tee -a logs/train.log) 2>&1
echo "=== $(date) · entraînement du student ==="

[[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] || { echo "MLX demande un Mac Apple Silicon."; exit 1; }
command -v uv >/dev/null || { echo "uv introuvable : curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }

# 1. Dépendances : mlx-lm (entraînement + inférence locale) et openpyxl (jeu d'or).
grep -q 'mlx-lm' pyproject.toml || uv add --optional train "mlx-lm; sys_platform == 'darwin'"
grep -q 'openpyxl' pyproject.toml || uv add openpyxl
uv sync --extra train

# 2. Le modèle de base. Jusqu'à 16 Go de mémoire unifiée, on le quantifie en 4 bits
#    (QLoRA) et on passe en batch 1 : avec un vocabulaire de 152k tokens, les logits
#    d'un batch de 2 × 3 072 tokens pèsent à eux seuls ~4 Go en float32, et un Mac
#    de 16 Go part en swap (constaté le 2 novembre : 30 s par batch, puis plus rien).
MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
BASE="Qwen/Qwen3-1.7B"
if (( MEM_GB <= 16 )); then
  if [[ ! -d models/qwen3-1.7b-4bit ]]; then
    uv run python -m mlx_lm convert --hf-path "$BASE" -q --mlx-path models/qwen3-1.7b-4bit \
      || uv run mlx_lm.convert --hf-path "$BASE" -q --mlx-path models/qwen3-1.7b-4bit
  fi
  BASE="models/qwen3-1.7b-4bit"; BATCH=1
else
  BATCH=2
fi
echo "mémoire ${MEM_GB} Go · base ${BASE} · batch ${BATCH}"
echo "$BASE" > adapters/BASE_MODEL

# 3. LoRA. Perte calculée sur la réponse seulement (--mask-prompt), comme au cours sur le SFT.
#    510 exemples, 2 époques : 1 020 exemples vus, soit 1 020 / BATCH itérations.
ITERS=$(( 1020 / BATCH ))
ARGS=(--model "$BASE" --train --data data/sft --iters "$ITERS" --batch-size "$BATCH"
      --num-layers 16 --learning-rate 1e-4 --max-seq-length 4608 --mask-prompt
      --grad-checkpoint --steps-per-eval 200 --val-batches 25 --save-every 100
      --adapter-path adapters/qwen3-1.7b-reprochem --seed 0)
# 4 608 et non 3 072 : le plus long exemple fait 4 551 tokens. Tronqué, un exemple
# perd sa réponse, sa perte vaut 0/0 = NaN et tous les poids sont empoisonnés
# (premier essai du 2 novembre, NaN à l'itération ~105).
uv run python -m mlx_lm lora "${ARGS[@]}" || echo "entraînement interrompu"

# 4. Garde le dernier checkpoint sans NaN dans adapters.safetensors.
uv run python scripts/check_adapter.py adapters/qwen3-1.7b-reprochem


echo "=== $(date) · terminé : adapters/qwen3-1.7b-reprochem ==="
