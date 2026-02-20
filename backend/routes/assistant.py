"""Assistant transport command route with NDJSON state streaming."""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Iterator, List, Sequence, TypedDict

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from pydantic import BaseModel, ConfigDict, Field

from agent.graph import get_graph
from routes.thread import (
    get_thread_record_snapshot,
    get_thread_state_snapshot,
    resolve_userid,
    update_thread_state,
)

assistant_routes = APIRouter()

DEFAULT_BRANCH_ID = "branch-main"
HITL_ACTIONS = ["approve", "decline", "change-args"]


class AssistantMessagePayload(BaseModel):
    """Incoming message payload from assistant transport command."""

    id: str | None = None
    role: str | None = None
    parts: List[Dict[str, Any]] = Field(default_factory=list)
    content: List[Dict[str, Any]] = Field(default_factory=list)
    parent_id: str | None = Field(default=None, alias="parentId")
    branch_id: str | None = Field(default=None, alias="branchId")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AssistantCommand(BaseModel):
    """Command item in assistant transport batch."""

    type: str
    message: AssistantMessagePayload | None = None
    tool_call_id: str | None = Field(default=None, alias="toolCallId")
    result: Dict[str, Any] | None = None
    resume: Dict[str, Any] | None = None
    decision: str | None = None
    args: Dict[str, Any] | None = None
    parent_id: str | None = Field(default=None, alias="parentId")
    message_id: str | None = Field(default=None, alias="messageId")
    branch_id: str | None = Field(default=None, alias="branchId")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AssistantCommandBatchRequest(BaseModel):
    """Batch request payload for assistant transport."""

    thread_id: str | None = Field(default=None, alias="threadId")
    commands: List[AssistantCommand] = Field(default_factory=list)
    state: Dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class StateOperation(TypedDict):
    """State operation emitted over NDJSON stream."""

    type: str
    path: List[Any]
    value: Any


class PendingToolCallContext(TypedDict):
    """Pending tool-call metadata extracted from graph snapshot."""

    ai_message: AIMessage
    tool_call: Dict[str, Any]


def _container_for(next_key: Any) -> Any:
    """Return default container for traversal."""

    return [] if isinstance(next_key, int) else {}


def _set_by_path(state: Any, path: List[Any], value: Any) -> None:
    """Set a nested value by path, creating intermediate containers."""

    current = state
    for index, key in enumerate(path[:-1]):
        next_key = path[index + 1]
        if isinstance(key, int):
            if not isinstance(current, list):
                raise TypeError(f"Expected list while traversing {path}")
            while len(current) <= key:
                current.append(None)
            if current[key] is None:
                current[key] = _container_for(next_key)
            current = current[key]
            continue

        if not isinstance(current, dict):
            raise TypeError(f"Expected dict while traversing {path}")
        if key not in current or current[key] is None:
            current[key] = _container_for(next_key)
        current = current[key]

    last_key = path[-1]
    if isinstance(last_key, int):
        if not isinstance(current, list):
            raise TypeError(f"Expected list for final key in {path}")
        while len(current) <= last_key:
            current.append(None)
        current[last_key] = value
        return

    if not isinstance(current, dict):
        raise TypeError(f"Expected dict for final key in {path}")
    current[last_key] = value


def _get_by_path(state: Any, path: List[Any]) -> Any:
    """Read a nested value by path."""

    current = state
    for key in path:
        current = current[key]
    return current


def _append_text(state: Dict[str, Any], path: List[Any], value: str) -> None:
    """Append text into an existing string field."""

    try:
        existing = _get_by_path(state, path)
    except (KeyError, IndexError, TypeError):
        _set_by_path(state, path, "")
        existing = ""

    if not isinstance(existing, str):
        raise TypeError(f"append-text target must be string at {path}")
    _set_by_path(state, path, existing + value)


def _apply_operation(state: Dict[str, Any], operation: StateOperation) -> None:
    """Apply a state operation to current state snapshot."""

    op_type = operation["type"]
    if op_type == "set":
        _set_by_path(state, operation["path"], copy.deepcopy(operation["value"]))
        return
    if op_type == "append-text":
        _append_text(state, operation["path"], str(operation["value"]))
        return
    raise ValueError(f"Unsupported operation type: {op_type}")


def _add_operation(
    operations: List[StateOperation],
    state: Dict[str, Any],
    operation: StateOperation,
) -> None:
    """Append operation and apply it to local state."""

    operations.append(operation)
    _apply_operation(state, operation)


def _commit_operation(state: Dict[str, Any], operation: StateOperation) -> StateOperation:
    """Apply and return a single operation."""

    _apply_operation(state, operation)
    return operation


def _normalize_state(state: Dict[str, Any]) -> None:
    """Ensure required top-level state containers exist."""

    if not isinstance(state.get("messages"), list):
        state["messages"] = []
    if not isinstance(state.get("interrupts"), list):
        state["interrupts"] = []
    if not isinstance(state.get("thread"), dict):
        state["thread"] = {}
    if not isinstance(state.get("ui"), dict):
        state["ui"] = {}
    if state.get("head_id") is not None and not isinstance(state.get("head_id"), str):
        state["head_id"] = None


