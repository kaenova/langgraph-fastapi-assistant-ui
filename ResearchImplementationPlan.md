# Assistant UI + LangGraph (FastAPI) Integration Guide

End‑to‑end guide for integrating **Assistant UI** with a **custom LocalRuntime** that talks to a **LangGraph + FastAPI** backend, including streaming, cancellation, tool calling, and human‑in‑the‑loop (HITL).

***

## 1. Architecture overview

### High‑level layers

```text
┌─────────────────────────────────────────────────────────────┐
│                    Assistant UI (React)                     │
│  - Chat UI components (Thread, Composer, etc.)              │
│  - Renders messages, tools, streaming text                  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          │ Runtime API (React hooks)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│           Custom LocalRuntime (client adapter)              │
│  - Uses useLocalRuntime                                    │
│  - Implements ChatModelAdapter.run                         │
│  - Translates runtime calls ↔ HTTP(SSE)                    │
│  - Forwards AbortSignal                                    │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          │ HTTP POST + SSE
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Backend (Python)                       │
│  - /stream: initial graph runs (SSE)                        │
│  - /feedback: HITL resume runs (SSE)                        │
│  - Shared LangGraph→SSE event handler                       │
│  - Uses jsonable_encoder for serialization                  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          │ Python API
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     LangGraph                               │
│  - Graph definition (agent, tools, approval node)           │
│  - astream_events(..., version="v2")                        │
│  - Tools via ToolNode                                       │
│  - interrupt(...) + Command(resume=...) for HITL            │
│  - Checkpointer (Postgres) for persistence                  │
└─────────────────────────────────────────────────────────────┘
```

### Key principles

- **LocalRuntime is client‑side only.** It owns UI state but delegates durable state to LangGraph using `thread_id`. [github](https://github.com/sheikhhanif/LangGraph_Streaming)
- **Streaming is unidirectional via SSE.** Frontend reads tokens as they arrive from FastAPI. [softgrade](https://www.softgrade.org/sse-with-fastapi-react-langgraph/)
- **LangGraph owns execution state.** Checkpointer + `thread_id` manage resumability and HITL. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/persistence)
- **HITL uses interrupts.** `interrupt(...)` pauses graphs; `Command(resume=...)` continues them, both over streaming. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/interrupts)

***

## 2. Assistant UI runtime model & LocalRuntime

