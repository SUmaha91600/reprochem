# Running ReproChem in a terminal, with uv and Qwen

Tested on macOS (Apple Silicon). Everything runs locally, with no API key and
no network once the models are pulled.

## 0 · The November 3 deliverable, in four commands

Apple Silicon Mac, uv installed, network for the first Qwen download.

```bash
bash scripts/mac_train.sh    # mlx-lm, then the student's LoRA: 30 to 60 min → logs/train.log
# validate data/gold_review.xlsx (Décision column), then:
bash scripts/mac_bench.sh    # gold set, 3 rows, red team, docs/results.md → logs/bench.log
bash scripts/web.sh          # the app in one HTML page, no network (Lens voice excepted)
```

`mac_bench.sh` runs, in order: `gold_from_review.py` (validated sheet → gold
set), `eval.py` for `teacher`, `student-base` and `student-lora`,
`red_team.py`, `compare.py` (→ `eval/benchmark.txt`) and `results_md.py`
(→ `docs/results.md`). Ollama is not needed on this path: the student is
served by MLX in the same process (`base_url: mlx`). The sections below
describe the older Ollama path, which still works without a Mac.

## 1 · uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh    # or: brew install uv
uv --version
```

No need to install Python first: `.python-version` asks for CPython 3.12, and
uv fetches it on its own if it is missing.

## 2 · Qwen locally

```bash
brew install ollama          # or the .dmg from ollama.com/download
ollama serve &               # leave it running, it is the server on port 11434
ollama pull qwen3:1.7b       # ≈ 1.4 GB, the repo default
ollama pull bge-m3           # ≈ 1.2 GB, embeddings for dense retrieval
ollama list                  # the tag shown here is the one to put in config.yaml
```

## 3 · The repository

```bash
cd reprochem
uv sync                      # creates .venv and installs the core from uv.lock
uv run python scripts/check.py
```

`uv sync` reads `uv.lock` rather than `pyproject.toml`, so everyone gets
exactly the same versions. There is no `source .venv/bin/activate` step:
`uv run` handles it, and resyncs the environment if it has drifted.

`check.py` should show the model as reachable. If it does not, either Ollama
is not running, or the model name in `config.yaml` does not match
`ollama list`.

## 4 · The corpus

```bash
uv sync --extra convert                           # pymupdf4llm only, ~40 MB
uv run python scripts/fetch_corpus.py --n 60 \
    --query B3LYP --query def2-TZVP --query "geometry optimization"
uv run python scripts/make_sheet.py --sample 20   # annotation sheet, to fill in a spreadsheet app
uv run python scripts/build_testset.py            # sheet -> eval/testset.jsonl, with checks
```

`--query` can be repeated: each occurrence is a separate pass, and the
manifest is **additive**, so rerunning with other keywords adds to the corpus
instead of overwriting it. Without `--query`, sorting the category by
relevance mostly brings up methods papers, which have no protocol to extract.
Targeting the names of functionals and basis sets pulls in application
papers, and those are the ones the project needs.

The detailed protocol for the manual steps is in
`ReproChem_protocole_collecte.pdf`. The `fetch_corpus.py` parsers can be
tested offline: `uv run python scripts/fetch_corpus.py --selftest`.

## 5 · First measurement

```bash
uv run python eval/eval.py --mode bm25
```

This reads `eval/testset.jsonl`, calls Qwen once per field and per paper, and
writes `eval/report.json`.

## 6 · The two extras

```bash
uv sync --extra convert      # pymupdf4llm: PDF -> markdown  (~40 MB)
uv sync --extra chem         # rdkit + pyscf: runnability test  (~120 MB)
uv sync --extra rerank       # cross-encoder: rerank mode  (~500 MB, pulls in torch)
uv sync --all-extras         # all three
```

Three extras instead of one, because only `rerank` is heavy. Collection needs
only `convert`, and embeddings need nothing at all.

**Embeddings need no extra.** `embedder_backend: ollama` calls `bge-m3`,
already pulled on the machine, through `/v1/embeddings`. The `dense` and
`hybrid` modes therefore work with the core alone, without torch and the 3 GB
that come with it. Only reranking relies on a cross-encoder, which has no
Ollama equivalent and requires `--extra rerank`.

To switch back to the path from the October 7 lab:

```yaml
embedder_backend: sentence-transformers
embedder: BAAI/bge-m3
```

Both have macOS arm64 wheels on PyPI, **PySCF included**: uv installs
everything without compiling and without conda.

Each `uv sync` **puts the environment back in the requested state**, so a
later `uv sync` without `--extra` uninstalls the extras. To keep the full
setup at all times:

```bash
uv sync --all-extras
```

The fallback happens in two steps, and the report always states what actually
ran. Without a cross-encoder, `rerank` becomes `hybrid` and the report writes
`"mode": "rerank (repli : hybrid)"`. With no embeddings at all, everything
becomes `bm25`. Without `pyscf`, the runnability test returns `null` instead
of being counted as a failure.

## 7 · Comparing two models without editing a file

Three environment variables override `config.yaml`:

```bash
# A bigger Qwen, once pulled: the difference shows up as one row of the report
REPROCHEM_MODEL=qwen3:8b uv run python eval/eval.py --mode bm25

