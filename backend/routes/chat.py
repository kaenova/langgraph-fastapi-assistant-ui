"""Chat run routes with EventStream streaming and HITL tool handling."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from agent.model import model
from agent.tools import AVAILABLE_TOOLS
from lib.thread_store import thread_store


chat_routes = APIRouter()


class RunRequest(BaseModel):
    """Run request payload for local runtime adapter."""

    messages: list[dict[str, Any]]
    run_config: dict[str, Any] = Field(default_factory=dict, alias="runConfig")


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _event_line(payload: dict[str, Any]) -> bytes:
    """Encode event payload as SSE event line."""
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n".encode("utf-8")


def _chunk_field(item: Any, key: str, default: Any = None) -> Any:
    """Safely read a field from dict-like or attribute-like chunk objects."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _extract_text_parts(parts: Any) -> str:
    """Extract text content from assistant-ui message parts."""
    if isinstance(parts, str):
        return parts
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            texts.append(str(part.get("text", "")))
    return "\n".join(texts).strip()


def _extract_tool_call_parts(parts: Any) -> list[dict[str, Any]]:
    """Extract tool-call parts from assistant message content."""
    if not isinstance(parts, list):
        return []
    tool_calls: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "tool-call":
            tool_calls.append(part)
    return tool_calls


def _extract_tool_result_parts(parts: Any) -> list[dict[str, Any]]:
    """Extract tool-result parts from tool message content."""
    if not isinstance(parts, list):
        return []
    tool_results: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "tool-result":
            tool_results.append(part)
    return tool_results


def _extract_chunk_text(content: Any) -> str:
    """Extract incremental text from AI message chunk content."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            text_parts.append(item)
            continue
        if isinstance(item, dict):
            if item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
                continue
            if "text" in item:
                text_parts.append(str(item.get("text", "")))
    return "".join(text_parts)


def _find_tool(name: str):
    """Find a tool instance by name."""
    for tool in AVAILABLE_TOOLS:
        if tool.name == name:
            return tool
    return None


def _apply_human_tool_decisions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply approve/reject + edited args decisions before model call."""
    if not messages:
        return messages
    if messages[-1].get("role") != "tool":
        return messages

    # Find preceding assistant tool-call message.
    assistant_tool_message: dict[str, Any] | None = None
    for candidate in reversed(messages[:-1]):
        if candidate.get("role") != "assistant":
            continue
        if _extract_tool_call_parts(candidate.get("content")):
            assistant_tool_message = candidate
            break
    if assistant_tool_message is None:
        return messages

    tool_call_map = {
        part.get("toolCallId"): part
        for part in _extract_tool_call_parts(assistant_tool_message.get("content"))
    }

    rewritten_tool_parts: list[dict[str, Any]] = []
    for part in _extract_tool_result_parts(messages[-1].get("content")):
        tool_call_id = str(part.get("toolCallId", ""))
        base_tool_call = tool_call_map.get(tool_call_id, {})
        base_args = base_tool_call.get("args") if isinstance(base_tool_call, dict) else {}
        tool_name = str(base_tool_call.get("toolName", ""))
        result_payload = part.get("result")

        if isinstance(result_payload, dict) and "decision" in result_payload:
            decision = str(result_payload.get("decision", "reject")).lower()
            edited_args = result_payload.get("editedArgs")
            if isinstance(edited_args, dict):
                call_args = edited_args
            elif isinstance(base_args, dict):
                call_args = base_args
            else:
                call_args = {}

            if decision == "approve":
                tool = _find_tool(tool_name)
                if tool is None:
                    execution_result: Any = {
                        "status": "error",
                        "error": f"Tool '{tool_name}' not found",
                    }
                else:
                    try:
                        execution_result = tool.invoke(call_args)
                    except Exception as exc:  # noqa: BLE001
                        execution_result = {
                            "status": "error",
                            "error": str(exc),
                        }
            else:
                execution_result = {
                    "status": "rejected",
                    "reason": result_payload.get("reason", "Rejected by user"),
                }

            rewritten_tool_parts.append(
                {
                    "type": "tool-result",
                    "toolCallId": tool_call_id,
                    "result": execution_result,
                }
            )
        else:
            rewritten_tool_parts.append(part)

    updated_messages = [*messages]
    updated_messages[-1] = {
        **updated_messages[-1],
        "content": rewritten_tool_parts,
    }
    return updated_messages


