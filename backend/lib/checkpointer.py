"""Checkpointer factory with CosmosDB or in-memory fallback.

Supports two CosmosDB checkpointer implementations:
- Existing: `langgraph-checkpoint-cosmosdb`
- New: `langgraph-cosmosdb-checkpointer`
"""

import importlib
import os
from typing import Any

import dotenv
from langgraph.checkpoint.memory import InMemorySaver

dotenv.load_dotenv()

# Toggle between the existing and the new CosmosDB checkpointer.
# Prefer configuring via `.env`: NEW_CHECKPOINTERS=true/false
NEW_CHECKPOINTERS = os.getenv("NEW_CHECKPOINTERS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

try:
    from langgraph_checkpoint_cosmosdb import CosmosDBSaver as CosmosDBSaverV1
except ImportError:  # pragma: no cover - optional dependency
    CosmosDBSaverV1 = None

# Global cached checkpointer instance
_checkpointer_instance: Any | None = None


def _has_cosmos_configuration() -> bool:
    """Return True if all required Cosmos env vars are configured."""
    required_env = [
        "COSMOS_ENDPOINT",
        "COSMOS_KEY",
        "COSMOS_DATABASE_NAME",
    ]
    return all(os.getenv(var) for var in required_env)


def _cosmos_checkpointer_v2() -> Any:
    """Create the new CosmosDB checkpointer (langgraph-cosmosdb-checkpointer)."""
    try:
        from azure.cosmos import CosmosClient, PartitionKey

        pkg = importlib.import_module("langgraph_cosmosdb_checkpointer")
        cosmosdb = importlib.import_module("langgraph_cosmosdb_checkpointer.cosmosdb")
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "New CosmosDB checkpointer dependencies are not installed"
        ) from e

    CosmosDBSaverV2 = getattr(pkg, "CosmosDBSaver")
    CosmosDBSettings = getattr(pkg, "CosmosDBSettings")
    checkpoint_indexing_policy = getattr(cosmosdb, "_checkpoint_indexing_policy")
    writes_indexing_policy = getattr(cosmosdb, "_writes_indexing_policy")
    blob_indexing_policy = getattr(cosmosdb, "_blob_indexing_policy")

    endpoint = os.getenv("COSMOS_ENDPOINT", "")
    key = os.getenv("COSMOS_KEY", "")
    database_name = os.getenv("COSMOS_DATABASE_NAME", "langgraph")

    # Keep v2 containers separate by default to avoid mixing schemas.
    settings = CosmosDBSettings(
        database_name=database_name,
        checkpoint_container_name=os.getenv(
            "COSMOS_CHECKPOINT_CONTAINER_NAME",
            "langgraph_checkpoints_v2",
        ),
        writes_container_name=os.getenv(
            "COSMOS_WRITES_CONTAINER_NAME",
            "langgraph_writes_v2",
        ),
        blob_container_name=os.getenv(
            "COSMOS_BLOBS_CONTAINER_NAME",
            "langgraph_checkpoint_blobs_v2",
        ),
        create_containers=True,
    )

    client = CosmosClient(endpoint, credential=key)

    database = client.create_database_if_not_exists(id=settings.database_name)
    checkpoints = database.create_container_if_not_exists(
        id=settings.checkpoint_container_name,
        partition_key=PartitionKey(path="/thread_id"),
        indexing_policy=checkpoint_indexing_policy(),
    )
    writes = database.create_container_if_not_exists(
        id=settings.writes_container_name,
        partition_key=PartitionKey(path="/thread_id"),
        indexing_policy=writes_indexing_policy(),
    )

    # Work around CosmosDB rejecting indexing paths that mention system property `id`.
    blob_policy = blob_indexing_policy()
    blob_policy["includedPaths"] = [
        p for p in blob_policy.get("includedPaths", []) if p.get("path") != "/id/?"
    ]
    blobs = database.create_container_if_not_exists(
        id=settings.blob_container_name,
        partition_key=PartitionKey(path="/thread_id"),
        indexing_policy=blob_policy,
    )
    return CosmosDBSaverV2(
        checkpoints,
        writes,
        blobs,
        settings=settings,
        client=client,
        owns_client=True,
    )


def _cosmos_checkpointer_v1() -> Any:
    """Create the existing CosmosDB checkpointer (langgraph-checkpoint-cosmosdb)."""
    if CosmosDBSaverV1 is None:
        raise RuntimeError("Existing CosmosDB checkpointer dependency is not installed")

    # Backwards-compatible env var names expected by `langgraph_checkpoint_cosmosdb`.
    os.environ["COSMOSDB_ENDPOINT"] = os.getenv("COSMOS_ENDPOINT", "")
    os.environ["COSMOSDB_KEY"] = os.getenv("COSMOS_KEY", "")
    return CosmosDBSaverV1(
        database_name=os.getenv("COSMOS_DATABASE_NAME", "default"),
        container_name="langgraph_checkpoints",
    )


def checkpointer() -> Any:
    """Get or create the cached checkpointer instance."""
    global _checkpointer_instance

    if _checkpointer_instance is not None:
        return _checkpointer_instance

    if _has_cosmos_configuration():
        if NEW_CHECKPOINTERS:
            try:
                _checkpointer_instance = _cosmos_checkpointer_v2()
                print("✅ Using CosmosDB checkpointer (v2)")
                return _checkpointer_instance
            except Exception as e:
                print(f"⚠️ Failed to init CosmosDB checkpointer (v2): {e}")

        try:
            _checkpointer_instance = _cosmos_checkpointer_v1()
            print("✅ Using CosmosDB checkpointer (v1)")
            return _checkpointer_instance
        except Exception as e:
            print(f"⚠️ Failed to init CosmosDB checkpointer (v1): {e}")

    _checkpointer_instance = InMemorySaver()
    print("✅ Using in-memory checkpointer")
    return _checkpointer_instance
