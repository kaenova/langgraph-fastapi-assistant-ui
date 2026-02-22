"""Checkpointer factory with CosmosDB or in-memory fallback."""

import os

import dotenv
from langgraph.checkpoint.memory import InMemorySaver

dotenv.load_dotenv()

try:
    from langgraph_checkpoint_cosmosdb import CosmosDBSaver
except ImportError:  # pragma: no cover - optional dependency
    CosmosDBSaver = None

# Global cached checkpointer instance
_checkpointer_instance = None


def _has_cosmos_configuration() -> bool:
    """Return True if all required Cosmos env vars are configured."""
    required_env = [
        "COSMOS_ENDPOINT",
        "COSMOS_KEY",
        "COSMOS_DATABASE_NAME",
    ]
    return all(os.getenv(var) for var in required_env)


def checkpointer():
    """Get or create the cached checkpointer instance."""
    global _checkpointer_instance

    if _checkpointer_instance is not None:
        return _checkpointer_instance

    if CosmosDBSaver is not None and _has_cosmos_configuration():
        os.environ["COSMOSDB_ENDPOINT"] = os.getenv("COSMOS_ENDPOINT", "")
        os.environ["COSMOSDB_KEY"] = os.getenv("COSMOS_KEY", "")
        _checkpointer_instance = CosmosDBSaver(
            database_name=os.getenv("COSMOS_DATABASE_NAME", "default"),
            container_name="langgraph_checkpoints",
        )
        print("✅ Using CosmosDB checkpointer")
        return _checkpointer_instance

    _checkpointer_instance = InMemorySaver()
    print("✅ Using in-memory checkpointer")
    return _checkpointer_instance