def _next_message_id(state: Dict[str, Any], prefix: str) -> str:
    """Generate the next deterministic message identifier for a prefix."""

    existing_ids = {
        message.get("id")
        for message in state.get("messages", [])
        if isinstance(message, dict) and isinstance(message.get("id"), str)
    }
    index = 1
    while f"{prefix}_{index}" in existing_ids:
        index += 1
    return f"{prefix}_{index}"


def _extract_text(parts: List[Dict[str, Any]]) -> str:
    """Extract text content from message parts."""

    chunks: List[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return "".join(chunks).strip()


def _message_parts(message: AssistantMessagePayload) -> List[Dict[str, Any]]:
    """Normalize incoming message parts/content into content list."""

    if message.parts:
        return [copy.deepcopy(part) for part in message.parts]
    if message.content:
        return [copy.deepcopy(part) for part in message.content]
    return []


def _find_message_by_id(state: Dict[str, Any], message_id: str | None) -> Dict[str, Any] | None:
    """Find message by message id."""

    if message_id is None:
        return None
    for message in state.get("messages", []):
        if isinstance(message, dict) and message.get("id") == message_id:
            return message
    return None


def _graph_config(thread_id: str) -> Dict[str, Any]:
    """Build graph invocation config for a thread."""

    return {"configurable": {"thread_id": thread_id}}


def _run_graph_thread_id(thread_id: str, run_id: str) -> str:
    """Build run-scoped graph thread id to isolate branch executions."""

    return f"{thread_id}:run:{run_id}"


def _split_text_chunks(text: str) -> List[str]:
    """Split text into small chunks for append-text streaming ops."""

    if not text:
        return []
    chunks = [chunk for chunk in text.split(" ") if chunk]
    if len(chunks) <= 1:
        return [text]
    output: List[str] = []
    for index, chunk in enumerate(chunks):
        suffix = " " if index < len(chunks) - 1 else ""
        output.append(f"{chunk}{suffix}")
    return output


def _extract_chunk_text(content: Any) -> str:
    """Extract text delta from streamed chunk content."""

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: List[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        for key in ("text", "delta", "content"):
            value = item.get(key)
            if isinstance(value, str):
                parts.append(value)
                break
    return "".join(parts)


def _message_parts_to_graph_content(parts: List[Dict[str, Any]]) -> Any:
    """Convert assistant transport parts into LangChain message content."""

    if not parts:
        return ""

    text_chunks: List[str] = []
    rich_parts: List[Dict[str, Any]] = []

    for part in parts:
        if not isinstance(part, dict):
            continue

        part_type = part.get("type")
        if part_type == "text" and isinstance(part.get("text"), str):
            text_chunks.append(part["text"])
            continue

        if part_type == "image" and isinstance(part.get("image"), str):
            rich_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": part["image"]},
                }
            )
            continue

        if part_type == "image_url":
            rich_parts.append(copy.deepcopy(part))
            continue

        rich_parts.append(copy.deepcopy(part))

    if rich_parts:
        text_value = "".join(text_chunks).strip()
        if text_value:
            rich_parts.insert(0, {"type": "text", "text": text_value})
        return rich_parts

    return "".join(text_chunks).strip()


def _message_parts_from_graph_content(content: Any) -> List[Dict[str, Any]]:
    """Convert LangChain message content into assistant transport parts."""

    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    if isinstance(content, list):
        parts: List[Dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                parts.append({"type": "text", "text": item})
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            if item_type == "text" and isinstance(item.get("text"), str):
                parts.append({"type": "text", "text": item["text"]})
                continue

            if item_type == "image_url":
                image_url = item.get("image_url")
                if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
                    parts.append({"type": "image", "image": image_url["url"]})
                    continue

            parts.append(copy.deepcopy(item))

        if parts:
            return parts

    return [{"type": "text", "text": ""}]


def _serialize_tool_message_content(payload: Any) -> str:
    """Serialize tool payload for ToolMessage content."""

    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload)
    except TypeError:
        return str(payload)


def _parse_tool_message_content(content: Any) -> Any:
    """Parse ToolMessage content back into JSON-compatible payload."""

    if not isinstance(content, str):
        return copy.deepcopy(content)

    stripped = content.strip()
    if not stripped:
        return ""

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return content


def _tool_result_is_error(payload: Any) -> bool:
    """Infer incomplete tool status from result payload."""

    if isinstance(payload, dict):
        decision = payload.get("decision")
        if isinstance(decision, str) and decision.strip().lower() == "decline":
            return True
        if payload.get("approved") is False:
            return True
        if payload.get("declined") is True:
            return True
        if payload.get("error") is not None:
            return True
    return False


def _graph_snapshot_messages(
    graph: Any,
    thread_id: str,
) -> tuple[List[BaseMessage], tuple[str, ...]]:
    """Read graph state messages and pending next nodes for a thread."""

    snapshot = graph.get_state(_graph_config(thread_id))
    values = getattr(snapshot, "values", {})
    raw_messages = values.get("messages") if isinstance(values, dict) else []

    messages: List[BaseMessage] = []
    if isinstance(raw_messages, list):
        for item in raw_messages:
            if isinstance(item, BaseMessage):
                messages.append(item)

    raw_next = getattr(snapshot, "next", ())
    if isinstance(raw_next, tuple):
        next_nodes = tuple(str(item) for item in raw_next)
    elif isinstance(raw_next, list):
        next_nodes = tuple(str(item) for item in raw_next)
    else:
        next_nodes = ()

    return messages, next_nodes


