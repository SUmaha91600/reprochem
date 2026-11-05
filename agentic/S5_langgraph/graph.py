"""The S4 agent rebuilt in LangGraph.

    agent ──tool calls──> tools ──compile error──> reflect ──> agent
      │                     └──────────other───────────────────┘
      └──no tool call──> END

agent    the model (config.yaml `agent`) with the tools and lessons.md (S4).
tools    runs the tool calls (tools.py, through the MCP server of S3).
reflect  after a failed compile, asks the model to find the cause before it
         tries again (strategy of S4: reflection).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools import P, TOOLS  # noqa: E402
from memory import Lessons  # noqa: E402  (S4, on the path through tools.py)

SYSTEM = """You are ReproChem, an agent that turns the computational details of \
chemistry papers into PySCF jobs. Papers are given by paper_id; the user's own \
message is the document "request".

Rules:
- Use the tools. Never invent a setting: NOT_FOUND stays NOT_FOUND unless a quote supports a value.
- Charge and multiplicity belong to the user's molecule: set them only with \
set_user_molecule when the user gives them.
- compile_and_validate_job runs a calculation. Call it only when the user asks for a job.
- Never change a value only to make the compiler accept it.
- The tools cannot generate conformers, run CREST or xTB, compare energies, or read tables of results. If the request needs that, say so first, then do the part you can.
- A SMILES gives heavy atoms only: "O" is water, "CCCC" is butane.
- Answer in a short, factual way. Give JSON when the user asks for JSON.

Lessons from earlier runs:
{lessons}"""

REFLECT = """Reflection: the last compile failed ({error}). Before you call a tool \
again, say in one or two sentences which field causes the error and why. Read the \
method passages if you need them. Correct a field only with a quote. If the \
paper's value is not supported, do not replace it: stop and explain."""


def model() -> ChatOpenAI:
    c = P._section("agent", "AGENT")
    return ChatOpenAI(base_url=c["base_url"], model=c["name"], temperature=0,
                      api_key=os.environ.get(c["api_key_env"], "missing"), max_retries=6,
                      max_tokens=c.get("max_tokens", 3000))


def build():
    llm = model().bind_tools(TOOLS)
    system = SystemMessage(SYSTEM.format(lessons=Lessons().prompt_block()))

    def agent(state: MessagesState):
        reply = llm.invoke([system, *state["messages"]])
        if not reply.content and not reply.tool_calls:          # empty answer: ask once more
            reply = llm.invoke([system, *state["messages"],
                                HumanMessage("Your last answer was empty. Use the tools, then answer.")])
        return {"messages": [reply]}

    def after_tools(state: MessagesState) -> str:
        last = state["messages"][-1]
        failed = (isinstance(last, ToolMessage) and last.name == "compile_and_validate_job"
                  and str(last.content).startswith("ERROR"))
        return "reflect" if failed else "agent"

    def reflect(state: MessagesState):
        return {"messages": [HumanMessage(REFLECT.format(error=state["messages"][-1].content[:200]))]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(TOOLS))
    g.add_node("reflect", reflect)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    g.add_conditional_edges("tools", after_tools, {"reflect": "reflect", "agent": "agent"})
    g.add_edge("reflect", "agent")
    return g.compile()
