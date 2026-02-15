"""Server-side persistence for Assistant UI message repositories.

This stores the exported MessageRepository JSON keyed only by thread_id.
No user scoping is applied (intentional per project requirements).
"""

import os
import time
from typing import Any, Dict, Optional

from azure.cosmos import PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.cosmos import CosmosClient as SyncCosmosClient


class ThreadRepoStore:
    """Cosmos-backed store for Assistant UI ExportedMessageRepository."""

    def __init__(self) -> None:
        endpoint = os.getenv("COSMOS_ENDPOINT")
        key = os.getenv("COSMOS_KEY")
        database_name = os.getenv("COSMOS_DATABASE_NAME", "chatbot-db")
        if not endpoint or not key:
            raise ValueError("COSMOS_ENDPOINT and COSMOS_KEY must be set")

        self._client = SyncCosmosClient(endpoint, key)
        self._db = self._client.create_database_if_not_exists(id=database_name)
        self._container = self._db.create_container_if_not_exists(
            id="thread_repos",
            partition_key=PartitionKey(path="/thread_id"),
        )

    def get(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Fetch repository document for thread_id."""
        try:
            return self._container.read_item(item=thread_id, partition_key=thread_id)
        except CosmosResourceNotFoundError:
            return None

    def put(self, thread_id: str, repo: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert repository document for thread_id."""
        now = int(time.time())
        doc = {
            "id": thread_id,
            "thread_id": thread_id,
            "updated_at": now,
            "repo": repo,
        }

        existing = self.get(thread_id)
        if existing and "created_at" in existing:
            doc["created_at"] = existing["created_at"]
        else:
            doc["created_at"] = now

        self._container.upsert_item(body=doc)
        return doc


_store: ThreadRepoStore | None = None


def thread_repo_store() -> ThreadRepoStore:
    """Get a cached ThreadRepoStore instance."""
    global _store
    if _store is None:
        _store = ThreadRepoStore()
    return _store
