"""Server-side persistence for Assistant UI message repositories.

This stores the exported MessageRepository JSON keyed only by thread_id.
No user scoping is applied (intentional per project requirements).

Repo payloads are stored in Azure Blob Storage to avoid CosmosDB item size limits.
The Cosmos document stores only pointer metadata.
"""

import gzip
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from azure.cosmos import PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.cosmos import CosmosClient as SyncCosmosClient

from lib.blob import delete_file, download_blob_to_bytes, upload_bytes_to_blob

REPO_BLOB_PREFIX = "thread_repos"
REPO_ENCODING_GZIP = "gzip"
REPO_SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)


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
        existing = self.get(thread_id)

        blob_name, sizes, sha256_hex = self._write_repo_blob(
            thread_id, repo, existing
        )

        doc = {
            "id": thread_id,
            "thread_id": thread_id,
            "updated_at": now,
            "repo_blob_name": blob_name,
            "repo_sha256": sha256_hex,
            "repo_bytes": sizes["repo_bytes"],
            "repo_gzip_bytes": sizes["repo_gzip_bytes"],
            "repo_encoding": REPO_ENCODING_GZIP,
            "repo_schema_version": REPO_SCHEMA_VERSION,
        }

        if existing and "created_at" in existing:
            doc["created_at"] = existing["created_at"]
        else:
            doc["created_at"] = now

        self._container.upsert_item(body=doc)

        previous_blob = existing.get("repo_blob_name") if existing else None
        if previous_blob and previous_blob != blob_name:
            try:
                delete_file(previous_blob)
            except Exception:
                # Best-effort cleanup; ignore if deletion fails
                pass

        return doc

    def resolve_repo(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Resolve the stored repo JSON for thread_id."""
        doc = self.get(thread_id)
        if not doc:
            return None

        legacy_repo = doc.get("repo")
        if not isinstance(legacy_repo, dict):
            legacy_repo = None

        blob_name = doc.get("repo_blob_name")
        if isinstance(blob_name, str) and blob_name:
            try:
                return self._read_repo_from_doc(doc)
            except Exception as exc:
                if legacy_repo is not None:
                    logger.warning(
                        "Failed to read repo blob for thread_id=%s; using legacy repo: %s",
                        thread_id,
                        exc,
                    )
                    return legacy_repo
                raise

        # Legacy: inline repo fallback
        if legacy_repo is not None:
            return legacy_repo

        return None

    def _write_repo_blob(
        self, thread_id: str, repo: Dict[str, Any], existing: Optional[Dict[str, Any]]
    ) -> Tuple[str, Dict[str, int], str]:
        """Serialize, compress, hash, and upload repo to blob storage."""
        repo_json = json.dumps(repo, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
        gzipped = gzip.compress(repo_json)
        sha256_hex = hashlib.sha256(repo_json).hexdigest()
        sizes = {"repo_bytes": len(repo_json), "repo_gzip_bytes": len(gzipped)}

        if existing:
            existing_sha = existing.get("repo_sha256")
            existing_blob = existing.get("repo_blob_name")
            if (
                isinstance(existing_sha, str)
                and existing_sha == sha256_hex
                and isinstance(existing_blob, str)
                and existing_blob
            ):
                return existing_blob, sizes, sha256_hex

        blob_name = f"{REPO_BLOB_PREFIX}/{thread_id}/{uuid4().hex}.json.gz"
        upload_bytes_to_blob(
            gzipped,
            blob_name,
            content_type="application/json",
            content_encoding=REPO_ENCODING_GZIP,
        )

        return blob_name, sizes, sha256_hex

    def _read_repo_from_doc(self, doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Load repo JSON from blob pointer if present."""
        blob_name = doc.get("repo_blob_name")
        if not isinstance(blob_name, str) or not blob_name:
            return None

        data = download_blob_to_bytes(blob_name)
        encoding = doc.get("repo_encoding")
        if encoding == REPO_ENCODING_GZIP:
            data = gzip.decompress(data)

        decoded = data.decode("utf-8")
        repo = json.loads(decoded)
        if not isinstance(repo, dict):
            raise ValueError("Repo payload must be a JSON object")
        return repo


_store: ThreadRepoStore | None = None


def thread_repo_store() -> ThreadRepoStore:
    """Get a cached ThreadRepoStore instance."""
    global _store
    if _store is None:
        _store = ThreadRepoStore()
    return _store
