# Preparing for questions — ReproChem

Each answer fits in 30 seconds. The numbers come from the repository. The
benchmark figures are in `docs/results.md`: reread them the night before.

## The problem and the technical choice

**Why distillation instead of calling Claude?**
Three reasons. A team's documents are confidential, so they must stay on the
machine. Once the student is trained, the cost per document drops to zero.
And the demo works offline. We used the teacher only once, in the Claude
desktop app, with no API.

**Why not just use RAG with a large model?**
That is our teacher. It sets the ceiling in the benchmark. The student uses
exactly the same pipeline, with the same passages and the same messages.
Only the model changes. So we measure what we lose by going local.

**Why is the model prompt in French?**
The papers are in English. We wrote the instruction prompt in French early
on, and the student was trained on that exact prompt. Translating it now
would mean evaluating the model on a prompt it never saw. For a future
retraining, it is a one-line change.

**Why Qwen3-1.7B?**
It has an Apache-2.0 license. It fits in memory on a Mac for LoRA training
and for inference, and MLX supports it natively. The 4B is the next step if
memory allows.

**Why these seven fields?**
Without these settings, you cannot rerun a geometry optimization:
functional, basis set, dispersion, solvation, charge, multiplicity,
software. Charge and multiplicity are required to compile a calculation. The
others change the result.

## The data

**Where does the training data come from?**
From 120 arXiv papers under CC-BY, CC-BY-SA or CC0, filtered on license
before download. Claude answered field by field, on the passages the student
will see: 840 answers. No internal document was used.

**The teacher ran in Claude desktop, without an API. Is that
reproducible?**
Yes. The 840 labels are versioned in `data/teacher/labels/`, together with
the exact tasks the teacher received (`data/teacher/tasks/`, the same
passages as the student). Anyone can replay these tasks in Claude, or through
an API if they have one (`scripts/teacher_label.py`, optional). And training
can be redone from `data/sft/` without touching the teacher.

**How much does the teacher cost?**
Nothing was billed: it ran on the Claude subscription. For comparison, the
same job through the Anthropic API would cost about $5 for 120 papers
(≈ 1.2 M input tokens, estimated at 4 characters per token).

**Your data is very imbalanced. How do you handle that?**
90% of the kept answers are `NOT_FOUND` (665 out of 735). Many papers do not
describe a DFT optimization, or BM25 does not retrieve the right sentence.
Without a fix, the model would learn to always answer `NOT_FOUND`. We bring
that share down to 50%. Each positive answer is repeated three times, with
different distractor passages. That gives 510 training examples.

**Doesn't the augmentation cause overfitting?**
The risk is real: these are 70 positives seen in three contexts. That is why
validation uses 10 disjoint papers, and the gold set was never seen. The
validation loss curve is in `results.md`.

**Leakage between training and test?**
The 15 gold set papers are excluded by ID in `make_sft.py` (105 answers
dropped for this reason). Validation also uses different papers from
training.

**How is the gold set built, and why not by Claude?**
If Claude annotated the test set, we would be measuring the teacher against
itself. A regex pre-annotation proposes a value and a sentence. A human
validates each field (OK, Fix, NOT_FOUND, Out of scope). A second manual pass
covered 27 ambiguous cases, and each decision was rechecked in the paper with
its source sentence. This pass removed two papers where the authors do not
optimize the geometry themselves (13 papers, 91 fields). The rule: the
authors' own geometry optimization, the last one if there are several, with
the value copied exactly as written.

## The system

**Why 200-word passages, and why 3?**
The student has a short context and gets lost in long text. A longer section
is cut into windows that keep its heading. Three 200-word passages fit with
the prompt under ~2,200 tokens, well below the training limit of 3,072.
Splitting by section beat fixed-size splitting in the October 7 lab (0.88
against 0.69).

**Why BM25 and not embeddings?**
The settings are exact terms ("B3LYP", "def2-TZVP"). BM25 finds them well,
needs no model, and makes the demo more robust. The limit is known: on a
French text, English queries do not find the passage (red team R5).

