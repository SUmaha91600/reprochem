# ReproChem · S5: the agent in LangGraph

The S4 agent rebuilt as a LangGraph `StateGraph`, with our own tools.

```
agent ──tool calls──> tools ──compile error──> reflect ──> agent
  │                     └──────────other───────────────────┘
  └──no tool call──> END
```

| File | Role |
|---|---|
| `tools.py` | 5 LangChain tools. They call the MCP server of S3 (`server.py`). The papers and cards stay in the process: the model sends only a `paper_id`. |
| `graph.py` | The graph. The `reflect` node runs after a failed compile (S4 strategy). The prompt includes the lessons of S4 (`lessons.md`). |
| `run_requests.py` | Runs the agent on the 5 requests of the S1 sheet. Writes `runs.md`. |
| `runs.md` | The result of the last run: tool calls, reflection steps and answer for each request. |

## Run

Install the extra and put `GROQ_API_KEY` in `.env`. The agent model is `config.yaml` → `agent`. The extraction model is `config.yaml` → `model`, or the `REPROCHEM_*` variables:

```bash
uv sync --extra agents --extra chem
REPROCHEM_BASE_URL=https://api.groq.com/openai/v1 REPROCHEM_MODEL=qwen/qwen3.8-27b REPROCHEM_API_KEY_ENV=GROQ_API_KEY uv run python agentic/S5_langgraph/run_requests.py
```

The papers must be in `data/papers/md` (`scripts/fetch_corpus.py`). PySCF has no Windows wheels: use Linux, macOS or WSL to run the calculations.
