# LangGraph + Assistant UI HITL Integration Guide

This document explains how to integrate a LangGraph backend (FastAPI + SSE) with Assistant UI (Next.js). It covers streaming, tool calls, human-in-the-loop (HITL) approvals, and tool result rendering.

Use this as a copy‑paste checklist for other projects.

---

## 1) Backend (LangGraph + FastAPI) Integration

### 1.1 Required runtime behavior

Your backend must:

- Stream **tokens**, **tool calls**, **tool results**, and **interrupts** over SSE.
- Use LangGraph `interrupt(...)` + `Command(resume=...)` for HITL.
- Persist graph state per `thread_id` (checkpointer) so interruptions can be resumed.

### 1.2 Required endpoints

Implement two SSE endpoints:

- `POST /stream` → start a fresh run
- `POST /feedback` → resume an interrupted run with approval data

Both must emit the exact same SSE event schema.

### 1.3 SSE event schema (required)

Each SSE `data:` payload is JSON with one of these shapes:

```json
{ "type": "token", "content": "..." }
{ "type": "tool_call", "id": "call_x", "name": "tool_name", "arguments": { ... } }
{ "type": "tool_result", "id": "call_x", "tool_call_id": "call_x", "name": "tool_name", "content": "..." }
{ "type": "interrupt", "payload": { "type": "tool_approval_required", "tool_calls": [ ... ] } }
{ "type": "done" }
{ "type": "error", "error": "..." }
```

Notes:

- `tool_result.content` should contain the **user‑visible result string**. Avoid dumping `ToolMessage` stringified objects. If the tool returns a `ToolMessage`, extract `output.content`.
- Always send `tool_call_id` to map results to the correct tool UI card.

### 1.4 Reference implementation (portable)

This guide is **self-contained** and assumes the reader does **not** have access to the original codebase. All references below are generic paths you can adapt to your project structure.

Key parts:

- `langgraph_events_to_sse(...)` handles tokens, tool calls, tool results, and interrupts.
- `/feedback` uses `Command(resume=approval_data)` to continue the graph.
- HITL pauses are emitted as `interrupt` events after streaming completes.

### 1.5 HITL approval node (LangGraph)

A typical flow:

1. LLM emits tool calls.
2. If any tool call is dangerous, route to approval node.
3. Approval node calls `interrupt({ tool_calls: [...] })`.
4. Frontend approves/rejects, sends `/feedback`.
5. Graph resumes and runs only approved tool calls.

This applies to any LangGraph-based graph definition that uses tool calls.

---

## 2) Frontend (Assistant UI + LocalRuntime)

### 2.1 Runtime adapter overview

Assistant UI uses a `ChatModelAdapter` to control how model runs are executed. Most starter templates do **not** include a custom runtime provider, so you must create one (e.g., `RuntimeProvider.tsx`) that wraps `useLocalRuntime` and `AssistantRuntimeProvider` and implements a `ChatModelAdapter` that talks to your SSE backend. This implementation uses a custom adapter that:

- Maps Assistant UI messages → LangGraph message format.
- Sends `POST /stream` or `POST /feedback` with `thread_id`.
- Parses SSE and yields **full content snapshots**.
- Emits `requires-action` when interrupted.

Reference file:

- Your runtime provider module (the component that wires `useLocalRuntime` + `AssistantRuntimeProvider` and contains the SSE adapter)

### 2.2 Critical adapter behavior

- **Never append a synthetic user message** to resume HITL. Use `thread.startRun({ parentId })` so it continues in‑place.
- Parse `tool_result` events and associate them by `tool_call_id`.
- When an interrupt is received, yield a run result with:

```ts
status: { type: "requires-action", reason: "interrupt" }
```

This stops the stream and tells Assistant UI to wait for user approval.

### 2.3 UI: inline HITL controls

HITL approval controls are rendered in the tool-call card component, not in a separate banner. This makes the approval context visible next to the tool arguments.

Reference file:

- Your tool UI component (the tool-call card renderer)

Behavior:

- When a tool call is in the interrupt list, it shows **Approve/Reject** buttons.
- The card displays a hint badge when collapsed: `Needs approval`, `Approved`, `Rejected`.
- A single “Send Feedback” button appears on the last interrupt tool card.

### 2.4 Tool results in the UI

Tool result rendering uses Assistant UI’s native tool card behavior:

- The adapter emits `tool_result` SSE events.
- The tool card receives and displays the result.

The tool card also normalizes any raw tool result string to show only **content** (if the backend still returns `ToolMessage`‑like strings).

---

## 3) Integration Checklist (copy/paste)

### Backend

