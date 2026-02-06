import dotenv
dotenv.load_dotenv()

import os
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

required_env = [
    "COSMOS_ENDPOINT",
    "COSMOS_KEY",
    "COSMOS_DATABASE_NAME",
]

not_present_env = [var for var in required_env if var not in os.environ]
if not_present_env:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(not_present_env)}"
    )

os.environ["COSMOSDB_ENDPOINT"] = os.getenv("COSMOS_ENDPOINT")
os.environ["COSMOSDB_KEY"] = os.getenv("COSMOS_KEY")

# Global cached checkpointer instance
_checkpointer_instance = None

def checkpointer():
    """Get or create the cached checkpointer instance.
    
    This avoids creating a new SQLite connection on every request.
    """
    global _checkpointer_instance
    
    if _checkpointer_instance is not None:
        return _checkpointer_instance
    
    _checkpointer_instance = CosmosDBSaver(database_name=os.getenv("COSMOS_DATABASE_NAME"), container_name='langgraph_checkpoints')
    
    print("✅ Checkpointer initialized and cached")
    
    return _checkpointer_instance