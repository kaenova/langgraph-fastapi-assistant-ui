"""Thread repository persistence routes.

Persists Assistant UI ExportedMessageRepository keyed by thread_id only.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lib.thread_repo_store import thread_repo_store

logger = logging.getLogger(__name__)

thread_repo_routes = APIRouter()


class RepoPutRequest(BaseModel):
    repo: Dict[str, Any]


@thread_repo_routes.get("/{thread_id}/repo")
async def get_thread_repo(thread_id: str):
    store = thread_repo_store()
    doc = store.get(thread_id)
    if not doc:
        return {"thread_id": thread_id, "repo": None}
    return {"thread_id": thread_id, "repo": doc.get("repo")}


@thread_repo_routes.put("/{thread_id}/repo")
async def put_thread_repo(thread_id: str, payload: RepoPutRequest):
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")
    store = thread_repo_store()
    doc = store.put(thread_id, payload.repo)
    logger.info(f"Upserted thread repo for thread_id={thread_id}")
    return {
        "thread_id": thread_id,
        "updated_at": doc.get("updated_at"),
    }
