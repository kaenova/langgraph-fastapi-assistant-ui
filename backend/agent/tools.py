"""Tools for the LangGraph agent.

This module provides various tools that can be used by the LangGraph agent:

1. get_current_time: Get current date and time
2. SessionsPythonREPLTool: Execute Python code (requires AZURE_SESSIONPOOL_ENDPOINT)
3. web_search: Perform web search using SearxNG (requires SEARXNG_URL)
4. Azure AI Search tools (require AZURE_SEARCH_* environment variables):
   - azure_search_documents: Text-based search
   - azure_search_semantic: Semantic search with AI ranking
   - azure_search_filter: Search with OData filters
   - azure_search_vector: Vector similarity search (requires Azure OpenAI)

Environment Variables Required:
- AZURE_SEARCH_ENDPOINT: Your Azure AI Search service endpoint
- AZURE_SEARCH_KEY: Your Azure AI Search admin key
- AZURE_SEARCH_INDEX_NAME: The search index to query
- AZURE_SEARCH_SEMANTIC_CONFIG: Semantic configuration name (optional, defaults to 'default')
- AZURE_SEARCH_VECTOR_FIELD: Vector field name (optional, defaults to 'content_vector')
- AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint (for vector search)
- AZURE_OPENAI_KEY: Azure OpenAI key (for vector search)
- AZURE_OPENAI_EMBEDDING_MODEL: Embedding model name (optional, defaults to 'text-embedding-ada-002')
"""

import base64
import os
import uuid
from datetime import datetime

import requests
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import load_dotenv
from langchain_core.tools import tool
from openai import AzureOpenAI
from pydantic import BaseModel, Field

# Load environment variables from .env file if present
load_dotenv()


# Pydantic models for tool arguments
class WebSearchInput(BaseModel):
    """Input schema for web_search tool."""

    query: str = Field(..., description="The search query string to look up on the web")


class AzureSearchFilterInput(BaseModel):
    """Input schema for Azure Search filter tool."""

    query: str = Field(..., description="The search query string")
    filter_expression: str = Field(
        ..., description="OData filter expression (e.g., \"userid eq 'mock-user-1'\")"
    )
    top: int = Field(
        5, description="Number of results to return (default: 5, max: 50)", ge=1, le=50
    )


tool_generator = []


# Initialize Azure OpenAI client for DALL-E
def get_dalle_client():
    return AzureOpenAI(
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    )


def get_blob_service_client():
    return BlobServiceClient.from_connection_string(
        os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    )


@tool
def get_current_time() -> str:
    """Get the current date and time.

    Returns:
        str: Current date and time in ISO format
    """
    return datetime.now().isoformat()


tool_generator.append(get_current_time)


# Azure AI Search tools
def _generate_image_flux(prompt: str, size: str) -> bytes:
    """Generate an image using FLUX model via Azure AI Foundry.

    Args:
        prompt: Prompt for image generation
        size: Size of the generated image

    Returns:
        bytes: Generated image bytes
    """
    # Get base endpoint and derive FLUX endpoint
    openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment_name = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT_NAME", "flux.2-pro")

    if not openai_endpoint:
        raise EnvironmentError("AZURE_OPENAI_ENDPOINT environment variable is not set")
    if not api_key:
        raise EnvironmentError(
            "AZURE_OPENAI_API_KEY environment variable is not set for FLUX model"
        )

    # Transform endpoint from openai.azure.com to services.ai.azure.com
    # e.g., https://foundry-poc-chatbot.openai.azure.com -> https://foundry-poc-chatbot.services.ai.azure.com
    flux_endpoint = openai_endpoint.replace(
        ".openai.azure.com", ".services.ai.azure.com"
    )

    # Transform flux endpoint model name to match FLUX naming convention
    # e.g. "FLUX.2-PRO" -> "flux-2-pro"
    endpoint_model_name = deployment_name.replace(".", "-").lower()

    # Build the full URL with the model path
    url = f"{flux_endpoint.rstrip('/')}/providers/blackforestlabs/v1/{endpoint_model_name}?api-version=preview"

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    payload = {"prompt": prompt, "size": size, "n": 1, "model": deployment_name.lower()}

    print(f"  🌐 Calling FLUX API: {url}")
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()

    result = response.json()
    b64_data = result["data"][0]["b64_json"]
    return base64.b64decode(b64_data)


