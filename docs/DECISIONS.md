# Design decisions

Each choice, what we compared it with, and the measurement that settled it.
Every number comes from a file in this repository; the source is given on each
line. Gold set: 13 papers, 91 fields, 43 of them absent from the paper.

## 1 · A small local student, taught once by a large model

- **Choice.** Qwen3-1.7B, 4-bit, with a LoRA adapter, running on the laptop.
  Claude labelled the training data once.
- **Why.** The target documents are confidential and numerous: an API sends
  them out and charges per call. Reading by hand needs an expert each time.
- **Measured.** Correct fields 0.56 (base) → 0.71 (LoRA), teacher 0.81: the
  student closes 61 % of the gap. Paired gain +0.15 [+0.07, +0.25].
  Invented values on absent fields 0.26 → 0.07. (`docs/results.md`,
  `eval/report_*.json`)
- **Cost.** About 20 s per paper on the Mac; nothing per document.

## 2 · Training setup

- **Choice.** QLoRA with MLX: base model frozen in 4 bits; LoRA rank 8, scale 20,
  16 layers, learning rate 1e-4, 1,020 iterations, max-seq 4,608, loss on the
  answer only (`--mask-prompt`), seed 0.
- **Why.** It fits a 16 GB Mac: peak memory 5.1 GB. Only 4.98 M of 1,720 M
  weights are trained (0.29 %).
- **Measured.** Validation loss 2.237 → 0.169. A first run with max-seq 3,072
  broke at iteration 110 (prompts longer than the limit leave no answer token,
  so the loss is 0/0). (`logs/train.log`)

## 3 · Which teacher answers to keep

- **Choice.** An answer is kept only if its quote is in the passages and its
  value is in its quote; gold-set papers are removed; half of the examples
  are `NOT_FOUND`; positive examples are repeated 3 times with distractor
  passages. (`scripts/make_sft.py`)
- **Why.** Refusing to invent is the skill that matters most here: a wrong
  setting makes someone rerun a calculation that never existed.
- **Limit.** The effect of the 50 % balance is not isolated: we never trained
  without it.

## 4 · BM25 rather than embeddings

- **Choice.** BM25, 3 passages per field.
- **Compared with.** bge-m3 embeddings, and the two fused (reciprocal rank fusion).
- **Measured.** Recall@3 on the 48 present fields: BM25 0.90, bge-m3 0.73,
  fusion 0.79. Paired BM25 − bge-m3: +0.17 [+0.04, +0.31]. Basis-set names
  are where embeddings fail: 11/12 for BM25 against 8/12.
  (`docs/retrieval_ablation.md`)
- **Why it holds.** Settings are written as exact notation ("6-311++G(d,p)",
  "D3(BJ)"); lexical matching keeps them apart, embeddings blur them.

## 5 · Sections of at most 200 words

- **Measured.** Recall@3 is 0.90 from 150 to 300 words and 0.94 at 400. At 200
  words the longest prompt is 2,633 tokens; at 400 it is 4,862, beyond the
  4,608 used in training, and the median prompt grows by 43 %.
  (`docs/retrieval_ablation.md`)
- **Why.** 400 words finds 2 more fields out of 48, inside the noise, for
  longer prompts on every field; it would also mean relabelling and retraining.

## 6 · A gold set built without the teacher

- **Choice.** A rule-based pre-annotation, then every field checked by hand in
  the paper, twice for the 27 doubtful ones. (`scripts/preannotate.py`,
  `scripts/gold_from_review.py`, `data/gold_*.xlsx`)
- **Why.** Scoring against Claude alone would only measure imitation. Claude
  itself scores 0.81 on this set, κ 0.73.

## 7 · Statistics

- **Choice.** 95 % bootstrap intervals (2,000 resamples, seed 0) on every rate;
  paired differences on the same fields; Cohen's κ for agreement.
  (`eval/eval.py`, `scripts/figures.py`)
- **Why.** With 13 papers a 5-point gap can be chance, and with 47 % absent
  fields two systems agree often by luck; κ removes that share.

## 8 · Never guess

- **Choice.** No citation, or a retrieval score under the configured threshold, means `NOT_FOUND`; a quote
  that is not in the passages is flagged on screen; a value over 60 characters
  is refused; a PySCF script is compiled only when the four mandatory settings
  are present and on the whitelist. (`app/guardrails.py`, `app/pipeline.py`,
  `app/schema.py`)

## 9 · Security by entry point

- **Choice.** The app is offline, so the threats are what comes in with a
  document, what goes out to an API, and the files we download. 20 attacks,
  mapped to the OWASP Top 10 for LLM Applications (2025), replayed by
  `scripts/security_eval.py`; every protection is marked `SAFEGUARD` in the code.
- **Measured.** 17 blocked, 2 detected, 1 passed: success rate 1/20, exact 95 %
  interval [0.1 %, 24.9 %]. The new guards change 1 of 7,610 ordinary passages.
  (`docs/security_results.md`, `docs/SAFEGUARDS.md`)
- **Known limit.** Keyword stuffing (B2) can push the real passage out of the
  top 3.

## 10 · Lens: hand-checked explanations

- **Choice.** Ten concepts written and checked by hand (130 nodes, 35
  references); a keyword router with a premise check chooses one; the video is
  the same diagram narrated in five acts by the system voice. (`app/lens/`)
- **Why.** A generated diagram can look right and be wrong.
- **Measured.** On the exact text, the router opens the right concept for
  20/20 sentences and catches 6/6 false premises, with 0 false alarms
  (`docs/lens_router.md`). These sentences were written by us; the microphone
  test with other speakers (`app/lens/voicetest.html`) is still to run.
- **Today and next.** Speech recognition is the browser's (needs the network);
  the next version runs Whisper locally so audio stays on the machine.

## 11 · Data

- **Choice.** Only open papers: 120 arXiv papers in physics.chem-ph, licences
  CC-BY (109), CC0 (7), CC-BY-SA (4). No internal document was used; the code
  refuses to send one to an API (`allow_internal: false`), and anonymises
  before any external call. (`data/corpus_manifest.csv`, `docs/licences.md`)

## 12 · A second teacher

- **Measured.** Claude Fable on the same passages: correct 0.78 against 0.81,
  paired −0.03 [−0.09, +0.01], κ between the two teachers 0.86. The limit is
  what the passages contain more than which teacher reads them.
  (`eval/report_teacher-fable.json`)

## 13 · The application

- **Choice.** One HTML page served by a small standard-library server on
  127.0.0.1 (`app/server.py`, `scripts/web.sh`); the model runs in the same
  process, one request at a time.
- **Why.** No extra dependency, nothing reachable from outside the laptop, and
  the extraction, its passages, Lens and the attacks in one place.