**What happens when the information is not in the document?**
The model answers `NOT_FOUND`. Half of its training examples are this case.
The "invented value" metric measures exactly that. And if a required field is
missing, compilation is blocked and the reason is shown.

**How do you know the citation is not invented?**
Two checks. The quoted sentence must exist in the paper (`quote_in_paper`),
and the value must appear in that sentence (`citation_verified`). During
training, any teacher answer that fails these checks is thrown out.

**LoRA hyperparameters?**
The mlx-lm defaults: rank 8, scale 20, no dropout, Adam. On the last 16
layers, learning rate 1e-4, two epochs. The loss is computed on the answer
only (`--mask-prompt`), seed 0. On our 16 GB Mac: 4-bit base model (QLoRA),
batch size 1, 1,020 iterations. With batch 2 and no quantization, the logits
(a 152k-token vocabulary) filled the memory and the machine started
swapping.

**Did your training crash?**
Yes, and we learned from it. The first run hit a NaN loss around iteration
105. The cause: 4 of the 510 examples had a prompt longer than 3,072 tokens,
the maximum length we had set. Once truncated, they had no answer tokens
left. With `--mask-prompt`, the loss is then 0/0, and a single NaN spreads to
every weight through Adam. We saw it in the log, confirmed it by counting
tokens, then fixed it: maximum length 4,608 (the longest example is 4,551
tokens), plus a script (`check_adapter.py`) that automatically keeps the last
checkpoint without NaN.

**What breaks if you change the model?**
The prompt format is generic (chat messages), so the pipeline still works.
But the LoRA adapter is tied to the base model, so you have to retrain. That
takes less than an hour, because the data is versioned. `/no_think` is
specific to Qwen3. The abstention thresholds depend on the retriever's score
scale. The model has no effect on them.

## The evaluation

**How do you compute your metrics?**
Per field, on the 91 fields of the gold set. Accuracy is measured after
normalizing the notation ((d,p) = \*\*, GD3BJ = D3(BJ)). Hallucination is
measured on absent fields only. Confidence intervals come from a bootstrap:
we resample the fields 2,000 times with replacement and take the 2.5th and
97.5th percentiles.

**Isn't 13 papers too few?**
Yes, and we say so. The intervals are wide, and two close systems cannot be
told apart. We chose a gold set validated by hand over a large one annotated
automatically, whose accuracy we could not guarantee.

**What is your baseline?**
The same Qwen3-1.7B without LoRA, on the same passages. The gap from base to
LoRA is the effect of distillation. The gap from LoRA to teacher is what is
left to gain.

**Where do your errors come from?**
We separate retrieval from generation. A retrieval error means the value is
not in the 3 passages, so no model can find it. A generation error means the
value was there and the model got it wrong. `results.md` gives the retrieval
ceiling field by field.

## Security and limits

**Prompt injection?**
Document text is treated as data. Known patterns are neutralized before the
teacher and before the student. The red team shows the limit: an injection
without a keyword gets past the filter (R2). The real protection is that the
output is a schema-validated value with a citation anyone can check. The
filter also has false positives: 13 in the corpus, all on "system:".

**Internal documents?**
The code refuses to send them to the teacher while `allow_internal` is false,
and we checked it. Once the student is trained, they never leave the machine.

**Licenses?**
Papers under CC-BY, CC-BY-SA, CC0. Qwen3 under Apache-2.0. Anthropic's terms
on using outputs to train another model must be reread before any commercial
use of the adapter.

**What if we asked you to put it in production?**
Human review of the values (the citation makes it quick), a larger gold set,
bilingual retrieval, and a real, authorized internal document to measure how
well it transfers beyond papers.

## What everyone must be able to redo alone

- Restart the demo: `bash scripts/demo.sh`.
- Explain a line of `app/pipeline.py`, especially `extract_messages` (why a
  single function serves the teacher, the student and training).
- Read table 1 of `results.md` and say whether a gap is proven.