def _to_langchain_messages(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """Convert assistant-ui thread messages into LangChain message objects."""
    converted: list[BaseMessage] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")

        if role == "system":
            converted.append(SystemMessage(content=_extract_text_parts(content)))
            continue

        if role == "user":
            converted.append(HumanMessage(content=_extract_text_parts(content)))
            continue

        if role == "assistant":
            text = _extract_text_parts(content)
            tool_calls = []
            for part in _extract_tool_call_parts(content):
                tool_calls.append(
                    {
                        "id": part.get("toolCallId"),
                        "name": part.get("toolName"),
                        "args": part.get("args", {}),
                    }
                )
            converted.append(AIMessage(content=text, tool_calls=tool_calls))
            continue

        if role == "tool":
            for part in _extract_tool_result_parts(content):
                converted.append(
                    ToolMessage(
                        content=json.dumps(part.get("result")),
                        tool_call_id=str(part.get("toolCallId", "")),
                    )
                )
            continue

    return converted


def _assistant_text_from_response(response: AIMessage) -> str:
    """Extract text from AIMessage response."""
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "".join(texts)
    return str(content)


@chat_routes.post("/{thread_id}/runs/stream")
async def run_stream(thread_id: str, payload: RunRequest) -> StreamingResponse:
    """Run model roundtrip and stream SSE events for LocalRuntime adapter."""
    if not payload.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="messages is required",
        )

    run_id = str(uuid.uuid4())
    thread_store.ensure_document(thread_id)

    prepared_messages = _apply_human_tool_decisions(payload.messages)
    langchain_messages = _to_langchain_messages(prepared_messages)
    model_with_tools = model.bind_tools(AVAILABLE_TOOLS)

    async def event_stream():
        accumulated_text = ""
        tool_states: dict[int, dict[str, Any]] = {}
        assistant_message_id = f"assistant-{uuid.uuid4()}"
        try:
            async for chunk in model_with_tools.astream(langchain_messages):
                delta = _extract_chunk_text(getattr(chunk, "content", ""))
                if delta:
                    accumulated_text += delta
                    yield _event_line({"type": "text_delta", "delta": delta})

                tool_call_chunks = getattr(chunk, "tool_call_chunks", None) or []
                for raw_chunk in tool_call_chunks:
                    raw_index = _chunk_field(raw_chunk, "index", 0)
                    try:
                        tool_index = int(raw_index)
                    except (TypeError, ValueError):
                        tool_index = 0

                    tool_state = tool_states.get(tool_index)
                    if tool_state is None:
                        tool_state = {
                            "toolCallId": f"{run_id}:tool:{tool_index}",
                            "toolName": "",
                            "args": {},
                            "argsText": "",
                        }
                        tool_states[tool_index] = tool_state

                    name_piece = _chunk_field(raw_chunk, "name", "")
                    if isinstance(name_piece, str) and name_piece:
                        tool_state["toolName"] = name_piece

                    args_piece = _chunk_field(raw_chunk, "args", "")
                    if args_piece:
                        tool_state["argsText"] += str(args_piece)

                    try:
                        parsed_args = (
                            json.loads(tool_state["argsText"])
                            if tool_state["argsText"].strip()
                            else {}
                        )
                        if isinstance(parsed_args, dict):
                            tool_state["args"] = parsed_args
                    except json.JSONDecodeError:
                        pass

                    yield _event_line(
                        {
                            "type": "tool_call",
                            "toolCallId": tool_state["toolCallId"],
                            "toolName": tool_state["toolName"] or f"tool_{tool_index}",
                            "args": tool_state["args"],
                            "argsText": tool_state["argsText"],
                        }
                    )

            if tool_states:
                tool_parts: list[dict[str, Any]] = []
                for tool_index in sorted(tool_states):
                    tool_state = tool_states[tool_index]
                    tool_parts.append(
                        {
                            "type": "tool-call",
                            "toolCallId": tool_state["toolCallId"],
                            "toolName": tool_state["toolName"] or f"tool_{tool_index}",
                            "args": tool_state["args"],
                            "argsText": tool_state["argsText"],
                        }
                    )
                    thread_store.upsert_tool_call(
                        thread_id,
                        {
                            "id": tool_state["toolCallId"],
                            "run_id": run_id,
                            "tool_name": tool_state["toolName"] or f"tool_{tool_index}",
                            "args": tool_state["args"],
                            "edited_args": None,
                            "decision": "pending",
                            "status": "pending",
                            "created_at": _now_iso(),
                            "resolved_at": None,
                        },
                    )

                assistant_message = {
                    "id": assistant_message_id,
                    "role": "assistant",
                    "content": tool_parts,
                    "status": {"type": "requires-action", "reason": "tool-calls"},
                    "metadata": {"custom": {}},
                    "createdAt": _now_iso(),
                }
                persisted_messages = [*prepared_messages, assistant_message]
                thread_store.replace_messages(thread_id, persisted_messages)
                thread_store.append_run(
                    thread_id,
                    {
                        "id": run_id,
                        "status": "requires-action",
                        "created_at": _now_iso(),
                        "completed_at": _now_iso(),
                        "error": None,
                    },
                )
                yield _event_line({"type": "done", "status": "requires-action"})
                return

            assistant_message = {
                "id": assistant_message_id,
                "role": "assistant",
                "content": [{"type": "text", "text": accumulated_text}],
                "status": {"type": "complete", "reason": "stop"},
                "metadata": {"custom": {}},
                "createdAt": _now_iso(),
            }
            persisted_messages = [*prepared_messages, assistant_message]
            thread_store.replace_messages(thread_id, persisted_messages)
            thread_store.append_run(
                thread_id,
                {
                    "id": run_id,
                    "status": "complete",
                    "created_at": _now_iso(),
                    "completed_at": _now_iso(),
                    "error": None,
                },
            )
            yield _event_line({"type": "done", "status": "complete"})
        except Exception as exc:  # noqa: BLE001
            thread_store.append_run(
                thread_id,
                {
                    "id": run_id,
                    "status": "failed",
                    "created_at": _now_iso(),
                    "completed_at": _now_iso(),
                    "error": str(exc),
                },
            )
            yield _event_line({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