# Qwen hosted on Groq (free key: console.groq.com/keys)
REPROCHEM_BASE_URL=https://api.groq.com/openai/v1 \
REPROCHEM_MODEL=qwen/qwen3-32b \
REPROCHEM_API_KEY_ENV=GROQ_API_KEY \
uv run python eval/eval.py --mode bm25

# The course model, for the comparison row
REPROCHEM_BASE_URL=https://api.groq.com/openai/v1 \
REPROCHEM_MODEL=openai/gpt-oss-20b \
REPROCHEM_API_KEY_ENV=GROQ_API_KEY \
uv run python eval/eval.py --mode bm25
```

Each run overwrites `eval/report.json`: copy it under another name between
runs.

## 7 bis · The strong baseline: the week 1 test

The jury will ask "why not just use a big model?". We measure it. A strong
model reads the whole paper, with the same rules as the system (NOT_FOUND
allowed, citation required), and with no retrieval or safeguards.

```bash
# the Groq key in .env (GROQ_API_KEY=...), then:
uv run python eval/eval.py --baseline --limit 5   # first 5 papers -> eval/report_baseline.json
uv run python eval/eval.py --mode rerank --limit 5   # the system, on the same 5
uv run python eval/compare.py                     # side by side, with intervals
```

The baseline model is set in the `baseline:` section of `config.yaml`
(default: `openai/gpt-oss-120b` on Groq), or on the fly:

```bash
REPROCHEM_BASELINE_MODEL=openai/gpt-oss-20b uv run python eval/eval.py --baseline --limit 5
# the floor: the small local model on the whole paper
REPROCHEM_BASELINE_BASE_URL=http://localhost:11434/v1 REPROCHEM_BASELINE_MODEL=qwen3:1.7b \
REPROCHEM_BASELINE_API_KEY_ENV=none uv run python eval/eval.py --baseline --limit 5 \
  --out eval/report_floor.json
```

What the test looks at, in this order:

1. **invented value when the field is missing**: the number that decides.
   The report lists every invented value, paper by paper.
2. **citation present in the paper**: does the quoted sentence really exist,
   or did the model rephrase or invent it?
3. **correct field**: if the baseline reaches 9 out of 10 without inventing
   anything, a big model has solved extraction, and the project's value moves
   to running the calculation. That result gets reported as it is.

Free tiers limit tokens per minute. A rejected paper (too long, quota) is
logged in `failed` and left out of the computation: rerun later, or switch
models. A paper beyond `max_context_tokens` is rejected rather than
truncated.

With the fake model, the whole chain can be tested offline:

```bash
uv run scripts/fake_llm.py &
REPROCHEM_BASELINE_BASE_URL=http://127.0.0.1:8111/v1 REPROCHEM_BASELINE_MODEL=fake \
REPROCHEM_BASELINE_API_KEY_ENV=none uv run python eval/eval.py --baseline
```

## 8 · Testing the plumbing without any model

```bash
uv run scripts/fake_llm.py &
REPROCHEM_BASE_URL=http://127.0.0.1:8111/v1 \
REPROCHEM_MODEL=fake REPROCHEM_API_KEY_ENV=none \
uv run python eval/eval.py --mode bm25
```

`fake_llm.py` is an OpenAI-compatible server written with the standard
library, which answers using regular expressions. Its PEP 723 header lets
`uv run` execute it with no environment at all. It is used in continuous
integration, and on November 3 if the network drops during the demo.

## 9 · The interface

```bash
uv run streamlit run app/ui.py
```

## 10 · Adding a dependency

```bash
uv add pandas                      # core
uv add --optional retrieval faiss-cpu
uv lock --upgrade-package openai   # upgrade a single dependency
```

`uv add` updates `pyproject.toml` **and** `uv.lock`. Always commit the two
together.

To regenerate the `requirements.txt` files for people who do not use uv:

```bash
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
uv export --format requirements-txt --no-hashes --no-emit-project --all-extras -o requirements-full.txt
```

Both files are **generated**. The source of truth is `uv.lock`.

## 11 · Distillation, end to end

A large model (the teacher, Claude through the API) labels the documents. A
local Qwen3 (the student) is trained with LoRA to reproduce its answers. The
benchmark compares the two on a gold set checked by hand.

```
documents ──► markdown ──► retrieved passages ──► teacher ──► filter ──► LoRA (MLX) ──► local student
                                                     │                                        │
                                      human gold set ┴──────────► benchmark ◄─────────────────┘