def _pending_tool_calls(
    messages: Sequence[BaseMessage],
    next_nodes: Sequence[str],
) -> List[Dict[str, Any]]:
    """Extract pending tool calls when graph is paused before tools."""

    if "tools" not in set(next_nodes):
        return []

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue

        resolved_tool_ids = {
            tool_message.tool_call_id
            for tool_message in messages[index + 1 :]
            if isinstance(tool_message, ToolMessage)
            and isinstance(tool_message.tool_call_id, str)
        }

        pending: List[Dict[str, Any]] = []
        for tool_call in message.tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_call_id = tool_call.get("id")
            if isinstance(tool_call_id, str) and tool_call_id not in resolved_tool_ids:
                pending.append(copy.deepcopy(tool_call))

        if pending:
            return pending

    return []


def _interrupts_from_pending_calls(
    state: Dict[str, Any],
    pending_calls: Sequence[Dict[str, Any]],
    graph_thread_id: str,
) -> List[Dict[str, Any]]:
    """Build frontend interrupt payloads from pending tool calls."""

    existing_interrupts: Dict[str, Dict[str, Any]] = {}
    for interrupt_item in state.get("interrupts", []):
        if (
            isinstance(interrupt_item, dict)
            and isinstance(interrupt_item.get("tool_call_id"), str)
        ):
            existing_interrupts[interrupt_item["tool_call_id"]] = interrupt_item

    interrupts: List[Dict[str, Any]] = []
    for pending_call in pending_calls:
        tool_call_id = pending_call.get("id")
        if not isinstance(tool_call_id, str):
            continue

        existing = existing_interrupts.get(tool_call_id, {})
        args = pending_call.get("args")
        if not isinstance(args, dict):
            args = {}

        interrupts.append(
            {
                "id": (
                    existing.get("id")
                    if isinstance(existing.get("id"), str)
                    else f"interrupt_{tool_call_id}"
                ),
                "tool_call_id": tool_call_id,
                "tool_name": (
                    pending_call.get("name")
                    if isinstance(pending_call.get("name"), str)
                    else "tool"
                ),
                "graph_thread_id": graph_thread_id,
                "args": copy.deepcopy(args),
                "actions": HITL_ACTIONS,
            }
        )

    return interrupts


