# Assistant UI + LangGraph (FastAPI) Integration

This repository is a reference implementation that wires **Assistant UI** (Next.js) to a **LangGraph** backend (FastAPI) with:

- Streaming tokens via **SSE**
- Tool calling + tool results
- Human-in-the-loop (HITL) tool approval via **LangGraph interrupts**
- Assistant UI v1 features: **reload**, **edit**, **branching** backed by LangGraph **checkpoint time-travel/forking**
- Server-side persistence of Assistant UI's **MessageRepository** keyed by `thread_id` (CosmosDB)

If you want to integrate these ideas into another repo, this README tells you what to **copy**, what to **create**, and what to **adjust**.

## Architecture (what connects to what)

```text
Assistant UI (React) -> LocalRuntime adapter -> Next.js proxy (/api/be/*)
  -> FastAPI (/api/v1/*) -> LangGraph (checkpointer) -> CosmosDB

CosmosDB containers:
  - langgraph_checkpoints  (LangGraph state)
  - thread_repos           (Assistant UI MessageRepository pointer metadata)

Azure Blob Storage:
  - thread_repos/*         (Assistant UI MessageRepository payloads)
```

Key rule: the backend is authoritative.

- The frontend does NOT replay the full transcript into LangGraph.
- The frontend sends only the delta user message plus a `checkpoint_id` to fork from.

## Quickstart (this repo)

Backend:

```bash
cd backend
uv sync
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
bun install
bun run dev
```

Set `BACKEND_URL` for the frontend if your FastAPI host differs:

```bash
export BACKEND_URL="http://localhost:8000"
```

## Integrate with LLM

If you want to port this integration into an existing codebase quickly, you can have an LLM agent add this repo as a reference **submodule** and generate a concrete integration plan from the submodule README.

### Paste this prompt into your LLM agent (it will add the submodule)

Replace paths/placeholders, then send the full prompt as-is:

```text
You are a senior full-stack engineer. Your job is to create an integration plan and implementation outline based on the current project and the example project based on the submodule.

Context:
- Target repository root: <ABSOLUTE_PATH_TO_MY_REPO>
- Reference repo URL: https://github.com/kaenova/langgraph-fastapi-assistant-ui
- Reference submodule path to add: vendor/assistant-ui-langgraph-reference
- Stack constraints:
  - Backend: FastAPI + LangGraph (Python 3.12+)
  - Frontend: Next.js (TypeScript)
- Requirements:
  - Streaming over SSE
  - Tool calling + tool results
  - Human-in-the-loop tool approval using LangGraph interrupts + resume endpoint
  - Support assistant-ui features: reload/edit/branching using checkpoint time-travel/forking
  - Persist assistant-ui MessageRepository server-side keyed by thread_id

First, in <ABSOLUTE_PATH_TO_MY_REPO>, add the reference repo as a git submodule at vendor/assistant-ui-langgraph-reference:

  git submodule add https://github.com/kaenova/langgraph-fastapi-assistant-ui vendor/assistant-ui-langgraph-reference
  git submodule update --init --recursive

Then, read these docs from the submodule:

1) vendor/assistant-ui-langgraph-reference/README.md
2) vendor/assistant-ui-langgraph-reference/backend/routes/chat.py (SSE contract)
3) vendor/assistant-ui-langgraph-reference/frontend/components/assistant-ui/CustomLanggraphRuntime.tsx (runtime adapter)

Deliverables:
1) A step-by-step integration plan tailored to my repo, with a clear order of operations.
2) A file-by-file map of what to copy vs what to re-implement, including the exact destination paths.
3) The SSE event contract my backend must emit (verbatim JSON shapes).
4) The minimal set of endpoints I must add (paths + request/response shapes).
5) A checklist to validate correctness (manual tests + build commands).
6) A short risk list (auth/multi-user, data retention, replay/branching pitfalls).

Rules:
- Prefer minimal diff: integrate into existing structure instead of rewrites.
- Do NOT invent endpoints; align with the reference README unless you explicitly call out a divergence.
- If something is ambiguous in my repo, ask exactly ONE targeted question at the end and provide a recommended default.

Output format:
- Use headings and bullet points.
- Include commands and code snippets where useful.
```

## Integration Checklist

### 1) Backend: LangGraph + SSE endpoints

Copy/create these backend pieces:

- `backend/routes/chat.py`
  - `POST /api/v1/chat/stream`: start a run and stream events
  - `POST /api/v1/chat/feedback`: resume after HITL approval
  - `GET /api/v1/chat/interrupt`: query whether a thread/checkpoint is currently paused (rehydrate approvals after refresh)
