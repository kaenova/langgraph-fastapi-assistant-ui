"""Message compaction route for summary generation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from agent.compaction_graph import compact_messages
from agent.utils import change_file_to_url, sanitize_and_validate_messages
from routes.chat import _to_langchain_messages


compaction_routes = APIRouter()


class CompactRequest(BaseModel):
    """Compaction request payload."""

    messages: list[dict[str, Any]]


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


@compaction_routes.post("")
async def compact(payload: CompactRequest) -> dict[str, Any]:
    """Compact incoming messages into one summary assistant message."""
    if not payload.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="messages is required",
        )

    langchain_messages = _to_langchain_messages(payload.messages)
    langchain_messages = sanitize_and_validate_messages(langchain_messages)
    langchain_messages = change_file_to_url(langchain_messages)
    summary = await compact_messages(langchain_messages)

    compacted_message = {
        "id": f"assistant-{uuid.uuid4()}",
        "role": "assistant",
        "content": [{"type": "text", "text": summary}],
        "status": {"type": "complete", "reason": "stop"},
        "metadata": {"custom": {"compaction": True}},
        "createdAt": _now_iso(),
    }
    return {"message": compacted_message}