```

### Step 0 · Dependencies, once

```bash
uv add --optional ingest python-docx openpyxl          # .docx reports, .xlsx spreadsheets
uv add --optional train "mlx-lm; sys_platform == 'darwin'"  # LoRA on Apple Silicon
uv sync --all-extras
```

`uv add` writes the resolved version into `pyproject.toml` and `uv.lock`:
commit both together.

### Step 1 · Internal documents

```bash
mkdir -p data/internal/raw            # drop PDF, DOCX, XLSX, CSV, IPYNB files here
uv run python scripts/ingest_docs.py  # -> data/internal/md/ and data/internal/manifest.csv
```

All of `data/internal/` is ignored by git. Read three converted markdown files
before going further.

### Step 2 · The gold set, by hand

It never comes from the teacher, because its whole job is to grade the
teacher.

```bash
uv run python scripts/make_sheet.py --manifest data/internal/manifest.csv \
    --sheet data/internal/annotation_sheet.csv --sample 30
# annotate, then:
uv run python scripts/build_testset.py --manifest data/internal/manifest.csv \
    --sheet data/internal/annotation_sheet.csv --out data/internal/testset.jsonl
```

The public gold set (`eval/testset.jsonl`, the five priority papers) follows
the same path. Documents from a test set never go into training:
`make_sft.py` excludes them.

### Step 3 · The teacher labels

Put the key in `.env`: `ANTHROPIC_API_KEY=...`. Check the exact model ID in
the `teacher` section of `config.yaml`.

```bash
uv run python scripts/teacher_label.py --dry          # estimated tokens, no calls
uv run python scripts/teacher_label.py --limit 5      # small trial, read the outputs
uv run python scripts/teacher_label.py                # the whole public corpus
uv run python scripts/teacher_label.py --internal     # only if teacher.allow_internal: true
```

The teacher produces two things: one card per whole document
(`doc_cards.jsonl`, the fidelity reference) and one answer per field on the
passages the student will see (`passages.jsonl`, the training material).
Every call is cached, so a rerun costs nothing extra.

`--dry` gives about 19,000 input tokens per paper. Multiply by the model's
price before launching all 120.

### Step 4 · The training set

```bash
uv run python scripts/make_sft.py      # -> data/sft/train.jsonl, valid.jsonl
```

It prints what it dropped and why: citation missing from the passages, value
missing from its citation, teacher disagreeing with its own card. These counts
go into the report. Under 500 examples, label more documents
(`scripts/fetch_corpus.py --add`) before training.

### Step 5 · LoRA on the Mac

Qwen3 comes in 1.7B and 4B (there is no 3B). Start with 1.7B.

```bash
uv run mlx_lm.lora --model Qwen/Qwen3-1.7B --train --data data/sft \
    --iters 600 --batch-size 2 --num-layers 16 --learning-rate 1e-4 \
    --max-seq-length 4096 --mask-prompt \
    --adapter-path adapters/qwen3-1.7b-v1
```

`--mask-prompt` computes the loss on the answer only, as in the SFT class.
Keep an eye on the validation loss: if it rises while the training loss falls,
the adapter is overfitting, and you keep an earlier checkpoint. Depending on
the version, the command may also be written
`uv run python -m mlx_lm lora …`.

### Step 6 · Serving the student

`mlx_lm.server` exposes the same API as Groq or Ollama, so the rest of the
code stays as it is.

```bash
uv run mlx_lm.server --model Qwen/Qwen3-1.7B --adapter-path adapters/qwen3-1.7b-v1 --port 8080
REPROCHEM_BASE_URL=http://127.0.0.1:8080/v1 REPROCHEM_MODEL=default_model \
REPROCHEM_API_KEY_ENV=none uv run python scripts/check.py
```

If `check.py` cannot find `default_model`, copy the name shown in the list
into `REPROCHEM_MODEL`.

### Step 7 · The benchmark

Same gold set, same retrieval mode, four rows:

```bash
# 1. the teacher, cards already paid for, no calls
uv run python eval/eval.py --cards data/teacher/doc_cards.jsonl --label professeur