- `backend/agent/graph.py`
  - Graph compiled with a **checkpointer**
  - HITL approval node uses `interrupt(...)` and resumes via `Command(resume=...)`
- `backend/lib/checkpointer.py`
  - CosmosDB checkpointer (`langgraph_checkpoint_cosmosdb.CosmosDBSaver`)

Wire routes in `backend/main.py`:

- `app.include_router(chat_routes, prefix="/api/v1/chat")`

#### SSE event contract

The frontend adapter expects these SSE `data:` payloads (JSON), in any order consistent with the run:

- `{"type":"meta","phase":"start","thread_id":"...","checkpoint_id":null}`
- `{"type":"token","content":"..."}`
- `{"type":"tool_call","id":"...","name":"...","arguments":{...}}`
- `{"type":"tool_result","tool_call_id":"...","name":"...","content":"..."}`
- `{"type":"interrupt","payload":{ "type":"tool_approval_required","tool_calls":[...] }}`
- `{"type":"meta","phase":"interrupt","checkpoint_id":"..."}`
- `{"type":"meta","phase":"complete","checkpoint_id":"..."}`
- `{"type":"done"}` and a final `data: [DONE]`
- `{"type":"error","error":"..."}`

Important backend detail (HITL correctness): when inspecting the final graph state after streaming, do NOT pass the same `checkpoint_id` you resumed from, otherwise LangGraph will time-travel and you may re-emit the same interrupt.

### 2) Backend: persist Assistant UI MessageRepository (thread-only)

Assistant UI keeps a message DAG (branches/edits). To make reload/edit/branch survive refresh, persist the exported repository server-side.

Copy/create:

- `backend/routes/thread_repo.py`
  - `GET /api/v1/threads/{thread_id}/repo`
  - `PUT /api/v1/threads/{thread_id}/repo`
- `backend/lib/thread_repo_store.py`
  - CosmosDB container `thread_repos` partitioned by `/thread_id` (pointer metadata)
  - Repo payloads stored in Azure Blob Storage under `thread_repos/`

Wire it in `backend/main.py`:

- `app.include_router(thread_repo_routes, prefix="/api/v1/threads")`

Security note: this implementation intentionally keys persistence by `thread_id` only (no user scoping). Do not use this as-is for multi-user production without adding auth + tenant/user partitioning.

### 3) Backend: environment variables

For the checkpointer + repo store (CosmosDB), set:

- `COSMOS_ENDPOINT`
- `COSMOS_KEY`
- `COSMOS_DATABASE_NAME`

For repo payloads in Blob Storage, set:

- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_STORAGE_CONTAINER_NAME`

Your model/tool environment variables depend on your graph/tools (see `backend/agent/tools.py`).

### 4) Frontend: Next.js proxy route

Copy/create:

- `frontend/app/api/be/[...path]/route.ts`

This proxies browser requests to `process.env.BACKEND_URL` (default `http://localhost:8000`) and correctly forwards streaming SSE.

### 5) Frontend: LocalRuntime adapter + checkpoint mapping

Copy/create:

- `frontend/components/assistant-ui/CustomLanggraphRuntime.tsx`

What it does:

- Maintains a stable `thread_id` (URL `?thread=` + `localStorage`)
- Implements `ChatModelAdapter.run()` that calls:
  - `/api/be/api/v1/chat/stream` for normal runs
  - `/api/be/api/v1/chat/feedback` to resume interrupts
- Parses SSE and yields Assistant UI snapshots
- Stores LangGraph checkpoint ids into assistant message metadata:
  - `metadata.custom.lg = { thread_id, checkpoint_id }`
- Persists/restores Assistant UI's message DAG:
  - `runtime.thread.export()` -> `PUT /api/be/api/v1/threads/{thread_id}/repo`
  - `GET .../repo` -> `runtime.thread.import(...)`
- Rehydrates HITL approvals after refresh:
  - calls `GET /api/be/api/v1/chat/interrupt?thread_id=...&checkpoint_id=...`

Branching/editing correctness:

- For any user message send/edit/reload, compute `checkpoint_id` from the parent message's stored metadata.
- Never fall back to "latest checkpoint" for existing threads; missing checkpoint data should be treated as an error (otherwise branches merge).

### 6) Frontend: render tool calls + HITL approval UI

Copy/create:

- `frontend/components/assistant-ui/tool-fallback.tsx`
  - Renders tool calls
  - For interrupt tool calls: shows Approve/Reject, editable JSON args, and "Send Feedback"
