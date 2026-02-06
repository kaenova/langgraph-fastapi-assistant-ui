# AGENTS.md - Coding Guidelines for AI Agents

This document provides agentic coding systems (like yourself) with build commands, testing procedures, and code style guidelines for the langgraph-local-runtime repository.

## Quick Reference

- **Language Stack**: Python 3.12+ (backend), TypeScript 5 + Next.js 16 (frontend)
- **Build Tools**: uv + FastAPI (backend), bun (frontend)
- **Framework**: LangGraph + FastAPI (backend), Next.js + Assistant UI (frontend)

## 1. Build & Run Commands

### Backend (Python/FastAPI)

```bash
# Development: Start the FastAPI server with auto-reload
cd backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production build
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Install dependencies
cd backend && uv sync
```

### Frontend (Next.js)

```bash
# Development: Start Next.js dev server with Turbopack
cd frontend && bun run dev

# Production build
cd frontend && bun run build

# Start production server
cd frontend && bun start

# Install dependencies
cd frontend && bun install  # or pnpm install
```

## 2. Testing & Linting

### Backend Testing
- **Status**: No test framework configured yet (consider pytest)
- **Suggested**: Add pytest configuration and test files
- **Manual testing**: Use FastAPI `/docs` endpoint at `http://localhost:8000/docs`

### Frontend Testing
- **Status**: No test framework configured (consider Vitest)
- **TypeScript Checking**: Built into Next.js dev server
- **Manual testing**: Try to build the application by doing the `bun run build`

### Code Quality
- **Backend**: No eslint/linter config
- **Frontend**: No eslint config

## 3. Code Style Guidelines

### Python (Backend)

**Imports**:
- Group imports: stdlib → third-party → local (see `main.py:1-20`)
- Use docstrings for modules: `"""Main FastAPI server with LangGraph integration."""`
- Relative imports for local modules: `from routes.attachment import attachment_routes`

**Formatting**:
- Line length: Follow PEP 8 (~88 chars for readability)
- Type hints: Use `Annotated` from typing for complex types (see `agent/graph.py:3`)
- Use TypedDict for state objects: `class AgentState(TypedDict):`

**Naming Conventions**:
- Functions: `snake_case` (e.g., `should_continue`, `call_model`)
- Classes: `PascalCase` (e.g., `AgentState`, `AttachmentUploadResponse`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `AVAILABLE_TOOLS`, `FALLBACK_SYSTEM_PROMPT`)
- Private: prefix with `_` (e.g., `_internal_helper`)

**Docstrings**:
- Use Google-style docstrings with Args, Returns, Raises sections
- Example from `graph.py:26-32`:
  ```python
  def should_continue(state: AgentState) -> Literal["tools", "end"]:
      """Determine whether to continue to tools or end the conversation.
      
      Args:
          state: Current agent state
      
      Returns:
          str: Next node to execute ("tools" or "end")
      """
  ```

**Error Handling**:
- Use FastAPI HTTPException for API errors (see `routes/attachment.py:59-60`)
- Log errors with context: `logger.error(f"Error uploading attachment: {str(e)}")`
- Always catch specific exceptions, re-raise HTTPException without catching it
- Use status codes: `status.HTTP_401_UNAUTHORIZED`, `status.HTTP_500_INTERNAL_SERVER_ERROR`

**Logging**:
- Configure at module level: `logger = logging.getLogger(__name__)`
- Log at appropriate levels: INFO for operations, ERROR for failures
- Include context: `logger.info(f"Uploading attachment: {file.filename}")`

### TypeScript/React (Frontend)

**Imports**:
- Organize: external packages → absolute imports (@/*) → relative imports
- Use explicit import types: `import { type UIMessage } from "ai"`

**Formatting**:
- Strict TypeScript enabled in `tsconfig.json` (no implicit any)
- Module resolution: "bundler", JSX as "react-jsx"
- Arrow functions preferred for components and callbacks

**Naming Conventions**:
- Components: `PascalCase` (e.g., `Home`, `Assistant`, `MessageInput`)
- Variables/functions: `camelCase` (e.g., `getUserMessages`, `isLoading`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `API_ENDPOINT`, `MAX_FILE_SIZE`)
- Private/internal: prefix with `_` in scope

**Component Patterns**:
- Functional components only
- Use hooks for state: `useState`, `useCallback`, `useEffect`
- Props interface example:
  ```typescript
  interface MessageProps {
    id: string;
    content: string;
    timestamp: Date;
  }
  ```

**Error Handling**:
- Use try-catch in async operations
- Show user-friendly error messages
- Log errors to console in development
- Example pattern (from `api/chat/route.ts`):
  ```typescript
  export async function POST(req: Request) {
    const { messages }: { messages: UIMessage[] } = await req.json();
    // Validate input, then process
  }
  ```

**Styling**:
- Use Tailwind CSS (v4 configured)
- Component variants: `class-variance-authority` library
- Utility: `clsx` for conditional classes, `tailwind-merge` for merging
- Icon library: `lucide-react` for consistent icons

## 4. Architecture Notes

**Backend Structure** (`RepositoryCondition.md`):
- Graph available via `get_graph()` in `/backend/agent/graph.py`
- Avoid modifying graph except for human-in-the-loop features
- Add simple tools with hardcoded returns for testing
- All routes in `/backend/routes/` directory

**Frontend Structure**:
- Chat API route: `/frontend/app/api/chat/route.ts` (uses AI SDK)
- Backend proxy: `/frontend/app/api/be/[...path]/route.ts` for Python API
- Components in `/frontend/components/` with UI subdir for primitives

## 5. Key Dependencies & Versions

**Backend**:
- Python >=3.12, FastAPI >=0.128.2, LangGraph >=1.0.8
- LangChain >=1.2.9, azure-cosmos >=4.14.6, azure-storage-blob >=12.28.0

**Frontend**:
- Next.js 16.1.5, React 19.2.4, TypeScript 5
- Assistant UI @0.12.1, AI SDK 6.0.50, Tailwind 4

## 6. Common Tasks

### Running a Single Test
*No test framework currently configured. To run tests once implemented:*
```bash
# Backend: pytest backend/tests/test_specific.py::test_name -v
# Frontend: npm run test -- --run tests/specific.test.ts
```

### Adding a New Tool
1. Define in `backend/agent/tools.py`
2. Add to `AVAILABLE_TOOLS` list
3. Graph will automatically pick it up on next request

### Adding a New API Route
1. Create file in `backend/routes/`
2. Define router and endpoints
3. Include in `main.py` with `app.include_router()`

### Adding Frontend Component
1. Create in `frontend/components/`
2. Use TypeScript interfaces for props
3. Export as default function component
4. Use Tailwind + Radix UI patterns from existing components

## 7. Environment & Secrets

- **Backend**: `.env` file contains Azure credentials (keep private, never commit)
- **Frontend**: No sensitive config needed (requests go through backend proxy)
- **Both**: gitignore configured properly, never add secrets to code

## 8. Development Best Practices

1. **Understand the graph**: Before modifying `agent/graph.py`, read the LangGraph docs and current implementation
2. **Use type hints**: Both Python and TypeScript codebases use strict typing
3. **Document changes**: Update docstrings when modifying functions
4. **Test manually**: Use FastAPI docs UI and frontend chat interface for testing
5. **Log properly**: Add logging for debugging without changing user experience

---

*Last updated: Feb 2026 | Python 3.12, TypeScript 5, LangGraph 1.0.8*
