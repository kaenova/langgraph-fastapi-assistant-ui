"""Thread management routes."""

from __future__ import annotations

import copy
import time
import uuid
from threading import Lock
from typing import Any, Dict, Optional, TypedDict

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from lib.database import db_manager

thread_routes = APIRouter()

DEFAULT_USER_ID = "default"


class _ThreadRecord(TypedDict):
    """Internal thread record."""

    thread_id: str
    status: str
    title: Optional[str]
    created_at: int
    updated_at: int
    state: Dict[str, Any]
    durable: bool


class ThreadCreateRequest(BaseModel):
    """Create thread request."""

    thread_id: Optional[str] = None
    title: Optional[str] = None


class ThreadRenameRequest(BaseModel):
    """Rename thread request."""

    title: str


class ThreadMetadataResponse(BaseModel):
    """Thread metadata response."""

    thread_id: str
    status: str
    title: Optional[str]
    created_at: int
    updated_at: int


class ThreadListResponse(BaseModel):
    """Thread list response."""

    threads: list[ThreadMetadataResponse]


class ThreadStateResponse(ThreadMetadataResponse):
    """Thread state response."""

    state: Dict[str, Any] = Field(default_factory=dict)


_THREAD_STORE: Dict[str, Dict[str, _ThreadRecord]] = {}
_THREAD_STORE_LOCK = Lock()


def _now() -> int:
    """Return current epoch timestamp."""

    return int(time.time())


def _resolve_userid(userid: str | None) -> str:
    """Resolve userid from header with a safe default."""

    return userid or DEFAULT_USER_ID


def _sync_durable_threads(userid: str) -> None:
    """Best-effort sync from durable conversation metadata."""

    try:
        conversations = db_manager.get_user_conversations(userid)
    except Exception:
        return

    with _THREAD_STORE_LOCK:
        user_threads = _THREAD_STORE.setdefault(userid, {})
        for conversation in conversations:
            existing = user_threads.get(conversation.id)
            if existing is None:
                user_threads[conversation.id] = {
                    "thread_id": conversation.id,
                    "status": "regular",
                    "title": conversation.title,
                    "created_at": conversation.created_at,
                    "updated_at": conversation.created_at,
                    "state": {},
                    "durable": True,
                }
                continue

            existing["durable"] = True
            existing["created_at"] = conversation.created_at
            if existing["title"] is None:
                existing["title"] = conversation.title


def _load_durable_state(thread_id: str) -> Dict[str, Any] | None:
    """Best-effort load of checkpointed thread state."""

    try:
        from lib.checkpointer import checkpointer
    except Exception:
        return None

    try:
        saver = checkpointer()
        config = {"configurable": {"thread_id": thread_id}}

        if hasattr(saver, "get_tuple"):
            checkpoint_tuple = saver.get_tuple(config)
            if checkpoint_tuple is not None:
                checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
                if isinstance(checkpoint, dict):
                    channel_values = checkpoint.get("channel_values")
                    if isinstance(channel_values, dict):
                        return copy.deepcopy(channel_values)
                    return copy.deepcopy(checkpoint)

        if hasattr(saver, "get"):
            checkpoint = saver.get(config)
            if isinstance(checkpoint, dict):
                return copy.deepcopy(checkpoint)
    except Exception:
        return None

    return None