- `frontend/components/assistant-ui/thread.tsx`
  - Uses `ToolFallback` for tool-call message parts

#### Tool-specific UI (recommended)

This repo supports custom Tool UI per tool name using assistant-ui's `Tools()` API.

How it works:

- Define a **UI-only toolkit** where keys match backend tool names.
- Register the toolkit once in the runtime provider via `useAui({ tools: Tools({ toolkit }) })`.
- Keep `ToolFallback` as the fallback UI for tools without custom renderers.

Reference implementation in this repo:

- `frontend/components/assistant-ui/toolkit.tsx`
  - Exports `appToolkit` with `current_weather`
- `frontend/components/assistant-ui/CustomLanggraphRuntime.tsx`
  - Registers `Tools({ toolkit: appToolkit })` via `useAui(...)` and extends the provider context
- `frontend/components/assistant-ui/tools/current-weather.tsx`
  - Fully custom UI card for `current_weather`

To add another custom tool UI:

1) Add a renderer in `frontend/components/assistant-ui/toolkit.tsx`:

```tsx
import { z } from "zod";

export const appToolkit: Toolkit = {
  my_backend_tool: {
    description: "...",
    parameters: z.object({ /* args shape */ }),
    // UI-only: omit execute (backend runs it)
    render: (props) => <MyBackendToolCard {...props} />,
  },
};
```

2) Implement the card component (e.g. `frontend/components/assistant-ui/tools/my-backend-tool.tsx`).

HITL note (important):

- In this repo, HITL is triggered by **LangGraph interrupts** (`type: "interrupt"` SSE events),
  not by `human()` inside a tool.
- When resuming via `/api/v1/chat/feedback`, tool results may stream without re-emitting the
  original tool-call part in the same run.
- Therefore, custom tool UIs that want to show results reliably must support **result backfill**
  (see `frontend/components/assistant-ui/tool-fallback.tsx` and `frontend/components/assistant-ui/tools/current-weather.tsx`).

The HITL UI state is held in React state (decisions/args drafts), but the *existence* of a pending interrupt is rehydrated from the backend after refresh.

### 7) Optional: attachments proxy + URL rewriting

This repo includes an image attachment adapter:

- `frontend/lib/vision-adapter.ts`

And backend attachment routes (upload + download) under:

- `backend/routes/attachment.py`

If you use `chatbot://{id}` URLs in messages, make sure your graph sanitization converts them to real URLs before sending to the model.

## What to copy into your repo

Backend:

- `backend/routes/chat.py`
- `backend/routes/thread_repo.py`
- `backend/lib/checkpointer.py`
- `backend/lib/thread_repo_store.py`
- `backend/agent/graph.py` (or port the HITL + checkpointer parts into your existing graph)
- `backend/main.py` (or port the router wiring)

Frontend:

- `frontend/app/api/be/[...path]/route.ts`
- `frontend/components/assistant-ui/CustomLanggraphRuntime.tsx`
- `frontend/components/assistant-ui/thread.tsx`
- `frontend/components/assistant-ui/tool-fallback.tsx`

## What you must adjust

- Storage:
  - If you don't want CosmosDB, replace `backend/lib/checkpointer.py` and `backend/lib/thread_repo_store.py` with your own persistence.
- Auth/multi-user:
  - Add authentication and scope `thread_id` to a user/tenant; update the `thread_repos` partitioning.
- Graph/tools:
  - Update dangerous tool allowlist in `backend/agent/graph.py` and tool definitions in `backend/agent/tools.py`.
- Backend URL:
  - Set `BACKEND_URL` for the frontend in your environment.

## Troubleshooting

- Branches merge after editing: you're missing `checkpoint_id` mapping from message metadata; ensure assistant messages store `metadata.custom.lg.checkpoint_id` and your adapter uses the parent checkpoint.
- Approval UI disappears after refresh: ensure `GET /api/v1/chat/interrupt` exists and the frontend calls it after importing the thread repo.
- Interrupt repeats after approval: ensure the backend state inspection after streaming uses thread-only config (no `checkpoint_id`).

### Tool UI doesn’t appear for a tool

- Ensure the toolkit key exactly matches the backend tool name (e.g. `current_weather`).
- Ensure `CustomLanggraphRuntime` registers the toolkit via `Tools()` and extends the Assistant UI context using `AuiProvider` (see `frontend/components/assistant-ui/CustomLanggraphRuntime.tsx`).
