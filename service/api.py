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
# Add reorg_glkb_backend to path for search service
backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
reorg_path = os.path.join(backend_root, "reorg_glkb_backend")
if reorg_path not in sys.path:
    sys.path.insert(0, reorg_path)

import logging
import json
import re
import time
import uuid
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from typing import List, Dict

from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    ChatRequest,
    ChatResponse,
    RewindRequest,
    RewindResponse,
    SessionInfo,
    SessionListResponse,
    HealthResponse,
    ErrorResponse,
)
from .session_service import get_session_service
from .runner import get_runner

# Configure logging — use a dedicated named logger with its own file handler
# so third-party libraries (LiteLLM, ADK) can't override it via root logger.
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "agent.log")
_LOG_FORMAT = "%(asctime)s - %(levelname)s - [pid:%(process)d] %(message)s"

def _get_agent_logger() -> logging.Logger:
    """Create a self-contained logger that writes to agent.log and stderr.

    Uses propagate=False so root-logger reconfigurations by LiteLLM/ADK
    cannot silently swallow our log messages.
    """
    _logger = logging.getLogger("glkb_agent_service")
    if _logger.handlers:          # already set up (module re-import guard)
        return _logger
    _logger.setLevel(logging.INFO)
    _logger.propagate = False     # critical: isolate from root logger

    fh = logging.FileHandler(_LOG_FILE)
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT))
    _logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(_LOG_FORMAT))
    _logger.addHandler(sh)
    return _logger

logger = _get_agent_logger()

# Import search service for reference generation
try:
    from app.api.deps import get_search_service
    _has_search_service = True
except ImportError as e:
    # Fallback if import fails
    logger.warning(f"Could not import search service: {e}. Reference generation will be disabled.")
    get_search_service = None
    _has_search_service = False


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
# Exception Handlers
# -----------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Log validation errors with request details for debugging."""
    error_details = exc.errors()
    body = await request.body()
    
    # Try to parse body as JSON for better logging
    body_str = None
    body_json = None
    try:
        if body:
            body_str = body.decode('utf-8')
            body_json = json.loads(body_str)
    except (UnicodeDecodeError, json.JSONDecodeError):
        body_str = str(body)[:500]  # Truncate if too long
    
    # Log detailed error information
    logger.error(
        f"Validation error on {request.method} {request.url.path}",
        extra={
            "path": str(request.url.path),
            "method": request.method,
            "client_ip": request.client.host if request.client else None,
            "request_body": body_json if body_json else body_str,
            "validation_errors": error_details,
        }
    )
    
    # Print to console for development mode
    print(f"\n{'='*60}")
    print(f"VALIDATION ERROR (422) on {request.method} {request.url.path}")
    print(f"Client IP: {request.client.host if request.client else 'unknown'}")
    print(f"Request Body: {json.dumps(body_json, indent=2) if body_json else body_str}")
    print(f"Validation Errors:")
    for error in error_details:
        print(f"  - {error}")
    print(f"{'='*60}\n")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": error_details,
            "body": body_json if body_json else body_str
        }
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
# Trajectory Builder (post-processes events into user-facing reasoning trace)
# -----------------------------------------

# Tool name -> phase mapping
_TOOL_PHASE_MAP = {
    "load_skill": "Preparing my approach",
    "load_skill_resource": "Preparing my approach",
    "get_database_schema": "Preparing my approach",
    "article_search": "Searching for relevant articles",
    "search_pubmed": "Searching for relevant articles",
    "vocabulary_search": "Exploring the knowledge graph",
    "execute_cypher": "Exploring the knowledge graph",
    "fetch_abstract": "Reading article details",
    "get_fulltext": "Reading article details",
    "comprehensive_report": "Reading article details",
    "find_similar_articles": "Following citation trails",
    "get_citing_articles": "Following citation trails",
    "cite_evidence": "Selecting supporting evidence",
}

# Fixed display order for phases
_PHASE_ORDER = [
    "Preparing my approach",
    "Searching for relevant articles",
    "Exploring the knowledge graph",
    "Reading article details",
    "Following citation trails",
    "Selecting supporting evidence",
]


