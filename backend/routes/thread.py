"""Thread and chat streaming routes backed by LangGraph checkpoints."""

import json
import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from pydantic import BaseModel, Field

from agent.graph import get_graph
from lib.checkpointer import checkpointer

logger = logging.getLogger(__name__)

thread_routes = APIRouter()
graph = get_graph(checkpointer=checkpointer())


class ClientMessageInput(BaseModel):
    """Client message input payload."""

    content: Any = ""
    attachments: List[Dict[str, Any]] = Field(default_factory=list)


class StreamRunRequest(BaseModel):
    """Run request payload for chat streaming."""

    message: Optional[ClientMessageInput] = None
    parent_message_id: Optional[str] = None
    source_message_id: Optional[str] = None
    run_config: Dict[str, Any] = Field(default_factory=dict)


class ThreadCreateResponse(BaseModel):
    """Thread create response."""

    thread_id: str


def _graph_config(thread_id: str, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
    configurable: Dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def _checkpoint_id_from_config(config: Optional[Dict[str, Any]]) -> Optional[str]:
    if not config:
        return None
    configurable = config.get("configurable", {})
    if not isinstance(configurable, dict):
        return None
    checkpoint_id = configurable.get("checkpoint_id")
    if checkpoint_id is None:
        return None
    return str(checkpoint_id)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _content_to_parts(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    if not isinstance(content, list):
        return [{"type": "text", "text": _stringify(content)}]

    parts: List[Dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({"type": "text", "text": _stringify(item)})
            continue

        item_type = item.get("type")
        if item_type == "text":
            parts.append({"type": "text", "text": _stringify(item.get("text", ""))})
            continue

        if item_type == "image_url":
            image_url_obj = item.get("image_url", {})
            image_url = (
                image_url_obj.get("url")
                if isinstance(image_url_obj, dict)
                else _stringify(image_url_obj)
            )
            parts.append({"type": "image", "image": image_url})
            continue

        parts.append({"type": "text", "text": _stringify(item)})

    return parts or [{"type": "text", "text": ""}]


def _attachments_to_openai_parts(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    parts: List[Dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        content_items = attachment.get("content")
        if not isinstance(content_items, list):
            continue
        for item in content_items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image":
                image_url = item.get("image")
                if image_url:
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        }
                    )
            elif item.get("type") == "text":
                parts.append({"type": "text", "text": _stringify(item.get("text", ""))})
    return parts


def _to_human_message(
    message_input: ClientMessageInput, source_message_id: Optional[str]
) -> HumanMessage:
    content_parts: List[Dict[str, Any]] = []

    if isinstance(message_input.content, str):
        content_parts.append({"type": "text", "text": message_input.content})
    elif isinstance(message_input.content, list):
        for item in message_input.content:
            if not isinstance(item, dict):
                content_parts.append({"type": "text", "text": _stringify(item)})
                continue
            item_type = item.get("type")
            if item_type == "text":
                content_parts.append({"type": "text", "text": _stringify(item.get("text", ""))})
            elif item_type == "image":
                image_url = item.get("image")
                if image_url:
                    content_parts.append(
                        {"type": "image_url", "image_url": {"url": _stringify(image_url)}}
                    )

    content_parts.extend(_attachments_to_openai_parts(message_input.attachments))

    normalized_content: Any = content_parts
    if len(content_parts) == 1 and content_parts[0].get("type") == "text":
        normalized_content = content_parts[0]["text"]
    if not content_parts:
        normalized_content = ""

    return HumanMessage(
        content=normalized_content,
        id=source_message_id or str(uuid.uuid4()),
    )


def _get_history(thread_id: str) -> List[Any]:
    try:
        history = list(graph.get_state_history(_graph_config(thread_id), limit=500))
    except Exception:
        return []
    history.reverse()
    return history


def _build_checkpoint_indexes(
    thread_id: str,
) -> Tuple[Dict[str, str], Dict[str, Optional[str]]]:
    message_to_checkpoint: Dict[str, str] = {}
    message_to_parent_checkpoint: Dict[str, Optional[str]] = {}

    for snapshot in _get_history(thread_id):
        checkpoint_id = _checkpoint_id_from_config(snapshot.config)
        parent_checkpoint_id = _checkpoint_id_from_config(snapshot.parent_config)
        values = snapshot.values if isinstance(snapshot.values, dict) else {}
        snapshot_messages = values.get("messages", [])
        if not isinstance(snapshot_messages, list):
            continue

        if snapshot_messages:
            last_message = snapshot_messages[-1]
            last_message_id = getattr(last_message, "id", None)
            if last_message_id and checkpoint_id:
                if last_message_id not in message_to_checkpoint:
                    message_to_checkpoint[last_message_id] = checkpoint_id
                    message_to_parent_checkpoint[last_message_id] = parent_checkpoint_id

        for message in snapshot_messages:
            message_id = getattr(message, "id", None)
            if not message_id or not checkpoint_id:
                continue
            if message_id not in message_to_checkpoint:
                message_to_checkpoint[message_id] = checkpoint_id
                message_to_parent_checkpoint[message_id] = parent_checkpoint_id

    return message_to_checkpoint, message_to_parent_checkpoint


def _serialize_messages(
    messages: List[BaseMessage],
    checkpoint_by_message_id: Dict[str, str],
    parent_checkpoint_by_message_id: Dict[str, Optional[str]],
) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    tool_call_lookup: Dict[str, Dict[str, Any]] = {}

    for message in messages:
        if isinstance(message, ToolMessage):
            tool_call_id = getattr(message, "tool_call_id", None)
            if tool_call_id and tool_call_id in tool_call_lookup:
                tool_call_lookup[tool_call_id]["result"] = _stringify(message.content)
                if getattr(message, "status", "") == "error":
                    tool_call_lookup[tool_call_id]["isError"] = True
            continue

        role: Optional[str] = None
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, SystemMessage):
            role = "system"

        if role is None:
            continue

        message_id = getattr(message, "id", None) or str(uuid.uuid4())
        parts = _content_to_parts(message.content)
        checkpoint_id = checkpoint_by_message_id.get(message_id)
        parent_checkpoint_id = parent_checkpoint_by_message_id.get(message_id)

        payload: Dict[str, Any] = {
            "id": message_id,
            "role": role,
            "content": parts,
            "createdAt": None,
            "metadata": {
                "custom": {
                    "checkpointId": checkpoint_id,
                    "parentCheckpointId": parent_checkpoint_id,
                }
            },
        }

        if role == "assistant" and isinstance(message, AIMessage):
            payload["status"] = {"type": "complete", "reason": "unknown"}
            for tool_call in message.tool_calls or []:
                tool_call_id = tool_call.get("id") or str(uuid.uuid4())
                args = tool_call.get("args", {})
                tool_part: Dict[str, Any] = {
                    "type": "tool-call",
                    "toolCallId": tool_call_id,
                    "toolName": tool_call.get("name", "tool"),
                    "args": args,
                    "argsText": _stringify(args),
                }
                payload["content"].append(tool_part)
                tool_call_lookup[tool_call_id] = tool_part
        elif role == "user":
            payload["attachments"] = []

        serialized.append(payload)

    return serialized


def _build_message_repository(
    thread_id: str,
    checkpoint_by_message_id: Dict[str, str],
    parent_checkpoint_by_message_id: Dict[str, Optional[str]],
    head_id: Optional[str],
) -> Dict[str, Any]:
    items_by_message_id: Dict[str, Dict[str, Any]] = {}
    message_order: List[str] = []

    for snapshot in _get_history(thread_id):
        values = snapshot.values if isinstance(snapshot.values, dict) else {}
        snapshot_messages = values.get("messages", [])
        if not isinstance(snapshot_messages, list):
            continue

        serialized = _serialize_messages(
            snapshot_messages,
            checkpoint_by_message_id,
            parent_checkpoint_by_message_id,
        )

        previous_message_id: Optional[str] = None
        for serialized_message in serialized:
            message_id = serialized_message.get("id")
            if not message_id:
                continue
            if message_id not in items_by_message_id:
                items_by_message_id[message_id] = {
                    "parentId": previous_message_id,
                    "message": serialized_message,
                }
                message_order.append(message_id)
            previous_message_id = message_id

    return {
        "headId": head_id,
        "messages": [items_by_message_id[mid] for mid in message_order],
    }


def _get_thread_snapshot(thread_id: str) -> Dict[str, Any]:
    try:
        state = graph.get_state(_graph_config(thread_id))
    except Exception:
        return {"thread_id": thread_id, "checkpoint_id": None, "messages": []}

    values = state.values if isinstance(state.values, dict) else {}
    messages = values.get("messages", [])
    if not isinstance(messages, list):
        messages = []

    checkpoint_id = _checkpoint_id_from_config(state.config)
    checkpoint_by_message_id, parent_checkpoint_by_message_id = _build_checkpoint_indexes(
        thread_id
    )
    serialized_messages = _serialize_messages(
        messages, checkpoint_by_message_id, parent_checkpoint_by_message_id
    )
    head_id = serialized_messages[-1]["id"] if serialized_messages else None
    message_repository = _build_message_repository(
        thread_id,
        checkpoint_by_message_id,
        parent_checkpoint_by_message_id,
        head_id,
    )
    return {
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
        "messages": serialized_messages,
        "messageRepository": message_repository,
    }


def _resolve_parent_checkpoint(thread_id: str, parent_message_id: str) -> str:
    checkpoint_by_message_id, _ = _build_checkpoint_indexes(thread_id)
    checkpoint_id = checkpoint_by_message_id.get(parent_message_id)
    if not checkpoint_id:
        raise HTTPException(
            status_code=404,
            detail=f"Parent message checkpoint not found: {parent_message_id}",
        )
    return checkpoint_id


def _resolve_edit_checkpoint(thread_id: str, source_message_id: str) -> str:
    checkpoint_by_message_id, parent_checkpoint_by_message_id = _build_checkpoint_indexes(
        thread_id
    )
    checkpoint_id = parent_checkpoint_by_message_id.get(source_message_id)
    if not checkpoint_id:
        checkpoint_id = checkpoint_by_message_id.get(source_message_id)
    if not checkpoint_id:
        raise HTTPException(
            status_code=404,
            detail=f"Edit source checkpoint not found: {source_message_id}",
        )
    return checkpoint_id


def _encode_event(event: Dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


def _extract_text_delta(content: Any) -> str:
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    chunks: List[str] = []
    for item in content:
        if isinstance(item, str):
            chunks.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"text", "text_delta"}:
            text = item.get("text")
            if text:
                chunks.append(_stringify(text))
    return "".join(chunks)


@thread_routes.post("/threads", response_model=ThreadCreateResponse)
def create_thread() -> ThreadCreateResponse:
    """Create a thread ID on demand."""
    return ThreadCreateResponse(thread_id=str(uuid.uuid4()))


@thread_routes.get("/threads/{thread_id}/messages")
def get_thread_messages(thread_id: str) -> Dict[str, Any]:
    """Get the current message view for a thread."""
    return _get_thread_snapshot(thread_id)


@thread_routes.post("/threads/{thread_id}/runs/stream")
def stream_thread_run(thread_id: str, request: StreamRunRequest) -> StreamingResponse:
    """Run a thread turn and stream backend-confirmed message snapshots."""

    parent_checkpoint_id: Optional[str] = None
    if request.source_message_id and request.message is not None:
        parent_checkpoint_id = _resolve_edit_checkpoint(
            thread_id, request.source_message_id
        )
    elif request.parent_message_id:
        parent_checkpoint_id = _resolve_parent_checkpoint(thread_id, request.parent_message_id)

    config = _graph_config(thread_id, checkpoint_id=parent_checkpoint_id)
    graph_input: Optional[Dict[str, Any]] = None
    if request.message is not None:
        graph_input = {
            "messages": [_to_human_message(request.message, None)]
        }

    def event_stream() -> Iterable[bytes]:
        try:
            for event in graph.stream(
                graph_input,
                config=config,
                stream_mode=["messages", "values"],
            ):
                if not isinstance(event, tuple) or len(event) != 2:
                    continue
                mode, payload = event
                if mode == "messages":
                    if not isinstance(payload, tuple) or len(payload) != 2:
                        continue
                    message, _metadata = payload
                    if not isinstance(message, (AIMessage, AIMessageChunk)):
                        continue
                    text_delta = _extract_text_delta(message.content)
                    if not text_delta:
                        continue
                    yield _encode_event(
                        {
                            "type": "token",
                            "message_id": getattr(message, "id", None),
                            "text": text_delta,
                        }
                    )
                    continue

                if mode != "values" or not isinstance(payload, dict):
                    continue

                messages = payload.get("messages", [])
                if not isinstance(messages, list):
                    continue

                checkpoint_by_message_id, parent_checkpoint_by_message_id = (
                    _build_checkpoint_indexes(thread_id)
                )
                snapshot_payload = {
                    "thread_id": thread_id,
                    "checkpoint_id": _checkpoint_id_from_config(
                        graph.get_state(_graph_config(thread_id)).config
                    ),
                    "messages": _serialize_messages(
                        messages, checkpoint_by_message_id, parent_checkpoint_by_message_id
                    ),
                }
                snapshot_payload["messageRepository"] = _build_message_repository(
                    thread_id,
                    checkpoint_by_message_id,
                    parent_checkpoint_by_message_id,
                    snapshot_payload["messages"][-1]["id"]
                    if snapshot_payload["messages"]
                    else None,
                )
                yield _encode_event({"type": "snapshot", **snapshot_payload})

            yield _encode_event({"type": "snapshot", **_get_thread_snapshot(thread_id)})
        except Exception as exc:
            logger.exception("Error streaming thread run")
            yield _encode_event({"type": "error", "error": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
