# ReproChem

> Extracts the seven settings of a geometry optimisation in computational
> chemistry (functional, basis set, dispersion, solvation, charge,
> multiplicity, software), each with the sentence that proves it, using a
> small local model trained by distillation from a large one.

## 1 · User and problem

- **User.** A computational chemistry team that piles up reports,
  spreadsheets, notebooks and papers, and has to find, compare or audit the
  settings of its calculations.
- **Today.** Someone rereads everything by hand, or the documents go to a
  large model through an API. That works, but the documents are confidential
  and every call costs money.
- **If it works.** A local model, offline and with no per-document cost,
  returns each setting with its citation. A setting missing from the document
  is shown as missing (`NOT_FOUND`) and is never guessed.

## 2 · What the system does

```
document ─► sections ≤ 200 words ─► BM25, 3 passages per field ─► local student ─► cited card
                                                               (Qwen3-1.7B + LoRA)     │
                                                                    PySCF compilation ◄┘
```

- **Input.** A paper (markdown or plain text). DOCX reports, XLSX and CSV
  spreadsheets, and IPYNB notebooks go through `app/ingest.py`.
- **Output.** A method card: for each field, the value and its source
  sentence, or `NOT_FOUND`. When the mandatory fields are present, it also
  yields a schema-validated spec and a PySCF script tested on a toy molecule
  (water).
- **Distillation.**
  1. The teacher, Claude, answers field by field on **exactly** the passages
     the student will see (`scripts/export_teacher_tasks.py`). 120 papers ×
     7 fields = 840 answers, produced in the Claude desktop application
     (Cowork), with no key and no API call. `scripts/teacher_label.py` can
     optionally redo them through an API.
  2. Filtering (`scripts/make_sft.py`): a citation missing from the passages,
     a value missing from its citation, or a paper from the gold set → rejected.
     NOT_FOUND is brought down to 50%; each positive answer is repeated three
     times with different distractor passages. Result: 510 training examples
     and 50 validation examples, drawn from disjoint papers.
  3. The student, Qwen3-1.7B, is trained with LoRA using MLX on the Mac
     (`scripts/mac_train.sh`), with the loss computed on the answer only.
- **Why these models.** The teacher is the strongest one available, and its
  answers set the student's ceiling. The student fits on a laptop: in
  production nothing leaves the machine, and the demo runs without a network.

## 2 bis · Voice module: ReproChem Lens

You ask out loud ("explain the BP86 basis set to me in a video"); the system
answers with an animated diagram and, on request, a narrated video in five
acts. Ten verified concepts cover the seven fields of the card; a false
premise is corrected before the explanation starts. `bash scripts/lens.sh`.
Details, demo limits and target version: `docs/LENS.md`.

## 3 · Running it (Apple Silicon Mac)

```bash
uv sync                                    # core, from uv.lock
bash scripts/mac_train.sh                  # student LoRA, 30 to 60 min
bash scripts/mac_bench.sh                  # benchmark on the gold set, 20 to 30 min
bash scripts/demo.sh                       # the demo in the browser
uv run python scripts/retrieval_ablation.py # chunk size and retriever, no model
uv run --with matplotlib python scripts/figures.py   # every figure, from the result files
```

The gold set comes from `data/gold_review.xlsx`, validated by hand
(`scripts/gold_from_review.py`). Step-by-step guide, extras, troubleshooting:
`RUN.md`. Without a Mac, the older Ollama path is still available (`RUN.md`,
sections 1 to 9).

**Reproducibility.** `uv.lock` is authoritative. The teacher labels
(`data/teacher/`) and the training set (`data/sft/`) are versioned, so
training can be rerun without paying the teacher again. Fixed seed
(`--seed 0`), greedy decoding (temperature 0).

## 4 · Data

`data/README.md` and `docs/licences.md`. 120 arXiv papers under CC-BY,
CC-BY-SA or CC0 licences (`data/corpus_manifest.csv`). The papers themselves
are not versioned; no internal document was used for this submission.

## 5 · Evaluation

Gold set: 15 papers held out from training, 13 of which were kept after
validation (91 fields). They were pre-annotated by a rule-based extractor
(`scripts/preannotate.py`), then validated by hand in two passes
(`data/gold_review_edited.xlsx`, `data/gold_corrections.xlsx`).

Three rows, all fed the same BM25 passages:

| Row | What it is |
|---|---|
| `teacher` | Claude's labels on the gold set papers |
| `student-base` | Qwen3-1.7B without LoRA: the baseline |
| `student-lora` | Qwen3-1.7B + distilled LoRA: the delivered system |

Results on the 13-paper gold set (95% bootstrap intervals):

| | base | LoRA (delivered) | teacher |
|---|---|---|---|
| correct field | 0.56 [0.46 – 0.67] | **0.71 [0.63 – 0.80]** | 0.81 [0.74 – 0.89] |
| invented value when absent ↓ | 0.26 [0.12 – 0.40] | **0.07 [0.00 – 0.16]** | 0.02 [0.00 – 0.07] |
| seconds per paper | 18.1 | 19.8 | — |

Distillation gains +0.15 [+0.07, +0.25] correct fields (paired) and closes
61% of the base → teacher gap. Figures: `docs/figures.md`.

The figures, with 95% bootstrap intervals, are in `docs/results.md`
(generated by `scripts/results_md.py`, never copied by hand) and
`eval/benchmark.txt`. Analysis: `docs/evaluation_report.md`. System card:
`docs/system_card.md`. Red team: `docs/red_team_log.md`.

## 6 · AI tools used

| Tool | Used for |
|---|---|
| Claude (Cowork) | teacher for the distillation (840 labels); writing and reviewing the code, scripts and documentation; help preparing the second pass of the gold set |
| Qwen3-1.7B | student, the production model |

Every team member must be able to explain any line of this repository,
including the lines an assistant wrote.

## 7 · Team

| Member | Main role | Also worked on |
|---|---|---|
| | ingestion and gold set | |
| | teacher and training data | |
| | LoRA and benchmark | |
| Sutharsan Mahadevan | evaluation and safety | architecture |

## 8 · After 3 November

`parse`, `retrieve`, `extract`, `compile_spec` and `validate` in
`app/pipeline.py` already have the granularity of agent tools. In December,
the student becomes the core of an agent that reads a new report, flags
missing settings, launches the calculation and compares the result with the
reported value.