Assistant UI’s runtimes abstract “how messages are managed and how the model is called.” LocalRuntime keeps messages in memory and delegates model calls through a `ChatModelAdapter`. [github](https://github.com/sheikhhanif/LangGraph_Streaming)

### ChatModelAdapter interface (conceptual)

```ts
interface ChatModelAdapter {
  run(
    options: ChatModelRunOptions
  ): ChatModelRunResult | AsyncGenerator<ChatModelRunResult>;
}

interface ChatModelRunOptions {
  messages: readonly ThreadMessage[];
  abortSignal: AbortSignal;
  context: ModelContext;
  unstable_threadId?: string;
}

interface ChatModelRunResult {
  content: MessageContent[];
  metadata?: {
    custom?: Record<string, unknown>;
    unstable_data?: Record<string, unknown>;
  };
}

type MessageContent =
  | { type: "text"; text: string }
  | { type: "tool-call"; toolCallId: string; toolName: string; args: any }
  | { type: "tool-result"; toolCallId: string; result: any; isError?: boolean };
```

Important runtime behaviors: [github](https://github.com/sheikhhanif/LangGraph_Streaming)

- `run` may return a **single** result or an **async generator**; streaming requires an async generator.
- The adapter must yield **full snapshots** of the assistant’s content, not deltas (e.g., “Hello”, then “Hello world”), which LocalRuntime expects. [github](https://github.com/sheikhhanif/LangGraph_Streaming)

***

## 3. Custom LocalRuntime design (TypeScript)

We create a `LangGraphAdapter` that:

- Serializes messages → backend JSON.
- Sends `POST /stream` with `AbortSignal`.
- Reads SSE from FastAPI.
- Accumulates text & tool calls and yields `ChatModelRunResult`s.

### Adapter implementation (with HITL awareness)

```tsx
// frontend/components/MyRuntimeProvider.tsx
"use client";

import {
  useLocalRuntime,
  AssistantRuntimeProvider,
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ChatModelRunResult,
} from "@assistant-ui/react";

const LangGraphAdapter: ChatModelAdapter = {
  async *run({
    messages,
    abortSignal,
    context,
    unstable_threadId,
  }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult> {
    // 1. Map Assistant UI messages → backend messages
    const formattedMessages = messages.map((m) => {
      const text = m.content
        .filter((c: any) => c.type === "text")
        .map((c: any) => c.text)
        .join("");
      if (m.role === "user") return { role: "human", content: text };
      if (m.role === "assistant") return { role: "ai", content: text };
      return { role: m.role, content: text };
    });

    // 2. Tool metadata (if needed by backend)
    const tools = (context.tools ?? []).map((t) => ({
      name: t.name,
      description: t.description,
      parameters: t.parameters,
    }));

    const payload = {
      messages: formattedMessages,
      thread_id: unstable_threadId ?? "default",
      tools,
    };

    // 3. Start SSE streaming request
    const response = await fetch("http://localhost:8000/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: abortSignal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`Backend error: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    let buffer = "";
    let accumulatedText = "";
    const toolCalls = new Map<string, { toolCallId: string; toolName: string; args: any }>();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.slice(6).trim();
        if (!dataStr || dataStr === "[DONE]") continue;

        let evt: any;
        try {
          evt = JSON.parse(dataStr);
        } catch {
          continue;
        }

        if (evt.type === "token") {
          accumulatedText += evt.content;
        } else if (evt.type === "tool_call") {
          // LangGraph executes tools server-side; we only surface the call
          // and rely on subsequent LLM tokens for explanations.
          toolCalls.set(evt.id, {
            toolCallId: evt.id,
            toolName: evt.name,
            args: evt.arguments, // backend guarantees this is a dict
          });
        } else if (evt.type === "interrupt") {
          // HITL: expose pending tool calls + pause
          const pending = (evt.payload?.tool_calls ?? []).map((tc: any) => ({
            type: "tool-call" as const,
            toolCallId: tc.id,
            toolName: tc.name,
            args: tc.arguments,
          }));
          const content: any[] = [];
          if (accumulatedText) content.push({ type: "text", text: accumulatedText });
          content.push(...pending);
          if (content.length) {
            yield { content };
          }
          // Stop streaming; frontend should now call /feedback to resume
          return;
        } else if (evt.type === "error") {
          const msg = evt.error ?? "Unknown error";
          yield { content: [{ type: "text", text: `Error: ${msg}` }] };
          return;
        }

        // Yield full snapshot (text + all tool calls)
        const content: any[] = [];
        if (accumulatedText) {
          content.push({ type: "text", text: accumulatedText });
        }
        for (const tc of toolCalls.values()) {
          content.push({ type: "tool-call", ...tc });
        }
        if (content.length) {
          yield { content };
        }
      }
    }
  },
};

export function MyRuntimeProvider({ children }: { children: React.ReactNode }) {
  const runtime = useLocalRuntime(LangGraphAdapter);
  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}
```

Notes: [github](https://github.com/sheikhhanif/LangGraph_Streaming)

- The adapter yields frequently; you can later buffer for performance.
- Since LangGraph executes tools, this adapter does **not** emit `tool-result` entries; it only shows tool calls and the follow‑up LLM output.
- HITL: the adapter stops streaming when it sees an `interrupt` event, after yielding pending tool calls for UI to approve.

***

## 4. FastAPI + LangGraph backend

### Core responsibilities

- `/stream`: handle initial runs (user asks a question) and stream tokens/tool calls/interrupts via SSE. [mlvector](https://mlvector.com/2025/06/30/30daysoflangchain-day-25-fastapi-for-langgraph-agents-streaming-responses/)
- `/feedback`: handle **resume** after HITL approval and stream continuation in the same format. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/interrupts)
- Shared `langgraph_events_to_sse` to keep behavior identical between the two endpoints.
- Use Postgres checkpointer to maintain per‑thread graph state. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/persistence)

### Models

```py
# backend/models.py
from pydantic import BaseModel
from typing import List, Dict, Any

class Message(BaseModel):
    role: str
    content: str

class StreamRequest(BaseModel):
    messages: List[Message]
    thread_id: str = "default"

class FeedbackRequest(BaseModel):
    thread_id: str
    approval_data: Dict[str, Any]  # e.g. {"approved_ids": [...], "rejected_ids": [...]}
```

### LangGraph with tools + HITL

```py
# backend/hitl_graph.py
from typing import TypedDict, Annotated, List, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import interrupt
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

class GraphState(TypedDict):
    messages: Annotated[List, add_messages]

