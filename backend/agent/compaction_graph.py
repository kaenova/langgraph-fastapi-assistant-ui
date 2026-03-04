"""LangGraph-based message compaction graph."""

from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from .model import model


COMPACTION_PROMPT = """
You compact chat history for future assistant turns.

Write a concise summary that preserves:
- user goals and constraints
- key decisions and resolved points
- important facts and entities
- pending questions or TODOs
- meaningful tool outcomes

Do not include conversational filler.
Do not invent new information.
Keep it short but complete.
""".strip()


class CompactionState(TypedDict):
    """State for compaction graph execution."""

    messages: list[BaseMessage]
    summary: str


def _extract_response_text(content: object) -> str:
    """Extract plain text from model response content."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text", "")))
        return "".join(texts).strip()
    return str(content).strip()


async def _summarize_node(state: CompactionState) -> dict[str, str]:
    """Summarize message history into a compact context string."""
    prompt_messages: list[BaseMessage] = [
        SystemMessage(content=COMPACTION_PROMPT),
        *state["messages"],
        HumanMessage(content="Create the compaction summary now."),
    ]
    response = await model.ainvoke(prompt_messages)
    summary_text = _extract_response_text(getattr(response, "content", ""))
    return {"summary": summary_text}


def _build_compaction_graph():
    """Build and compile the compaction graph."""
    workflow = StateGraph(CompactionState)
    workflow.add_node("summarize", _summarize_node)
    workflow.set_entry_point("summarize")
    workflow.add_edge("summarize", END)
    return workflow.compile()


_COMPACTION_GRAPH = _build_compaction_graph()


async def compact_messages(messages: list[BaseMessage]) -> str:
    """Run compaction graph and return compacted summary text."""
    result = await _COMPACTION_GRAPH.ainvoke({"messages": messages, "summary": ""})
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return "Summary unavailable."
