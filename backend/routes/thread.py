"""Thread metadata routes for remote thread-list runtime integration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from lib.thread_store import thread_store

thread_routes = APIRouter()


class ThreadInitializeRequest(BaseModel):
    """Initialize thread request model."""

    thread_id: str = Field(..., alias="threadId")


class ThreadRenameRequest(BaseModel):
    """Rename thread request model."""

    title: str


class ThreadHistoryAppendRequest(BaseModel):
    """Append one history item request model."""

    parent_id: str | None = Field(default=None, alias="parentId")
    message: dict[str, Any]
    run_config: dict[str, Any] | None = Field(default=None, alias="runConfig")


@thread_routes.get("")
async def list_threads() -> dict[str, object]:
    """List all available threads."""
    return {"threads": thread_store.list_threads()}


@thread_routes.get("/{thread_id}")
async def fetch_thread(thread_id: str) -> dict[str, object]:
    """Fetch single thread metadata."""
    thread = thread_store.get_thread_metadata(thread_id)
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )
    return thread


@thread_routes.get("/{thread_id}/history")
async def get_thread_history(thread_id: str) -> dict[str, object]:
    """Get exported message repository for LocalRuntime history adapter."""
    return thread_store.get_history_repository(thread_id)


@thread_routes.post("/{thread_id}/history/append")
async def append_thread_history(
    thread_id: str, payload: ThreadHistoryAppendRequest
) -> dict[str, str]:
    """Append or update one history repository item."""
    thread_store.append_history_item(
        thread_id,
        {
            "parentId": payload.parent_id,
            "message": payload.message,
            "runConfig": payload.run_config,
        },
    )
    return {"message": "History appended"}


@thread_routes.post("/initialize")
async def initialize_thread(
    payload: ThreadInitializeRequest,
) -> dict[str, str | None]:
    """Initialize thread document for a given thread id."""
    return thread_store.initialize_thread(payload.thread_id)


@thread_routes.patch("/{thread_id}/rename")
async def rename_thread(thread_id: str, payload: ThreadRenameRequest) -> dict[str, str]:
    """Rename a thread."""
    if not thread_store.rename_thread(thread_id, payload.title):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )
    return {"message": "Thread renamed"}


@thread_routes.post("/{thread_id}/archive")
async def archive_thread(thread_id: str) -> dict[str, str]:
    """Archive a thread."""
    if not thread_store.set_thread_status(thread_id, "archived"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )
    return {"message": "Thread archived"}


@thread_routes.post("/{thread_id}/unarchive")
async def unarchive_thread(thread_id: str) -> dict[str, str]:
    """Unarchive a thread."""
    if not thread_store.set_thread_status(thread_id, "regular"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )
    return {"message": "Thread unarchived"}


@thread_routes.delete("/{thread_id}")
async def delete_thread(thread_id: str) -> dict[str, str]:
    """Delete a thread."""
    if not thread_store.delete_thread(thread_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )
    return {"message": "Thread deleted"}


@thread_routes.post("/{thread_id}/generate-title")
async def generate_thread_title(thread_id: str) -> dict[str, str]:
    """Generate simple thread title from first user message."""
    document = thread_store.get_document(thread_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )

    title = "New Chat"
    for message in document.get("messages", []):
        if message.get("role") != "user":
            continue
        for part in message.get("content", []):
            if isinstance(part, dict) and part.get("type") == "text":
                raw_title = str(part.get("text", "")).strip()
                if raw_title:
                    title = raw_title[:80]
                    break
        if title != "New Chat":
            break

    thread_store.rename_thread(thread_id, title)
    return {"title": title}
