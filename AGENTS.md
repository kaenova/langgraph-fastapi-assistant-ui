# AGENTS.md - Assistant UI + LangGraph FastAPI Backend

This file provides guidelines for agentic coding in this monorepo. The project contains:
- **Frontend**: Next.js + React + TypeScript with Assistant UI and Tailwind CSS
- **Backend**: FastAPI + LangGraph + Python 3.12 with Azure OpenAI integration

---

## Build, Lint, Test Commands

### Frontend (Node.js with Bun)

```bash
cd frontend

# Development
bun run dev          # Start Next.js dev server with Turbopack (http://localhost:3000)

# Production
bun run build        # Build production bundle
bun start            # Start production server

# Type checking (built-in with Next.js)
bun tsc              # Run TypeScript compiler

# Run single component/test (when tests added)
bun test --testPathPattern=<pattern>
```

### Backend (Python 3.12 with UV)

```bash
cd backend

# Install dependencies
uv sync              # Install all dependencies

# Development
uv run python main.py          # Run FastAPI server (http://localhost:8000)
uvicorn main:app --reload      # With reload on file changes

# Type checking
uv run pyright                  # Static type checking

# Linting
uv run ruff check .             # Run ruff linter (if added)

# Testing (when tests added)
uv run pytest                   # Run all tests
uv run pytest path/to/test.py   # Run single test file
uv run pytest -k "test_name"    # Run single test by name
```

---

## Frontend Code Style Guidelines

### Imports & Structure
- **Organize imports**: React/Next imports first, then external libs, then local imports (grouped by type)
- **Path aliases**: Use `@/` prefix for imports (`@/components`, `@/lib`, `@/app`)
- Use `"use client"` directive at top of client components
- Import types with `type` keyword: `import type { FC } from "react"`

### Formatting & Types
- **TypeScript strict mode enabled** in tsconfig.json
- **Tailwind CSS** for styling with class composition using `cn()` utility
- **File naming**: lowercase with hyphens for components (`thread.tsx`, `action-bar.tsx`)
- **Component types**: Use `FC` (FunctionComponent) or explicit return types
- **Props**: Define interface or use `type Props` for component props
- **JSX formatting**: Multi-line JSX uses parentheses; attributes on new lines if >2

Example:
```typescript
import type { FC } from "react";
import { cn } from "@/lib/utils";

interface ThreadProps {
  maxWidth?: string;
}

export const Thread: FC<ThreadProps> = ({ maxWidth }) => {
  return (
    <div className={cn("flex flex-col h-full", maxWidth)}>
      {/* content */}
    </div>
  );
};
```

### Error Handling
- Use React error boundaries for component-level errors
- Handle async/await with try-catch in event handlers
- Provide user-facing error messages via UI components
- Log errors to console in development

### Naming Conventions
- **Components**: PascalCase (`Thread`, `Composer`, `ThreadWelcome`)
- **Functions/hooks**: camelCase (`useThreadRuntime`, `formatMessage`)
- **Constants**: UPPERCASE_SNAKE_CASE (`SUGGESTIONS`, `DEFAULT_MAX_WIDTH`)
- **CSS classes**: lowercase with hyphens (`aui-thread-root`, `aui-composer-input`)

---

## Backend Code Style Guidelines

### Imports & Structure
- **Module docstring**: Start every module with `"""docstring."""`
- **Organize imports**: stdlib, then external libs (alphabetically), then local imports
- **Type hints**: Annotate all function parameters and return types using `typing` module
- **File organization**: Constants, types/models, utility functions, main functions

Example:
```python
"""Module docstring explaining purpose."""

import os
from typing import Annotated, Dict, List, Optional

from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel

from lib.database import db_manager
```

### Formatting & Types
- **Type hints required** for all functions (parameters and return types)
- **Docstrings**: Use Google-style docstrings for functions/classes (Args, Returns, Raises sections)
- **Use `TypedDict`** for state objects (e.g., `AgentState`)
- **Pydantic models** for request/response validation (e.g., `AttachmentUploadResponse`)
- **Line length**: Aim for 80-100 characters
- **Async functions**: Use `async def` for FastAPI endpoints; prefix with `async`

Example:
```python
class AttachmentUploadResponse(BaseModel):
    """Response model for attachment upload."""
    
    url: str
    filename: str
    metadata: Optional[Dict[str, Any]] = None


async def upload_attachment(file: UploadFile = File(...)) -> AttachmentUploadResponse:
    """Upload an attachment file.
    
    Args:
        file: The file to upload
        
    Returns:
        AttachmentUploadResponse with chatbot://{id} URL
    """
    # implementation
```

### Error Handling
- **Use HTTPException** for API errors with appropriate status codes
- **Logging**: Use Python's `logging` module (configure at module level)
- **Validation**: Use Pydantic for automatic request validation
- **Custom exceptions**: Create specific exception classes for domain errors
- Always log errors with context before raising

Example:
```python
import logging

logger = logging.getLogger(__name__)

if not user_id:
    logger.warning(f"Missing user_id for request")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, 
        detail="userid header is required"
    )
```

### Naming Conventions
- **Classes**: PascalCase (`AgentState`, `AttachmentUploadResponse`, `ToolNode`)
- **Functions/variables**: snake_case (`call_model`, `upload_file_to_blob`, `attachment_id`)
- **Constants**: UPPERCASE_SNAKE_CASE (`AVAILABLE_TOOLS`, `MAX_TOKENS`)
- **Private functions**: Prefix with `_` (`_create_http_client`)
- **Route parameters**: snake_case in URL paths (`/api/v1/attachments`)

---

## Project Structure

```
/frontend
  /app                    # Next.js app directory
    /api                  # API routes
    /assistant.tsx        # Main assistant component
  /components             # Reusable React components
    /assistant-ui         # Assistant UI customizations
    /ui                   # Base UI components
  /lib                    # Utilities (cn(), fetch helpers)
  package.json
  tsconfig.json
  next.config.ts

/backend
  /agent                  # LangGraph agent implementation
    /graph.py            # Agent state & workflow
    /model.py            # LLM configuration
    /tools.py            # Tool definitions
  /lib                    # Shared utilities
    /database.py         # Database operations
    /blob.py             # Azure blob storage
  /routes                 # FastAPI route handlers
  main.py                 # FastAPI app entry point
  pyproject.toml
```

---

## Environment Setup

**Frontend**: Create `.env.local` with `OPENAI_API_KEY`
**Backend**: Configure `.env` with:
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT_NAME`
- `AZURE_OPENAI_API_VERSION`
- `PORT` (default: 8000)

---

## Key Patterns

- **Frontend**: Assistant UI components use primitives from `@assistant-ui/react`; styling via Tailwind; type-safe with strict TypeScript
- **Backend**: FastAPI routes return Pydantic models; LangGraph handles agent state and tool calls; Azure services for storage
- **Integration**: Frontend calls `/api/chat` endpoint; backend can proxy to `/api/v1/*` for separate FastAPI backend