def _summarize_tool_call(tool_name: str, tool_input: dict, tool_output: dict) -> dict:
    """Generate a human-readable summary for a single tool call."""
    inp = tool_input if isinstance(tool_input, dict) else {}
    out = tool_output if isinstance(tool_output, dict) else {}

    if tool_name == "load_skill":
        name = inp.get("name", "unknown")
        return {"tool": tool_name, "summary": f"Loaded skill: {name}"}

    if tool_name == "load_skill_resource":
        skill = inp.get("skill_name", "")
        resource = inp.get("resource_name", "")
        return {"tool": tool_name, "summary": f"Loaded reference: {resource} from {skill}"}

    if tool_name == "get_database_schema":
        return {"tool": tool_name, "summary": "Retrieved GLKB database schema (node types, relationships, properties)"}

    if tool_name == "article_search":
        keywords = inp.get("keywords", [])
        pmids = inp.get("pubmed_ids", [])
        count = out.get("count", "?")
        if keywords:
            query_hint = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
            return {"tool": tool_name, "summary": f"Searched GLKB articles for: {query_hint}", "result": f"Found {count} articles"}
        elif pmids:
            return {"tool": tool_name, "summary": f"Retrieved articles by PMID: {', '.join(pmids[:5])}", "result": f"Found {count} articles"}
        return {"tool": tool_name, "summary": "Searched GLKB articles", "result": f"Found {count} articles"}

    if tool_name == "search_pubmed":
        query = inp.get("query", "")
        min_date = inp.get("min_date", "")
        max_date = inp.get("max_date", "")
        count = out.get("count", "?")
        summary = f"Searched PubMed for: {query}"
        if min_date or max_date:
            summary += f" ({min_date or '...'} to {max_date or 'present'})"
        return {"tool": tool_name, "summary": summary, "result": f"Found {count} articles"}

    if tool_name == "vocabulary_search":
        name = inp.get("name", "")
        results = out.get("related_vocabulary", [])
        count = len(results)
        top_names = [r.get("name", "") for r in results[:3] if r.get("name")]
        result_hint = f"Found {count} terms"
        if top_names:
            result_hint += f": {', '.join(top_names)}"
        return {"tool": tool_name, "summary": f"Looked up biomedical concept: {name}", "result": result_hint}

    if tool_name == "execute_cypher":
        query = inp.get("query", "")
        count = out.get("count", "?")
        # Extract relationship types and node labels for a human-readable hint
        hint_parts = []
        for rel in re.findall(r':(\w+(?:Association|Structure|Mapping|Cooccur|ContainTerm|Cite))', query):
            hint_parts.append(rel)
        for label in re.findall(r'\((?:\w+):(\w+)\)', query):
            if label not in hint_parts:
                hint_parts.append(label)
        if hint_parts:
            summary = f"Queried knowledge graph ({', '.join(hint_parts[:4])})"
        else:
            summary = "Queried knowledge graph"
        return {"tool": tool_name, "summary": summary, "result": f"Returned {count} records"}

    if tool_name == "fetch_abstract":
        pmid = inp.get("pmid", "")
        title = out.get("title", "")
        summary = f"Read abstract of PMID {pmid}"
        result = {"tool": tool_name, "summary": summary}
        if title:
            result["result"] = title
        return result

    if tool_name == "get_fulltext":
        article_id = inp.get("article_id", "")
        title = out.get("title", "")
        word_count = out.get("word_count", "")
        summary = f"Read full text of {article_id}"
        result = {"tool": tool_name, "summary": summary}
        if title:
            result["result"] = title
        if word_count:
            result["result"] = result.get("result", "") + f" ({word_count} words)"
        return result

    if tool_name == "comprehensive_report":
        pmid = inp.get("pmid", "")
        title = out.get("article", {}).get("title", "") if isinstance(out.get("article"), dict) else ""
        result = {"tool": tool_name, "summary": f"Generated comprehensive report for PMID {pmid}"}
        if title:
            result["result"] = title
        return result

    if tool_name == "find_similar_articles":
        pmid = inp.get("pmid", "")
        count = out.get("similar_count", "?")
        return {"tool": tool_name, "summary": f"Found articles similar to PMID {pmid}", "result": f"{count} similar articles"}

    if tool_name == "get_citing_articles":
        pmid = inp.get("pmid", "")
        count = out.get("citation_count", "?")
        return {"tool": tool_name, "summary": f"Found articles citing PMID {pmid}", "result": f"{count} citing articles"}

    # cite_evidence is aggregated separately, but handle individual if needed
    if tool_name == "cite_evidence":
        pmid = inp.get("pmid", "")
        ctx = inp.get("context_type", "abstract")
        return {"tool": tool_name, "summary": f"Selected evidence from PMID {pmid} ({ctx})", "pmid": pmid, "context_type": ctx}

    # Fallback for unknown tools
    return {"tool": tool_name, "summary": f"Called {tool_name}"}