# the student, served by mlx_lm.server (step 6)
export REPROCHEM_BASE_URL=http://127.0.0.1:8080/v1 REPROCHEM_API_KEY_ENV=none REPROCHEM_MODEL=default_model
# 2. server started without --adapter-path
uv run python eval/eval.py --mode hybrid --label eleve-base
# 3. server restarted with --adapter-path
uv run python eval/eval.py --mode hybrid --label eleve-lora
unset REPROCHEM_BASE_URL REPROCHEM_API_KEY_ENV REPROCHEM_MODEL

# 4. the teacher on the same task as the student (passages), for the ceiling
REPROCHEM_BASE_URL=https://api.anthropic.com/v1/ REPROCHEM_MODEL=claude-opus-5-5 \
REPROCHEM_API_KEY_ENV=ANTHROPIC_API_KEY uv run python eval/eval.py --mode hybrid --label professeur-passages

uv run python eval/compare.py eval/report_*.json
```

Add `--testset data/internal/testset.jsonl` to do the same on the internal
documents. The "agreement with the teacher" row measures how faithful the
student is; the "correct field" row measures the truth. Read together, they
show whether the student also copies the teacher's mistakes.

A learning curve is worth a row in the report: train on 25%, 50% and 100% of
`train.jsonl` and plot the accuracy. If the curve is still climbing at 100%,
labeling more documents will pay off.

## What Qwen changes in the code

`qwen3` reasons by default. That triples the number of generated tokens and
sometimes puts the answer inside a `<think>` block. Two lines handle it:

- `config.yaml` → `disable_thinking: true` adds `/no_think` to the prompt.
- `app/pipeline.py` → `_json_block` strips `<think>…</think>` before looking
  for the JSON.

Setting `disable_thinking: false` and rerunning the evaluation makes an
interesting ablation for the report: does reasoning improve extraction, and
how much time does it cost?

## Troubleshooting

`scripts/check.py` tells apart three failures that the raw error lumps
together: **server unreachable** (nothing is listening), **server up but model
unknown** (it then lists the models actually being served), and **key
rejected**.

| Symptom | Likely cause |
|---|---|
| `serveur injoignable` | `ollama serve` is not running, or `base_url` is wrong |
| `serveur ok, modèle « … » inconnu` | the model has not been pulled: `ollama pull qwen3:1.7b`, or copy a tag from the list shown |
| `embeddings : modèle d'embedding absent` | `ollama pull bge-m3` |
| `VIRTUAL_ENV ... does not match the project environment` | another venv is active in the shell. uv ignores it and uses the project's own, so it has no effect. To silence the warning, run `deactivate` before calling uv |
| `No solution found` during `uv sync` | a pinned version does not exist for Python 3.12; rerun `uv lock` after fixing it |
| `uv sync` uninstalls rdkit and pyscf | a `uv sync` without `--extra`: rerun it with `--all-extras` |
| `{}` returned by the extraction | the model answered outside JSON; check `disable_thinking` |
| Everything comes out as `NOT_FOUND` | `abstain_threshold` is too high for BM25, whose scores are not on the same scale as the reranker's |
| The laptop heats up and slows down | switch to `qwen3:4b`, or offload to Groq |

The all-`NOT_FOUND` case deserves a measurement rather than a quick patch:
the threshold is calibrated in week 3, per retrieval mode, on the development
set.

## Two free ablations, already possible with the models pulled

1. **The model.** `qwen3:1.7b` against `qwen3:8b` on the same test set, with
   one environment variable as the only difference.
2. **The embedder.** `bge-m3:latest` against `nomic-embed-text:latest` in
   `dense` mode: this is experiment 2 from the October 7 lab, replayed on the
   project's data.

## Verified

Full chain run under uv with the fake model: the four retrieval modes,
extraction, compilation, and a real PySCF run through to convergence, with
`runnable` at 1.00 in 1.6 s per paper.