def _transport_messages_from_graph(
    messages: Sequence[BaseMessage],
    pending_calls: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert LangGraph state messages into frontend transport messages."""

    pending_tool_ids = {
        tool_call.get("id")
        for tool_call in pending_calls
        if isinstance(tool_call.get("id"), str)
    }

    tool_results: Dict[str, Any] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.tool_call_id, str):
            tool_results[message.tool_call_id] = _parse_tool_message_content(message.content)

    transport_messages: List[Dict[str, Any]] = []
    branch_id = DEFAULT_BRANCH_ID
    hidden_parent_id: str | None = None
    last_visible_message_id: str | None = None

    for index, message in enumerate(messages):
        message_id = message.id if isinstance(message.id, str) else f"graph_msg_{index + 1}"

        if isinstance(message, HumanMessage):
            additional_kwargs = (
                message.additional_kwargs
                if isinstance(message.additional_kwargs, dict)
                else {}
            )
            branch_candidate = additional_kwargs.get("branch_id")
            if isinstance(branch_candidate, str):
                branch_id = branch_candidate

            parent_id = additional_kwargs.get("parent_id")
            parent_value = (
                parent_id
                if isinstance(parent_id, str)
                else last_visible_message_id
            )

            if additional_kwargs.get("transport_hidden") is True:
                hidden_parent_id = parent_value or message_id
                continue

            payload: Dict[str, Any] = {
                "id": message_id,
                "role": "human",
                "branch_id": branch_id,
                "content": _message_parts_from_graph_content(message.content),
            }
            if parent_value is not None:
                payload["parent_id"] = parent_value
            transport_messages.append(payload)
            last_visible_message_id = message_id
            hidden_parent_id = None
            continue

        if isinstance(message, AIMessage):
            content_parts = _message_parts_from_graph_content(message.content)

            for tool_call in message.tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                tool_call_id = tool_call.get("id")
                if not isinstance(tool_call_id, str):
                    continue

                args = tool_call.get("args")
                if not isinstance(args, dict):
                    args = {}

                tool_part: Dict[str, Any] = {
                    "type": "tool-call",
                    "tool_call_id": tool_call_id,
                    "name": tool_call.get("name") if isinstance(tool_call.get("name"), str) else "tool",
                    "args": copy.deepcopy(args),
                }

                if tool_call_id in pending_tool_ids:
                    tool_part["status"] = "requires-action"
                elif tool_call_id in tool_results:
                    result_payload = copy.deepcopy(tool_results[tool_call_id])
                    if _tool_result_is_error(result_payload):
                        tool_part["status"] = "incomplete"
                        error_text = (
                            result_payload.get("error")
                            if isinstance(result_payload, dict)
                            and isinstance(result_payload.get("error"), str)
                            else "cancelled by user"
                        )
                        tool_part["error"] = error_text
                    else:
                        tool_part["status"] = "complete"
                        tool_part["result"] = result_payload
                else:
                    tool_part["status"] = "running"

                content_parts.append(tool_part)

            payload = {
                "id": message_id,
                "role": "ai",
                "branch_id": branch_id,
                "content": content_parts if content_parts else [{"type": "text", "text": ""}],
            }
            parent_value = hidden_parent_id or last_visible_message_id
            if parent_value is not None:
                payload["parent_id"] = parent_value
            transport_messages.append(payload)
            last_visible_message_id = message_id
            hidden_parent_id = None
            continue

        if isinstance(message, ToolMessage):
            tool_call_id = message.tool_call_id if isinstance(message.tool_call_id, str) else ""
            payload = {
                "id": message_id,
                "role": "tool",
                "tool_call_id": tool_call_id,
                "branch_id": branch_id,
                "content": [
                    {
                        "type": "tool-result",
                        "tool_call_id": tool_call_id,
                        "result": _parse_tool_message_content(message.content),
                    }
                ],
            }
            if last_visible_message_id is not None:
                payload["parent_id"] = last_visible_message_id
            transport_messages.append(payload)
            last_visible_message_id = message_id

    return transport_messages


def _sync_graph_state_operations(
    operations: List[StateOperation],
    state: Dict[str, Any],
    graph: Any,
    graph_thread_id: str,
) -> None:
    """Sync graph checkpoint state back into assistant transport state."""

    graph_messages, next_nodes = _graph_snapshot_messages(graph, graph_thread_id)
    pending_calls = _pending_tool_calls(graph_messages, next_nodes)

    transport_messages = _transport_messages_from_graph(graph_messages, pending_calls)
    merged_messages = _merge_transport_messages(
        state.get("messages", []) if isinstance(state.get("messages"), list) else [],
        transport_messages,
    )
    interrupts = _interrupts_from_pending_calls(state, pending_calls, graph_thread_id)
    head_id = transport_messages[-1]["id"] if transport_messages else None

    previous_messages = (
        state.get("messages", []) if isinstance(state.get("messages"), list) else []
    )
    for index, message in enumerate(merged_messages):
        previous_message = (
            previous_messages[index]
            if index < len(previous_messages) and isinstance(previous_messages[index], dict)
            else None
        )
        if previous_message == message:
            continue

        is_single_ai_text_message = (
            message.get("role") == "ai"
            and isinstance(message.get("content"), list)
            and len(message["content"]) == 1
            and isinstance(message["content"][0], dict)
            and message["content"][0].get("type") == "text"
            and isinstance(message["content"][0].get("text"), str)
        )

        can_stream_text = (
            is_single_ai_text_message
            and (
                previous_message is None
                or (
                    isinstance(previous_message, dict)
                    and previous_message.get("id") == message.get("id")
                    and previous_message.get("role") == "ai"
                    and isinstance(previous_message.get("content"), list)
                    and len(previous_message["content"]) == 1
                    and isinstance(previous_message["content"][0], dict)
                    and previous_message["content"][0].get("type") == "text"
                    and isinstance(previous_message["content"][0].get("text"), str)
                )
            )
        )

        if not can_stream_text:
            _add_operation(
                operations,
                state,
                {
                    "type": "set",
                    "path": ["messages", index],
                    "value": message,
                },
            )
            continue

        previous_text = (
            previous_message["content"][0]["text"]
            if isinstance(previous_message, dict)
            else ""
        )
        target_text = message["content"][0]["text"]

        if target_text == previous_text:
            continue

        base_message = copy.deepcopy(message)
        base_message["content"][0]["text"] = previous_text
        _add_operation(
            operations,
            state,
            {
                "type": "set",
                "path": ["messages", index],
                "value": base_message,
            },
        )

        suffix = (
            target_text[len(previous_text) :]
            if target_text.startswith(previous_text)
            else target_text
        )
        for chunk in _split_text_chunks(suffix):
            _add_operation(
                operations,
                state,
                {
                    "type": "append-text",
                    "path": ["messages", index, "content", 0, "text"],
                    "value": chunk,
                },
            )

    if len(merged_messages) < len(previous_messages):
        _add_operation(
            operations,
            state,
            {
                "type": "set",
                "path": ["messages"],
                "value": merged_messages,
            },
        )

    _add_operation(
        operations,
        state,
        {
            "type": "set",
            "path": ["interrupts"],
            "value": interrupts,
        },
    )
    _add_operation(
        operations,
        state,
        {
            "type": "set",
            "path": ["head_id"],
            "value": head_id,
        },
    )


def _graph_message_from_transport(record: Dict[str, Any]) -> BaseMessage | None:
    """Convert persisted transport message into LangChain message."""

    role = record.get("role")
    message_id = record.get("id") if isinstance(record.get("id"), str) else None
    branch_id = record.get("branch_id") if isinstance(record.get("branch_id"), str) else None
    parent_id = record.get("parent_id") if isinstance(record.get("parent_id"), str) else None
    parts = record.get("content") if isinstance(record.get("content"), list) else []

    if role == "human":
        kwargs: Dict[str, Any] = {}
        if branch_id is not None:
            kwargs["branch_id"] = branch_id
        if parent_id is not None:
            kwargs["parent_id"] = parent_id
        return HumanMessage(
            id=message_id,
            content=_message_parts_to_graph_content(parts),
            additional_kwargs=kwargs,
        )

    if role == "ai":
        text_parts: List[Dict[str, Any]] = []
        tool_calls: List[Dict[str, Any]] = []

        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool-call":
                tool_call_id = part.get("tool_call_id")
                if not isinstance(tool_call_id, str):
                    continue
                args = part.get("args")
                if not isinstance(args, dict):
                    args = {}
                tool_calls.append(
                    {
                        "id": tool_call_id,
                        "name": (
                            part.get("name")
                            if isinstance(part.get("name"), str)
                            else "tool"
                        ),
                        "args": copy.deepcopy(args),
                        "type": "tool_call",
                    }
                )
                continue

            text_parts.append(copy.deepcopy(part))

        return AIMessage(
            id=message_id,
            content=_message_parts_to_graph_content(text_parts),
            tool_calls=tool_calls,
        )

    if role == "tool":
        tool_call_id = record.get("tool_call_id")
        if not isinstance(tool_call_id, str):
            tool_call_id = ""

        result_payload: Any = ""
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool-result":
                result_payload = copy.deepcopy(part.get("result"))
                nested_tool_call_id = part.get("tool_call_id")
                if isinstance(nested_tool_call_id, str):
                    tool_call_id = nested_tool_call_id
                break

        return ToolMessage(
            id=message_id,
            tool_call_id=tool_call_id,
            content=_serialize_tool_message_content(result_payload),
        )

    return None


def _select_state_history_for_parent(
    state_messages: Sequence[Dict[str, Any]],
    parent_id: str | None,
) -> List[Dict[str, Any]]:
    """Select branch-local history up to a specific parent message."""

    if parent_id is None:
        return []

    by_id: Dict[str, Dict[str, Any]] = {}
    for message in state_messages:
        message_id = message.get("id")
        if isinstance(message_id, str):
            by_id[message_id] = message

    lineage: List[Dict[str, Any]] = []
    cursor = parent_id
    visited: set[str] = set()
    while isinstance(cursor, str) and cursor not in visited and cursor in by_id:
        visited.add(cursor)
        message = by_id[cursor]
        lineage.append(message)
        next_parent = message.get("parent_id")
        cursor = next_parent if isinstance(next_parent, str) else None

    lineage.reverse()
    return [copy.deepcopy(message) for message in lineage]


def _merge_transport_messages(
    existing_messages: Sequence[Dict[str, Any]],
    incoming_messages: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge incoming graph-derived messages into persisted transport messages by id."""

    merged = [copy.deepcopy(message) for message in existing_messages]
    id_to_index: Dict[str, int] = {}
    for index, message in enumerate(merged):
        message_id = message.get("id")
        if isinstance(message_id, str):
            id_to_index[message_id] = index

    for incoming in incoming_messages:
        message_id = incoming.get("id")
        if not isinstance(message_id, str):
            continue
        payload = copy.deepcopy(incoming)
        if message_id in id_to_index:
            merged[id_to_index[message_id]] = payload
        else:
            id_to_index[message_id] = len(merged)
            merged.append(payload)

    return merged


def _seed_graph_from_state(
    graph: Any,
    graph_thread_id: str,
    state: Dict[str, Any],
    parent_id: str | None = None,
) -> None:
    """Seed graph checkpoint from persisted transport state when checkpoint is empty."""

    existing_messages, _ = _graph_snapshot_messages(graph, graph_thread_id)
    if existing_messages:
        return

    state_messages = state.get("messages")
    if not isinstance(state_messages, list):
        return

    if parent_id is not None:
        selected_history = _select_state_history_for_parent(state_messages, parent_id)
    else:
        selected_history = [copy.deepcopy(item) for item in state_messages if isinstance(item, dict)]

    if not selected_history:
        return

    converted_messages: List[BaseMessage] = []
    for state_message in selected_history:
        graph_message = _graph_message_from_transport(state_message)
        if graph_message is not None:
            converted_messages.append(graph_message)

    if not converted_messages:
        return

    last_message = converted_messages[-1]
    as_node = "tools" if isinstance(last_message, ToolMessage) else "agent"
    graph.update_state(
        _graph_config(graph_thread_id),
        {"messages": converted_messages},
        as_node=as_node,
    )


def _bootstrap_thread_operations(
    operations: List[StateOperation],
    state: Dict[str, Any],
    thread_snapshot: Dict[str, Any],
    thread_id: str,
) -> None:
    """Emit initial thread metadata operations when state is still draft."""

    thread_state = state.get("thread", {})
    if not isinstance(thread_state, dict):
        thread_state = {}

    if thread_state.get("id") != thread_id:
        _add_operation(
            operations,
            state,
            {
                "type": "set",
                "path": ["thread", "id"],
                "value": thread_id,
            },
        )
    if thread_state.get("title") != thread_snapshot.get("title"):
        _add_operation(
            operations,
            state,
            {
                "type": "set",
                "path": ["thread", "title"],
                "value": thread_snapshot.get("title"),
            },
        )
    if thread_state.get("status") != thread_snapshot.get("status"):
        _add_operation(
            operations,
            state,
            {
                "type": "set",
                "path": ["thread", "status"],
                "value": thread_snapshot.get("status"),
            },
        )

    route_value = f"/chat/{thread_id}"
    ui_state = state.get("ui", {})
    if not isinstance(ui_state, dict) or ui_state.get("route") != route_value:
        _add_operation(
            operations,
            state,
            {
                "type": "set",
                "path": ["ui", "route"],
                "value": route_value,
            },
        )


def _handle_add_message(
    command: AssistantCommand,
    state: Dict[str, Any],
    thread_id: str,
    graph: Any,
) -> List[StateOperation]:
    """Handle add-message command by invoking agent graph."""

    if command.message is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="add-message requires message payload",
        )

    message_payload = command.message
    branch_id = message_payload.branch_id or DEFAULT_BRANCH_ID
    message_id = message_payload.id or _next_message_id(state, "msg_user")
    run_thread_id = _run_graph_thread_id(thread_id, message_id)
    parts = _message_parts(message_payload)
    if not parts:
        parts = [{"type": "text", "text": ""}]

    additional_kwargs: Dict[str, Any] = {"branch_id": branch_id}
    if isinstance(message_payload.parent_id, str):
        additional_kwargs["parent_id"] = message_payload.parent_id

    _seed_graph_from_state(
        graph,
        run_thread_id,
        state,
        message_payload.parent_id,
    )
    graph.invoke(
        {
            "messages": [
                HumanMessage(
                    id=message_id,
                    content=_message_parts_to_graph_content(parts),
                    additional_kwargs=additional_kwargs,
                )
            ]
        },
        config=_graph_config(run_thread_id),
        interrupt_before=["tools"],
    )

    operations: List[StateOperation] = []
    _sync_graph_state_operations(operations, state, graph, run_thread_id)
    return operations


