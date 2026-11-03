# Safeguards

Every protection in the code carries a comment starting with `SAFEGUARD Sx`: search the repository for **SAFEGUARD** to see them all, in place. The attacks that test them are replayed by `scripts/security_eval.py` (results: `docs/security_results.md`).

| # | Safeguard | OWASP LLM 2025 | Where | Tested by | What it does |
|---|---|---|---|---|---|
| S1 | hidden characters and look-alike letters | LLM01 | `app/guardrails.py` | A3, A4, B1 | Zero-width characters are removed and Cyrillic/Greek look-alikes inside Latin words are repaired before anything else. |
| S2 | fake chat turns and control tokens | LLM01 | `app/guardrails.py` | A5 | `<\|im_start\|>` … `<\|im_end\|>` written in a document is removed with its content; our own `<sources>` tags cannot be closed from inside. |
| S3 | injection phrases, whole sentence removed | LLM01, LLM07 | `app/guardrails.py` | A1, A6 | A matching sentence is dropped entirely, so the value it smuggles in ("... report PBE0") never reaches the model. |
| S4 | instructions addressed to a machine, no keyword | LLM01 | `app/guardrails.py` | A2 | "Note for automated extraction tools: ..." is caught by its grammar, not by a keyword list; 0 hits on 7,610 normal passages. |
| S5 | documents are data, never instructions | LLM01 | `app/pipeline.py` | A1-A6 | Every passage goes through scrub() and is wrapped in `<sources>`; the system prompt is a separate message the document cannot edit. |
| S6 | bounded context | LLM10 | `app/pipeline.py` | C4 | A passage is cut at 8,000 characters and a title at 300: a 5 MB document still gives prompts of about 12,000 characters. |
| S7 | a value is a setting, not a paragraph | LLM07 | `app/pipeline.py` | A6 | Any answer over 60 characters (a leaked prompt, a pasted paragraph) becomes NOT_FOUND. |
| S8 | citation check on every answer | LLM09 | `app/pipeline.py` | B3 | The quote must be in the passages and the value in the quote; otherwise the screen says 'quote not found, check by hand'. |
| S9 | abstention | LLM09 | `app/guardrails.py` | gold set: invented values 26% -> 7% | Without a citation or with a weak retrieval score, the field is NOT_FOUND: no guess. |
| S10 | typed schema, whitelists and bounds | LLM05 | `app/schema.py` | C1 | Only known functionals and basis sets compile; charge and multiplicity are bounded integers; anything else is refused. |
| S11 | values enter the script as quoted strings | LLM05 | `app/compile_pyscf.py` | C1 | Every value is inserted with repr(): code inside a value stays an inert string (checked with ast in security_eval.py). |
| S12 | compute cost gate | LLM10 | `app/guardrails.py` | C3 | A job whose estimated basis functions exceed config.yaml compiler.max_basis_functions is refused before it starts. |
| S13 | model output shown as text only (Streamlit) | LLM05 | `app/guardrails.py` | C2 | Markdown in a value is escaped: `![x](https://...)` is displayed, never fetched. |
| S13 | model output shown as text only (HTML app) | LLM05 | `app/web/index.html` | C2 | Every value from the model or a document is written with textContent, never parsed as HTML. |
| S13 | link text shown as text only (Lens) | LLM05 | `app/lens/lens.js` | D2 | The `?q=` text goes through the router and is displayed with textContent: an `<img onerror>` stays characters. |
| S14 | closed voice router | LLM01, LLM06 | `app/lens/router.js` | D1 | A sentence can only open one of 10 hand-checked concepts, or nothing: no model, nothing to jailbreak. |
| S15 | internal documents never sent to an API | LLM02 | `scripts/teacher_label.py` | E1 | Refused unless config.yaml teacher.allow_internal is set, which requires written authorisation. |
| S16 | pseudonymisation before any API call | LLM02 | `scripts/teacher_label.py` | E2 | Authors, e-mails, phones, ORCID, URLs and names are replaced; the mapping stays on the machine (app/anonymize.py). |
| S16 | pseudonymisation | LLM02 | `app/anonymize.py` | E2 | 1,097 identifiers replaced on the 120 papers; 48/48 gold values kept, recall@3 unchanged. |
| S17 | no key ever published | LLM02 | `scripts/publish_github.sh` | E3 | The push is refused if anything looks like an API key or if .env is staged; .env is in .gitignore. |
| S18 | integrity of model, adapter and prompts | LLM03 | `scripts/integrity.py` | F1 | SHA-256 of the evaluated files; a swapped adapter or an edited prompt is reported and the run should stop. |
| S19 | poisoned training labels rejected | LLM04 | `scripts/make_sft.py` | B4 | A teacher answer is kept only if its quote is in the passages and its value in its quote. |
| S19 | gold papers never trained on | LLM04 | `scripts/make_sft.py` | gold set integrity | Every gold-set paper is excluded from the training data, so the score measures generalisation. |
| S20 | local server only | LLM10 | `app/server.py` | server test | Bound to 127.0.0.1: nothing outside the laptop can reach the app. |
| S20 | no free path, bounded upload, one model call at a time | LLM10 | `app/server.py` | server test | Paper ids are checked against a pattern, static files cannot leave their folder, uploads stop at 5 MB. |
| S21 | audit log of injection attempts | LLM01 | `app/pipeline.py` | docs/injections.log | Every neutralised attempt is written with its paper id, for review. |

Known limit: keyword stuffing (attack B2) can push the real passage out of BM25's top 3; no safeguard stops it yet. Possible fix: remove near-duplicate passages and flag a passage scoring far above the others.
