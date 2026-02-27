"""Main FastAPI server with LangGraph integration."""

import os
import sys

sys.dont_write_bytecode = True

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Disable Azure Cosmos DB HTTP logging
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.attachment import attachment_routes
from routes.thread import thread_routes

logging.getLogger("azure.cosmos._cosmos_http_logging_policy").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


# Initialize FastAPI app
app = FastAPI(title="LangGraph Azure Inference API", version="1.0.0")

# Add CORS middleware to allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

app.include_router(
    attachment_routes,
    prefix="/api/v1/attachments",
    tags=["attachments"],
)
app.include_router(
    thread_routes,
    prefix="/api/v1",
    tags=["threads"],
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