def _build_trajectory(events: list) -> list:
    """
    Build a user-facing reasoning trajectory from raw tool call events.

    Args:
        events: list of dicts with keys: tool_name, tool_input, tool_output

    Returns:
        list of phase dicts: [{phase, actions: [{tool, summary, result?}]}]
    """
    # Group summarized actions by phase
    phase_actions = {phase: [] for phase in _PHASE_ORDER}

    # For cite_evidence, aggregate per PMID
    cite_counts = {}  # pmid -> {count, context_types}

    for ev in events:
        tool_name = ev.get("tool_name", "")
        if not tool_name:
            continue

        phase = _TOOL_PHASE_MAP.get(tool_name)
        if not phase:
            continue

        summary = _summarize_tool_call(tool_name, ev.get("tool_input", {}), ev.get("tool_output", {}))

        if tool_name == "cite_evidence":
            pmid = summary.get("pmid", "")
            ctx = summary.get("context_type", "abstract")
            if pmid not in cite_counts:
                cite_counts[pmid] = {"count": 0, "context_types": set()}
            cite_counts[pmid]["count"] += 1
            cite_counts[pmid]["context_types"].add(ctx)
        else:
            phase_actions[phase].append(summary)

    # Build aggregated cite_evidence actions
    for pmid, info in cite_counts.items():
        ctx_str = ", ".join(sorted(info["context_types"]))
        phase_actions["Selecting supporting evidence"].append({
            "tool": "cite_evidence",
            "summary": f"Selected {info['count']} passage{'s' if info['count'] > 1 else ''} from PMID {pmid} ({ctx_str})",
        })

    # Build final trajectory, only include phases that have actions
    trajectory = []
    for phase in _PHASE_ORDER:
        if phase_actions[phase]:
            trajectory.append({
                "phase": phase,
                "actions": phase_actions[phase],
            })

    return trajectory


# -----------------------------------------
# Simple Stream Endpoint (mimics glkb_agent_service.py)
# -----------------------------------------

class StreamRequest(BaseModel):
    """Request body for the /stream endpoint."""
    question: str = Field(..., description="The user's question")
    messages: Optional[List[Dict]] = Field(default=[], description="List of messages in the conversation")
    max_articles: int = Field(default=30, description="Maximum number of articles to return")
    session_id: Optional[str] = Field(default=None, description="Session ID")


