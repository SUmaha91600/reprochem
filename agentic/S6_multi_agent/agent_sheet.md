# ReproChem · Agent sheet (complete, S1 to S6)

ReproChem turns the computational details of a chemistry paper into a PySCF job that runs.

## 1. Five real requests: workflow or agent? (S1)

| # | Request | Decision | Justification (one sentence) |
|---|---|---|---|
| 1 | Read the Computational Details of this paper and give me the 7 fields as JSON. | Workflow | The steps never change (find the methods, extract into a strict schema, mark empty fields). |
| 2 | Turn this protocol (wB97X-D/def2-TZVP, SMD water, charge 0, singlet) into a ready-to-run job for my geometry. | Workflow | Compilation is a template plus a validator, so a loop only adds cost. |
| 3 | For these 20 papers, tell me which ones report all 7 fields and which ones omit charge, multiplicity or solvation. | Workflow | The same extraction runs on independent papers and the results are aggregated. |
| 4 | Reproduce the CREST conformer ensemble of the paper for my molecule and give the global minimum at their level. | Agent | Key details are often missing, so the agent must search, decide, run, check and retry, with approval before each calculation. |
| 5 | My relative energies differ from the paper by up to 2 kcal/mol: find out why. | Agent | The next check depends on the last result, and a wrong read-only step is cheap. |

## 2. Tools (S2, S3)

| Tool | Access | What it does |
|---|---|---|
| `parse_document` | read | Markdown paper to section-based passages. |
| `extract_method_card` | read | 7 settings with a cited quote each, or NOT_FOUND. Uses the distilled extraction model. |
| `compile_and_validate_job` | **write** | Method card + molecule to a PySCF job, then runs it. |

The parameters and outputs are Pydantic models (`app/tool_schemas.py`). The tools are exposed by an MCP server (`server.py`). The S5 agent adds three small tools on top of them: `read_method_passages`, `correct_field` (the correction must cite the paper) and `set_user_molecule`.

## 3. Control strategy and memory (S4)

- **Strategy: reflection.** After a failed compile, the agent must find the field that causes the error before it tries again. It corrects a field only with a quote, never changes a value only to please the compiler, and stops after 3 attempts.
- **Approval:** the write tool runs only after the user approves the card (`--yes` in tests).
- **Short-term memory:** the context of one request, plus a journal of attempts. Deleted at the end of the request.
- **Long-term memory:** `lessons.md`, a skill file of lessons on the tools and on how to read a paper. No paper, molecule or result is kept. A reading lesson goes into the prompt only after the gold set or a person confirms it.

## 4. Framework (S5)

LangGraph `StateGraph` with three nodes: `agent` (model with tools), `tools` (MCP calls) and `reflect` (after a failed compile). Results on the 5 requests: `agentic/S5_langgraph/runs.md`.

## 5. One agent or several? (S6)

**Decision: one agent.**

| Question | Answer for ReproChem |
|---|---|
| Can the work be split into independent parts that run in parallel? | No. Each step needs the result of the step before (passages, then card, then job). Request 3 runs the same extraction on several papers, but that is a parallel workflow, not several agents. |
| Do the parts need different expertise or different context? | No. The 5 tools fit in one prompt, and all of them work on the same card. |
| Is the context too large for one agent? | No. The agent sees the method passages (about 1,200 words), never the whole paper. |
| Does a second agent add a check that the first one cannot do? | Not today. The checks are deterministic (quote in the paper, Pydantic schema, PySCF run), and they are more reliable than a second model. |
| What does a second agent cost? | More model calls and tokens (the free API quota is already a limit), more latency, and errors that pass from one agent to the other. |

The only specialist is already a tool: the distilled extraction model runs inside `extract_method_card`. It is a model with one job, called by the agent, not an agent that decides.

**When we would change:** if ReproChem gets the request 4 tools (conformer search, energy comparison), a separate "calculation" agent could run long jobs in parallel, while the main agent reads and checks the papers. That split is based on a real need (long parallel jobs), not on the number of steps.
