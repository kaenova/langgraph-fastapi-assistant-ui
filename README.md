# LangGraph FastAPI Assistant UI - External Store Integration

This repository packages a custom **Assistant UI External Store runtime** on the frontend with a **LangGraph checkpoint-backed thread API** on the backend.

## Packaged custom integration

### Frontend package
- `frontend/lib/external-store-langgraph/external-store-chat.ts`
  - External-store transport, snapshot conversion, and stream handling.
- `frontend/lib/external-store-langgraph/chat-thread-page.tsx`
  - Chat runtime wiring (`onNew`, `onEdit`, `onReload`, branch switching, token merge).
- `frontend/lib/external-store-langgraph/welcome-page.tsx`
  - Welcome handoff flow (`/welcome` -> `/chat/{threadId}`).

### Backend package
- `backend/lib/external_store_langgraph/thread_routes.py`
  - `/threads` API implementation and stream event serialization.
- `backend/routes/thread.py`
  - Compatibility re-export of `thread_routes` from the packaged module.

> Note: backend package uses underscore (`external_store_langgraph`) because Python modules cannot use `-` in directory names.

## Integration endpoints

- `POST /api/v1/threads`
  - Create thread ID.
- `GET /api/v1/threads/{thread_id}/messages`
  - Fetch authoritative thread snapshot + message repository graph.
- `POST /api/v1/threads/{thread_id}/runs/stream`
  - Stream NDJSON events (`token`, `snapshot`, `error`).

## How to verify packaged integration quickly

1. Start backend and frontend dev servers.
2. Open `/welcome`, submit first message, confirm redirect to `/chat/{threadId}`.
3. In chat, verify:
   - streaming updates appear,
   - regenerate creates assistant branches,
   - edit creates user branches,
   - reload preserves branch picker state.

## Important note: CosmosDBSaver stability

Using `CosmosDBSaver` from `langgraph-checkpoint-cosmosdb` is currently **unstable** in this integration flow.

- Treat Cosmos checkpointing as optional/experimental.
- Keep a safe fallback path (for example, in-memory checkpointing) for local/dev and incident recovery.
- If checkpoint consistency issues appear (missing head, branch restore mismatch), retry with fallback checkpointer first before debugging frontend state.