def _stream_add_message_operations(
    command: AssistantCommand,
    state: Dict[str, Any],
    thread_id: str,
    graph: Any,
) -> Iterator[StateOperation]:
    """Handle add-message with incremental assistant text streaming."""

    if command.message is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="add-message requires message payload",
        )

    message_payload = command.message
    branch_id = message_payload.branch_id or DEFAULT_BRANCH_ID
    message_id = message_payload.id or _next_message_id(state, "msg_user")
    run_thread_id = _run_graph_thread_id(thread_id, message_id)
    parts = _message_parts(message_payload)
    if not parts:
        parts = [{"type": "text", "text": ""}]

    additional_kwargs: Dict[str, Any] = {"branch_id": branch_id}
    if isinstance(message_payload.parent_id, str):
        additional_kwargs["parent_id"] = message_payload.parent_id

    _seed_graph_from_state(
        graph,
        run_thread_id,
        state,
        message_payload.parent_id,
    )

    user_message: Dict[str, Any] = {
        "id": message_id,
        "role": "human",
        "branch_id": branch_id,
        "content": copy.deepcopy(parts),
    }
    if isinstance(message_payload.parent_id, str):
        user_message["parent_id"] = message_payload.parent_id

    user_index = len(state["messages"])
    yield _commit_operation(
        state,
        {
            "type": "set",
            "path": ["messages", user_index],
            "value": user_message,
        },
    )

    ai_stream_index: int | None = None
    ai_stream_id: str | None = None
    for event in graph.stream(
        {
            "messages": [
                HumanMessage(
                    id=message_id,
                    content=_message_parts_to_graph_content(parts),
                    additional_kwargs=additional_kwargs,
                )
            ]
        },
        config=_graph_config(run_thread_id),
        stream_mode="messages",
        interrupt_before=["tools"],
    ):
        if not isinstance(event, tuple) or len(event) != 2:
            continue

        chunk, metadata = event
        if not isinstance(metadata, dict):
            continue
        node_name = metadata.get("langgraph_node")
        if isinstance(node_name, str) and node_name != "agent":
            continue
        if not isinstance(chunk, (AIMessageChunk, AIMessage)):
            continue
        chunk_text = _extract_chunk_text(chunk.content)
        if not chunk_text:
            continue

        if ai_stream_index is None:
            ai_stream_index = len(state["messages"])
            ai_stream_id = chunk.id if isinstance(chunk.id, str) else _next_message_id(state, "msg_ai_stream")
            ai_message: Dict[str, Any] = {
                "id": ai_stream_id,
                "role": "ai",
                "branch_id": branch_id,
                "content": [{"type": "text", "text": ""}],
                "parent_id": message_id,
            }
            yield _commit_operation(
                state,
                {
                    "type": "set",
                    "path": ["messages", ai_stream_index],
                    "value": ai_message,
                },
            )

        stream_chunks = (
            [chunk_text]
            if isinstance(chunk, AIMessageChunk)
            else _split_text_chunks(chunk_text)
        )
        for text_chunk in stream_chunks:
            yield _commit_operation(
                state,
                {
                    "type": "append-text",
                    "path": ["messages", ai_stream_index, "content", 0, "text"],
                    "value": text_chunk,
                },
            )

    final_operations: List[StateOperation] = []
    _sync_graph_state_operations(final_operations, state, graph, run_thread_id)
    for operation in final_operations:
        yield operation