@app.post("/stream", tags=["Chat"])
async def stream_process(request: StreamRequest):
    """
    Stream the processing of a question using Server-Sent Events (SSE).
    Mimics the output format of glkb_agent_service.py /stream endpoint.
    
    - **question**: The user's question
    - **messages**: List of messages in the conversation
    - **max_articles**: Maximum number of articles to return
    - **session_id**: Session ID
    
    Returns an SSE stream with intermediate steps and final response.
    """
    try:
        question = request.question
        step_start_time = time.time()
        logger.info(f"[STREAM REQUEST] question={question!r} session_id={request.session_id}")

        # Create a temporary session for this request
        session_service = get_session_service()
        app_name = "glkb"
        user_id = "stream_user"
        if request.session_id:
            session_id = request.session_id
        else:
            session_id = f"stream_{uuid.uuid4().hex[:8]}"
        
        session = await session_service.get_session(app_name, user_id, session_id)
        if session is None:
            logger.info(f"Streaming chat request in new session {session_id}")
            session = await session_service.create_session(app_name, user_id, session_id)
        else:
            logger.info(f"Streaming chat request in existing session {session_id}")
        
        async def generate():
            """Async generator function to stream progress"""
            # Helper function to format SSE messages
            def send_message(data):
                return f"data: {json.dumps(data)}\n\n"
            
            try:
                runner = get_runner()
                response_parts = []
                final_response = ""
                invocation_id = None
                evidence_map = {}  # pmid -> list of {quote, context_type}
                trajectory_events = []  # raw tool calls for trajectory builder

                # Map agent names to step names
                agent_step_map = {
                    "QuestionRouterAgent": "Routing",
                    "KgQueryAgent": "Answering",
                    "ArticleRetrievalAgent": "Retrieving",
                    "EvidenceMergeAgent": "Merging",
                    "FinalAnswerAgent": "Answering"
                }
                
                current_step = None
                step_started = {}
                seen_agents = set()
                agent_states = {}  # Track state per agent
                
                # Stream agent events with detailed information
                async for event_dict in runner.run_stream(
                    app_name=app_name,
                    user_id=user_id,
                    session_id=session_id,
                    message=question
                ):
                    # Extract event information
                    agent_name = event_dict.get("agent_name", "")
                    event_type = event_dict.get("type", "")
                    content = event_dict.get("content", "")
                    tool_name = event_dict.get("tool_name", "")
                    tool_input = event_dict.get("tool_input", "")
                    tool_output = event_dict.get("tool_output", "")
                    timestamp = event_dict.get("timestamp", "")

                    # Capture invocation_id from the first event that has one
                    if invocation_id is None and event_dict.get("invocation_id"):
                        invocation_id = event_dict["invocation_id"]
                    
                    # Map agent to step name
                    step_name = agent_step_map.get(agent_name, "Processing")

                    # Capture cite_evidence tool calls for evidence mapping
                    if tool_name == "cite_evidence" and isinstance(tool_input, dict):
                        ev_pmid = str(tool_input.get("pmid", ""))
                        if ev_pmid:
                            if ev_pmid not in evidence_map:
                                evidence_map[ev_pmid] = []
                            evidence_map[ev_pmid].append({
                                "quote": tool_input.get("quote", ""),
                                "context_type": tool_input.get("context_type", "abstract"),
                            })

                    # Auto-capture abstracts from search_pubmed results
                    if tool_name == "search_pubmed" and isinstance(tool_output, dict):
                        for sp_article in tool_output.get("articles", []):
                            sp_pmid = str(sp_article.get("pmid", ""))
                            sp_abstract = sp_article.get("abstract", "")
                            if sp_pmid and sp_abstract:
                                if sp_pmid not in evidence_map:
                                    evidence_map[sp_pmid] = []
                                # Only add if no evidence yet for this PMID
                                if not evidence_map[sp_pmid]:
                                    evidence_map[sp_pmid].append({
                                        "quote": sp_abstract,
                                        "context_type": "abstract",
                                        "auto": True,
                                    })

                    # Auto-capture abstract from fetch_abstract results
                    if tool_name == "fetch_abstract" and isinstance(tool_output, dict):
                        fa_pmid = str(tool_output.get("pmid", ""))
                        fa_abstract = tool_output.get("abstract", "")
                        if fa_pmid and fa_abstract:
                            # Replace any auto-captured evidence with the
                            # directly-fetched abstract (same content, but
                            # confirms the agent read this article)
                            evidence_map[fa_pmid] = [
                                e for e in evidence_map.get(fa_pmid, [])
                                if not e.get("auto")
                            ]
                            evidence_map[fa_pmid].append({
                                "quote": fa_abstract,
                                "context_type": "abstract",
                                "auto": True,
                            })

                    # Auto-capture abstracts from article_search (GLKB KG) results
                    if tool_name == "article_search" and isinstance(tool_output, dict):
                        for as_article in tool_output.get("results", []):
                            as_pmid = str(as_article.get("pubmedid", ""))
                            as_abstract = as_article.get("abstract", "")
                            if as_pmid and as_abstract:
                                if as_pmid not in evidence_map:
                                    evidence_map[as_pmid] = []
                                if not evidence_map[as_pmid]:
                                    evidence_map[as_pmid].append({
                                        "quote": as_abstract,
                                        "context_type": "abstract",
                                        "auto": True,
                                    })

                    # Capture tool events for trajectory builder
                    if tool_name:
                        if tool_output:
                            # Tool result event — merge output into last matching call
                            merged = False
                            for ev in reversed(trajectory_events):
                                if ev["tool_name"] == tool_name and not ev["tool_output"]:
                                    ev["tool_output"] = tool_output if isinstance(tool_output, dict) else {}
                                    merged = True
                                    break
                            if not merged:
                                # Result without a prior call (e.g. no-arg tools) — create entry
                                trajectory_events.append({
                                    "tool_name": tool_name,
                                    "tool_input": tool_input if isinstance(tool_input, dict) else {},
                                    "tool_output": tool_output if isinstance(tool_output, dict) else {},
                                })
                        elif isinstance(tool_input, dict) and tool_input:
                            # Tool call event with input args — record it
                            trajectory_events.append({
                                "tool_name": tool_name,
                                "tool_input": tool_input,
                                "tool_output": {},
                            })

                    # Build detailed message content
                    detail_parts = []
                    
                    # Handle Agent START events
                    if agent_name and agent_name not in seen_agents:
                        seen_agents.add(agent_name)
                        detail_parts.append(f"[AGENT START] {agent_name}")
                        if step_name:
                            yield send_message({
                                'step': step_name,
                                'content': f'[AGENT START] {agent_name}'
                            })
                    
                    # Handle Agent INPUT events - show when we have content and an agent
                    if content and agent_name and not tool_name and event_type != "ToolCallEvent":
                        # Check if this looks like user input (first content from an agent)
                        if agent_name in seen_agents and agent_name not in agent_states:
                            input_display = content
                            if len(input_display) > 300:
                                input_display = input_display[:300] + "..."
                            if step_name:
                                yield send_message({
                                    'step': step_name,
                                    'content': f"[AGENT INPUT] {agent_name} | User: parts=[Part(text='{input_display}')] role='user'"
                                })
                    
                    # Handle Agent STATE events - show state information when available
                    # State information might come in various forms, so we'll show it when we detect it
                    if agent_name and agent_name in seen_agents and not tool_name:
                        # If we have state-like information, display it
                        # This is a heuristic - actual state might be in session state
                        # For now, we'll show state when we see structured content
                        pass  # State will be shown through other events
                    
                    # Handle TOOL CALL events
                    if tool_name or "ToolCall" in event_type:
                        tool_input_display = ""
                        if tool_input:
                            if isinstance(tool_input, dict):
                                # Format like the logs: {"kwargs": {...}}
                                tool_input_display = json.dumps(tool_input)
                            else:
                                tool_input_display = str(tool_input)
                        
                        if len(tool_input_display) > 500:
                            tool_input_display = tool_input_display[:500] + "... [truncated]"
                        
                        yield send_message({
                            'step': step_name,
                            'content': f'[TOOL CALL] {tool_name} | Input: {tool_input_display}'
                        })
                    
                    # Handle TOOL RESULT events
                    if tool_output or "ToolResult" in event_type or "ToolResponse" in event_type:
                        tool_output_display = ""
                        if tool_output:
                            if isinstance(tool_output, dict):
                                tool_output_display = json.dumps(tool_output)
                            else:
                                tool_output_display = str(tool_output)
                        
                        # Truncate very long outputs but keep more detail
                        if len(tool_output_display) > 2000:
                            tool_output_display = tool_output_display[:2000] + "... [truncated]"
                        
                        yield send_message({
                            'step': step_name,
                            'content': f'[TOOL RESULT] {tool_name} | Output: {tool_output_display}'
                        })
                    
                    # Handle Agent OUTPUT events
                    if content and event_type and "Output" in event_type:
                        # This is an agent output with a key
                        output_display = content
                        # Try to detect key from content or event_dict
                        key_match = re.search(r'Key=(\w+)', str(event_dict))
                        key = key_match.group(1) if key_match else "output"
                        
                        if len(output_display) > 2000:
                            output_display = output_display[:2000] + "... [truncated]"
                        
                        yield send_message({
                            'step': step_name,
                            'content': f'[AGENT OUTPUT] {agent_name} | Key={key} | Output: {output_display}'
                        })
                        
                        # Collect for final response (only from FinalAnswerAgent)
                        if agent_name == "FinalAnswerAgent":
                            response_parts.append(output_display)
                    
                    # Handle regular content (text responses)
                    elif content and content.strip() and event_type != "ToolCallEvent":
                        # This might be a text response
                        content_display = content
                        if len(content_display) > 2000:
                            content_display = content_display[:2000] + "... [truncated]"
                        
                        # Only show if it's substantial content
                        if len(content.strip()) > 50:
                            yield send_message({
                                'step': step_name,
                                'content': f'[AGENT OUTPUT] {agent_name} | Output: {content_display}'
                            })
                        
                        # Collect for final response
                        if agent_name == "FinalAnswerAgent" or not tool_name:
                            response_parts.append(content)
                    
                    # Handle Agent END events
                    if event_type and "End" in event_type:
                        if agent_name:
                            yield send_message({
                                'step': step_name,
                                'content': f'[AGENT END] {agent_name}'
                            })
                    
                    # Handle conditional/check events
                    if event_type and ("Check" in event_type or "Conditional" in event_type):
                        check_display = str(event_dict)
                        if len(check_display) > 500:
                            check_display = check_display[:500] + "..."
                        yield send_message({
                            'step': step_name,
                            'content': f'[AGENT CHECK] {check_display}'
                        })
                
                # Get final response (last non-empty content)
                for part in reversed(response_parts):
                    if part and part.strip():
                        final_response = part
                        break
                
                if not final_response:
                    final_response = "I couldn't find an answer to your question."
                
                # Finalize evidence_map: if cite_evidence provided specific
                # quotes for a PMID, drop the auto-captured abstract fallback.
                # Then strip the internal "auto" flag before output.
                for ev_pmid, ev_list in evidence_map.items():
                    has_manual = any(not e.get("auto") for e in ev_list)
                    if has_manual:
                        evidence_map[ev_pmid] = [e for e in ev_list if not e.get("auto")]
                    for e in evidence_map[ev_pmid]:
                        e.pop("auto", None)

                # Extract PMIDs from response.
                # The structured `references` field is populated by looking for PubMed URLs/PMID-style
                # markdown links in the final response text.
                pmid_url_re = re.compile(r"https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?")
                pmid_md_re = re.compile(r"\[(\d+)\]\(https?://pubmed\.ncbi\.nlm\.nih\.gov/\d+/?\)")
                pmids = set(pmid_url_re.findall(final_response or ""))
                pmids.update(pmid_md_re.findall(final_response or ""))
                pmids = sorted([p for p in pmids if p and p.isdigit()])
                
                # Get article references (list of dicts with evidence)
                references: List[Dict] = []
                if pmids and _has_search_service:
                    try:
                        search_service = get_search_service()
                        article_rows = await search_service.search_articles_by_pmids(pmids[:request.max_articles])
                        if article_rows and isinstance(article_rows[0], dict):
                            for r in article_rows:
                                ref_pmid = str(r.get("pubmedid", r.get("pmid", "")))
                                # Fallback: extract PMID from URL if not in dict keys
                                if not ref_pmid:
                                    url = r.get("url", "")
                                    url_match = pmid_url_re.search(url)
                                    ref_pmid = url_match.group(1) if url_match else ""
                                references.append({
                                    "pmid": ref_pmid,
                                    "title": r.get("title"),
                                    "url": r.get("url", f"https://pubmed.ncbi.nlm.nih.gov/{ref_pmid}/"),
                                    "n_citation": r.get("n_citation", 0),
                                    "date": r.get("date"),
                                    "journal": r.get("journal"),
                                    "authors": r.get("authors") or [],
                                    "evidence": evidence_map.get(ref_pmid, []),
                                })
                        else:
                            for ref in (article_rows or []):
                                ref_pmid = str(ref[1]).rstrip("/").split("/")[-1] if ref[1] else ""
                                references.append({
                                    "pmid": ref_pmid,
                                    "title": ref[0],
                                    "url": ref[1],
                                    "n_citation": ref[2],
                                    "date": ref[3],
                                    "journal": ref[4],
                                    "authors": ref[5] if len(ref) > 5 else [],
                                    "evidence": evidence_map.get(ref_pmid, []),
                                })
                    except Exception as e:
                        # Log error but don't fail the request - references are optional
                        logger.warning(f"Error fetching article references (continuing without references): {e}")
                        if logger.isEnabledFor(logging.DEBUG):
                            import traceback
                            logger.debug(traceback.format_exc())
                        references = []

                # Fallback: if we detected PMIDs but couldn't fetch metadata (import failure,
                # missing dependencies, Neo4j unavailable), still return a useful reference list.
                if pmids and not references:
                    references = [
                        {
                            "pmid": pmid,
                            "title": f"PMID {pmid}",
                            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                            "n_citation": 0,
                            "date": None,
                            "journal": None,
                            "authors": [],
                            "evidence": evidence_map.get(pmid, []),
                        }
                        for pmid in pmids[:request.max_articles]
                    ]
                
                # Calculate execution time
                execution_time = time.time() - step_start_time

                # Build reasoning trajectory from collected tool events
                trajectory = _build_trajectory(trajectory_events)

                # Log completion BEFORE the final yield (generator may be
                # cancelled by client disconnect after the last yield)
                logger.info(f"[STREAM COMPLETE] question={question!r} session_id={session_id} time={execution_time:.1f}s refs={len(pmids)}")

                # Send final completion message
                yield send_message({
                    'step': 'Complete',
                    'response': final_response,
                    'references': references,
                    'trajectory': trajectory,
                    'execution_time': execution_time,
                    'messages': request.messages,
                    'session_id': session_id,
                    'invocation_id': invocation_id,
                    'done': True
                })
                
                # Clean up temporary session
                # try:
                #     await session_service.delete_session(app_name, user_id, session_id)
                # except Exception:
                #     pass
                    
            except Exception as e:
                import traceback
                tb_str = traceback.format_exc()
                error_msg = f"Error processing question: {str(e)}"
                logger.error(f"Error in stream_process: {e}", exc_info=True)

                yield send_message({
                    'step': 'Error',
                    'content': error_msg,
                    'done': True
                })
        
        # Return streaming response
        return StreamingResponse(
            generate(),
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache, no-transform',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
                'Content-Encoding': 'identity'
            }
        )
        
    except Exception as e:
        logger.error(f"Error setting up streaming: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error setting up streaming: {str(e)}")


