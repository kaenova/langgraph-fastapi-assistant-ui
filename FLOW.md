# FLOW.md

## Scope
This document explains how functions and data connect end-to-end:
- from **welcome input** (`/welcome`)
- to **chat thread runtime** (`/chat/:threadId`)
- to **LangGraph backend execution + checkpoints**
- and how **branching** works for **regenerate** vs **edit**.

---

## 1) Main Components and Responsibilities

### Frontend
- `frontend/app/page.tsx`
  - Redirects root route to `/welcome`.
- `frontend/app/welcome/page.tsx`
  - Hosts `WelcomePage`.
- `frontend/lib/external-store-langgraph/welcome-page.tsx`
  - Captures first user prompt (and attachments) with `useExternalStoreRuntime`.
  - Creates `threadId` and stores first payload in `sessionStorage`.
  - Navigates to `/chat/{threadId}`.
- `frontend/app/chat/[threadId]/page.tsx`
  - Hosts `ChatThreadPage` with selected thread id.
- `frontend/lib/external-store-langgraph/chat-thread-page.tsx`
  - Main ExternalStore runtime integration (`onNew`, `onEdit`, `onReload`, `setMessages`).
  - Fetches snapshots and consumes token stream + snapshot stream.
  - Maintains per-run token target to avoid appending to old assistant messages.
- `frontend/lib/external-store-langgraph/external-store-chat.ts`
  - Transport helpers:
    - `fetchThreadMessages`
    - `streamThreadRun`
    - `toBackendMessageInput`
- `frontend/app/api/be/[...path]/route.ts`
  - Proxy from Next.js to FastAPI, including stream passthrough for `application/x-ndjson`.
- `frontend/components/assistant-ui/thread.tsx`
  - UI primitives:
    - `ActionBarPrimitive.Reload` (assistant regenerate)
    - `ActionBarPrimitive.Edit` (user edit)
    - `BranchPickerPrimitive` (switch branches on message nodes)

### Backend
- `backend/main.py`
  - Mounts routes:
    - `/api/v1/attachments`
    - `/api/v1/*` thread/chat routes
- `backend/lib/external_store_langgraph/thread_routes.py`
  - Thread state API:
    - `POST /threads` create thread id
    - `GET /threads/{thread_id}/messages` snapshot
    - `POST /threads/{thread_id}/runs/stream` streaming run
  - Converts frontend message format to LangGraph `HumanMessage`.
  - Resolves checkpoint fork points for new/edit/regenerate.
  - Emits NDJSON events:
    - `token` (incremental)
    - `snapshot` (authoritative state)
- `backend/routes/thread.py`
  - Thin compatibility export that re-exports `thread_routes` from `lib/external_store_langgraph`.
- `backend/agent/graph.py`
  - LangGraph state graph with `messages: Annotated[..., add_messages]`.
- `backend/lib/checkpointer.py`
  - Checkpointer provider (CosmosDB when configured, otherwise in-memory).

---

## 2) Core Data Contracts

### Frontend -> Backend run payload
`BackendRunRequest` (`frontend/lib/external-store-langgraph/external-store-chat.ts`)
- `message?: { content, attachments }`
- `parent_message_id?: string | null`
- `source_message_id?: string | null`
- `run_config?: Record<string, unknown>`

### Backend stream events (NDJSON)
- `{"type":"token","run_id":"...","sequence":1,"message_id":"...","text":"..."}`
- `{"type":"snapshot","run_id":"...","sequence":2,"thread_id":"...","checkpoint_id":"...","messages":[...],"messageRepository":{...}}`
- `{"type":"error","run_id":"...","sequence":N,"error":"..."}`

Notes:
- During active streaming, snapshot events may omit `messageRepository` to reduce payload size.
- The final snapshot remains authoritative and includes full `messageRepository` for branching state.
- Frontend drops stale/out-of-order events by run identity and sequence.

### Snapshot message metadata
Each serialized message includes:
- `metadata.custom.checkpointId`
- `metadata.custom.parentCheckpointId`

These fields are the bridge between UI message graph and LangGraph checkpoint graph.

---

## 3) Welcome -> Chat Handoff Flow

