# FLOW.md

## End-to-end flow (current implementation)

### 1) Entry and thread bootstrap
- User lands on `/` (`frontend/app/page.tsx`) and sees `WelcomePage` (`frontend/app/welcome-page.tsx`).
- On submit:
  - Frontend creates `threadId` via `crypto.randomUUID()`.
  - Calls `POST /api/be/api/v1/threads/initialize` with `{ threadId }`.
  - Redirects to `/chat/{threadId}?q={initialPrompt}`.

### 2) Chat page runtime wiring
- `/chat/[threadId]` renders `LocalRuntimeProvider` (`frontend/components/assistant-ui/runtime-provider.tsx`).
- Provider uses:
  - `useLocalRuntime` for model execution.
  - `useLocalRuntime(..., { adapters: { history } })` to load/append message history from backend.
  - `useLocalRuntime(..., { unstable_humanToolNames: [...] })` for HITL approval gating per LocalRuntime docs.
  - `unstable_useRemoteThreadListRuntime` for thread lifecycle API integration.
- Provider ensures current thread exists, switches runtime to that thread, then renders `Thread`.
- Initial prompt (`q`) is sent via `useThreadRuntime().append(...)` only when:
  - thread history has finished loading,
  - current thread has zero messages,
  - and a session-scoped dedupe key has not already sent that prompt.

### 3) Message run + streaming
- LocalRuntime adapter `run()` sends:
  - `POST /api/be/api/v1/threads/{threadId}/runs/stream`
  - payload: `{ messages, runConfig }`.
- Backend (`backend/routes/chat.py`) converts assistant-ui messages to LangChain messages.
- Backend invokes `model.bind_tools(AVAILABLE_TOOLS).invoke(...)`.
- Backend streams SSE EventStream events (`text/event-stream`) back to frontend:
  - `text_delta`
  - `tool_call`
  - `tool_result` (when present)
  - `done`
  - `error`
- Frontend parses EventStream incrementally (with NDJSON fallback for compatibility), reconstructs assistant parts, and yields updates to LocalRuntime.

### 4) Tool calling + HITL (with editable args)
- If model emits tool calls, backend marks response as `requires-action` and persists pending tool calls.
- UI fallback (`frontend/components/assistant-ui/tool-fallback.tsx`) shows editable JSON args.
- User can **Approve** or **Reject**; action is sent back through tool result payload:
  - `{ decision, editedArgs, reason? }`.
- Next backend run applies decisions:
  - Approve: executes tool using edited args (or original args).
  - Reject: returns rejected result payload.

### 5) Persistence model (local JSON per thread)
- Implemented in `backend/lib/thread_store.py`.
- Each thread is stored at:
  - `backend/data/threads/{threadId}.json`
- File shape:
  - `thread` metadata (`id`, `title`, `status`, timestamps)
  - `messages` (assistant-ui message snapshots)
  - `runs` (run status history)
  - `tool_calls` (pending/resolved HITL + edited args audit)
  - `history` (LocalRuntime exported repository: `headId`, `messages[]` for branch-safe restoration)
- Thread listing is derived by scanning thread JSON files (no separate persisted threadlist store).

### 6) Thread management APIs
- Implemented in `backend/routes/thread.py`, mounted in `backend/main.py`:
  - `GET /api/v1/threads`
  - `GET /api/v1/threads/{thread_id}`
  - `POST /api/v1/threads/initialize`
  - `GET /api/v1/threads/{thread_id}/history`
  - `POST /api/v1/threads/{thread_id}/history/append`
  - `PATCH /api/v1/threads/{thread_id}/rename`
  - `POST /api/v1/threads/{thread_id}/archive`
  - `POST /api/v1/threads/{thread_id}/unarchive`
  - `DELETE /api/v1/threads/{thread_id}`
  - `POST /api/v1/threads/{thread_id}/generate-title`

### 7) Proxy behavior
- Next proxy route (`frontend/app/api/be/[...path]/route.ts`) forwards backend requests.
- Streaming passthrough supports:
  - `text/stream`
  - `application/stream`
  - `application/x-ndjson`
  - `text/event-stream`
  - chunked transfer.
