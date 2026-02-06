"""Database connection factory - Azure Cosmos DB."""
import os
from typing import Optional
from azure.cosmos.aio import CosmosClient
from azure.cosmos import CosmosClient as SyncCosmosClient
from azure.cosmos import PartitionKey

class CosmosDBConnection:
    """Async Cosmos DB connection manager."""
    
    def __init__(self):
        # Cosmos DB configuration from environment variables
        self.endpoint = os.getenv("COSMOS_ENDPOINT")
        self.key = os.getenv("COSMOS_KEY")
        self.database_name = os.getenv("COSMOS_DATABASE_NAME", "chatbot-db")
        
        # Container names
        self.conversations_container = "conversations"
        self.files_container = "files"
        self.attachments_container = "attachments"
        
        # Client instance
        self._client: Optional[CosmosClient] = None
        self._database = None
        self._conversations_container = None
        self._files_container = None
    
    async def init_cosmos_client(self):
        """Initialize Cosmos DB client and containers."""
        if not self._client:
            if not self.endpoint or not self.key:
                raise ValueError("COSMOS_ENDPOINT and COSMOS_KEY must be set in environment variables")
            
            self._client = SyncCosmosClient(self.endpoint, self.key)
            
            # Create database if not exists
            self._database = self._client.create_database_if_not_exists(id=self.database_name)
            
            # Create conversations container with userid as partition key
            self._conversations_container = self._database.create_container_if_not_exists(
                id=self.conversations_container,
                partition_key=PartitionKey(path="/userid")
            )
            
            # Create files container with userid as partition key
            self._files_container = self._database.create_container_if_not_exists(
                id=self.files_container,
                partition_key=PartitionKey(path="/userid")
            )

            # Create attachments container with userid as partition key
            self._database.create_container_if_not_exists(
                id=self.attachments_container,
                partition_key=PartitionKey(path="/userid")
            )
            
            print("✅ Cosmos DB client initialized")
            print(f"   Database: {self.database_name}")
            print(f"   Containers: {self.conversations_container}, {self.files_container}, {self.attachments_container}")
    
    async def close_cosmos_client(self):
        """Close Cosmos DB client."""
        if self._client:
            self._client.close()
            self._client = None
            self._database = None
            self._conversations_container = None
            self._files_container = None
            print("🔌 Cosmos DB client closed")
    
    def get_conversations_container(self):
        """Get conversations container."""
        if not self._conversations_container:
            raise RuntimeError("Cosmos DB client not initialized. Call init_cosmos_client() first.")
        return self._conversations_container
    
    def get_files_container(self):
        """Get files container."""
        if not self._files_container:
            raise RuntimeError("Cosmos DB client not initialized. Call init_cosmos_client() first.")
        return self._files_container
    
    def get_attachments_container(self):
        """Get attachments container."""
        if not self._database:
            raise RuntimeError("Cosmos DB client not initialized. Call init_cosmos_client() first.")
        return self._database.get_container_client(self.attachments_container)

# Global database connection instance
db_connection = CosmosDBConnection()
