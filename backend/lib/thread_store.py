"""Local JSON-backed storage for thread conversation data."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _sanitize_thread_id(thread_id: str) -> str:
    """Sanitize thread id for safe filename usage."""
    cleaned = "".join(ch for ch in thread_id if ch.isalnum() or ch in ("-", "_"))
    return cleaned or "thread"


class ThreadStore:
    """Store thread data in local JSON files."""

    def __init__(self, base_dir: str | None = None) -> None:
        default_dir = Path(__file__).resolve().parent.parent / "data" / "threads"
        self._base_dir = Path(base_dir or os.getenv("THREADS_DIR", str(default_dir)))
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _thread_path(self, thread_id: str) -> Path:
        """Get file path for a thread document."""
        return self._base_dir / f"{_sanitize_thread_id(thread_id)}.json"

    def _default_document(self, thread_id: str) -> dict[str, Any]:
        """Create default thread document."""
        now = _now_iso()
        return {
            "thread": {
                "id": thread_id,
                "title": "New Chat",
                "status": "regular",
                "created_at": now,
                "updated_at": now,
                "last_message_at": now,
            },
            "messages": [],
            "runs": [],
            "tool_calls": [],
            "history": {"headId": None, "messages": []},
        }

    def get_document(self, thread_id: str) -> dict[str, Any] | None:
        """Get full thread document by thread id."""
        with self._lock:
            path = self._thread_path(thread_id)
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

    def save_document(self, thread_id: str, document: dict[str, Any]) -> None:
        """Persist a full thread document."""
        with self._lock:
            path = self._thread_path(thread_id)
            path.write_text(
                json.dumps(document, ensure_ascii=True, indent=2), encoding="utf-8"
            )

    def ensure_document(self, thread_id: str) -> dict[str, Any]:
        """Ensure thread document exists and return it."""
        existing = self.get_document(thread_id)
        if existing is not None:
            return existing
        document = self._default_document(thread_id)
        self.save_document(thread_id, document)
        return document

    def list_threads(self) -> list[dict[str, Any]]:
        """List thread metadata derived from local JSON files."""
        threads: list[dict[str, Any]] = []
        with self._lock:
            for path in self._base_dir.glob("*.json"):
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                    thread = document.get("thread", {})
                    remote_id = str(thread.get("id", path.stem))
                    threads.append(
                        {
                            "status": thread.get("status", "regular"),
                            "remoteId": remote_id,
                            "externalId": None,
                            "title": thread.get("title"),
                        }
                    )
                except (json.JSONDecodeError, OSError):
                    continue

        threads.sort(key=lambda item: item.get("remoteId", ""), reverse=True)
        return threads

    def get_thread_metadata(self, thread_id: str) -> dict[str, Any] | None:
        """Get thread metadata formatted for remote thread list adapter."""
        document = self.get_document(thread_id)
        if document is None:
            return None
        thread = document.get("thread", {})
        return {
            "status": thread.get("status", "regular"),
            "remoteId": thread.get("id", thread_id),
            "externalId": None,
            "title": thread.get("title"),
        }

    def initialize_thread(self, thread_id: str) -> dict[str, str | None]:
        """Initialize thread and return remote mapping."""
        self.ensure_document(thread_id)
        return {"remoteId": thread_id, "externalId": None}

    def rename_thread(self, thread_id: str, title: str) -> bool:
        """Rename a thread."""
        document = self.get_document(thread_id)
        if document is None:
            return False
        thread = document.setdefault("thread", {})
        thread["title"] = title
        thread["updated_at"] = _now_iso()
        self.save_document(thread_id, document)
        return True

    def set_thread_status(self, thread_id: str, status: str) -> bool:
        """Set thread status to regular/archived."""
        document = self.get_document(thread_id)
        if document is None:
            return False
        thread = document.setdefault("thread", {})
        thread["status"] = status
        thread["updated_at"] = _now_iso()
        self.save_document(thread_id, document)
        return True

    def delete_thread(self, thread_id: str) -> bool:
        """Delete thread JSON file."""
        with self._lock:
            path = self._thread_path(thread_id)
            if not path.exists():
                return False
            path.unlink()
            return True

    def get_history_repository(self, thread_id: str) -> dict[str, Any]:
        """Get exported message repository for LocalRuntime history adapter."""
        document = self.ensure_document(thread_id)
        history = document.get("history")
        if (
            isinstance(history, dict)
            and isinstance(history.get("messages"), list)
            and "headId" in history
        ):
            return history

        exported_messages: list[dict[str, Any]] = []
        previous_message_id: str | None = None
        for message in document.get("messages", []):
            if not isinstance(message, dict):
                continue
            message_id = message.get("id")
            if not isinstance(message_id, str):
                continue
            exported_messages.append(
                {
                    "message": message,
                    "parentId": message.get("parentId", previous_message_id),
                }
            )
            previous_message_id = message_id

        repository = {
            "headId": previous_message_id,
            "messages": exported_messages,
        }
        document["history"] = repository
        self.save_document(thread_id, document)
        return repository

    def append_history_item(self, thread_id: str, item: dict[str, Any]) -> None:
        """Append/update one history item from LocalRuntime history adapter."""
        document = self.ensure_document(thread_id)
        history = document.setdefault("history", {"headId": None, "messages": []})
        history_messages = history.setdefault("messages", [])
        message = item.get("message")
        if not isinstance(message, dict):
            return
        message_id = message.get("id")
        if not isinstance(message_id, str):
            return

        replaced = False
        for index, existing in enumerate(history_messages):
            existing_message = existing.get("message", {})
            if isinstance(existing_message, dict) and existing_message.get("id") == message_id:
                history_messages[index] = item
                replaced = True
                break

        if not replaced:
            history_messages.append(item)

        history["headId"] = message_id
        now = _now_iso()
        thread = document.setdefault("thread", {})
        thread["updated_at"] = now
        thread["last_message_at"] = now
        self.save_document(thread_id, document)

    def replace_messages(self, thread_id: str, messages: list[dict[str, Any]]) -> None:
        """Replace thread message snapshot with latest messages."""
        document = self.ensure_document(thread_id)
        document["messages"] = messages
        now = _now_iso()
        thread = document.setdefault("thread", {})
        thread["updated_at"] = now
        thread["last_message_at"] = now
        self.save_document(thread_id, document)

    def append_run(self, thread_id: str, run_record: dict[str, Any]) -> None:
        """Append run metadata into thread document."""
        document = self.ensure_document(thread_id)
        runs = document.setdefault("runs", [])
        runs.append(run_record)
        thread = document.setdefault("thread", {})
        thread["updated_at"] = _now_iso()
        self.save_document(thread_id, document)

    def upsert_tool_call(self, thread_id: str, tool_call: dict[str, Any]) -> None:
        """Upsert tool call metadata for audit/history."""
        document = self.ensure_document(thread_id)
        tool_calls = document.setdefault("tool_calls", [])
        tool_call_id = tool_call.get("id")
        found = False
        for index, item in enumerate(tool_calls):
            if item.get("id") == tool_call_id:
                tool_calls[index] = {**item, **tool_call}
                found = True
                break
        if not found:
            tool_calls.append(tool_call)
        self.save_document(thread_id, document)


thread_store = ThreadStore()