def create_hitl_graph(checkpointer: BaseCheckpointSaver):
    llm = ChatOpenAI(model="gpt-4o", streaming=True)

    @tool
    def dangerous_delete(table: str) -> str:
        """Dangerous DB delete, requires human approval."""
        return f"Deleted table {table}"

    @tool
    def safe_search(query: str) -> str:
        """Safe search tool."""
        return f"Results for {query}"

    tools = [dangerous_delete, safe_search]
    dangerous_names = {"dangerous_delete"}

    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: GraphState) -> GraphState:
        resp = llm_with_tools.invoke(state["messages"])
        return {"messages": [resp]}

    def approval_node(state: GraphState) -> GraphState:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return state

        calls = last.tool_calls
        need_approval = [tc for tc in calls if tc["name"] in dangerous_names]
        if not need_approval:
            return state

        # Pause graph to ask for human approval
        approval = interrupt(
            {
                "type": "tool_approval_required",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "name": tc["name"],
                        "arguments": tc["args"],
                    }
                    for tc in need_approval
                ],
            }
        )
        # When resumed, approval will contain user decision
        approved_ids = set(approval.get("approved_ids", []))
        rejected_ids = set(approval.get("rejected_ids", []))

        filtered = [tc for tc in calls if tc["id"] in approved_ids]
        rejections: List[ToolMessage] = [
            ToolMessage(content="Tool call rejected by user", tool_call_id=tc["id"])
            for tc in calls
            if tc["id"] in rejected_ids
        ]

        updated = last.copy()
        updated.tool_calls = filtered

        return {"messages": state["messages"][:-1] + [updated] + rejections}

    tool_node = ToolNode(tools)

    def route(state: GraphState) -> Literal["approval", "tools", "__end__"]:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "__end__"
        if any(tc["name"] in dangerous_names for tc in last.tool_calls):
            return "approval"
        return "tools"

    sg = StateGraph(GraphState)
    sg.add_node("agent", agent_node)
    sg.add_node("approval", approval_node)
    sg.add_node("tools", tool_node)

    sg.add_edge(START, "agent")
    sg.add_conditional_edges(
        "agent",
        route,
        {"approval": "approval", "tools": "tools", "__end__": END},
    )
    sg.add_edge("approval", "tools")
    sg.add_edge("tools", "agent")

    return sg.compile(checkpointer=checkpointer)
```

LangGraph’s interrupts and Command resume are documented here. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/interrupts)

### FastAPI app & checkpointer

```py
# backend/main.py
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from typing import AsyncIterator, Dict, Any
import json

from models import StreamRequest, FeedbackRequest
from hitl_graph import create_hitl_graph
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost:5432/langgraph"
)

def sse(data: dict) -> str:
    """Encode Python data as SSE 'data:' line."""
    encoded = jsonable_encoder(data)
    return f"data: {json.dumps(encoded)}\n\n"
```

### Shared LangGraph → SSE converter

```py
async def langgraph_events_to_sse(
    events: AsyncIterator[Dict[str, Any]],
    req: Request,
) -> AsyncIterator[str]:
    """
    Convert LangGraph v2 events to SSE events (token, tool_call, interrupt, done).
    Shared by /stream and /feedback.
    """
    try:
        async for event in events:
            if await req.is_disconnected():
                break

            ev = event.get("event")

            # Token streaming
            if ev == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if getattr(chunk, "content", None):
                    yield sse({"type": "token", "content": chunk.content})

            # Tool calls (complete)
            elif ev == "on_chat_model_end":
                output = event["data"]["output"]
                if getattr(output, "tool_calls", None):
                    for tc in output.tool_calls:
                        args = tc["args"]
                        if not isinstance(args, dict):
                            import json as _json
                            args = _json.loads(args)
                        yield sse(
                            {
                                "type": "tool_call",
                                "id": tc["id"],
                                "name": tc["name"],
                                "arguments": args,
                            }
                        )

            # HITL interrupts
            elif ev == "on_chain_interrupt":
                interrupt_payload = event["data"].get("interrupt")
                yield sse({"type": "interrupt", "payload": interrupt_payload})
                # After interrupt, stop; continuation is via /feedback
                return

        # Normal completion
        yield sse({"type": "done"})
        yield "data: [DONE]\n\n"

    except Exception as e:
        yield sse({"type": "error", "error": str(e)})
```

This pattern (using a shared converter) is consistent with FastAPI streaming best practices. [fastapi.tiangolo](https://fastapi.tiangolo.com/advanced/custom-response/)

### `/stream` endpoint (initial runs)

```py
@app.post("/stream")
async def stream_endpoint(payload: StreamRequest, req: Request):
    graph = create_hitl_graph(checkpointer)

    graph_input = {
        "messages": [
            {"role": m.role, "content": m.content}
            for m in payload.messages
        ],
    }
    config = {"configurable": {"thread_id": payload.thread_id}}

    async def event_gen():
        events = graph.astream_events(graph_input, config=config, version="v2")
        async for chunk in langgraph_events_to_sse(events, req):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

