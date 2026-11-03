# Licences

| Component | Role | Licence | Checked on |
|---|---|---|---|
| Claude (Anthropic API) | teacher | Anthropic commercial terms: check the reuse of outputs to train another model and the retention of submitted data | |
| Qwen/Qwen3-1.7B, Qwen3-4B | student | Apache-2.0 | |
| openai/gpt-oss-120b | strong baseline (optional) | Apache-2.0 | |
| BAAI/bge-m3 | embeddings | MIT | |
| BAAI/bge-reranker-v2-m3 | reranking (optional) | Apache-2.0 | |
| mlx-lm | LoRA training and serving | MIT | |
| pymupdf4llm / PyMuPDF | PDF conversion | AGPL-3.0: acceptable for an internal tool, to be reviewed before any distribution of the product | |
| python-docx, openpyxl | DOCX, XLSX conversion | MIT | |
| PySCF | computation | Apache-2.0 | |
| RDKit | chemistry | BSD-3-Clause | |
| Paper corpus | training and test data | CC-BY, CC-BY-SA or CC0 only | |
| Internal documents | training and test data | company property; written agreement required before any upload to the API | |

Each row is checked on the model or repository page, and dated. An unchecked
licence counts as an unknown licence.

The LoRA adapter inherits the constraints of both its sources: the licence of
the base model (Apache-2.0) and the terms of use of the teacher's outputs.
Both are cited in `docs/system_card.md`.
