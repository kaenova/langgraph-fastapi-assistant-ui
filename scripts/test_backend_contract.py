"""Validate assistant transport fixture from backend-contract perspective."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "scripts" / "fixtures" / "weather-assistant-transport.json"


def _container_for(next_key: Any) -> Any:
    return [] if isinstance(next_key, int) else {}


def _set_by_path(state: Any, path: list[Any], value: Any) -> None:
    current = state
    for index, key in enumerate(path[:-1]):
        next_key = path[index + 1]
        if isinstance(key, int):
            if not isinstance(current, list):
                raise TypeError(f"Expected list while traversing {path}, got {type(current)}")
            while len(current) <= key:
                current.append(None)
            if current[key] is None:
                current[key] = _container_for(next_key)
            current = current[key]
            continue

        if not isinstance(current, dict):
            raise TypeError(f"Expected dict while traversing {path}, got {type(current)}")
        if key not in current or current[key] is None:
            current[key] = _container_for(next_key)
        current = current[key]

    last_key = path[-1]
    if isinstance(last_key, int):
        if not isinstance(current, list):
            raise TypeError(f"Expected list for final key in {path}")
        while len(current) <= last_key:
            current.append(None)
        current[last_key] = value
        return

    if not isinstance(current, dict):
        raise TypeError(f"Expected dict for final key in {path}")
    current[last_key] = value


def _get_by_path(state: Any, path: list[Any]) -> Any:
    current = state
    for key in path:
        current = current[key]
    return current


def _append_text(state: Any, path: list[Any], value: str) -> None:
    try:
        existing = _get_by_path(state, path)
    except (KeyError, IndexError, TypeError):
        _set_by_path(state, path, "")
        existing = ""

    if not isinstance(existing, str):
        raise TypeError(f"append-text target must be string at {path}")
    _set_by_path(state, path, existing + value)


def _extract_requires_action_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    part_list = payload.get("content", [])
    if not isinstance(part_list, list):
        return set()

    found: set[str] = set()
    for part in part_list:
        if (
            isinstance(part, dict)
            and part.get("type") == "tool-call"
            and part.get("status") == "requires-action"
            and isinstance(part.get("tool_call_id"), str)
        ):
            found.add(part["tool_call_id"])
    return found


def main() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    state = copy.deepcopy(fixture["initial_state"])

    command_types = {command["type"] for command in fixture["commands"]}
    if "add-message" not in command_types or "add-tool-result" not in command_types:
        raise AssertionError("Fixture must contain add-message and add-tool-result commands")

    decisions = {
        command.get("result", {}).get("decision")
        for command in fixture["commands"]
        if command["type"] == "add-tool-result"
    }
    if not {"change-args", "approve"}.issubset(decisions):
        raise AssertionError("Fixture must contain change-args and approve decisions")

    requires_action_seen: set[str] = set()
    interrupt_seen = False
    first_thread_id_set_index: int | None = None
    first_message_set_index: int | None = None
    operation_index = 0

    for batch in fixture["stream_operations"]:
        for operation in batch:
            operation_index += 1
            op_type = operation["type"]
            if op_type == "set" and operation["path"] == ["thread", "id"]:
                if first_thread_id_set_index is None:
                    first_thread_id_set_index = operation_index
            if op_type == "set" and operation["path"] == ["messages", 0]:
                if first_message_set_index is None:
                    first_message_set_index = operation_index
            if op_type == "set":
                _set_by_path(state, operation["path"], operation["value"])
                requires_action_seen |= _extract_requires_action_ids(operation["value"])
            elif op_type == "append-text":
                _append_text(state, operation["path"], operation["value"])
            else:
                raise ValueError(f"Unsupported operation: {op_type}")
        if state.get("interrupts"):
            interrupt_seen = True

    expectations = fixture["expectations"]
    if expectations["welcome_page_when_messages_empty"] and fixture["initial_state"]["messages"]:
        raise AssertionError("Welcome-page expectation requires initial empty messages")
    if expectations.get("thread_id_initially_null") and fixture["initial_state"]["thread"]["id"] is not None:
        raise AssertionError("Initial thread ID must be null for welcome bootstrap flow")
    if first_thread_id_set_index is None or first_message_set_index is None:
        raise AssertionError("Thread-ID set and first message set operations are both required")
    if first_thread_id_set_index > first_message_set_index:
        raise AssertionError("Thread ID must be created before first message is sent")
    if state["thread"]["id"] != expectations.get("created_thread_id"):
        raise AssertionError("Created thread ID mismatch")
    if state.get("ui", {}).get("route") != expectations.get("navigate_to"):
        raise AssertionError("Navigation route mismatch after thread creation")

    expected_requires_action = set(expectations["requires_action_tool_call_ids"])
    if not expected_requires_action.issubset(requires_action_seen):
        raise AssertionError(
            f"Missing requires-action calls: {expected_requires_action - requires_action_seen}"
        )
    if not interrupt_seen:
        raise AssertionError("Expected to observe at least one interrupt snapshot")

    messages = state["messages"]
    if len(messages) != expectations["final_message_count"]:
        raise AssertionError("Final message count mismatch")

    branch_ids = {message.get("branch_id") for message in messages if isinstance(message, dict)}
    if not set(expectations["branch_ids"]).issubset(branch_ids):
        raise AssertionError("Missing expected branch IDs in final state")

    regen_message = next(
        (
            message
            for message in messages
            if message.get("id") == expectations["regenerate_message_id"]
        ),
        None,
    )
    if regen_message is None:
        raise AssertionError("Regenerate message missing in final state")
    if regen_message.get("parent_id") != expectations["regenerate_parent_id"]:
        raise AssertionError("Regenerate parent ID mismatch")

    changed_city = expectations["weather_city_after_change"]
    found_changed_city = False
    for message in messages:
        for part in message.get("content", []):
            if (
                isinstance(part, dict)
                and part.get("type") == "tool-call"
                and part.get("tool_call_id") == "tool_weather_1"
                and part.get("args", {}).get("city") == changed_city
                and part.get("status") == "complete"
            ):
                found_changed_city = True
    if not found_changed_city:
        raise AssertionError("Expected completed tool call with changed city not found")

    print(
        "backend-contract-ok:",
        f"messages={len(messages)}",
        f"requires_action={sorted(requires_action_seen)}",
        f"branches={sorted(branch_ids)}",
    )


if __name__ == "__main__":
    main()
