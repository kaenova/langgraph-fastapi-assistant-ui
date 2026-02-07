# LangGraph + Assistant UI HITL Integration (PoC → Production Guide)

This document explains how to integrate the LangGraph backend (FastAPI + SSE) with Assistant UI (Next.js) using the PoC in this repo as a reference. It covers streaming, tool calls, human-in-the-loop (HITL) approvals, and tool result rendering.

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

### 1.4 Reference implementation (this repo)

Backend implementation lives here:

- `backend/routes/chat.py`
- `backend/agent/graph.py`

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

See:

- `backend/agent/graph.py`

---

## 2) Frontend (Assistant UI + LocalRuntime)

### 2.1 Runtime adapter overview

Assistant UI uses a `ChatModelAdapter` to control how model runs are executed. This PoC implements a custom adapter that:

- Maps Assistant UI messages → LangGraph message format.
- Sends `POST /stream` or `POST /feedback` with `thread_id`.
- Parses SSE and yields **full content snapshots**.
- Emits `requires-action` when interrupted.

Reference file:

- `frontend/components/assistant-ui/MyRuntimeProvider.tsx`

### 2.2 Critical adapter behavior

- **Never append a synthetic user message** to resume HITL. Use `thread.startRun({ parentId })` so it continues in‑place.
- Parse `tool_result` events and associate them by `tool_call_id`.
- When an interrupt is received, yield a run result with:

```ts
status: { type: "requires-action", reason: "interrupt" }
```

This stops the stream and tells Assistant UI to wait for user approval.

### 2.3 UI: inline HITL controls

HITL approval controls are rendered in the tool card (`ToolFallback`), not in a separate banner. This makes the approval context visible next to the tool arguments.

Reference file:

- `frontend/components/assistant-ui/tool-fallback.tsx`

Behavior:

- When a tool call is in the interrupt list, it shows **Approve/Reject** buttons.
- The card displays a hint badge when collapsed: `Needs approval`, `Approved`, `Rejected`.
- A single “Send Feedback” button appears on the last interrupt tool card.

### 2.4 Tool results in the UI

Tool result rendering uses Assistant UI’s native tool card behavior:

- The adapter emits `tool_result` SSE events.
- The tool card receives and displays the result.

In this PoC, the tool card also normalizes any raw tool result string to show only **content** (if the backend still returns `ToolMessage`‑like strings).

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

## 5) Reference Paths (this repo)

Backend:

- `backend/routes/chat.py`
- `backend/agent/graph.py`

Frontend:

- `frontend/components/assistant-ui/MyRuntimeProvider.tsx`
- `frontend/components/assistant-ui/tool-fallback.tsx`
- `frontend/components/assistant-ui/thread.tsx`

---

## 6) What to change per project

- Replace the backend URLs in `frontend/components/assistant-ui/MyRuntimeProvider.tsx` with your proxy path.
- Update dangerous tool names in `backend/agent/graph.py`.
- Adjust tool UI styling in `tool-fallback.tsx`.
- Ensure the backend uses the same SSE event schema.

---

## 7) Quick smoke test

1. Trigger a dangerous tool.
2. Verify interrupt UI shows inline approvals in the tool card.
3. Approve/reject and confirm the run resumes without a new user message.
4. Confirm tool result text is clean (content only).

---

If you want, I can provide a minimal starter template for another repo (backend + frontend) using this same integration pattern.

---

## 8) Snippets for reference

### Important: replace local paths

When adapting this guide, replace any local absolute paths with your repo path. Use this pattern:

```text
/path/to/your/repo/**
```

### 8.1 Backend: emit tool_result with clean content

From `backend/routes/chat.py`:

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

### 8.2 Frontend: interrupt handling + tool results

From `frontend/components/assistant-ui/MyRuntimeProvider.tsx`:

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

### 8.3 Frontend: normalize tool result for display

From `frontend/components/assistant-ui/tool-fallback.tsx`:

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
    const match = trimmed.match(/content=(["'])(.*?)\\1/);
    if (match && match[2]) return match[2];
    return result;
  }
  return result;
}
```
