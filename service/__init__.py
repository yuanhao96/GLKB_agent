"""
GLKB Agent FastAPI Service

A REST API service for the GLKB Multi-Agent System with:
- Session management (SQLite persistence)
- Chat with streaming (SSE) and non-streaming modes

Usage:
    cd google_adk
    uvicorn service.api:app --host 0.0.0.0 --port 8000 --reload
"""

from .api import app
from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    ChatRequest,
    ChatResponse,
    SessionInfo,
    SessionListResponse,
)
from .session_service import SQLiteSessionService, get_session_service
from .runner import AgentRunner, get_runner

__all__ = [
    "app",
    "CreateSessionRequest",
    "CreateSessionResponse", 
    "ChatRequest",
    "ChatResponse",
    "SessionInfo",
    "SessionListResponse",
    "SQLiteSessionService",
    "get_session_service",
    "AgentRunner",
    "get_runner",
]