- [ ] Implement `POST /stream` and `POST /feedback` endpoints (SSE).
- [ ] Use `Command(resume=approval_data)` to continue HITL.
- [ ] Emit `tool_call` events from `on_chat_model_end`.
- [ ] Emit `tool_result` events from `on_tool_end` with `tool_call_id`.
- [ ] Emit `interrupt` after stream end when graph is paused.
- [ ] Persist by `thread_id` (checkpointer).

### Frontend

- [ ] Replace default runtime with custom `useLocalRuntime` adapter.
- [ ] Parse SSE events → yield full snapshot updates.
- [ ] On interrupt, set `requires-action` and pause.
- [ ] Use `thread.startRun({ parentId })` to resume without synthetic user message.
- [ ] Render HITL approval inline in tool card UI.
- [ ] Add tool result normalization if backend returns `ToolMessage` string.

---

## 4) Known Constraints & Best Practices

- Assistant UI expects **full content snapshots**, not incremental deltas.
- Tool call IDs must be stable and identical between `tool_call` and `tool_result`.
- Avoid showing `ToolMessage` raw strings—extract `content` when possible.
- HITL approvals are tied to `thread_id`, so thread IDs must be stable for the session.

---

## 5) What to change per project

- Replace the backend URLs in your runtime provider with your proxy path.
- Update dangerous tool names in your graph definition.
- Adjust tool UI styling in your tool-call card component.
- Ensure the backend uses the same SSE event schema.

---

## 6) Quick smoke test

1. Trigger a dangerous tool.
2. Verify interrupt UI shows inline approvals in the tool card.
3. Approve/reject and confirm the run resumes without a new user message.
4. Confirm tool result text is clean (content only).

---

## 7) Snippets for reference

### Important: replace local paths

When adapting this guide, replace any local absolute paths with your project path. Use this pattern:

```text
/path/to/your/project/**
```

### 7.1 Backend: emit tool_result with clean content

Example from your SSE route module:

```python
            elif ev == "on_tool_end":
                output = event["data"].get("output")
                if output is not None:
                    data = event.get("data", {})
                    tool_call_id = ""
                    if isinstance(data, dict):
                        tool_call_id = data.get("tool_call_id", "") or data.get(
                            "call_id", ""
                        )
                        input_data = data.get("input")
                        if not tool_call_id and isinstance(input_data, dict):
                            tool_call_id = input_data.get(
                                "tool_call_id", ""
                            ) or input_data.get("id", "")
                    if not tool_call_id:
                        if hasattr(output, "tool_call_id"):
                            tool_call_id = getattr(output, "tool_call_id")
                        elif isinstance(output, dict):
                            tool_call_id = output.get("tool_call_id", "")
                    if not tool_call_id:
                        tool_call_id = event.get("run_id", "")

                    name = event.get("name", "")
                    if hasattr(output, "content"):
                        content = getattr(output, "content")
                    elif isinstance(output, dict) and "content" in output:
                        content = output.get("content")
                    else:
                        content = str(output)
                    yield sse(
                        {
                            "type": "tool_result",
                            "id": tool_call_id,
                            "tool_call_id": tool_call_id,
                            "name": name,
                            "content": content,
                        }
                    )
```

### 7.2 Frontend: interrupt handling + tool results

Example from your runtime provider:

```tsx
if (evt.type === "tool_result") {
  const toolCallId = evt.tool_call_id ?? evt.id;
  if (toolCallId) {
    const result = evt.content ?? null;
    const isError = evt.is_error ?? false;
    const existing = toolCalls.get(toolCallId);
    if (existing) {
      existing.result = result;
      existing.isError = isError;
    }
    onToolResult(toolCallId, result, isError);
  }
} else if (evt.type === "interrupt" && evt.payload) {
  onInterrupt(evt.payload);
  // yield requires-action and stop streaming
  yield {
    content: parts,
    status: { type: "requires-action", reason: "interrupt" },
  };
  return;
}
```

### 7.3 Frontend: normalize tool result for display

Example from your tool UI component:

```tsx
function normalizeToolResult(result: unknown) {
  if (result === null || result === undefined) return result;
  if (typeof result === "object") {
    if ("content" in result) {
      return (result as { content?: unknown }).content;
    }
    return result;
  }
  if (typeof result === "string") {
    const trimmed = result.trim();
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed && typeof parsed === "object" && "content" in parsed) {
          return parsed.content;
        }
      } catch {
        // ignore JSON parse errors
      }
    }
    const match = trimmed.match(/content=(["'])(.*?)\1/);
    if (match && match[2]) return match[2];
    return result;
  }
  return result;
}
```

---

## 8) Minimal changes from a base implementation (diff-oriented)

Below is a **minimal change map** for integrating HITL + SSE streaming into a base LangGraph + Assistant UI app. If you are integrating into a fresh project, implement **only these deltas**.

### 8.1 Backend: add SSE chat routes