1. User enters message in `WelcomePage` composer.
2. `onNew` in `lib/external-store-langgraph/welcome-page.tsx`:
   - creates `threadId` (`crypto.randomUUID()`),
   - stores first payload under key:
     - `WELCOME_INITIAL_MESSAGE_KEY_PREFIX + threadId`,
   - navigates to `/chat/{threadId}`.
3. `ChatThreadPage` loads:
   - checks sessionStorage handoff key first,
   - if present, submits that payload to `/runs/stream` (skipping initial snapshot fetch),
   - otherwise fetches existing thread snapshot (`GET /threads/{threadId}/messages`),
   - removes handoff key.

Result: first message starts from welcome, but conversation state lives in chat thread route.

---

## 4) Normal New Message Flow (onNew)

1. User submits in chat composer.
2. `onNew` builds `BackendRunRequest` with:
   - `parent_message_id = message.parentId`
   - `source_message_id = message.sourceId`
   - `message = toBackendMessageInput(message)`
3. Backend `stream_thread_run` resolves checkpoint:
   - uses `parent_message_id` -> `_resolve_parent_checkpoint(...)`.
4. Backend runs `graph.stream(..., stream_mode=["messages","values"])`.
5. Frontend consumes stream:
   - `token` events update current in-flight assistant message incrementally.
   - interim `snapshot` events keep UI message content current.
   - final `snapshot` reconciles backend-authoritative message graph + repository.

---

## 5) Branching Semantics

## 5.1 Regenerate (assistant branch)
Trigger: `ActionBarPrimitive.Reload` in assistant action bar.

Flow:
1. Runtime calls `onReload(parentId, config)`.
2. Frontend sends:
   - `parent_message_id = parentId`
   - no new `message`.
3. Backend forks from checkpoint of that assistant parent message:
   - `_resolve_parent_checkpoint(...)`.
4. LangGraph re-executes from that checkpoint, producing alternative assistant continuation.

Expected branch owner: **assistant message**.

## 5.2 Edit (user branch)
Trigger: `ActionBarPrimitive.Edit` on user message + submit edit composer.

Flow:
1. Runtime calls `onEdit(message)`.
2. Frontend sends:
   - `source_message_id = edited message id`
   - `message = edited user content`
3. Backend detects edit path:
   - if `source_message_id && message`, uses `_resolve_edit_checkpoint(...)`.
   - forks from **parent checkpoint of edited user message**.
4. Backend appends edited user message as a new node and runs forward.

Expected branch owner: **user message**.

---

## 6) Branch Switching Flow

UI:
- `BranchPickerPrimitive.Previous/Next` in `thread.tsx` for both user and assistant rows.

Runtime:
- `useExternalStoreRuntime` uses `setMessages` capability to switch active branch projection.
- Message repository branch index changes which lineage is visible.

Important:
- Switching branch is a **view selection over persisted message graph**; it is not a new model run.

---

## 7) Stream Safety (Old-message Append Bug Prevention)

Problem previously:
- token chunks without early `message_id` could append to last assistant message.

Current fix in `lib/external-store-langgraph/chat-thread-page.tsx`:
- per-run `tokenTargetMessageIdRef`
- create temporary target id when `message_id` is not yet available
- replace temp id with actual id once provided
- no fallback to arbitrary “last assistant message”

Result:
- New run tokens stay isolated to current in-flight assistant message.

---

## 8) Reload/Persistence Flow

1. Browser refresh on `/chat/{threadId}`.
2. `ChatThreadPage` calls `fetchThreadMessages(threadId)`.
3. Backend reads graph state + checkpoint history:
   - `_get_thread_snapshot`
   - `_build_checkpoint_indexes`
4. Frontend restores full message/branch state from snapshot.

Result: branches persist across reload as long as backend checkpointer persists state.

---

## 9) Attachment Data Path (Brief)

1. Composer attachments are converted by `createAttachmentAdapter()`.
2. Frontend includes attachments in `BackendMessageInput`.
3. Backend maps attachment content to OpenAI-style content parts (`image_url`, `text`).
4. LangGraph model receives multimodal `HumanMessage` content.

---

## 10) End-State Behavior Summary

- Welcome input is handed off once into a concrete thread.
- Backend checkpoints are the source of truth.
- Regenerate branches assistant nodes.
- Edit branches user nodes.
- Branch picker selects lineage view.
- Streaming is incremental and isolated per active run.
