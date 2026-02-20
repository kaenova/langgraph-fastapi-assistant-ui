import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const fixturePath = path.join(
  __dirname,
  "fixtures",
  "weather-assistant-transport.json",
);

const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

const containerFor = (nextKey) => (Number.isInteger(nextKey) ? [] : {});

const setByPath = (state, pathParts, value) => {
  let current = state;
  for (let index = 0; index < pathParts.length - 1; index += 1) {
    const key = pathParts[index];
    const nextKey = pathParts[index + 1];
    if (Number.isInteger(key)) {
      if (!Array.isArray(current)) {
        throw new TypeError(`Expected list while traversing ${pathParts.join(".")}`);
      }
      while (current.length <= key) current.push(null);
      if (current[key] === null || current[key] === undefined) {
        current[key] = containerFor(nextKey);
      }
      current = current[key];
      continue;
    }

    if (typeof current !== "object" || current === null || Array.isArray(current)) {
      throw new TypeError(`Expected object while traversing ${pathParts.join(".")}`);
    }
    if (!(key in current) || current[key] === null || current[key] === undefined) {
      current[key] = containerFor(nextKey);
    }
    current = current[key];
  }

  const lastKey = pathParts[pathParts.length - 1];
  if (Number.isInteger(lastKey)) {
    if (!Array.isArray(current)) {
      throw new TypeError(`Expected list for final key in ${pathParts.join(".")}`);
    }
    while (current.length <= lastKey) current.push(null);
    current[lastKey] = value;
    return;
  }
  current[lastKey] = value;
};

const getByPath = (state, pathParts) =>
  pathParts.reduce((accumulator, key) => accumulator[key], state);

const appendText = (state, pathParts, value) => {
  let existing = "";
  try {
    existing = getByPath(state, pathParts);
  } catch {
    existing = "";
  }
  if (typeof existing !== "string") {
    throw new TypeError(`append-text target must be string at ${pathParts.join(".")}`);
  }
  setByPath(state, pathParts, existing + value);
};

const applyOperations = (state, operations) => {
  const requiresActionSeen = new Set();
  let firstThreadIdSetIndex = null;
  let firstMessageSetIndex = null;
  let operationIndex = 0;
  for (const batch of operations) {
    for (const operation of batch) {
      operationIndex += 1;
      if (
        operation.type === "set" &&
        JSON.stringify(operation.path) === JSON.stringify(["thread", "id"]) &&
        firstThreadIdSetIndex === null
      ) {
        firstThreadIdSetIndex = operationIndex;
      }
      if (
        operation.type === "set" &&
        JSON.stringify(operation.path) === JSON.stringify(["messages", 0]) &&
        firstMessageSetIndex === null
      ) {
        firstMessageSetIndex = operationIndex;
      }
      if (operation.type === "set") {
        setByPath(state, operation.path, operation.value);
        const content = operation.value?.content;
        if (Array.isArray(content)) {
          for (const part of content) {
            if (
              part?.type === "tool-call" &&
              part?.status === "requires-action" &&
              typeof part?.tool_call_id === "string"
            ) {
              requiresActionSeen.add(part.tool_call_id);
            }
          }
        }
      } else if (operation.type === "append-text") {
        appendText(state, operation.path, operation.value);
      } else {
        throw new Error(`Unsupported operation: ${operation.type}`);
      }
    }
  }
  return { requiresActionSeen, firstThreadIdSetIndex, firstMessageSetIndex };
};

const toThreadMessage = (message) => {
  const roleMap = {
    human: "user",
    ai: "assistant",
    tool: "tool",
  };
  return {
    id: message.id,
    role: roleMap[message.role] ?? message.role,
    parentId: message.parent_id ?? null,
    branchId: message.branch_id ?? "branch-main",
    content: (message.content ?? []).map((part) => {
      if (part.type === "text") {
        return { type: "text", text: part.text ?? "" };
      }
      if (part.type === "tool-call") {
        return {
          type: "tool-call",
          toolCallId: part.tool_call_id,
          toolName: part.name,
          args: part.args,
          status: part.status,
          result: part.result,
        };
      }
      if (part.type === "tool-result") {
        return {
          type: "tool-result",
          toolCallId: part.tool_call_id,
          result: part.result,
        };
      }
      return part;
    }),
  };
};

const state = structuredClone(fixture.initial_state);
const {
  requiresActionSeen,
  firstThreadIdSetIndex,
  firstMessageSetIndex,
} = applyOperations(state, fixture.stream_operations);
const expectations = fixture.expectations;

if (expectations.welcome_page_when_messages_empty && fixture.initial_state.messages.length !== 0) {
  throw new Error("Welcome-page expectation requires empty initial messages");
}
if (expectations.thread_id_initially_null && fixture.initial_state.thread?.id !== null) {
  throw new Error("Initial thread id must be null for welcome bootstrap flow");
}
if (firstThreadIdSetIndex === null || firstMessageSetIndex === null) {
  throw new Error("Missing thread-id set or first message set operation");
}
if (firstThreadIdSetIndex > firstMessageSetIndex) {
  throw new Error("Thread id must be set before first message send");
}
if (state.thread?.id !== expectations.created_thread_id) {
  throw new Error("Created thread id mismatch");
}
if (state.ui?.route !== expectations.navigate_to) {
  throw new Error("Navigation route mismatch after first send");
}

for (const toolCallId of expectations.requires_action_tool_call_ids) {
  if (!requiresActionSeen.has(toolCallId)) {
    throw new Error(`Missing requires-action tool call: ${toolCallId}`);
  }
}

const threadMessages = state.messages.map(toThreadMessage);
if (threadMessages.length !== expectations.final_message_count) {
  throw new Error("Final message count mismatch in frontend contract check");
}

const branchIds = new Set(threadMessages.map((message) => message.branchId));
for (const expectedBranch of expectations.branch_ids) {
  if (!branchIds.has(expectedBranch)) {
    throw new Error(`Missing branch id: ${expectedBranch}`);
  }
}

const regenMessage = threadMessages.find(
  (message) => message.id === expectations.regenerate_message_id,
);
if (!regenMessage) {
  throw new Error("Regenerate message missing");
}
if (regenMessage.parentId !== expectations.regenerate_parent_id) {
  throw new Error("Regenerate parent mismatch");
}

const hasChangedWeatherCall = threadMessages.some((message) =>
  message.content.some(
    (part) =>
      part.type === "tool-call" &&
      part.toolCallId === "tool_weather_1" &&
      part.status === "complete" &&
      part.args?.city === expectations.weather_city_after_change,
  ),
);
if (!hasChangedWeatherCall) {
  throw new Error("Expected complete weather tool-call with changed city");
}

console.log(
  "frontend-contract-ok:",
  `messages=${threadMessages.length}`,
  `requires_action=${Array.from(requiresActionSeen).join(",")}`,
  `branches=${Array.from(branchIds).join(",")}`,
);