### `/feedback` endpoint (HITL resume, streamed)

```py
@app.post("/feedback")
async def feedback_endpoint(payload: FeedbackRequest, req: Request):
    """
    Resume an interrupted graph after human approval, streaming continuation.
    """
    graph = create_hitl_graph(checkpointer)
    config = {"configurable": {"thread_id": payload.thread_id}}

    async def event_gen():
        command = Command(resume=payload.approval_data)
        events = graph.astream_events(command, config=config, version="v2")
        async for chunk in langgraph_events_to_sse(events, req):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

This matches LangGraph’s recommended pattern: use `Command(resume=...)` and stream events rather than a one‑shot `ainvoke`. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/interrupts)

***

## 5. Event & data flow (including HITL)

### Normal run

1. **User** sends message in Assistant UI.
2. LocalRuntime calls `LangGraphAdapter.run({ messages, abortSignal, unstable_threadId })`. [github](https://github.com/sheikhhanif/LangGraph_Streaming)
3. Adapter sends `POST /stream` with messages and `thread_id`.
4. FastAPI calls `graph.astream_events(input, config, version="v2")`, feeds events into `langgraph_events_to_sse`, streaming `token` and `tool_call` SSE.
5. Adapter reads SSE:
   - For `token`, updates `accumulatedText` and yields new snapshots.
   - For `tool_call`, updates `toolCalls` map and yields snapshots.
6. LocalRuntime updates assistant message; UI renders streaming text and tool call cards.

### HITL run

1. User asks for a dangerous operation.
2. Agent node decides to call `dangerous_delete(...)`, then router → `approval` node.
3. `approval_node` does `interrupt({type: "tool_approval_required", tool_calls: [...]})`. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/interrupts)
4. LangGraph emits `on_chain_interrupt`; FastAPI’s helper yields `{"type": "interrupt", "payload": {...}}` and stops streaming.
5. Adapter:
   - Yields an assistant snapshot with any text + pending tool calls with `requires approval` semantics.
   - Returns from `run`, ending the stream.
6. UI renders a confirmation UI: Approve/Reject.
7. On Approve/Reject, frontend calls `/feedback` (SSE) with `approval_data = {approved_ids, rejected_ids}`.
8. `/feedback` sends `Command(resume=approval_data)` into `graph.astream_events`, and `langgraph_events_to_sse` streams tokens/tool calls/interrupt exactly as before.
9. Adapter reads `/feedback` SSE just like `/stream` and yields updates, so the user sees “I deleted the table” (or similar) streamed back.

***

## 6. Abort / cancellation

- LocalRuntime passes an `AbortSignal` to the adapter. [github](https://github.com/sheikhhanif/LangGraph_Streaming)
- Adapter attaches it to `fetch` as `signal`; cancelling from the UI aborts the request.
- FastAPI sees disconnect with `await req.is_disconnected()` and stops reading events. [softgrade](https://www.softgrade.org/sse-with-fastapi-react-langgraph/)
- LangGraph and tools can respect cancellation via `asyncio.CancelledError` if you incorporate time‑outs or periodic `await asyncio.sleep` in long‑running operations. [mlvector](https://mlvector.com/2025/06/30/30daysoflangchain-day-25-fastapi-for-langgraph-agents-streaming-responses/)

***

## 7. State persistence & sessions

- Use PostgresSaver as checkpointer: `workflow.compile(checkpointer=checkpointer)`. Each `thread_id` gets its own persistent state, including interrupt checkpoints. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/persistence)
- LocalRuntime’s `unstable_threadId` can be wired to your own thread IDs (or used with `useRemoteThreadListRuntime` if you want a server‑side thread list). [github](https://github.com/sheikhhanif/LangGraph_Streaming)
- This persistence is crucial for HITL: `interrupt` relies on being able to resume from the last checkpoint. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/interrupts)

***

## 8. Minimal working setup (trimmed)

### Frontend

```bash
cd frontend
npm install @assistant-ui/react
```

```tsx
// app/page.tsx
import { Thread } from "@assistant-ui/react";
import { MyRuntimeProvider } from "../components/MyRuntimeProvider";

export default function Page() {
  return (
    <MyRuntimeProvider>
      <Thread />
    </MyRuntimeProvider>
  );
}
```

### Backend

```bash
cd backend
pip install fastapi uvicorn langgraph langchain-openai psycopg2-binary
```

```bash
# Run server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