def _thread_to_response(record: _ThreadRecord) -> ThreadMetadataResponse:
    """Convert internal thread record to response model."""

    return ThreadMetadataResponse(
        thread_id=record["thread_id"],
        status=record["status"],
        title=record["title"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _get_thread(userid: str, thread_id: str) -> _ThreadRecord | None:
    """Get thread record for a user."""

    _sync_durable_threads(userid)
    with _THREAD_STORE_LOCK:
        record = _THREAD_STORE.get(userid, {}).get(thread_id)
        if record is None:
            return None
        return copy.deepcopy(record)


def _require_thread(userid: str, thread_id: str) -> _ThreadRecord:
    """Get thread record or raise 404."""

    record = _get_thread(userid, thread_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread not found: {thread_id}",
        )
    return record


def resolve_userid(userid: str | None) -> str:
    """Resolve userid from header with default fallback."""

    return _resolve_userid(userid)


def get_thread_record_snapshot(userid: str, thread_id: str) -> Dict[str, Any]:
    """Get a thread metadata snapshot for internal route usage."""

    record = _require_thread(userid, thread_id)
    return {
        "thread_id": record["thread_id"],
        "status": record["status"],
        "title": record["title"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def get_thread_state_snapshot(userid: str, thread_id: str) -> Dict[str, Any]:
    """Get persisted thread state for internal route usage."""

    record = _require_thread(userid, thread_id)
    state_payload = copy.deepcopy(record["state"])
    if state_payload:
        return state_payload

    durable_state = _load_durable_state(thread_id)
    if durable_state is None:
        return {}

    with _THREAD_STORE_LOCK:
        if thread_id in _THREAD_STORE.get(userid, {}):
            _THREAD_STORE[userid][thread_id]["state"] = copy.deepcopy(durable_state)
    return copy.deepcopy(durable_state)


def update_thread_state(userid: str, thread_id: str, state: Dict[str, Any]) -> None:
    """Persist thread state for internal route usage."""

    _require_thread(userid, thread_id)
    with _THREAD_STORE_LOCK:
        stored_record = _THREAD_STORE[userid][thread_id]
        stored_record["state"] = copy.deepcopy(state)
        stored_record["updated_at"] = _now()


@thread_routes.post("", response_model=ThreadMetadataResponse, status_code=status.HTTP_201_CREATED)
def create_thread(
    payload: ThreadCreateRequest,
    userid: str | None = Header(None),
) -> ThreadMetadataResponse:
    """Create a thread."""

    user_id = _resolve_userid(userid)
    thread_id = payload.thread_id or str(uuid.uuid4())
    title = payload.title or "New Thread"

    if _get_thread(user_id, thread_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Thread already exists: {thread_id}",
        )

    created_at = _now()
    durable = False

    try:
        conversation = db_manager.create_conversation(thread_id, title, user_id)
        created_at = conversation.created_at
        title = conversation.title
        durable = True
    except Exception:
        durable = False

    record: _ThreadRecord = {
        "thread_id": thread_id,
        "status": "regular",
        "title": title,
        "created_at": created_at,
        "updated_at": created_at,
        "state": {},
        "durable": durable,
    }

    with _THREAD_STORE_LOCK:
        _THREAD_STORE.setdefault(user_id, {})[thread_id] = record

    return _thread_to_response(record)


@thread_routes.get("", response_model=ThreadListResponse)
def list_threads(
    userid: str | None = Header(None),
    include_archived: bool = Query(True),
) -> ThreadListResponse:
    """List threads for a user."""

    user_id = _resolve_userid(userid)
    _sync_durable_threads(user_id)

    with _THREAD_STORE_LOCK:
        records = [copy.deepcopy(record) for record in _THREAD_STORE.get(user_id, {}).values()]

    if not include_archived:
        records = [record for record in records if record["status"] != "archived"]

    records.sort(key=lambda record: record["updated_at"], reverse=True)
    return ThreadListResponse(threads=[_thread_to_response(record) for record in records])


@thread_routes.get("/{thread_id}/state", response_model=ThreadStateResponse)
def get_thread_state(
    thread_id: str,
    userid: str | None = Header(None),
) -> ThreadStateResponse:
    """Get thread state."""

    user_id = _resolve_userid(userid)
    record = _require_thread(user_id, thread_id)

    state_payload = copy.deepcopy(record["state"])
    if not state_payload:
        durable_state = _load_durable_state(thread_id)
        if durable_state is not None:
            state_payload = durable_state
            with _THREAD_STORE_LOCK:
                if thread_id in _THREAD_STORE.get(user_id, {}):
                    _THREAD_STORE[user_id][thread_id]["state"] = copy.deepcopy(durable_state)

    return ThreadStateResponse(
        thread_id=record["thread_id"],
        status=record["status"],
        title=record["title"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        state=state_payload,
    )


@thread_routes.patch("/{thread_id}/rename", response_model=ThreadMetadataResponse)
def rename_thread(
    thread_id: str,
    payload: ThreadRenameRequest,
    userid: str | None = Header(None),
) -> ThreadMetadataResponse:
    """Rename a thread."""

    user_id = _resolve_userid(userid)
    title = payload.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="title must not be empty",
        )

    record = _require_thread(user_id, thread_id)

    if record["durable"]:
        try:
            db_manager.rename_conversation(thread_id, user_id, title)
        except Exception:
            pass

    updated_at = _now()
    with _THREAD_STORE_LOCK:
        stored_record = _THREAD_STORE[user_id][thread_id]
        stored_record["title"] = title
        stored_record["updated_at"] = updated_at
        record = copy.deepcopy(stored_record)

    return _thread_to_response(record)


@thread_routes.post("/{thread_id}/archive", response_model=ThreadMetadataResponse)
def archive_thread(
    thread_id: str,
    userid: str | None = Header(None),
) -> ThreadMetadataResponse:
    """Archive a thread."""

    user_id = _resolve_userid(userid)
    _require_thread(user_id, thread_id)

    with _THREAD_STORE_LOCK:
        stored_record = _THREAD_STORE[user_id][thread_id]
        stored_record["status"] = "archived"
        stored_record["updated_at"] = _now()
        record = copy.deepcopy(stored_record)

    return _thread_to_response(record)


@thread_routes.delete("/{thread_id}", response_model=ThreadMetadataResponse)
def delete_thread(
    thread_id: str,
    userid: str | None = Header(None),
) -> ThreadMetadataResponse:
    """Delete a thread."""

    user_id = _resolve_userid(userid)
    record = _require_thread(user_id, thread_id)

    if record["durable"]:
        try:
            db_manager.delete_conversation(thread_id, user_id)
        except Exception:
            pass

    deleted_record = copy.deepcopy(record)
    deleted_record["status"] = "deleted"
    deleted_record["updated_at"] = _now()

    with _THREAD_STORE_LOCK:
        if user_id in _THREAD_STORE:
            _THREAD_STORE[user_id].pop(thread_id, None)

    return _thread_to_response(deleted_record)
