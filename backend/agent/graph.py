"""LangGraph agent implementation with human-in-the-loop approval."""

from typing import Annotated, List, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from lib.checkpointer import checkpointer

from .model import model
from .prompt import FALLBACK_SYSTEM_PROMPT, get_prompty_client
from .tools import AVAILABLE_TOOLS
from .utils import change_file_to_url, sanitize_and_validate_messages

# Tools that require human approval before execution
DANGEROUS_TOOL_NAMES = {"current_weather"}


class AgentState(TypedDict):
    """State for the agent graph."""

    messages: Annotated[List[BaseMessage], add_messages]


def should_continue(state: AgentState) -> Literal["approval", "tools", "end"]:
    """Determine whether to continue to tools, approval, or end.

    Routes to the approval node if any tool call targets a dangerous tool,
    otherwise routes directly to the tools node for safe tools.

    Args:
        state: Current agent state

    Returns:
        str: Next node to execute ("approval", "tools", or "end")
    """
    messages = state["messages"]
    last_message = messages[-1]

    # If the LLM makes a tool call, then we route to the "tools" node
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # Debug: Print tool calls
        print(f"\n🔧 LLM Tool Calls ({len(last_message.tool_calls)}):")
        for i, tool_call in enumerate(last_message.tool_calls, 1):
            print(f"  {i}. {tool_call.get('name', 'unknown')}")
            print(f"     Args: {tool_call.get('args', {})}")

        # Check if any tool call requires human approval
        if any(
            tc.get("name") in DANGEROUS_TOOL_NAMES for tc in last_message.tool_calls
        ):
            print("  ⚠️  Dangerous tool detected, routing to approval node")
            return "approval"

        return "tools"
    # Otherwise, we stop (reply to the user)
    return "end"


async def call_model(state: AgentState, config=None) -> dict:
    """Call the model with the current state.

    Uses async invocation so that ``astream_events`` can capture
    ``on_chat_model_stream`` token-level events during streaming.

    Args:
        state: Current agent state
        config: Configuration dictionary

    Returns:
        Dict containing the updated messages
    """
    messages = state["messages"]

    # Trim messages to fit within token limit
    messages = trim_messages(
        state["messages"],
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=120_000,
        start_on="human",
        end_on=("human", "tool"),
    )

    # Sanitize and validate messages to ensure proper tool call/response pairing
    messages = sanitize_and_validate_messages(messages)

    # Convert chatbot://{id} URLs to temporary blob URLs with SAS tokens
    messages = change_file_to_url(messages)

    print(messages)

    prompty = get_prompty_client()
    prompt = None
    try:
        prompt = prompty.get_prompt("Main Chat Agent")
    except Exception as e:
        print(f"Error getting prompt: {e}")

    if prompt is None:
        prompt = FALLBACK_SYSTEM_PROMPT

    system_msg = SystemMessage(content=prompt.strip())
    messages = [system_msg] + messages

    # Bind tools to the model
    model_with_tools = model.bind_tools(AVAILABLE_TOOLS)
    response = await model_with_tools.ainvoke(messages)

    # Return the response
    return {"messages": [response]}


def approval_node(state: AgentState) -> dict:
    """Gate dangerous tool calls behind human approval.

    Uses LangGraph's ``interrupt()`` to pause the graph and ask the user
    for approval. When resumed via ``Command(resume=...)``, the approval
    data determines which tool calls proceed and which are rejected.

    Args:
        state: Current agent state

    Returns:
        Dict containing the updated messages with filtered tool calls
        and rejection messages.
    """
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}

    calls = last_message.tool_calls
    need_approval = [tc for tc in calls if tc.get("name") in DANGEROUS_TOOL_NAMES]

    if not need_approval:
        return {"messages": []}

    # Pause the graph and wait for human approval
    approval = interrupt(
        {
            "type": "tool_approval_required",
            "tool_calls": [
                {
                    "id": tc["id"],
                    "name": tc["name"],
                    "arguments": tc.get("args", {}),
                }
                for tc in need_approval
            ],
        }
    )

    decisions_raw = approval.get("decisions", [])
    decisions_by_id: dict[str, dict] = {}
    if isinstance(decisions_raw, list):
        for item in decisions_raw:
            if not isinstance(item, dict):
                continue
            tc_id = item.get("id")
            decision = item.get("decision")
            if not tc_id or decision not in ("approved", "rejected"):
                continue
            decisions_by_id[tc_id] = {
                "decision": decision,
                "arguments": item.get("arguments", None),
            }

    # Keep safe tool calls. For dangerous tool calls, include only approved ones,
    # and allow the frontend to override arguments.
    filtered_calls = []
    for tc in calls:
        name = tc.get("name")
        if name not in DANGEROUS_TOOL_NAMES:
            filtered_calls.append(tc)
            continue

        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id:
            continue

        decision_info = decisions_by_id.get(tc_id)
        if not decision_info or decision_info.get("decision") != "approved":
            continue

        override_args = decision_info.get("arguments", None)
        if override_args is None:
            override_args = tc.get("args", {})

        # Only accept JSON-object arguments.
        if not isinstance(override_args, dict):
            continue

        updated_tc = dict(tc)
        updated_tc["args"] = override_args
        filtered_calls.append(updated_tc)

    # Build updated AI message with only the allowed tool calls
    updated_message = AIMessage(
        content=last_message.content,
        tool_calls=filtered_calls,
        id=last_message.id,
    )

    # Replace the last message with only the allowed tool calls.
    return {"messages": [updated_message]}


def get_graph():
    """Get or create the graph instance.

    Graph is rebuilt on every call to ensure tool changes are picked up.
    This may add slight latency but ensures correctness during development.
    """
    # Create the graph fresh every time
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("agent", call_model)
    workflow.add_node("approval", approval_node)
    workflow.add_node("tools", ToolNode(AVAILABLE_TOOLS))

    # Set the entrypoint as agent
    workflow.set_entry_point("agent")

    # Add conditional edges
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "approval": "approval",
            "tools": "tools",
            "end": END,
        },
    )

    # After approval, proceed to tool execution
    workflow.add_edge("approval", "tools")

    # Add edge from tools back to agent
    workflow.add_edge("tools", "agent")

    checkpointer_ins = checkpointer()

    # Compile the graph
    graph = workflow.compile(checkpointer=checkpointer_ins)

    return graph
