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
    try:
        repo = store.resolve_repo(thread_id)
    except Exception as exc:
        logger.error(f"Failed to load thread repo for thread_id={thread_id}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to load thread repo")

    if repo is None:
        return {"thread_id": thread_id, "repo": None}
    return {"thread_id": thread_id, "repo": repo}


@thread_repo_routes.put("/{thread_id}/repo")
async def put_thread_repo(thread_id: str, payload: RepoPutRequest):
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")
    store = thread_repo_store()
    try:
        doc = store.put(thread_id, payload.repo)
    except Exception as exc:
        logger.error(f"Failed to upsert thread repo for thread_id={thread_id}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to save thread repo")
    logger.info(
        "Upserted thread repo for thread_id=%s repo_bytes=%s repo_gzip_bytes=%s",
        thread_id,
        doc.get("repo_bytes"),
        doc.get("repo_gzip_bytes"),
    )
    return {"thread_id": thread_id, "updated_at": doc.get("updated_at")}
