# FLOW.md

## End-to-end flow (current implementation)

### 1) Entry and thread bootstrap
- Route files in `frontend/app` are thin wrappers; reusable custom frontend template logic lives in `frontend/lib/assistant-template/`.
- Root app layout mounts `AssistantTemplateShellLayout` (`frontend/lib/assistant-template/app-shell-layout.tsx`) so `/` and `/chat/[threadId]` share a left thread navigation rail.
- Shell thread list loads `GET /api/be/api/v1/threads` and navigates with Next links to `/chat/{threadId}`.
- User lands on `/` (`frontend/app/page.tsx`) and sees `WelcomePage` (`frontend/lib/assistant-template/welcome-page.tsx`).
- Welcome runtime is created via `useTemplateLocalRuntime` with shared attachment adapter config and no history adapter.
- Welcome uses Assistant UI `ComposerPrimitive` (same composer UX as chat, including attachments).
- On send from welcome composer:
  - Frontend creates `threadId` via `crypto.randomUUID()`.
  - Calls `POST /api/be/api/v1/threads/initialize` with `{ threadId }`.
  - Stores the initial user message payload in `sessionStorage` keyed by `threadId`.
  - Redirects to `/chat/{threadId}` (no query params).

### 2) Chat page runtime wiring
- `/chat/[threadId]` renders `LocalRuntimeProvider` (`frontend/lib/assistant-template/runtime/local-runtime-provider.tsx`).
- Provider uses:
  - `useTemplateLocalRuntime` (`frontend/lib/assistant-template/runtime/use-template-local-runtime.ts`) as the shared runtime hook.
  - Shared attachment adapter config (vision image compression + base64 conversion) across both welcome and chat.
  - Optional history adapter injection in chat to load/append message history from backend.
  - `unstable_useRemoteThreadListRuntime` for thread lifecycle API integration.
- Provider ensures current thread exists, switches runtime to that thread, then renders `Thread`.
- Initial welcome message (if any) is appended via `useThreadRuntime().append(...)` only when:
  - thread history has finished loading,
  - current thread has zero messages,
  - and a `sessionStorage` payload exists for that thread.
- Provider also mounts `ThreadCompactionSync` to auto-run compaction when backend sets `next_should_compact` in assistant metadata.

### 3) Message run + streaming
- LocalRuntime adapter `run()` sends:
  - `POST /api/be/api/v1/threads/{threadId}/runs/stream`
  - payload: `{ messages, runConfig }`, where `messages` is sliced from the latest compaction marker (`metadata.custom.compaction === true`) if present.
- Backend (`backend/routes/chat.py`) converts assistant-ui messages to LangChain messages.
- User image parts are mapped from both `message.content` and top-level `message.attachments[].content` into LangChain **standard content blocks** (`{ type: "image", url: "data:image/..." }`) so vision-capable models can consume base64 image inputs.
- Backend guards oversized inline image data and omits it with a user-visible text note to avoid upstream body-size validation errors.
- Backend invokes `model.bind_tools(AVAILABLE_TOOLS).astream(...)` and auto-executes emitted tool calls server-side.
- Backend streams SSE EventStream events (`text/event-stream`) back to frontend:
  - `text_delta`
  - `tool_call`
  - `tool_result` (when present)
  - `done` (includes metadata, including compaction flags)
  - `error`
- Frontend parses EventStream incrementally (with NDJSON fallback for compatibility), reconstructs assistant parts, and yields updates to LocalRuntime.

### 4) Message compaction (client-triggered summary)
- At the end of each normal run, backend estimates total conversation tokens and stores in assistant metadata:
  - `metadata.custom.total_tokens`
  - `metadata.custom.next_should_compact` (true when threshold is exceeded)
- Threshold is configured by `COMPACTION_TRIGGER_TOKENS` (default: `10000`).
- Frontend receives `done.metadata` and, when the latest assistant message has `next_should_compact === true`, triggers compaction immediately.
- Frontend calls stateless `POST /api/be/api/v1/compact` with the current context window (same compaction-aware sliced messages used for normal run input).
- Backend compaction route (`backend/routes/compaction.py`) does:
  - assistant-ui -> LangChain conversion
  - tool-call sequence sanitization
  - attachment URL expansion (`chatbot://` to blob URLs)
  - LLM summary generation via compaction graph (`backend/agent/compaction_graph.py`)
- Compaction response returns a normal assistant message with `metadata.custom.compaction = true`.
- Frontend appends that message via `threadRuntime.append(...)`; this message becomes the new context anchor for subsequent runs.

### 5) Tool calling (automatic)
- If model emits tool calls, backend executes them immediately and continues the same run loop.
- Frontend receives streamed `tool_call` and `tool_result` events for visibility.
- Run always completes with `done: complete` (no approval step).

### 6) Persistence model (local JSON per thread)
- Implemented in `backend/lib/thread_store.py`.
- Each thread is stored at:
  - `backend/data/threads/{threadId}.json`
- File shape:
  - `thread` metadata (`id`, `title`, `status`, timestamps)
  - `messages` (assistant-ui message snapshots)
  - `runs` (run status history)
  - `tool_calls` (executed tool-call audit with args and results status)
  - `history` (LocalRuntime exported repository: `headId`, `messages[]` for branch-safe restoration)
- Persistence keeps full snapshots and includes compaction summary messages as regular assistant messages; original local history repository remains intact.
- Thread listing is derived by scanning thread JSON files (no separate persisted threadlist store).

### 7) API surface
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
- Chat and compaction routes in `backend/routes/chat.py` and `backend/routes/compaction.py`:
  - `POST /api/v1/threads/{thread_id}/runs/stream`
  - `POST /api/v1/compact`

### 8) Proxy behavior
- Next proxy route (`frontend/app/api/be/[...path]/route.ts`) forwards backend requests.
- Streaming passthrough supports:
  - `text/stream`
  - `application/stream`
  - `application/x-ndjson`
  - `text/event-stream`
  - chunked transfer.
