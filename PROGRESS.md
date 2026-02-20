# Progress (Aligned With Integration Prompt)

## Goal
Integrate the existing Next.js Assistant UI frontend with the existing Python LangGraph (FastAPI) backend using Assistant Transport (prefer `data-stream`) so the frontend reflects backend-owned state with:

- Streaming assistant text + tool-call args/results
- Human-in-the-loop (HITL) approval/edit/decline for (nearly) all tools
- Message editing + branching that persists on the backend
- Persistence via Azure CosmosDB (LangGraph checkpointer) + Azure Blob Storage (attachments)
- Potential use of LangGraph time travel (checkpoint forking/resuming) to implement edits/branching

Additionally, validate the transport/wire protocol with a minimal runnable harness before attempting full integration.

## Instructions (Current Phase)
- Do not do full end-to-end integration yet; validate the streaming protocol first.
- Harness tooling preference: uv (Python) and bun (Node).

## Current Status
- Harness (protocol): bun-side decoding/accumulation validated from a saved `data-stream` payload; Python streaming harness not built yet.
- Backend: no assistant/chat endpoint yet; LangGraph node currently uses non-streaming `invoke()`.
- Frontend: still uses `/api/chat` (AI SDK/OpenAI direct); not yet switched to backend via Assistant Transport.
- HITL approvals: not implemented yet.
- Backend persistence (CosmosDB/Blob): existing attachment routes + `chatbot://{id}` to SAS conversion are present; checkpointer exists and requires `thread_id` in LangGraph config.
- Edit/branch semantics: explored frontend `MessageRepository` branching behavior; backend time-travel mapping not implemented.

## Discoveries

### Backend
- `backend/main.py` mounts only attachment routes at `/api/v1/attachments`; no assistant endpoint exists yet.
- `backend/agent/graph.py` binds tools but calls the model with `model_with_tools.invoke(...)` (non-streaming). For streaming UI, this needs an async streaming pattern (e.g. `astream`/event streaming) and a transport encoder.
- Persistence: `backend/lib/checkpointer.py` exposes a cached CosmosDB checkpointer; LangGraph persistence requires `config={"configurable": {"thread_id": ...}}`.
- Attachments: upload returns `chatbot://{uuid}`; `backend/agent/utils.py` converts `chatbot://...` references to SAS URLs before model calls.

### Frontend
- `frontend/app/assistant.tsx` uses `useChatRuntime` + `AssistantChatTransport({ api: "/api/chat" })`.
- `frontend/app/api/chat/route.ts` streams directly from OpenAI via the AI SDK.
- `frontend/app/api/be/[...path]/route.ts` exists as a general streaming-capable proxy to the backend.
- Thread UI already includes edit/reload/branch UI (`frontend/components/assistant-ui/thread.tsx`).

### Assistant Transport / `data-stream`
- `useAssistantTransportRuntime` sends a JSON payload containing `commands`, `state`, `system`, `tools`, `threadId`, and optional `parentId`.
- `assistant-stream` `DataStreamEncoder` expects responses with `Content-Type: text/plain; charset=utf-8` and `x-vercel-ai-data-stream: v1`.
- Chunks are line-delimited: `<type>:<json>\n` (e.g. `0:"delta"\n`, `b:{...}\n`, `c:{...}\n`, `a:{...}\n`, `d:{...}\n`, `aui-state:[...]\n`).
- `aui-state` (aka update-state ops) must use objects with a `type` field (e.g. `set`, `append-text`), and is accumulated into `metadata.unstable_state`.

## Accomplished
- Added a bun harness that decodes/accumulates a saved `data-stream` sample and prints the final assistant message + `metadata.unstable_state`.
- Added a small exploration script showing how `MessageRepository` represents branches and switches the active branch head.

## In Progress
- Minimal uv-based Python streaming harness that emits real `data-stream` lines over HTTP (so we can validate headers + streaming behavior end-to-end).

## Next Steps
1. Build a minimal Python (uv/FastAPI or Starlette) streaming endpoint that emits `data-stream` chunks (`0`, `b/c/a`, `aui-state`, `d`).
2. Add a bun script that calls that endpoint, decodes with `DataStreamDecoder` + `AssistantMessageAccumulator`, and prints the accumulated output.
3. After harness success, start integration:
   - Backend: add `/api/v1/assistant` streaming endpoint (data-stream) wired to LangGraph streaming.
   - Frontend: switch transport to `/api/be/api/v1/assistant` (via proxy) and wire attachment adapter to `/api/be/api/v1/attachments`.
   - Implement HITL approvals and define how `parentId` maps to checkpoint ids for time-travel edits/branching.

## Relevant Files

### Harness / Exploration
- `scripts/explore-data-stream.mjs`
- `scripts/data-stream.sample.txt`
- `scripts/explore-edit-branching.mjs`

### Backend
- `backend/main.py`
- `backend/agent/graph.py`
- `backend/agent/model.py`
- `backend/agent/utils.py`
- `backend/routes/attachment.py`
- `backend/lib/checkpointer.py`

### Frontend
- `frontend/app/assistant.tsx`
- `frontend/app/api/chat/route.ts`
- `frontend/app/api/be/[...path]/route.ts`
- `frontend/components/assistant-ui/thread.tsx`
- `frontend/components/assistant-ui/attachment.tsx`
