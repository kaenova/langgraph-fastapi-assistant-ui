"""Azure Blob Storage operations."""

import os
from datetime import datetime, timedelta
from typing import BinaryIO

from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas


def get_blob_service_client() -> BlobServiceClient:
    """Get Azure Blob Service client."""
    return BlobServiceClient.from_connection_string(
        os.getenv("AZURE_STORAGE_CONNECTION_STRING", "default")
    )


def upload_file_to_blob(file: bytes, blob_name: str) -> str:
    """
    Upload a file to Azure Blob Storage.

    Args:
        file: File object to upload
        blob_name: Name for the blob in storage

    Returns:
        str: The blob name
    """
    blob_service_client = get_blob_service_client()
    container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "default")

    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )

    # Upload the file
    blob_client.upload_blob(file, overwrite=True)

    return blob_name


def get_file_link(blob_name: str) -> str:
    """
    Get a permanent link to a blob (without SAS token).

    Args:
        blob_name: Name of the blob

    Returns:
        str: URL to the blob
    """
    blob_service_client = get_blob_service_client()
    container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "default")

    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )

    return blob_client.url


def get_file_temporary_link(blob_name: str, expiry: int = 3600) -> str:
    """
    Get a temporary link to a blob with SAS token.

    Args:
        blob_name: Name of the blob
        expiry: Expiry time in seconds (default: 1 hour)

    Returns:
        str: URL with SAS token
    """
    blob_service_client = get_blob_service_client()
    container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "default")

    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )

    account_name = blob_service_client.account_name
    if account_name is None:
        raise ValueError("Account Name is None")

    # Generate SAS token
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=blob_service_client.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(seconds=expiry),
    )

    # Construct URL with SAS token
    return f"{blob_client.url}?{sas_token}"


def delete_file(blob_name: str) -> bool:
    """
    Delete a file from Azure Blob Storage.

    Args:
        blob_name: Name of the blob to delete

    Returns:
        bool: True if deleted successfully
    """
    blob_service_client = get_blob_service_client()
    container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "default")

    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )

    blob_client.delete_blob()

    return True