def _generate_image_dalle(prompt: str, size: str, style: str) -> bytes:
    """Generate an image using DALL-E model.

    Args:
        prompt: Prompt for image generation
        size: Size of the generated image
        style: Style of the generated image

    Returns:
        bytes: Generated image bytes
    """
    client = get_dalle_client()
    deployment_name = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT_NAME", "dall-e-3")

    result = client.images.generate(
        model=deployment_name,
        prompt=prompt,
        size=size,
        quality="standard",
        style=style,
        n=1,
        response_format="b64_json",
    )

    b64_data = result.data[0].b64_json
    return base64.b64decode(b64_data)


@tool
def generate_image(prompt: str, size: str, style: str) -> str:
    """Generate an image using DALL-E or FLUX model.

    The model is automatically selected based on the AZURE_OPENAI_DALLE_DEPLOYMENT_NAME
    environment variable. If it contains 'flux', the FLUX model is used; otherwise DALL-E.

    Args:
        prompt: Prompt for image generation
        size: Size of the generated image. Pick one: ['1024x1024', '1792x1024', '1024x1792']
        style: Style of the generated image. Pick one: ['vivid', 'natural'] (only used for DALL-E)

    Returns:
        str: Generated image URL
    """
    try:
        # Validate environment variables
        storage_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME")

        if not storage_connection_string:
            raise EnvironmentError(
                "AZURE_STORAGE_CONNECTION_STRING environment variable is not set"
            )
        if not container_name:
            raise EnvironmentError(
                "AZURE_STORAGE_CONTAINER_NAME environment variable is not set"
            )

        deployment_name = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT_NAME", "dall-e-3")
        is_flux = "flux" in deployment_name.lower()

        print(
            f"🔍 Image generation: prompt='{prompt}', model={'FLUX' if is_flux else 'DALL-E'}"
        )

        # Generate image based on model type
        if is_flux:
            image_bytes = _generate_image_flux(prompt, size)
        else:
            image_bytes = _generate_image_dalle(prompt, size, style)

        print(f"  ✅ Image generated (size: {len(image_bytes)} bytes)")

        # Upload to Blob Storage
        blob_service = get_blob_service_client()
        blob_name = f"images/{uuid.uuid4()}.png"

        # Get blob client and upload with public content type
        blob_client = blob_service.get_blob_client(
            container=container_name, blob=blob_name
        )
        blob_client.upload_blob(
            image_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type="image/png"),
        )
        print(f"  ✅ Image uploaded to blob: {blob_name}")

        # Return the public URL
        image_url = blob_client.url
        print(f"  ✅ Image URL: {image_url}")
        return image_url

    except EnvironmentError as e:
        error_msg = f"Environment error: {str(e)}"
        print(f"  ❌ {error_msg}")
        import traceback

        print(traceback.format_exc())
        return error_msg
    except Exception as e:
        error_msg = f"Error generating image: {str(e)}"
        print(f"  ❌ {error_msg}")
        import traceback

        print(traceback.format_exc())
        return error_msg


tool_generator.append(generate_image)


@tool
def current_weather(city: str) -> str:
    """Checking current weather on the city

    Args:
        city: The city to check for the weather.

    Returns:
        str: Information on current citi's weather.
    """
    return f"{city} is sunny right now!"


tool_generator.append(current_weather)


print(f"✓ Tools loaded. Tools available: {[tool.name for tool in tool_generator]}")
# List of available tools
AVAILABLE_TOOLS = tool_generator
