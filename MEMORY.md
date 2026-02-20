# MEMORY

## Objective
- Propose an implementation path for Assistant UI (Next.js) + LangGraph API (FastAPI) with:
  - Thread management
  - Welcome page
  - Welcome bootstrap with no thread ID initially, then create thread on first send
  - Chat streaming
  - Tool-calling streaming
  - Regenerate assistant message
  - Edit user message with branching
  - Bonus: HITL (approve / decline / change args) for `weather` tool

## Baseline Concept Chosen
- Frontend runtime: **`useExternalStoreRuntime`** (state ownership in frontend)
- Backend protocol: **assistant-transport style state streaming** (`set` + `append-text`)
- Agent execution: **LangGraph graph + tool calls + interrupts**
- Persistence: existing Cosmos-backed metadata/checkpointer for thread continuity

## What Has Been Explored
- Frontend currently uses `useChatRuntime` + `AssistantChatTransport` to `/api/chat` (OpenAI direct), not backend LangGraph.
- UI already has important primitives in place in `thread.tsx`:
  - Welcome UI (`ThreadWelcome`)
  - Branch picker (`BranchPickerPrimitive`)
  - Edit action (`ActionBarPrimitive.Edit`)
  - Regenerate action (`ActionBarPrimitive.Reload`)
  - Tool display fallback (`ToolFallback`)
- Backend currently exposes only attachment routes; no chat/thread runtime routes yet.
- LangGraph graph + tools already exist in backend; `weather` tool exists but is not wired to frontend runtime flow.

## Exploration Results (Resolved)
1. **Runtime API surface choice**
   - `useExternalStoreRuntime` provides all required callbacks for this project (`onNew`, `onEdit`, `onReload`, `onCancel`, `onAddToolResult`, `onResumeToolCall`, `setMessages`).
   - `adapters.threadList` exists in `ExternalStoreAdapter` but is marked deprecated/unstable in the package types.
   - `unstable_useRemoteThreadListRuntime` exists and is the recommended custom-thread-list path in docs.
   - External-store thread core does not auto-block first send for thread initialization; welcome bootstrap must explicitly create/init thread before first backend send.
   - Decision: keep **ExternalStoreRuntime** for message/control ownership, and use remote-thread-list style thread metadata wiring where needed; do **explicit first-send thread creation** in app logic.

2. **HITL interrupt model choice**
   - LangGraph native interrupt/resume is available and works in this environment (`interrupt(...)`, `Command(resume=...)`, `thread_id` checkpointed resume).
   - Streaming updates surface interrupts via `__interrupt__`, which maps cleanly to frontend tool requires-action states.
   - Decision: use **LangGraph-native interrupts as source of truth**, and use transport commands only as delivery envelopes between frontend and backend.

3. **Canonical branching persistence schema**
   - assistant-ui tree/branching is parent-child based (message IDs + `parentId`), not `branch_id` based.
   - Canonical export shape in assistant-ui is `ExportedMessageRepository`:
     - `headId`
     - `messages: [{ parentId, message, runConfig? }]`
   - Decision: persist at minimum `id`, `parent_id`, message payload (`role/content/status/metadata`), and optional `run_config`; treat `branch_id` as optional denormalized index only.

## What Needs Done (Execution Plan)
1. **Frontend runtime migration**
   - Replace `useChatRuntime` with a dedicated runtime provider using `useExternalStoreRuntime`.
   - Maintain thread-scoped message store and running state.
   - Add handlers: `onNew`, `onEdit`, `onReload`, `onCancel`, `onAddToolResult`, `onResumeToolCall`, `setMessages`.

2. **Thread management**
   - Introduce thread list state + adapter (new/switch/rename/archive/delete).
   - Add frontend API client for thread CRUD against FastAPI.
   - Persist `externalId` per thread for backend state loading.
   - **Lazy thread bootstrap from welcome**:
     - Initial welcome state must not have a thread ID.
     - On first Enter/send: create thread ID first, navigate to `/chat/{threadId}`, then dispatch/send the message.

3. **Backend assistant transport endpoint**
   - Add `/assistant` endpoint (or `/api/v1/assistant`) accepting command batches.
   - Stream state ops (`set`, `append-text`) rather than waiting for full response.
   - Map incoming commands:
      - `add-message` -> append user message + trigger LangGraph run
      - `resume-tool-call` (or equivalent envelope) -> `Command(resume=payload)` for interrupted graph
      - `add-tool-result` -> optional direct tool-result injection path when needed

4. **Tool streaming + weather HITL**
   - Emit tool-call message parts with `status: "requires-action"` when interruption happens.
   - Frontend weather tool UI renders controls:
     - Approve
     - Decline
     - Change args (editable city/unit)
   - Submit user choice via `onResumeToolCall` (preferred for interrupt resume); keep `onAddToolResult` for non-interrupt/manual result paths.

5. **Edit + regenerate branching**
   - `onEdit`: truncate from parent, insert edited user message with correct `parentId`, rerun.
   - `onReload`: regenerate assistant response from selected branch context.
   - Keep parent-child lineage to power `BranchPickerPrimitive`.

