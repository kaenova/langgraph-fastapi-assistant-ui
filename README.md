# LangGraph FastAPI Assistant UI - Local Runtime Integration

This repository packages a custom **Assistant UI LocalRuntime** integration on the frontend with a **thread + history API** on the backend.

## Packaged custom integration

### Frontend package
- `frontend/lib/assistant-template/runtime/use-template-local-runtime.ts`
  - Shared LocalRuntime hook wiring model/history/attachment adapters.
- `frontend/lib/assistant-template/runtime/local-runtime-provider.tsx`
  - Runtime provider setup, remote thread-list runtime wiring, and initial welcome handoff send.
- `frontend/lib/assistant-template/runtime/adapters.ts`
  - Streaming model adapter (`runs/stream`) and history + remote thread-list adapters.
- `frontend/lib/assistant-template/chat-thread-page.tsx`
  - Route-level chat page mounting the LocalRuntime provider for `{threadId}`.
- `frontend/lib/assistant-template/welcome-page.tsx`
  - Welcome handoff flow (`/welcome` -> `/chat/{threadId}`) with first message persistence.

### Backend package
- `backend/routes/thread.py`
  - `/threads` metadata/history endpoints used by LocalRuntime thread list + history adapters.
- `backend/routes/chat.py`
  - `/{thread_id}/runs/stream` streaming endpoint for assistant responses and tool events.
- `backend/lib/thread_store.py`
  - In-memory thread document store for metadata, snapshots, and message history repository state.

## Integration endpoints

- `POST /api/v1/threads/initialize`
  - Create/initialize thread ID.
- `GET /api/v1/threads/{thread_id}`
  - Fetch thread metadata.
- `GET /api/v1/threads/{thread_id}/history`
  - Fetch authoritative message repository graph (`headId`, `messages`).
- `POST /api/v1/threads/{thread_id}/history/append`
  - Append/update one repository item (branch-aware persistence).
- `POST /api/v1/threads/{thread_id}/runs/stream`
  - Stream response events (`text_delta`, `tool_call`, `tool_result`, `done`, `error`).

## How to verify packaged integration quickly

1. Start backend and frontend dev servers.
2. Open `/welcome`, submit first message, confirm redirect to `/chat/{threadId}`.
3. In chat, verify:
   - streaming updates appear,
   - regenerate creates assistant branches,
   - edit creates user branches,
   - reload preserves branch picker state.
