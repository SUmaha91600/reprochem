# 2-minute pitch — ReproChem

Timing follows slide 21 of the kickoff. Read it aloud once with a timer before
class. The "measure" part is the one people always rush, and it is the part
that carries the project.

---

### 0:00 → 0:30 · The user and the problem

> A computational chemistry team piles up reports, spreadsheets, notebooks and
> papers. For every calculation, seven settings matter: functional, basis set,
> dispersion, solvent, charge, multiplicity, software.
>
> They are scattered across formats that look nothing alike. A large language
> model finds them well, but these documents are confidential, and across
> thousands of documents every call costs money.

**If someone cuts in:** the user has a name. It is the science team I work
with.

---

### 0:30 → 1:00 · What we are building

> We have a large model teach a small one. Claude reads public papers and
> authorised documents, and for each field it returns a value with the
> sentence that proves it. Its checked answers train, through LoRA, a
> 1.7-billion-parameter Qwen that runs on a laptop.
>
> In production only the small model reads the documents: nothing leaves the
> machine, nothing is billed, and a missing setting stays marked as missing.

---

### 1:00 → 1:20 · The data

> A hundred and twenty CC-BY papers, plus internal reports under written
> permission. Each document yields seven training examples; we aim for more
> than five hundred after filtering.
>
> And a gold set annotated by hand, which the large model never sees.

---

### 1:20 → 1:40 · How we measure it

> Three rows on that gold set: the teacher, the small model alone, the trained
> small model. Three measures: is the field right, how many values get invented
> when the document says nothing, and how closely the student follows the
> teacher.
>
> Target: the student within five points of the teacher, with no invented
> values.

---

### 1:40 → 2:00 · The risk and the plan

> The risk: the student copies the teacher's mistakes too. So the teacher is
> scored on the gold set before any training, and an answer we can't check
> against the text never enters the data.

---

### Closing line, because I don't have a team yet

> I'm looking for two or three people. There are three independent work
> streams: ingestion and the gold set, the teacher and the training data, and
> the LoRA with the benchmark. None of them needs any chemistry: the domain
> boundary is a seven-field schema, and I provide it.

---

## Likely questions, with short answers

| Question | Answer |
|---|---|
| "Why not use the large model directly?" | Three reasons: internal documents stay on the machine in production, cost per document at high volume, and offline use. What we lose in quality, we measure: that is the teacher row of the benchmark. |
| "What if the teacher is wrong?" | It is scored on the human gold set before any training. Its answers are filtered: quote missing from the text, value missing from its own quote, or disagreement with its own reading of the whole document. Every rejection is counted in the report. |
| "Why not train on your hand annotations?" | They take a quarter of an hour per document. Thirty annotated documents are enough to measure and too few to train. The teacher supplies the volume, the human supplies the truth. |
| "How many examples do you need?" | The course recommends more than five hundred for a LoRA. A learning curve at 25, 50 and 100 % shows whether labelling more would pay off. |
| "Why Qwen3-1.7B?" | Apache-2.0 licence, trainable on a Mac with MLX, fast locally. The 4B version is a comparison row if memory allows. |
| "Are you allowed to train on Claude's outputs?" | The provider's terms are checked and cited in the system card. Internal documents only go to the API under written permission, and the code refuses otherwise. |
| "What if the information isn't in the document?" | The field comes out as NOT_FOUND. Teacher and student are both judged on it: an invented value on a missing field is the first measure in the report. |
| "What breaks if you change the model?" | One line in `config.yaml`. The evaluation reruns with one command and reports the difference. |