def _resume_payload(
    command: AssistantCommand,
    fallback_args: Dict[str, Any],
) -> Dict[str, Any]:
    """Build normalized resume payload from command variants."""

    payload: Dict[str, Any] = {}
    if isinstance(command.result, dict):
        payload.update(command.result)
    if isinstance(command.resume, dict):
        payload.update(command.resume)
    if isinstance(command.decision, str) and "decision" not in payload:
        payload["decision"] = command.decision
    if isinstance(command.args, dict) and "args" not in payload:
        payload["args"] = command.args

    decision = str(payload.get("decision", "approve")).strip().lower()
    if decision not in set(HITL_ACTIONS):
        decision = "approve"

    args_payload = payload.get("args")
    args = dict(fallback_args)
    if isinstance(args_payload, dict):
        args.update(args_payload)

    return {
        "decision": decision,
        "args": args,
        "approved": decision != "decline",
        "source": "frontend-hitl",
    }


def _find_pending_tool_call(
    messages: Sequence[BaseMessage],
    next_nodes: Sequence[str],
    tool_call_id: str,
) -> PendingToolCallContext | None:
    """Find pending tool-call context from graph snapshot."""

    if "tools" not in set(next_nodes):
        return None

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue

        resolved_tool_ids = {
            tool_message.tool_call_id
            for tool_message in messages[index + 1 :]
            if isinstance(tool_message, ToolMessage)
            and isinstance(tool_message.tool_call_id, str)
        }

        for tool_call in message.tool_calls:
            if not isinstance(tool_call, dict):
                continue
            candidate_id = tool_call.get("id")
            if (
                isinstance(candidate_id, str)
                and candidate_id == tool_call_id
                and candidate_id not in resolved_tool_ids
            ):
                return {
                    "ai_message": message,
                    "tool_call": copy.deepcopy(tool_call),
                }

        break

    return None


