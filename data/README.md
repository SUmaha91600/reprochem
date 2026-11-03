# Data

No paper and no internal document is versioned in this repository. This file
states where they come from, under which licence, and how they are prepared.

## Public corpus

| Source | What we take from it | Licence |
|---|---|---|
| arXiv (physics.chem-ph, cond-mat.mtrl-sci) | papers with a "computational details" section | the full text follows the `license` field of the submission; only CC-BY, CC-BY-SA and CC0 are kept |
| ChemRxiv | computational chemistry preprints | chosen by the authors; only CC-BY and CC-BY-SA are kept |
| PMC Open Access Subset | open-access chemistry papers | CC licences, bulk download allowed |

The licence filter runs before download: `scripts/fetch_corpus.py` reads the
`license` field from arXiv's OAI-PMH interface and discards anything that is
not explicitly redistributable. The retained identifiers are listed in
`data/corpus_manifest.csv`, which is versioned; the PDFs are not.

## Internal documents

Experiment reports (DOCX, PDF), tracking spreadsheets (XLSX, CSV) and
notebooks (IPYNB), dropped into `data/internal/raw/` and converted by
`scripts/ingest_docs.py`. The whole of `data/internal/` is ignored by git,
internal gold set included, because the citations it holds are confidential.

They are sent to the teacher's API only if `teacher.allow_internal` is true
in `config.yaml`, which presupposes the company's written agreement and a
reading of the provider's data retention policy. Otherwise the teacher labels
only the public corpus, and internal documents are read only by the local
student and the human annotator.

## Derived data

| Folder | Content | Versioned |
|---|---|---|
| `data/teacher/` | teacher answers and their cache | no |
| `data/sft/` | filtered training set (train, valid) | no |
| `adapters/` | student LoRA weights | no |
| `eval/testset.jsonl` | public gold set, annotated by hand | yes |

The gold set is never produced by the teacher, since its job is to grade it.
No document from a test set enters `data/sft/`.

## Personal data

None in the public corpus: author names from the metadata are not used.
Internal documents may contain operator names; anonymise them before
ingestion if the written agreement does not cover this point.

## Preparation

1. Every document is converted to markdown (`app/ingest.py`), keeping the
   headings.
2. Section-based chunking (measured better than fixed-size chunking in the
   7 October lab: 0.88 correct answers against 0.69).
3. For each field, three passages are retrieved; these are the passages the
   teacher labels and the student learns to read.

## Before building anything

Open ten converted documents and read the extracted text. Tables and
formulas come out badly, and that is exactly where the basis sets and
functionals are.