# -----------------------------------------
# Message History Endpoint
# -----------------------------------------

@app.post(
    "/apps/{app_name}/users/{user_id}/sessions/{session_id}/rewind",
    tags=["Chat"],
    summary="Rewind a session to before a given invocation",
    response_model=RewindResponse
)
async def rewind_session(
    app_name: str,
    user_id: str,
    session_id: str,
    request: RewindRequest
):
    """
    Rewind a session to the state before a given invocation.

    Removes the specified invocation and all subsequent ones from the
    agent's memory and the stored message history.

    Use this to implement "edit message" or "regenerate answer":
    1. Call this endpoint with the invocation_id of the turn to undo
    2. Call /chat or /chat/stream with the new (or same) message

    - **app_name**: Name of the application
    - **user_id**: User identifier
    - **session_id**: Session identifier
    - **invocation_id**: The invocation to rewind before (this turn and all after it are removed)
    """
    # Verify session exists
    session_service = get_session_service()
    session = await session_service.get_session(app_name, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        runner = get_runner()
        result = await runner.rewind(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            invocation_id=request.invocation_id,
        )
        return RewindResponse(
            session_id=session_id,
            rewound_invocation_ids=result["rewound_invocation_ids"],
            remaining_message_count=result["remaining_message_count"],
            messages=[
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": m["content"],
                    "timestamp": m["timestamp"],
                    "invocation_id": m.get("invocation_id"),
                }
                for m in result["messages"]
            ],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error rewinding session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    
    # Set logging level to DEBUG for development
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    
    print("\n" + "="*60)
    print("Starting GLKB Agent API in DEVELOPMENT MODE")
    print("="*60)
    print("Server will run on: http://0.0.0.0:5001")
    print("API docs available at: http://0.0.0.0:5001/docs")
    print("Validation errors will be logged with full details")
    print("="*60 + "\n")
    
    # Run from service directory: python api.py
    # This uses relative import "api:app"
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_level="debug"  # Use debug for more verbose logging
    )