def _update_pending_tool_args(
    graph: Any,
    thread_id: str,
    ai_message: AIMessage,
    tool_call_id: str,
    args: Dict[str, Any],
) -> None:
    """Update pending tool-call args in graph checkpoint state."""

    updated_message = copy.deepcopy(ai_message)
    updated = False
    for tool_call in updated_message.tool_calls:
        if isinstance(tool_call, dict) and tool_call.get("id") == tool_call_id:
            tool_call["args"] = copy.deepcopy(args)
            updated = True

    if not updated:
        return

    graph.update_state(
        _graph_config(thread_id),
        {"messages": [updated_message]},
        as_node="agent",
    )


def _apply_tool_result_and_continue(
    graph: Any,
    thread_id: str,
    tool_call_id: str,
    payload: Any,
) -> None:
    """Inject tool result into graph and continue from agent node."""

    config = _graph_config(thread_id)
    graph.update_state(
        config,
        {
            "messages": [
                ToolMessage(
                    tool_call_id=tool_call_id,
                    content=_serialize_tool_message_content(payload),
                )
            ]
        },
        as_node="tools",
    )
    graph.invoke(None, config=config, interrupt_before=["tools"])


def _handle_resume_tool_call(
    command: AssistantCommand,
    state: Dict[str, Any],
    thread_id: str,
    graph: Any,
) -> List[StateOperation]:
    """Handle resume-tool-call and add-tool-result commands."""

    operations: List[StateOperation] = []
    tool_call_id = command.tool_call_id
    if not isinstance(tool_call_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resume-tool-call/add-tool-result requires toolCallId",
        )

    active_graph_thread_id = thread_id
    for interrupt_item in state.get("interrupts", []):
        if not isinstance(interrupt_item, dict):
            continue
        if interrupt_item.get("tool_call_id") != tool_call_id:
            continue
        graph_thread_candidate = interrupt_item.get("graph_thread_id")
        if isinstance(graph_thread_candidate, str) and graph_thread_candidate:
            active_graph_thread_id = graph_thread_candidate
        break

    graph_messages, next_nodes = _graph_snapshot_messages(graph, active_graph_thread_id)
    pending_context = _find_pending_tool_call(graph_messages, next_nodes, tool_call_id)
    if pending_context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tool call: {tool_call_id}",
        )

    fallback_args = pending_context["tool_call"].get("args")
    if not isinstance(fallback_args, dict):
        fallback_args = {}

    resume_payload = _resume_payload(command, dict(fallback_args))
    if resume_payload["args"] != fallback_args:
        _update_pending_tool_args(
            graph,
            active_graph_thread_id,
            pending_context["ai_message"],
            tool_call_id,
            resume_payload["args"],
        )

    command_type = command.type.strip().lower()
    decision = resume_payload["decision"]

    if decision == "change-args":
        _sync_graph_state_operations(operations, state, graph, thread_id)
        return operations

    if command_type == "add-tool-result":
        tool_result_payload: Any
        if command.result is not None:
            tool_result_payload = command.result
        elif command.resume is not None:
            tool_result_payload = command.resume
        else:
            tool_result_payload = resume_payload

        if decision == "decline" and isinstance(tool_result_payload, dict):
            tool_result_payload.setdefault("error", "cancelled by user")

        _apply_tool_result_and_continue(
            graph,
            active_graph_thread_id,
            tool_call_id,
            tool_result_payload,
        )
    elif decision == "decline":
        decline_payload = copy.deepcopy(resume_payload)
        decline_payload["error"] = "cancelled by user"
        _apply_tool_result_and_continue(
            graph,
            active_graph_thread_id,
            tool_call_id,
            decline_payload,
        )
    else:
        graph.invoke(
            None,
            config=_graph_config(active_graph_thread_id),
            interrupt_before=["tools"],
        )

    _sync_graph_state_operations(operations, state, graph, active_graph_thread_id)
    return operations


