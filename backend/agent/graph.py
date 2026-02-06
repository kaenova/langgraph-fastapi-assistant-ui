"""LangGraph agent implementation."""

from typing import Annotated, Dict, List, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from lib.checkpointer import checkpointer

from .model import model
from .prompt import FALLBACK_SYSTEM_PROMPT, get_prompty_client
from .tools import AVAILABLE_TOOLS
from .utils import change_file_to_url, sanitize_and_validate_messages


class AgentState(TypedDict):
    """State for the agent graph."""

    messages: Annotated[List[BaseMessage], add_messages]


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """Determine whether to continue to tools or end the conversation.

    Args:
        state: Current agent state

    Returns:
        str: Next node to execute ("tools" or "end")
    """
    messages = state["messages"]
    last_message = messages[-1]

    # If the LLM makes a tool call, then we route to the "tools" node
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # Debug: Print tool calls
        print(f"\n🔧 LLM Tool Calls ({len(last_message.tool_calls)}):")
        for i, tool_call in enumerate(last_message.tool_calls, 1):
            print(f"  {i}. {tool_call.get('name', 'unknown')}")
            print(f"     Args: {tool_call.get('args', {})}")
        return "tools"
    # Otherwise, we stop (reply to the user)
    return "end"


def call_model(state: AgentState, config=None) -> Dict[str, List[BaseMessage]]:
    """Call the model with the current state.

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
    prompt = prompty.get_prompt("Main Chat Agent")
    if prompt is None:
        prompt = FALLBACK_SYSTEM_PROMPT

    system_msg = SystemMessage(content=prompt.strip())
    messages = [system_msg] + messages

    # Bind tools to the model
    model_with_tools = model.bind_tools(AVAILABLE_TOOLS)
    response = model_with_tools.invoke(messages)

    # Return the response
    return {"messages": [response]}


def get_graph():
    """Get or create the graph instance.

    Graph is rebuilt on every call to ensure tool changes are picked up.
    This may add slight latency but ensures correctness during development.
    """
    # Create the graph fresh every time
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(AVAILABLE_TOOLS))

    # Set the entrypoint as agent
    workflow.set_entry_point("agent")

    # Add conditional edges
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END,
        },
    )

    # Add edge from tools back to agent
    workflow.add_edge("tools", "agent")

    checkpointer_ins = checkpointer()

    # Compile the graph
    graph = workflow.compile(checkpointer=checkpointer_ins)

    return graph
