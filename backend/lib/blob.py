"""Azure Blob Storage operations."""

import os
from datetime import datetime, timedelta
from typing import Optional

from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)


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
    return upload_bytes_to_blob(file, blob_name)


def upload_bytes_to_blob(
    file: bytes,
    blob_name: str,
    content_type: Optional[str] = None,
    content_encoding: Optional[str] = None,
) -> str:
    """
    Upload bytes to Azure Blob Storage with optional content settings.

    Args:
        file: Bytes to upload
        blob_name: Name for the blob in storage
        content_type: Optional content type
        content_encoding: Optional content encoding

    Returns:
        str: The blob name
    """
    blob_service_client = get_blob_service_client()
    container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "default")

    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )

    content_settings = None
    if content_type or content_encoding:
        content_settings = ContentSettings(
            content_type=content_type, content_encoding=content_encoding
        )

    blob_client.upload_blob(
        file, overwrite=True, content_settings=content_settings
    )

    return blob_name


def download_blob_to_bytes(blob_name: str) -> bytes:
    """
    Download a blob as bytes.

    Args:
        blob_name: Name of the blob

    Returns:
        bytes: Blob content
    """
    blob_service_client = get_blob_service_client()
    container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "default")

    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )

    downloader = blob_client.download_blob()
    return downloader.readall()


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