def _parent_for_regenerate(command: AssistantCommand, state: Dict[str, Any]) -> tuple[str | None, str]:
    """Resolve parent and branch metadata for regenerate command."""

    if isinstance(command.parent_id, str):
        parent_message = _find_message_by_id(state, command.parent_id)
        branch_id = command.branch_id or (
            parent_message.get("branch_id")
            if isinstance(parent_message, dict) and isinstance(parent_message.get("branch_id"), str)
            else DEFAULT_BRANCH_ID
        )
        return command.parent_id, branch_id

    target_message = _find_message_by_id(state, command.message_id)
    if isinstance(target_message, dict):
        parent_id = target_message.get("parent_id")
        branch_id = command.branch_id or target_message.get("branch_id") or DEFAULT_BRANCH_ID
        if isinstance(parent_id, str):
            return parent_id, str(branch_id)

    for message in reversed(state.get("messages", [])):
        if isinstance(message, dict) and message.get("role") == "human":
            if isinstance(message.get("id"), str):
                branch_id = command.branch_id or message.get("branch_id") or DEFAULT_BRANCH_ID
                return message["id"], str(branch_id)

    return None, command.branch_id or DEFAULT_BRANCH_ID


def _handle_regenerate(
    command: AssistantCommand,
    state: Dict[str, Any],
    thread_id: str,
    graph: Any,
) -> List[StateOperation]:
    """Handle regenerate command by rerunning graph with hidden parent prompt."""

    parent_id, branch_id = _parent_for_regenerate(command, state)
    parent_message = _find_message_by_id(state, parent_id)

    parent_parts: List[Dict[str, Any]] = []
    if isinstance(parent_message, dict):
        content = parent_message.get("content")
        if isinstance(content, list):
            parent_parts = [copy.deepcopy(part) for part in content if isinstance(part, dict)]

    if not parent_parts:
        parent_parts = [{"type": "text", "text": ""}]
    regen_message_id = _next_message_id(state, "msg_regen_user")
    run_thread_id = _run_graph_thread_id(thread_id, regen_message_id)

    additional_kwargs: Dict[str, Any] = {
        "branch_id": branch_id,
        "transport_hidden": True,
    }
    if isinstance(parent_id, str):
        additional_kwargs["parent_id"] = parent_id

    _seed_graph_from_state(graph, run_thread_id, state, parent_id)
    graph.invoke(
        {
            "messages": [
                HumanMessage(
                    id=regen_message_id,
                    content=_message_parts_to_graph_content(parent_parts),
                    additional_kwargs=additional_kwargs,
                )
            ]
        },
        config=_graph_config(run_thread_id),
        interrupt_before=["tools"],
    )

    operations: List[StateOperation] = []
    _sync_graph_state_operations(operations, state, graph, run_thread_id)
    return operations


def _resolve_thread_id(payload: AssistantCommandBatchRequest) -> str | None:
    """Resolve thread id from request body."""

    if isinstance(payload.thread_id, str) and payload.thread_id.strip():
        return payload.thread_id
    if isinstance(payload.state, dict):
        thread_state = payload.state.get("thread")
        if isinstance(thread_state, dict):
            thread_id = thread_state.get("id")
            if isinstance(thread_id, str) and thread_id.strip():
                return thread_id
    return None


def _stream_ndjson(operations: List[StateOperation]) -> Iterator[str]:
    """Yield operations as newline-delimited JSON."""

    for operation in operations:
        yield f"{json.dumps(operation)}\n"


@assistant_routes.post("")
def command_assistant(
    payload: AssistantCommandBatchRequest,
    userid: str | None = Header(None),
) -> StreamingResponse:
    """Process assistant command batch and stream state operations as NDJSON."""

    thread_id = _resolve_thread_id(payload)
    if thread_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="thread_id (or state.thread.id) is required",
        )

    user_id = resolve_userid(userid)
    thread_snapshot = get_thread_record_snapshot(user_id, thread_id)
    state = get_thread_state_snapshot(user_id, thread_id)
    if not state and isinstance(payload.state, dict):
        state = copy.deepcopy(payload.state)
    if not isinstance(state, dict):
        state = {}

    _normalize_state(state)
    operations: List[StateOperation] = []
    _bootstrap_thread_operations(operations, state, thread_snapshot, thread_id)

    graph = get_graph()

    def operation_stream() -> Iterator[str]:
        try:
            for operation in operations:
                yield f"{json.dumps(operation)}\n"

            for command in payload.commands:
                command_type = command.type.strip().lower()
                if command_type == "add-message":
                    for operation in _stream_add_message_operations(
                        command, state, thread_id, graph
                    ):
                        yield f"{json.dumps(operation)}\n"
                    continue

                if command_type in {"resume-tool-call", "add-tool-result"}:
                    command_operations = _handle_resume_tool_call(
                        command, state, thread_id, graph
                    )
                    for operation in command_operations:
                        yield f"{json.dumps(operation)}\n"
                    continue

                if command_type == "regenerate":
                    command_operations = _handle_regenerate(
                        command, state, thread_id, graph
                    )
                    for operation in command_operations:
                        yield f"{json.dumps(operation)}\n"
                    continue

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported assistant command: {command.type}",
                )
        finally:
            update_thread_state(user_id, thread_id, state)

    return StreamingResponse(
        operation_stream(),
        media_type="application/x-ndjson",
    )
