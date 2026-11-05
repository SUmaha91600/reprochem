# ReproChem · S4: control strategy and memory

1. **Strategy: reflection.** The path is fixed (parse, extract, compile), so the agent does not plan. After each step, the agent model reviews the method card with the lessons and the journal, corrects fields, and tries again. Each correction must cite a sentence that is in the paper and that contains the new value. The agent never changes a value only to make the compiler accept it, and never changes a value that the user gave. The loop stops after 3 compile attempts or when a correction does not change the card.
2. **Tools through MCP, approval before writing.** The agent is an MCP client of `server.py` (S3). `parse_document` and `extract_method_card` (read) run freely. `compile_and_validate_job` (write, runs PySCF) runs only after the user approves the card. A missing charge or multiplicity stops the loop with a question to the user, never with a guess.
3. **Short-term memory: one request.** The context plus a journal of attempts (step, result, error, correction). The agent uses it to not send the same card twice and to count the attempts. It is deleted at the end of the request.
4. **Long-term memory: `lessons.md`, a skill file.** It keeps how to use the tools and how to read a paper, never a paper, a molecule or a result: the agent works on one document at a time, so there is nothing to keep per document. The file is injected in the agent prompt at each request and kept in git, so a person can read and correct it.
5. **What becomes a lesson, and who confirms it.** Only a failure that was then fixed. A tool lesson is confirmed by the tool that passed. A reading lesson is confirmed only when the corrected field matches the gold set (`--gold`); otherwise it goes to "To review" and a person decides. Lessons are scrubbed for injections, limited to 220 characters and 20 per section, and a near duplicate is dropped.

## Files

| File | Role |
|---|---|
| `agent.py` | The reflection loop and the CLI. MCP client of `server.py`. |
| `reflect.py` | The two calls of the agent model: review the card, write lessons. |
| `memory.py` | `Journal` (short-term) and `Lessons` (long-term). |
| `lessons.md` | The skill file. The `[seed]` lessons were written by hand: a chemist must check them. |
| `test_agent_e2e.py` | End-to-end tests: real CLI, real MCP server, real models. |

## Run

The agent model is set in `config.yaml` (`agent`, Groq `openai/gpt-oss-120b` by default). Put `GROQ_API_KEY` in `.env`. The extraction model is the `model` section, or the variables `REPROCHEM_BASE_URL`, `REPROCHEM_MODEL` and `REPROCHEM_API_KEY_ENV`.

```bash
uv run python agentic/S4_strategy_memory/agent.py data/papers/md/2202.02370.md --smiles O --heavy-atoms 1 --charge 0 --multiplicity 1 --gold
```

Without `--yes`, the agent shows the card and asks before it runs PySCF. PySCF has no Windows wheels: on Windows the compile step runs, but the calculation test is skipped. Use Linux, macOS or WSL to run it.

```bash
uv run --with pytest pytest agentic/S4_strategy_memory -v
```