6. **Welcome page behavior**
   - Keep current `ThreadWelcome` behavior; show only when current thread has zero messages.
   - Welcome route can represent draft/no-thread state (`threadId = null`) until first send.

## Data / Logic Wiring (Detailed)
### Frontend runtime state (ExternalStoreRuntime owner)
- `currentThreadId: string | null`
- `threads: Record<string, { messages: ThreadMessageLike[]; isRunning: boolean; interrupts: unknown[] }>`
- `uiRoute: string` (welcome route starts at `/` with `currentThreadId = null`)
- `pendingWelcomeMessage: AppendMessage | null` (temporary buffer during first-send bootstrap)

### Welcome -> first message bootstrap (strict order)
1. User presses Enter from welcome composer (no thread selected yet).
2. Frontend calls `createThread()` to backend and receives `threadId`.
3. Frontend updates runtime/thread store with new thread shell (`messages=[]`, `isRunning=false`).
4. Frontend navigates to `/chat/{threadId}`.
5. Frontend appends user message into that thread and starts stream/send call.
6. Backend streams assistant/tool updates into that same `threadId`.

### Frontend-backend API wiring
- `POST /api/v1/threads` -> create thread (`{ thread_id, title?, status }`)
- `GET /api/v1/threads/{thread_id}/state` -> hydrate messages + interrupts
- `POST /api/v1/assistant` -> process command batch for a thread
  - `add-message`: push user message and run graph
  - `resume-tool-call`: resume interrupted graph with payload (`approve`/`decline`/`change-args`)
  - `add-tool-result`: optional explicit result injection path

### Assistant transport streaming contract
- Stream operations are emitted as state ops:
  - `set` for snapshots/object fields (thread id, messages, interrupts, route)
  - `append-text` for incremental token updates
- Client reducer applies ops into external store and re-renders thread primitives.

### Tool HITL weather flow wiring
1. Backend emits tool-call part with `status="requires-action"` + interrupt payload.
2. Frontend weather tool UI renders **Approve / Decline / Change args** controls.
3. UI sends `resume-tool-call` (preferred) with:
   - `decision: "approve" | "decline" | "change-args"`
   - optional changed `args`
4. Backend maps payload to `Command(resume=...)`, updates tool args if needed, executes or aborts tool, then streams continuation.

### Edit/regenerate branching wiring
- `onEdit`:
  - locate edited message parent
  - truncate descendants in active branch
  - create new user message linked by `parentId` to edited message parent
  - rerun from edited point
- `onReload`:
  - keep current branch context
  - regenerate assistant message node
- `BranchPickerPrimitive` navigates sibling branch nodes by shared parent lineage.

## Implementation Plan (Concrete, File-Level)
1. **Frontend runtime + routing bootstrap**
   - `frontend/app/assistant.tsx` -> replace with provider using `useExternalStoreRuntime`.
   - Add `frontend/app/chat/[threadId]/page.tsx` and keep welcome page at `/`.
   - Add runtime store/provider (e.g. `frontend/app/my-runtime-provider.tsx`) with first-send thread bootstrap logic.
2. **Frontend API and adapters**
   - Add `frontend/lib/chat-api.ts` for thread CRUD + assistant command streaming.
   - Add thread-list adapter wiring for create/switch/rename/archive/delete.
3. **Backend routes**
   - Add `backend/routes/thread.py` for thread create/list/load/rename/archive/delete.
   - Add `backend/routes/assistant.py` for assistant transport command + stream ops.
   - Register both routers in `backend/main.py`.
4. **LangGraph integration**
   - Reuse `backend/agent/graph.py` + tools, but add interrupt/resume payload mapping for HITL weather.
5. **Tool UI**
   - Add `frontend/components/tools/weather-tool.tsx` with approve/decline/change-args actions.
6. **Contract validation (no server)**
   - Keep fixture-first validation in `scripts/fixtures/weather-assistant-transport.json`.
   - Maintain backend/frontend contract scripts as compatibility guard for state-op wiring.

## Deep-Dive Contracts (Second Audit)
### Runtime callback -> UX capability map
- `setMessages` -> enables branch switching in assistant-ui runtime capabilities.
- `onEdit` -> enables inline user-message edit flow.
- `onReload` -> enables regenerate action for assistant messages.
- `onCancel` -> enables cancel during running generation.
- `onAddToolResult` -> supports adding tool result into a tool call.
- `onResumeToolCall` -> supports interrupt-resume payload for human-in-the-loop tool calls.

### Message model contract (frontend canonical)
- Preferred canonical runtime message model is assistant-ui `ThreadMessage` lineage:
  - `message.id` (stable unique message ID)
  - `parentId` relation (lineage + branching)
  - `role` (`user` / `assistant` / `system`)
  - `content[]` parts (`text`, `tool-call`, `tool-result`, etc.)
  - assistant `status` (`running`, `requires-action`, `complete`, `incomplete`)
