# System card — ReproChem

**Purpose.** Extract from a computational chemistry document the seven
settings of the geometry optimisation: functional, basis set, dispersion,
solvation, charge, multiplicity, software. Each value is returned with the
sentence that proves it; a setting the document does not give comes out as
`NOT_FOUND`. The production model is a small local model, trained by
distillation from a large one.

**Users.** A computational chemistry team that wants to find, compare or audit
the settings of its calculations without sending its documents to an API.

**Out of scope.** Producing a publishable result without human review.
Periodic systems, post-Hartree-Fock methods, protocols that appear only in
figures. Spreadsheets holding several calculations with different settings
(one card per document cannot tell them apart).

**Models.**
- Teacher: Claude (Anthropic). The 840 training labels (120 papers ×
  7 fields) were produced by Claude in the desktop application (Cowork), with
  no key and no API call, from the files in `data/teacher/tasks/`: for each
  field, exactly the passages the student will receive.
  `scripts/teacher_label.py` can optionally do the same thing through an API.
- Student: Qwen3-1.7B (Apache-2.0) + LoRA, trained and served locally with
  MLX on an Apple Silicon Mac. This is the production model.
- Retrieval: BM25 over sections of at most 200 words, three passages per
  field. No embedding model is needed.

**Data.** 120 arXiv papers under CC-BY, CC-BY-SA or CC0 licences, filtered on
licence before download (`data/corpus_manifest.csv`). No internal document was
used for this submission. The pipeline for them is ready
(`scripts/ingest_docs.py`), and the code blocks any upload to the teacher as
long as `teacher.allow_internal` is false. No personal data.

**Gold set.** 15 papers held out from training, 13 kept after validation
(91 fields). Pre-annotated by a rule-based extractor
(`scripts/preannotate.py`), then validated by hand in two passes, the second
one on the ambiguous cases. It is the only ground truth of the benchmark.

**Evaluation.** `docs/evaluation_report.md`. Per-field accuracy,
hallucination (a value returned where the gold set says `NOT_FOUND`),
agreement with the teacher, citation present in the document; 95% bootstrap
confidence intervals.

**Safety.**
- Document text is treated as data: instruction patterns are neutralised
  before the teacher and before the student alike (`app/guardrails.py`).
- A teacher label whose citation is not in the passages, or whose value is not
  in its citation, does not enter training.
- Sending internal documents to the API is refused without written
  authorisation.
- Cost guard before any PySCF calculation.
- Red team: `docs/red_team_log.md`.

**Known limitations.** The student learns whatever teacher errors slip past
the filter. The gold set is small (91 fields), so the confidence intervals are
wide, and they show it. 88% of the teacher's answers are `NOT_FOUND`, because
many papers in the corpus do not describe a DFT optimisation or BM25 fails to
surface the right passage. The training set is rebalanced to 50%, and the
positive examples are augmented by swapping the distractor passages.

**Licences and terms.** `docs/licences.md`. Anthropic's terms on reusing
outputs to train another model must be reread and cited before any commercial
use of the adapter.

**Contact.** Sutharsan Mahadevan — aivancity PGE 5.
