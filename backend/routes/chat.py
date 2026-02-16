"""Chat streaming routes for LangGraph integration.

Provides SSE-based streaming endpoints for chat and HITL (human-in-the-loop)
feedback. Both endpoints share the same LangGraph-to-SSE event converter.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, cast

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel

from agent.graph import get_graph

logger = logging.getLogger(__name__)

chat_routes = APIRouter()


def _checkpoint_id_from_state(state: Any) -> Optional[str]:
    """Extract checkpoint_id from a LangGraph state object."""
    try:
        cfg = getattr(state, "config", None) or {}
        configurable = cfg.get("configurable", {}) if isinstance(cfg, dict) else {}
        cp_id = configurable.get("checkpoint_id")
        if isinstance(cp_id, str) and cp_id:
            return cp_id
    except Exception:
        return None
    return None


def _first_interrupt_payload_from_state(state: Any) -> Optional[dict]:
    """Return the first interrupt payload if the graph is paused."""
    if not state or not getattr(state, "next", None):
        return None
    tasks = getattr(state, "tasks", [])
    for task in tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            intr = task.interrupts[0]
            if hasattr(intr, "value") and isinstance(intr.value, dict):
                return intr.value
            if hasattr(intr, "value"):
                return {"value": intr.value}
    return None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single chat message."""

    role: str
    content: str


class StreamRequest(BaseModel):
    """Request body for the /stream endpoint."""

    # Required: conversation thread id.
    thread_id: str = "default"

    # Optional: checkpoint to time travel / fork from.
    checkpoint_id: Optional[str] = None

    # Preferred: send only the delta user message.
    message: Optional[Message] = None

    # Back-compat: old clients sent the full transcript.
    messages: Optional[List[Message]] = None


class FeedbackRequest(BaseModel):
    """Request body for the /feedback endpoint (HITL resume)."""

    thread_id: str
    checkpoint_id: Optional[str] = None
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

    # NOTE: checkpoint helpers live at module scope for reuse.

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

        # -- Inspect final state (interrupt vs complete) ------------------------
        state = None
        try:
            # IMPORTANT: do not pass checkpoint_id when inspecting final state.
            # If we include checkpoint_id here (e.g. when /feedback resumes from an
            # interrupted checkpoint), LangGraph will "time travel" and we'll
            # incorrectly re-emit the original interrupt.
            thread_id = None
            if isinstance(config, dict):
                configurable = config.get("configurable")
                if isinstance(configurable, dict):
                    thread_id = configurable.get("thread_id")

            state_config = (
                cast(RunnableConfig, {"configurable": {"thread_id": thread_id}})
                if thread_id
                else config
            )

            state = await graph.aget_state(state_config)
        except Exception as e:
            logger.warning(f"Could not check graph state: {e}")

        cp_id = _checkpoint_id_from_state(state) if state else None

        # If paused, emit meta + interrupt payload.
        if state and getattr(state, "next", None):
            interrupts = getattr(state, "tasks", [])
            for task in interrupts:
                if hasattr(task, "interrupts") and task.interrupts:
                    if cp_id:
                        yield sse(
                            {
                                "type": "meta",
                                "phase": "interrupt",
                                "checkpoint_id": cp_id,
                            }
                        )
                    for intr in task.interrupts:
                        yield sse(
                            {
                                "type": "interrupt",
                                "payload": intr.value,
                            }
                        )
                    return

        # Normal completion: emit meta + done.
        if cp_id:
            yield sse({"type": "meta", "phase": "complete", "checkpoint_id": cp_id})
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

    # Prefer a single delta message (new architecture) but accept full transcripts
    # for back-compat.
    input_messages: List[dict] = []
    if payload.message is not None:
        input_messages = [
            {"role": payload.message.role, "content": payload.message.content}
        ]
    elif payload.messages is not None:
        input_messages = [
            {"role": m.role, "content": m.content} for m in payload.messages
        ]

    graph_input = {"messages": input_messages}

    configurable: Dict[str, Any] = {"thread_id": payload.thread_id}
    if payload.checkpoint_id:
        configurable["checkpoint_id"] = payload.checkpoint_id
    config = cast(RunnableConfig, {"configurable": configurable})

    logger.info(
        f"Starting stream for thread_id={payload.thread_id} "
        f"checkpoint_id={payload.checkpoint_id or ''} "
        f"input_messages={len(input_messages)}"
    )

    async def event_gen():
        yield sse(
            {
                "type": "meta",
                "phase": "start",
                "thread_id": payload.thread_id,
                "checkpoint_id": payload.checkpoint_id,
            }
        )
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

    configurable: Dict[str, Any] = {"thread_id": payload.thread_id}
    if payload.checkpoint_id:
        configurable["checkpoint_id"] = payload.checkpoint_id
    config = cast(RunnableConfig, {"configurable": configurable})

    logger.info(
        f"Resuming graph for thread_id={payload.thread_id} "
        f"checkpoint_id={payload.checkpoint_id or ''} "
        f"with approval_data={payload.approval_data}"
    )

    async def event_gen():
        yield sse(
            {
                "type": "meta",
                "phase": "start",
                "thread_id": payload.thread_id,
                "checkpoint_id": payload.checkpoint_id,
            }
        )
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


@chat_routes.get("/interrupt")
async def interrupt_status(
    thread_id: str = Query(..., description="LangGraph thread id"),
    checkpoint_id: Optional[str] = Query(
        None, description="Optional checkpoint_id to time travel / fork from"
    ),
):
    """Return whether the graph is currently paused (HITL interrupt).

    This is used by the frontend to rehydrate the approval UI after refresh.
    """
    graph = get_graph()

    configurable: Dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    config = cast(RunnableConfig, {"configurable": configurable})

    state = await graph.aget_state(config)
    cp_id = _checkpoint_id_from_state(state)
    payload = _first_interrupt_payload_from_state(state)
    if payload:
        return {
            "thread_id": thread_id,
            "interrupted": True,
            "checkpoint_id": cp_id,
            "payload": payload,
        }
    return {
        "thread_id": thread_id,
        "interrupted": False,
        "checkpoint_id": cp_id,
    }
