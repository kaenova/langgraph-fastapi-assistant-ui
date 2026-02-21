# FLOW.md

## End-to-end flow (current implementation)

### 1) Entry and thread bootstrap
- User lands on `/` (`frontend/app/page.tsx`) and sees `WelcomePage` (`frontend/app/welcome-page.tsx`).
- Welcome uses Assistant UI `ComposerPrimitive` (same composer UX as chat, including attachments).
- On send from welcome composer:
  - Frontend creates `threadId` via `crypto.randomUUID()`.
  - Calls `POST /api/be/api/v1/threads/initialize` with `{ threadId }`.
  - Stores the initial user message payload in `sessionStorage` keyed by `threadId`.
  - Redirects to `/chat/{threadId}` (no query params).

### 2) Chat page runtime wiring
- `/chat/[threadId]` renders `LocalRuntimeProvider` (`frontend/components/assistant-ui/runtime-provider.tsx`).
- Provider uses:
  - `useLocalRuntime` for model execution.
  - `useLocalRuntime(..., { adapters: { history } })` to load/append message history from backend.
  - `useLocalRuntime(..., { adapters: { attachments } })` with a vision image adapter that compresses large images and converts them to base64 data URLs.
  - `unstable_useRemoteThreadListRuntime` for thread lifecycle API integration.
- Provider ensures current thread exists, switches runtime to that thread, then renders `Thread`.
- Initial welcome message (if any) is appended via `useThreadRuntime().append(...)` only when:
  - thread history has finished loading,
  - current thread has zero messages,
  - and a `sessionStorage` payload exists for that thread.

### 3) Message run + streaming
- LocalRuntime adapter `run()` sends:
  - `POST /api/be/api/v1/threads/{threadId}/runs/stream`
  - payload: `{ messages, runConfig }`.
- Backend (`backend/routes/chat.py`) converts assistant-ui messages to LangChain messages.
- User image parts are mapped from both `message.content` and top-level `message.attachments[].content` into LangChain **standard content blocks** (`{ type: "image", url: "data:image/..." }`) so vision-capable models can consume base64 image inputs.
- Backend guards oversized inline image data and omits it with a user-visible text note to avoid upstream body-size validation errors.
- Backend invokes `model.bind_tools(AVAILABLE_TOOLS).astream(...)` and auto-executes emitted tool calls server-side.
- Backend streams SSE EventStream events (`text/event-stream`) back to frontend:
  - `text_delta`
  - `tool_call`
  - `tool_result` (when present)
  - `done`
  - `error`
- Frontend parses EventStream incrementally (with NDJSON fallback for compatibility), reconstructs assistant parts, and yields updates to LocalRuntime.

### 4) Tool calling (automatic)
- If model emits tool calls, backend executes them immediately and continues the same run loop.
- Frontend receives streamed `tool_call` and `tool_result` events for visibility.
- Run always completes with `done: complete` (no approval step).

### 5) Persistence model (local JSON per thread)
- Implemented in `backend/lib/thread_store.py`.
- Each thread is stored at:
  - `backend/data/threads/{threadId}.json`
- File shape:
  - `thread` metadata (`id`, `title`, `status`, timestamps)
  - `messages` (assistant-ui message snapshots)
  - `runs` (run status history)
  - `tool_calls` (executed tool-call audit with args and results status)
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