- Persistence canonical form:
  - `ExportedMessageRepository` with:
    - `headId`
    - `messages: [{ parentId, message, runConfig? }]`

### Thread metadata contract (backend/API)
- `thread_id` is the external durable thread key.
- Thread metadata minimum fields:
  - `id`/`thread_id`
  - `status`: `draft | regular | archived`
  - `title` (nullable during draft)
  - `created_at`, `updated_at`
- Welcome bootstrap invariant:
  - draft state starts with `thread_id = null`
  - first send must produce `thread_id` before first message persistence/stream.

### Assistant command envelope (proposed)
- Request shape (conceptual):
  - `thread_id: string`
  - `commands: Command[]`
  - optional `state` snapshot / metadata
- Command variants used by this implementation:
  - `add-message`
  - `resume-tool-call` (preferred for HITL interrupt resume)
  - `add-tool-result` (optional/manual explicit result path)
- Stream response shape:
  - state operations (`set`, `append-text`) consumable by frontend reducer.

### HITL payload contract for weather
- Interrupt payload from backend should include:
  - `tool_call_id`
  - `tool_name = "weather"`
  - current `args`
  - allowed decisions: `approve | decline | change-args`
- Resume payload from frontend:
  - `decision`
  - optional `args` overrides (for `change-args`)
  - optional reason/message (for `decline`)

## State Machines (Implementation Reference)
### Thread lifecycle
- `draft(no-thread-id)` -> `regular(active)` -> `archived` -> `deleted`
- Transition guard:
  - `draft -> regular` only on first send success (thread create + route switch succeeded).

### Run lifecycle per thread
- `idle` -> `sending` -> (`requires-action` | `complete` | `incomplete`)
- `requires-action` -> `resuming` -> (`sending` | `complete` | `incomplete`)
- `sending` -> `cancelled` when user cancels.

## Edge Cases and Handling Rules
1. If thread creation fails on first send, keep user on welcome and keep composer text intact.
2. If navigation to `/chat/{threadId}` fails after successful create, do not drop message payload; retry navigation and send.
3. Reject duplicate first-send race by locking bootstrap (`pendingWelcomeMessage` gate).
4. If stream breaks mid-run, set assistant status to `incomplete/error` and keep partial tokens.
5. On edit, truncate descendants from edited node before rerun.
6. On reload, regenerate only the selected assistant-node branch context.
7. On interrupt, render explicit action UI and block implicit auto-continue.
8. On decline decision, create explicit assistant completion/incomplete message explaining cancellation.
9. Preserve `thread_id` + `tool_call_id` correlation in logs for resume traceability.
10. Never map branches only by `branch_id`; always preserve `parentId` lineage.

## Acceptance Criteria (Implementation-Ready)
- Welcome page starts with no thread ID and no persisted draft thread.
- First-send path order is guaranteed: create thread -> navigate -> send -> stream.
- Thread switching reloads correct branch head and message history.
- Edit/regenerate produce visible sibling branches in `BranchPickerPrimitive`.
- Weather HITL supports approve/decline/change-args and resumes correctly.
- Streaming covers:
  - assistant token streaming (`append-text`)
  - tool-call state updates (`set`)
  - interrupt surfacing + resume.
- No-server fixture scripts remain green after each contract update.

## Remaining Exploration (Non-Blocking)
- Decide final public command name for interrupt resume (`resume-tool-call` vs another name) before coding backend route.
- Decide whether to expose one combined `/api/v1/assistant` endpoint or split command and stream endpoints.
- Decide whether to adopt `unstable_useRemoteThreadListRuntime` now or keep pure external-store thread metadata handling first (phased migration).

## Important Files
- Existing:
  - `frontend/app/assistant.tsx`
  - `frontend/components/assistant-ui/thread.tsx`
  - `frontend/components/assistant-ui/tool-fallback.tsx`
  - `frontend/app/api/be/[...path]/route.ts`
  - `backend/agent/graph.py`
  - `backend/agent/tools.py`
  - `backend/main.py`
  - `backend/lib/database.py`
- To add in implementation phase:
  - `frontend/app/MyRuntimeProvider.tsx` (or similar runtime provider)
  - `frontend/lib/chat-api.ts` (thread + run APIs)
  - `frontend/components/tools/weather-tool.tsx` (HITL UI)
  - `backend/routes/assistant.py` (transport endpoint)
  - `backend/routes/thread.py` (thread CRUD + state load)

## No-Server Hypothesis Test (Created)
- Shared fixture data: `scripts/fixtures/weather-assistant-transport.json`
- Backend contract script: `scripts/test_backend_contract.py`
- Frontend contract script: `scripts/test_frontend_contract.mjs`
- Purpose: validate that one shared transport stream fixture can be interpreted by both backend-side and frontend-side logic without running any server.

## Current Status
- Explored baseline and selected architecture: **done**
- Proposal documented: **done**
- No-server integration hypothesis scripts: **done**
- Welcome lazy thread-create + navigate requirement added to plan/fixture/scripts: **done**
