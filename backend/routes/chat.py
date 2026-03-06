"""Chat run routes with EventStream streaming powered by LangGraph."""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
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


chat_routes = APIRouter()
MAX_INLINE_IMAGE_URL_CHARS = 2_000_000


class RunRequest(BaseModel):
    """Run request payload for local runtime adapter."""

    messages: list[dict[str, Any]]
    run_config: dict[str, Any] = Field(default_factory=dict, alias="runConfig")


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


def _append_user_content_block(part: Any, blocks: list[dict[str, Any]]) -> bool:
    """Append one user content part as LangChain content blocks."""
    if not isinstance(part, dict):
        return False

    part_type = part.get("type")
    if part_type == "text":
        text = str(part.get("text", ""))
        if text:
            blocks.append({"type": "text", "text": text})
        return False

    if part_type == "image":
        image_data = part.get("image")
        if isinstance(image_data, str) and image_data:
            if len(image_data) > MAX_INLINE_IMAGE_URL_CHARS:
                blocks.append(
                    {
                        "type": "text",
                        "text": (
                            "[Image omitted: payload too large for model request. "
                            "Please upload a smaller image.]"
                        ),
                    }
                )
                return False
            blocks.append({"type": "image", "url": image_data})
            return True
        return False

    if part_type == "image_url":
        image_url = part.get("image_url")
        if isinstance(image_url, dict):
            image_data = image_url.get("url")
            if isinstance(image_data, str) and image_data:
                if len(image_data) > MAX_INLINE_IMAGE_URL_CHARS:
                    blocks.append(
                        {
                            "type": "text",
                            "text": (
                                "[Image omitted: payload too large for model request. "
                                "Please upload a smaller image.]"
                            ),
                        }
                    )
                    return False
                blocks.append({"type": "image", "url": image_data})
                return True

    return False


def _to_langchain_user_content_blocks(
    parts: Any, attachments: Any = None
) -> tuple[list[dict[str, Any]], bool]:
    """Convert user content and attachments into LangChain content blocks."""
    if isinstance(parts, str):
        part_list: list[Any] = [{"type": "text", "text": parts}] if parts else []
    elif isinstance(parts, list):
        part_list = parts
    else:
        part_list = []

    content_blocks: list[dict[str, Any]] = []
    has_image = False

    for part in part_list:
        has_image = _append_user_content_block(part, content_blocks) or has_image

    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            attachment_content = attachment.get("content")
            if not isinstance(attachment_content, list):
                continue
            for part in attachment_content:
                has_image = (
                    _append_user_content_block(part, content_blocks) or has_image
                )

    return content_blocks, has_image


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
    """Extract text from AI message or AI message chunk content."""
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


