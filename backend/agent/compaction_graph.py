"""LangGraph-based message compaction graph."""

from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from .model import model


COMPACTION_PROMPT = """
Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like file names, full code snippets, function signatures, file edits, etc
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Pay special attention to the most recent messages and include full code snippets where applicable and include a summary of why this file read or edit is important.
4. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.
5. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.
6. Current Work: Describe in detail precisely what was being worked on immediately before this summary request, paying special attention to the most recent messages from both user and assistant. Include file names and code snippets where applicable.
7. Optional Next Step: List the next step that you will take that is related to the most recent work you were doing. IMPORTANT: ensure that this step is DIRECTLY in line with the user's explicit requests, and the task you were working on immediately before this summary request. If your last task was concluded, then only list next steps if they are explicitly in line with the users request. Do not start on tangential requests without confirming with the user first.
8. If there is a next step, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.

Here's an example of how your output should be structured:

<example>
<analysis>
[Your thought process, ensuring all points are covered thoroughly and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Technical Concepts:
   - [Concept 1]
   - [Concept 2]
   - [...]

3. Files and Code Sections:
   - [File Name 1]
      - [Summary of why this file is important]
      - [Summary of the changes made to this file, if any]
      - [Important Code Snippet]
   - [File Name 2]
      - [Important Code Snippet]
   - [...]

4. Problem Solving:
   [Description of solved problems and ongoing troubleshooting]

5. Pending Tasks:
   - [Task 1]
   - [Task 2]
   - [...]

6. Current Work:
   [Precise description of current work]

7. Optional Next Step:
   [Optional Next step to take]

</summary>
</example>

Please provide your summary based on the conversation so far, following this structure and ensuring precision and thoroughness in your response. 
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
