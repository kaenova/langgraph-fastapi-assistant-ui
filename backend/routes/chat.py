"""Chat streaming routes for LangGraph integration.

Provides SSE-based streaming endpoints for chat and HITL (human-in-the-loop)
feedback. Both endpoints share the same LangGraph-to-SSE event converter.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from agent.graph import get_graph

logger = logging.getLogger(__name__)

chat_routes = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single chat message."""

    role: str
    content: str


class StreamRequest(BaseModel):
    """Request body for the /stream endpoint."""

    messages: List[Message]
    thread_id: str = "default"


class FeedbackRequest(BaseModel):
    """Request body for the /feedback endpoint (HITL resume)."""

    thread_id: str
    approval_data: Dict[str, Any]


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def sse(data: dict) -> str:
    """Encode a Python dict as an SSE ``data:`` line.

    Args:
        data: Dictionary to encode.

    Returns:
        Formatted SSE data string.
    """
    encoded = jsonable_encoder(data)
    return f"data: {json.dumps(encoded)}\n\n"


async def langgraph_events_to_sse(
    events: Any,
    req: Request,
    graph: Any,
    config: Any,
) -> AsyncIterator[str]:
    """Convert LangGraph v2 streaming events to SSE events.

    Shared by ``/stream`` and ``/feedback`` so both endpoints produce
    identical event formats for the frontend adapter.

    After the event stream ends, checks the graph state for pending
    interrupts (HITL) and emits an ``interrupt`` event if found.

    Emitted event types:
    - ``token``      - incremental text content from the chat model
    - ``tool_call``  - a completed tool invocation decided by the model
    - ``tool_result``- result from tool execution
    - ``interrupt``  - HITL pause requiring user approval
    - ``done``       - normal completion
    - ``error``      - unrecoverable error

    Args:
        events: Async iterator from ``graph.astream_events(..., version="v2")``.
        req: The incoming FastAPI request (used for disconnect detection).
        graph: The compiled graph instance (for state inspection).
        config: The graph config (for state inspection).

    Yields:
        SSE-formatted strings.
    """
    try:
        async for event in events:
            if await req.is_disconnected():
                logger.info("Client disconnected, stopping SSE stream")
                break

            ev = event.get("event")

            # -- Token streaming ------------------------------------------------
            if ev == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                content = getattr(chunk, "content", None)
                if content:
                    yield sse({"type": "token", "content": content})

            # -- Tool calls (emitted once the model finishes) -------------------
            elif ev == "on_chat_model_end":
                output = event["data"]["output"]
                tool_calls = getattr(output, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        args = tc["args"]
                        if not isinstance(args, dict):
                            args = json.loads(args)
                        yield sse(
                            {
                                "type": "tool_call",
                                "id": tc["id"],
                                "name": tc["name"],
                                "arguments": args,
                            }
                        )

            # -- Tool execution results -----------------------------------------
            elif ev == "on_tool_end":
                output = event["data"].get("output")
                if output is not None:
                    data = event.get("data", {})
                    tool_call_id = ""
                    if isinstance(data, dict):
                        tool_call_id = data.get("tool_call_id", "") or data.get(
                            "call_id", ""
                        )
                        input_data = data.get("input")
                        if not tool_call_id and isinstance(input_data, dict):
                            tool_call_id = input_data.get(
                                "tool_call_id", ""
                            ) or input_data.get("id", "")
                    if not tool_call_id:
                        if hasattr(output, "tool_call_id"):
                            tool_call_id = getattr(output, "tool_call_id")
                        elif isinstance(output, dict):
                            tool_call_id = output.get("tool_call_id", "")
                    if not tool_call_id:
                        tool_call_id = event.get("run_id", "")

                    name = event.get("name", "")
                    if hasattr(output, "content"):
                        content = getattr(output, "content")
                    elif isinstance(output, dict) and "content" in output:
                        content = output.get("content")
                    else:
                        content = str(output)
                    yield sse(
                        {
                            "type": "tool_result",
                            "id": tool_call_id,
                            "tool_call_id": tool_call_id,
                            "name": name,
                            "content": content,
                        }
                    )

        # -- Check for interrupts after stream ends -----------------------------
        try:
            state = await graph.aget_state(config)
            if state and state.next:
                # Graph is paused at a node -- check for interrupt values
                interrupts = getattr(state, "tasks", [])
                for task in interrupts:
                    if hasattr(task, "interrupts") and task.interrupts:
                        for intr in task.interrupts:
                            interrupt_value = intr.value
                            yield sse(
                                {
                                    "type": "interrupt",
                                    "payload": interrupt_value,
                                }
                            )
                        # After emitting interrupt, stop
                        return
        except Exception as e:
            logger.warning(f"Could not check graph state for interrupts: {e}")

        # -- Normal completion --------------------------------------------------
        yield sse({"type": "done"})
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error(f"Error in langgraph_events_to_sse: {e}")
        yield sse({"type": "error", "error": str(e)})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@chat_routes.post("/stream")
async def stream_endpoint(payload: StreamRequest, req: Request):
    """Start a new LangGraph run and stream results as SSE.

    The frontend sends the full message history plus a ``thread_id``.
    LangGraph streams back tokens, tool calls, and potential HITL
    interrupts.

    Args:
        payload: The stream request containing messages and thread_id.
        req: The incoming FastAPI request.

    Returns:
        StreamingResponse with SSE events.
    """
    graph = get_graph()

    graph_input = {
        "messages": [{"role": m.role, "content": m.content} for m in payload.messages],
    }
    config = {"configurable": {"thread_id": payload.thread_id}}

    logger.info(
        f"Starting stream for thread_id={payload.thread_id} "
        f"with {len(payload.messages)} messages"
    )

    async def event_gen():
        events = graph.astream_events(graph_input, config=config, version="v2")
        async for chunk in langgraph_events_to_sse(events, req, graph, config):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@chat_routes.post("/feedback")
async def feedback_endpoint(payload: FeedbackRequest, req: Request):
    """Resume an interrupted graph after human approval.

    Sends ``Command(resume=approval_data)`` into the graph and streams
    the continuation in the same SSE format as ``/stream``.

    Args:
        payload: The feedback request containing thread_id and approval_data.
        req: The incoming FastAPI request.

    Returns:
        StreamingResponse with SSE events.
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": payload.thread_id}}

    logger.info(
        f"Resuming graph for thread_id={payload.thread_id} "
        f"with approval_data={payload.approval_data}"
    )

    async def event_gen():
        command = Command(resume=payload.approval_data)
        events = graph.astream_events(command, config=config, version="v2")
        async for chunk in langgraph_events_to_sse(events, req, graph, config):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
