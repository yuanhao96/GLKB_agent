"""
FastAPI service for the GLKB Multi-Agent System.

Provides REST API endpoints for chat (with SSE streaming),
session management, and SQLite-based persistence.

Usage:
    cd google_adk
    uvicorn service.api:app --host 0.0.0.0 --port 8000 --reload
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import json
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    ChatRequest,
    ChatResponse,
    SessionInfo,
    SessionListResponse,
    HealthResponse,
    ErrorResponse,
)
from .session_service import get_session_service
from .runner import get_runner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


# -----------------------------------------
# Application Lifecycle
# -----------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    # Startup
    logger.info("Starting GLKB Agent API service...")
    session_service = get_session_service()
    await session_service.initialize()
    logger.info("Session service initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down GLKB Agent API service...")


# -----------------------------------------
# FastAPI Application
# -----------------------------------------

app = FastAPI(
    title="GLKB Agent API",
    description="""
    REST API for the GLKB Multi-Agent System.
    
    Features:
    - Session management (create, list, get, delete)
    - Chat with streaming (SSE) and non-streaming modes
    - SQLite-based session persistence
    
    Based on Google ADK (Agent Development Kit).
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------
# Health Check
# -----------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check endpoint"
)
async def health_check():
    """Check if the service is healthy."""
    return HealthResponse(status="healthy", timestamp=datetime.utcnow())


# -----------------------------------------
# Session Management Endpoints
# -----------------------------------------

