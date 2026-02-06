"""LangGraph utility functions for message processing."""

import re
from typing import List

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from lib.blob import get_file_temporary_link
from lib.database import db_manager


def change_file_to_url(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Convert chatbot://{id} URLs to temporary blob URLs with SAS tokens in all messages.

    This function inspects all messages and looks for image_url content with chatbot:// URLs,
    then replaces them with temporary blob URLs (valid for 1 hour) before sending to AI.

    Args:
        messages: List of BaseMessage objects that may contain chatbot:// URLs

    Returns:
        List[BaseMessage]: Messages with chatbot:// URLs replaced by blob URLs with SAS tokens
    """
    processed_messages = []

    for message in messages:
        # Create a copy of the message to avoid modifying the original
        if isinstance(message, HumanMessage):
            processed_message = process_human_message(message)
        elif isinstance(message, AIMessage):
            processed_message = process_ai_message(message)
        elif isinstance(message, SystemMessage):
            # System messages typically don't have images
            processed_message = message
        else:
            # For other message types, keep as is
            processed_message = message

        processed_messages.append(processed_message)

    return processed_messages


def process_human_message(message: HumanMessage) -> HumanMessage:
    """
    Process HumanMessage to convert chatbot:// URLs to blob URLs.

    Args:
        message: HumanMessage that may contain chatbot:// URLs

    Returns:
        HumanMessage: Message with converted URLs
    """
    # Check if message has content attribute
    if not hasattr(message, "content"):
        return message

    content = message.content

    # If content is a string, no images to process
    if isinstance(content, str):
        return message

    # If content is a list (multimodal content)
    if isinstance(content, list):
        new_content = []

        for item in content:
            if isinstance(item, dict):
                # Check if this is an image_url type
                if item.get("type") == "image_url":
                    new_item = process_image_url_item(item)
                    new_content.append(new_item)
                else:
                    # Keep other content types as is (text, etc.)
                    new_content.append(item)
            else:
                new_content.append(item)

        # Create new HumanMessage with updated content
        return HumanMessage(
            content=new_content,
            additional_kwargs=message.additional_kwargs
            if hasattr(message, "additional_kwargs")
            else {},
            id=message.id if hasattr(message, "id") else None,
        )

    return message


def process_ai_message(message: AIMessage) -> AIMessage:
    """
    Process AIMessage to convert chatbot:// URLs to blob URLs.

    Note: AI messages typically don't have chatbot:// URLs, but we process them
    for completeness in case they're present in the content.

    Args:
        message: AIMessage that may contain chatbot:// URLs

    Returns:
        AIMessage: Message with converted URLs
    """
    # Check if message has content attribute
    if not hasattr(message, "content"):
        return message

    content = message.content

    # If content is a string, no images to process
    if isinstance(content, str):
        return message

    # If content is a list (multimodal content)
    if isinstance(content, list):
        new_content = []

        for item in content:
            if isinstance(item, dict):
                # Check if this is an image_url type
                if item.get("type") == "image_url":
                    new_item = process_image_url_item(item)
                    new_content.append(new_item)
                else:
                    new_content.append(item)
            else:
                new_content.append(item)

        # Create new AIMessage with updated content
        return AIMessage(
            content=new_content,
            additional_kwargs=message.additional_kwargs
            if hasattr(message, "additional_kwargs")
            else {},
            id=message.id if hasattr(message, "id") else None,
        )

    return message


def process_image_url_item(item: dict) -> dict:
    """
    Process a single image_url content item to convert chatbot:// URL to blob URL.

    Expected input format:
    {
        "type": "image_url",
        "image_url": {
            "url": "chatbot://{attachment_id}"
        }
    }

    Output format:
    {
        "type": "image_url",
        "image_url": {
            "url": "https://storage.blob.core.windows.net/...?sas_token"
        }
    }

    Args:
        item: Dictionary containing image_url content

    Returns:
        dict: Updated item with blob URL
    """
    try:
        # Get the URL from the nested structure
        image_url_obj = item.get("image_url", {})
        url = image_url_obj.get("url", "")

        # Check if it's a chatbot:// URL
        if url.startswith("chatbot://"):
            # Extract attachment ID and sanitize it
            attachment_id = url.replace("chatbot://", "")
            # Remove trailing slashes and whitespace
            attachment_id = attachment_id.rstrip("/").strip()

            if not attachment_id:
                # Empty ID after sanitization
                print(
                    f"Warning: Empty attachment ID after sanitization from URL: {url}"
                )
                return item

            # Get attachment from database
            attachment = db_manager.get_attachment(attachment_id)

            if attachment:
                # Get temporary blob URL with SAS token (valid for 1 hour)
                blob_url = get_file_temporary_link(attachment.blob_name, expiry=3600)

                # Return updated item with blob URL
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": blob_url,
                        # Preserve any additional fields
                        **{k: v for k, v in image_url_obj.items() if k != "url"},
                    },
                }
            else:
                # Attachment not found, log warning and return original
                print(f"Warning: Attachment not found for ID: {attachment_id}")
                return item
        else:
            # Not a chatbot:// URL, return as is (might be http/https URL)
            return item

    except Exception as e:
        # If any error occurs, log it and return original item
        print(f"Error processing image_url item: {e}")
        return item


def extract_file_ids_from_messages(messages: List[BaseMessage]) -> List[str]:
    """
    Extract all chatbot:// IDs from messages.

    Useful for debugging or tracking which files are being used.

    Args:
        messages: List of BaseMessage objects

    Returns:
        List[str]: List of attachment IDs found in messages
    """
    file_ids = []

    for message in messages:
        if not hasattr(message, "content"):
            continue

        content = message.content

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("chatbot://"):
                        file_id = url.replace("chatbot://", "")
                        file_ids.append(file_id)

    return file_ids


def get_text_from_contents(contents: list[dict]) -> str:
    """Extract text from message contents."""
    if isinstance(contents, list):
        texts = [item["text"] for item in contents if item["type"] == "text"]
        return "\n".join(texts)
    elif isinstance(contents, str):
        return contents
    return ""


def sanitize_and_validate_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Sanitize and validate message list to ensure proper tool call/response pairing.

    This function:
    1. Removes incomplete tool call sequences (AIMessage with tool_calls but no ToolMessage responses)
    2. Ensures all tool calls have corresponding tool responses
    3. Maintains message order and conversation flow
    4. Removes orphaned ToolMessages (tool responses without preceding tool calls)

    Args:
        messages: List of BaseMessage objects from the conversation state

    Returns:
        List[BaseMessage]: Sanitized list of messages safe for OpenAI API
    """
    if not messages:
        return messages

    sanitized_messages = []
    i = 0

    while i < len(messages):
        current_message = messages[i]

        # Handle AIMessage with tool calls
        if (
            isinstance(current_message, AIMessage)
            and hasattr(current_message, "tool_calls")
            and current_message.tool_calls
        ):
            tool_call_ids = {tc["id"] for tc in current_message.tool_calls}

            # Look ahead to find corresponding ToolMessages
            j = i + 1
            found_tool_responses = set()
            tool_messages = []

            # Collect all consecutive ToolMessages that respond to this AIMessage
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                tool_msg = messages[j]
                if (
                    hasattr(tool_msg, "tool_call_id")
                    and tool_msg.tool_call_id in tool_call_ids
                ):
                    found_tool_responses.add(tool_msg.tool_call_id)
                    tool_messages.append(tool_msg)
                j += 1

            # Only include this AIMessage and its ToolMessages if ALL tool calls have responses
            if found_tool_responses == tool_call_ids:
                sanitized_messages.append(current_message)
                sanitized_messages.extend(tool_messages)
                i = j  # Skip past the tool messages we just processed
            else:
                # Skip this incomplete tool call sequence
                print(
                    f"Skipping incomplete tool call sequence. Missing responses for: {tool_call_ids - found_tool_responses}"
                )
                i = j  # Skip past any partial tool messages

        # Handle other message types (HumanMessage, SystemMessage, AIMessage without tool calls)
        elif isinstance(current_message, (HumanMessage, SystemMessage)) or (
            isinstance(current_message, AIMessage)
            and (
                not hasattr(current_message, "tool_calls")
                or not current_message.tool_calls
            )
        ):
            sanitized_messages.append(current_message)
            i += 1

        # Skip orphaned ToolMessages (shouldn't happen with proper sequencing, but safety check)
        elif isinstance(current_message, ToolMessage):
            print(f"Skipping orphaned ToolMessage: {current_message.tool_call_id}")
            i += 1

        else:
            # Unknown message type, skip
            print(f"Skipping unknown message type: {type(current_message)}")
            i += 1

    return sanitized_messages


def validate_message_sequence(messages: List[BaseMessage]) -> bool:
    """
    Validate that the message sequence follows OpenAI API requirements.

    Args:
        messages: List of BaseMessage objects

    Returns:
        bool: True if valid, False otherwise
    """
    if not messages:
        return True

    for i, message in enumerate(messages):
        if (
            isinstance(message, AIMessage)
            and hasattr(message, "tool_calls")
            and message.tool_calls
        ):
            tool_call_ids = {tc["id"] for tc in message.tool_calls}

            # Check that the next messages are ToolMessages responding to all tool calls
            j = i + 1
            found_responses = set()

            while j < len(messages) and isinstance(messages[j], ToolMessage):
                tool_msg = messages[j]
                if (
                    hasattr(tool_msg, "tool_call_id")
                    and tool_msg.tool_call_id in tool_call_ids
                ):
                    found_responses.add(tool_msg.tool_call_id)
                j += 1

            if found_responses != tool_call_ids:
                print(
                    f"Validation failed: Missing tool responses for {tool_call_ids - found_responses}"
                )
                return False

    return True


def get_last_complete_conversation_turn(
    messages: List[BaseMessage],
) -> List[BaseMessage]:
    """
    Get messages up to the last complete conversation turn.
    A complete turn ends with either:
    - A HumanMessage
    - An AIMessage without tool calls (final response)
    - A complete tool call sequence (AIMessage + all ToolMessages)

    Args:
        messages: List of BaseMessage objects

    Returns:
        List[BaseMessage]: Messages up to last complete turn
    """
    if not messages:
        return messages

    # Work backwards to find the last complete turn
    for i in range(len(messages) - 1, -1, -1):
        current_message = messages[i]

        # If we find a HumanMessage, this is a complete turn
        if isinstance(current_message, HumanMessage):
            return messages[: i + 1]

        # If we find an AIMessage without tool calls, this is a complete response
        if isinstance(current_message, AIMessage) and (
            not hasattr(current_message, "tool_calls") or not current_message.tool_calls
        ):
            return messages[: i + 1]

        # If we find a ToolMessage, look for the corresponding AIMessage
        if isinstance(current_message, ToolMessage):
            # Find the AIMessage that initiated this tool call
            for j in range(i - 1, -1, -1):
                if (
                    isinstance(messages[j], AIMessage)
                    and hasattr(messages[j], "tool_calls")
                    and messages[j].tool_calls
                ):
                    # Check if this tool call sequence is complete
                    ai_msg = messages[j]
                    tool_call_ids = {tc["id"] for tc in ai_msg.tool_calls}

                    # Count responses between j+1 and i+1
                    found_responses = set()
                    for k in range(j + 1, i + 1):
                        if isinstance(messages[k], ToolMessage) and hasattr(
                            messages[k], "tool_call_id"
                        ):
                            if messages[k].tool_call_id in tool_call_ids:
                                found_responses.add(messages[k].tool_call_id)

                    if found_responses == tool_call_ids:
                        # Complete tool sequence found
                        return messages[: i + 1]
                    break

    # If no complete turn found, return empty list or first message only
    return messages[:1] if messages else []