def _to_tool_message_content(value: Any) -> str:
    """Serialize arbitrary tool result values into ToolMessage text content."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)


def _parse_tool_message_content(content: Any) -> Any:
    """Parse ToolMessage content into structured JSON when possible."""
    if not isinstance(content, str):
        return content

    stripped = content.strip()
    if not stripped:
        return ""

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return content


def _to_langchain_messages(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """Convert assistant-ui thread messages into LangChain messages."""
    converted: list[BaseMessage] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content")
        attachments = message.get("attachments")

        if role == "system":
            converted.append(SystemMessage(content=_extract_text_parts(content)))
            continue

        if role == "user":
            user_content_blocks, has_image = _to_langchain_user_content_blocks(
                content,
                attachments,
            )
            if has_image:
                converted.append(
                    HumanMessage(
                        content=cast(
                            list[str | dict[str, Any]],
                            user_content_blocks,
                        )
                    )
                )
                continue

            text = "\n".join(
                str(block.get("text", ""))
                for block in user_content_blocks
                if block.get("type") == "text"
            ).strip()
            converted.append(HumanMessage(content=text))
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
                tool_call_id = str(part.get("toolCallId", "")).strip()
                if not tool_call_id:
                    continue
                converted.append(
                    ToolMessage(
                        content=_to_tool_message_content(part.get("result")),
                        tool_call_id=tool_call_id,
                        status="error" if part.get("isError") else "success",
                    )
                )

    return converted


def _unpack_streamed_message(data: Any) -> tuple[Any, dict[str, Any]]:
    """Unpack LangGraph `messages` stream mode payload."""
    if isinstance(data, tuple) and len(data) == 2:
        message, metadata = data
        if isinstance(metadata, dict):
            return message, metadata
        return message, {}
    return data, {}


@chat_routes.post("/{thread_id}/runs/stream")
async def run_stream(thread_id: str, payload: RunRequest) -> StreamingResponse:
    """Run LangGraph and stream SSE events for the LocalRuntime adapter."""
    del thread_id

    if not payload.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="messages is required",
        )

    run_id = str(uuid.uuid4())
    graph = get_graph()
    langchain_messages = _to_langchain_messages(payload.messages)

    async def event_stream():
        try:
            tool_chunk_states: dict[tuple[int, int], dict[str, Any]] = {}
            text_streamed_steps: set[int] = set()

            async for stream_item in graph.astream(
                {"messages": langchain_messages},
                stream_mode=["messages", "updates"],
            ):
                if not isinstance(stream_item, tuple) or len(stream_item) != 2:
                    continue

                stream_mode, data = stream_item

                if stream_mode == "messages":
                    message, metadata = _unpack_streamed_message(data)
                    raw_step = metadata.get("langgraph_step", 0)
                    try:
                        step = int(raw_step)
                    except (TypeError, ValueError):
                        step = 0

                    if isinstance(message, AIMessageChunk):
                        delta = _extract_chunk_text(message.content)
                        if delta:
                            text_streamed_steps.add(step)
                            yield _event_line({"type": "text_delta", "delta": delta})

                        tool_call_chunks = (
                            getattr(message, "tool_call_chunks", None) or []
                        )
                        for raw_chunk in tool_call_chunks:
                            raw_index = _chunk_field(raw_chunk, "index", 0)
                            try:
                                tool_index = int(raw_index)
                            except (TypeError, ValueError):
                                tool_index = 0

                            chunk_key = (step, tool_index)
                            tool_state = tool_chunk_states.get(chunk_key)
                            if tool_state is None:
                                tool_state = {
                                    "toolCallId": (f"{run_id}:s{step}:t{tool_index}"),
                                    "toolName": "",
                                    "args": {},
                                    "argsText": "",
                                }
                                tool_chunk_states[chunk_key] = tool_state

                            chunk_call_id = _chunk_field(raw_chunk, "id", "")
                            if isinstance(chunk_call_id, str) and chunk_call_id:
                                tool_state["toolCallId"] = chunk_call_id

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
                                    "toolName": tool_state["toolName"]
                                    or f"tool_{tool_index}",
                                    "args": tool_state["args"],
                                    "argsText": tool_state["argsText"],
                                }
                            )
                        continue

                    if isinstance(message, AIMessage):
                        if step not in text_streamed_steps:
                            delta = _extract_chunk_text(message.content)
                            if delta:
                                yield _event_line(
                                    {"type": "text_delta", "delta": delta}
                                )

                        for index, tool_call in enumerate(message.tool_calls):
                            tool_call_id = str(
                                tool_call.get("id") or f"{run_id}:s{step}:t{index}"
                            )
                            tool_name = str(tool_call.get("name") or f"tool_{index}")
                            args = tool_call.get("args", {})
                            if not isinstance(args, dict):
                                args = {}

                            yield _event_line(
                                {
                                    "type": "tool_call",
                                    "toolCallId": tool_call_id,
                                    "toolName": tool_name,
                                    "args": args,
                                    "argsText": json.dumps(args, ensure_ascii=True),
                                }
                            )
                        continue

                if stream_mode == "updates" and isinstance(data, dict):
                    for node_update in data.values():
                        if not isinstance(node_update, dict):
                            continue

                        raw_messages = node_update.get("messages")
                        if not isinstance(raw_messages, list):
                            continue

                        for raw_message in raw_messages:
                            tool_call_id = ""
                            result: Any = None
                            is_error = False

                            if isinstance(raw_message, ToolMessage):
                                tool_call_id = str(raw_message.tool_call_id).strip()
                                result = _parse_tool_message_content(
                                    raw_message.content
                                )
                                is_error = raw_message.status == "error"
                            elif isinstance(raw_message, dict):
                                raw_type = str(raw_message.get("type", "")).strip()
                                if raw_type != "tool":
                                    continue
                                tool_call_id = str(
                                    raw_message.get("tool_call_id")
                                    or raw_message.get("toolCallId")
                                    or ""
                                ).strip()
                                result = _parse_tool_message_content(
                                    raw_message.get("content")
                                )
                                is_error = (
                                    str(raw_message.get("status", "success")) == "error"
                                )
                            else:
                                continue

                            if not tool_call_id:
                                continue

                            yield _event_line(
                                {
                                    "type": "tool_result",
                                    "toolCallId": tool_call_id,
                                    "result": result,
                                    "isError": is_error,
                                }
                            )

            yield _event_line({"type": "done", "status": "complete"})
        except Exception as exc:  # noqa: BLE001
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