@app.post(
    "/apps/{app_name}/users/{user_id}/sessions",
    response_model=CreateSessionResponse,
    tags=["Sessions"],
    summary="Create a new session"
)
async def create_session(
    app_name: str,
    user_id: str,
    request: Optional[CreateSessionRequest] = None
):
    """
    Create a new chat session.
    
    - **app_name**: Name of the application (e.g., "glkb")
    - **user_id**: User identifier
    - **session_id**: Optional custom session ID (UUID generated if not provided)
    - **state**: Optional initial state dictionary
    """
    try:
        session_service = get_session_service()
        
        session_id = request.session_id if request else None
        state = request.state if request else None
        
        session = await session_service.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            state=state
        )
        
        logger.info(f"Created session {session.id} for user {user_id}")
        
        return CreateSessionResponse(
            id=session.id,
            app_name=session.app_name,
            user_id=session.user_id,
            created_at=session.created_at
        )
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/apps/{app_name}/users/{user_id}/sessions",
    response_model=SessionListResponse,
    tags=["Sessions"],
    summary="List user sessions"
)
async def list_sessions(
    app_name: str,
    user_id: str,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """
    List all sessions for a user.
    
    - **app_name**: Name of the application
    - **user_id**: User identifier
    - **limit**: Maximum number of sessions to return (default: 100)
    - **offset**: Number of sessions to skip (for pagination)
    """
    try:
        session_service = get_session_service()
        
        sessions = await session_service.list_sessions(
            app_name=app_name,
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        
        session_infos = []
        for session in sessions:
            msg_count = await session_service.get_message_count(session.id)
            session_infos.append(SessionInfo(
                id=session.id,
                app_name=session.app_name,
                user_id=session.user_id,
                state=session.state,
                created_at=session.created_at,
                updated_at=session.updated_at,
                message_count=msg_count
            ))
        
        return SessionListResponse(
            sessions=session_infos,
            total=len(session_infos)
        )
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/apps/{app_name}/users/{user_id}/sessions/{session_id}",
    response_model=SessionInfo,
    tags=["Sessions"],
    summary="Get session details"
)
async def get_session(
    app_name: str,
    user_id: str,
    session_id: str
):
    """
    Get details of a specific session.
    
    - **app_name**: Name of the application
    - **user_id**: User identifier
    - **session_id**: Session identifier
    """
    try:
        session_service = get_session_service()
        
        session = await session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id
        )
        
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        msg_count = await session_service.get_message_count(session.id)
        
        return SessionInfo(
            id=session.id,
            app_name=session.app_name,
            user_id=session.user_id,
            state=session.state,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=msg_count
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(
    "/apps/{app_name}/users/{user_id}/sessions/{session_id}",
    tags=["Sessions"],
    summary="Delete a session"
)
async def delete_session(
    app_name: str,
    user_id: str,
    session_id: str
):
    """
    Delete a session and its conversation history.
    
    - **app_name**: Name of the application
    - **user_id**: User identifier
    - **session_id**: Session identifier
    """
    try:
        session_service = get_session_service()
        
        deleted = await session_service.delete_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id
        )
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        
        logger.info(f"Deleted session {session_id}")
        
        return {"status": "deleted", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------
# Chat Endpoints
# -----------------------------------------

@app.post(
    "/apps/{app_name}/users/{user_id}/sessions/{session_id}/chat",
    response_model=ChatResponse,
    tags=["Chat"],
    summary="Send a chat message (non-streaming)"
)
async def chat(
    app_name: str,
    user_id: str,
    session_id: str,
    request: ChatRequest
):
    """
    Send a message to the agent and get a complete response.
    
    - **app_name**: Name of the application
    - **user_id**: User identifier
    - **session_id**: Session identifier
    - **message**: The message to send to the agent
    
    Returns the complete response after the agent finishes processing.
    """
    try:
        # Verify session exists
        session_service = get_session_service()
        session = await session_service.get_session(app_name, user_id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        logger.info(f"Chat request in session {session_id}: {request.message[:100]}...")
        
        # Run agent
        runner = get_runner()
        result = await runner.run(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            message=request.message
        )
        
        logger.info(f"Chat response in session {session_id}: {result.response[:100]}...")
        
        return ChatResponse(
            session_id=session_id,
            response=result.response,
            events=result.events,
            state=result.state
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/apps/{app_name}/users/{user_id}/sessions/{session_id}/chat/stream",
    tags=["Chat"],
    summary="Send a chat message (streaming via SSE)"
)
async def chat_stream(
    app_name: str,
    user_id: str,
    session_id: str,
    request: ChatRequest
):
    """
    Send a message to the agent and stream the response via Server-Sent Events.
    
    - **app_name**: Name of the application
    - **user_id**: User identifier
    - **session_id**: Session identifier
    - **message**: The message to send to the agent
    
    Returns an SSE stream with events as they occur.
    
    Event types:
    - `message`: Agent event (contains event data)
    - `done`: Stream complete
    - `error`: Error occurred
    """
    # Verify session exists
    session_service = get_session_service()
    session = await session_service.get_session(app_name, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    logger.info(f"Streaming chat request in session {session_id}: {request.message[:100]}...")
    
    async def event_generator():
        """Generate SSE events from agent execution."""
        try:
            runner = get_runner()
            
            async for event_dict in runner.run_stream(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                message=request.message
            ):
                yield {
                    "event": "message",
                    "data": json.dumps(event_dict)
                }
            
            # Signal completion
            yield {
                "event": "done",
                "data": json.dumps({"status": "complete"})
            }
            
        except Exception as e:
            logger.error(f"Error in streaming chat: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }
    
    return EventSourceResponse(event_generator())


# -----------------------------------------
# Message History Endpoint
# -----------------------------------------

@app.get(
    "/apps/{app_name}/users/{user_id}/sessions/{session_id}/messages",
    tags=["Messages"],
    summary="Get conversation history"
)
async def get_messages(
    app_name: str,
    user_id: str,
    session_id: str,
    limit: int = Query(default=100, le=1000)
):
    """
    Get the conversation history for a session.
    
    - **app_name**: Name of the application
    - **user_id**: User identifier
    - **session_id**: Session identifier
    - **limit**: Maximum number of messages to return
    """
    try:
        # Verify session exists
        session_service = get_session_service()
        session = await session_service.get_session(app_name, user_id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        messages = await session_service.get_messages(session_id, limit=limit)
        
        return {
            "session_id": session_id,
            "messages": [msg.to_dict() for msg in messages],
            "total": len(messages)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------
# Run directly for development
# -----------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