**Add a new SSE chat routes module** (e.g., a FastAPI router).

Key pieces to port:

```python
def sse(data: dict) -> str:
    encoded = jsonable_encoder(data)
    return f"data: {json.dumps(encoded)}\n\n"
```

```python
elif ev == "on_chat_model_end":
    output = event["data"]["output"]
    tool_calls = getattr(output, "tool_calls", None)
    if tool_calls:
        for tc in tool_calls:
            args = tc["args"]
            if not isinstance(args, dict):
                args = json.loads(args)
            yield sse(
                {
                    "type": "tool_call",
                    "id": tc["id"],
                    "name": tc["name"],
                    "arguments": args,
                }
            )
```

```python
elif ev == "on_tool_end":
    output = event["data"].get("output")
    if output is not None:
        # resolve tool_call_id and clean content (see full snippet above)
        yield sse(
            {
                "type": "tool_result",
                "id": tool_call_id,
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content,
            }
        )
```

```python
@chat_routes.post("/stream")
@chat_routes.post("/feedback")
```

### 8.2 Backend: register chat routes

**Modify your FastAPI app entry** to register the new chat routes.

```python
from routes.chat import chat_routes

app.include_router(
    chat_routes,
    prefix="/api/v1/chat",
    tags=["chat"],
)
```

### 8.3 Backend: add HITL approval node

**Modify your LangGraph graph definition** to add an approval node + interrupt handling.

Key diffs:

```python
from langgraph.types import interrupt

DANGEROUS_TOOL_NAMES = {"current_weather"}
```

```python
def should_continue(state: AgentState) -> Literal["approval", "tools", "end"]:
    if any(tc.get("name") in DANGEROUS_TOOL_NAMES for tc in last_message.tool_calls):
        return "approval"
    return "tools"
```

```python
def approval_node(state: AgentState) -> dict:
    approval = interrupt({
        "type": "tool_approval_required",
        "tool_calls": [{"id": tc["id"], "name": tc["name"], "arguments": tc.get("args", {})} for tc in need_approval],
    })
    approved_ids = set(approval.get("approved_ids", []))
    rejected_ids = set(approval.get("rejected_ids", []))
    # filter calls + add ToolMessage for rejections
```

```python
workflow.add_node("approval", approval_node)
workflow.add_conditional_edges("agent", should_continue, {"approval": "approval", "tools": "tools", "end": END})
workflow.add_edge("approval", "tools")
```

### 8.4 Frontend: add custom runtime provider

**Add a custom runtime provider** that bridges Assistant UI ↔ your SSE backend.

Key behavior to port:

```tsx
yield* parseSseStream(response, {
  onInterrupt: (payload) => {
    pendingInterruptMessageIdRef.current = unstable_assistantMessageId ?? null;
    setPendingInterrupt(payload);
  },
  onToolResult: (toolCallId, result, isError) => {
    setToolResults((prev) => ({ ...prev, [toolCallId]: { result, isError } }));
  },
});
```

```tsx
if (feedback) {
  url = "/api/be/api/v1/chat/feedback";
  body = JSON.stringify({ thread_id: threadId, approval_data: feedback });
} else {
  url = "/api/be/api/v1/chat/stream";
}
```

```tsx
// Resume HITL without fake user message:
runtimeRef.current.thread.startRun({ parentId });
```

### 8.5 Frontend: inline HITL UI inside tool card

**Modify your tool-call card component** to add inline approvals + result normalization.

Add hint on collapsed tool header:

```tsx
const hint = isInterruptTool
  ? decision === "approved"
    ? "Approved"
    : decision === "rejected"
      ? "Rejected"
      : "Needs approval"
  : undefined;
```

Render approvals inline:

```tsx
{isInterruptTool && (
  <div className="flex flex-col gap-2 px-4">
    <button onClick={() => setDecision(toolCallId, "approved")}>Approve</button>
    <button onClick={() => setDecision(toolCallId, "rejected")}>Reject</button>
    {isLastInterruptTool && (
      <button onClick={submitDecisions} disabled={!allDecided}>Send Feedback</button>
    )}
  </div>
)}
```

Normalize tool results so only `content` is shown:

```tsx
function normalizeToolResult(result: unknown) {
  if (typeof result === "object" && result && "content" in result) {
    return (result as { content?: unknown }).content;
  }
  if (typeof result === "string") {
    const match = result.trim().match(/content=(["'])(.*?)\1/);
    if (match && match[2]) return match[2];
  }
  return result;
}
```

### 8.6 Frontend: use custom runtime provider

**Wrap your Assistant UI entry** with the custom runtime provider.

```tsx
import { RuntimeProvider } from "@/components/RuntimeProvider";

export const Assistant = () => (
  <RuntimeProvider>
    <Thread />
  </RuntimeProvider>
);
```
