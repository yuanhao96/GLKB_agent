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
import urllib.parse
import urllib.request
import urllib.error

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Add reorg_glkb_backend to path for search service
backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
reorg_path = os.path.join(backend_root, "reorg_glkb_backend")
if reorg_path not in sys.path:
    sys.path.insert(0, reorg_path)

import asyncio
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

# --- Per-request transcript logger (separate file) ---
_TRANSCRIPT_LOG_FILE = os.path.join(_LOG_DIR, "transcript.jsonl")

def _get_transcript_logger() -> logging.Logger:
    """Logger that writes one JSON line per request to transcript.jsonl."""
    _tl = logging.getLogger("glkb_agent_transcript")
    if _tl.handlers:
        return _tl
    _tl.setLevel(logging.INFO)
    _tl.propagate = False
    fh = logging.FileHandler(_TRANSCRIPT_LOG_FILE)
    fh.setLevel(logging.INFO)
    # Raw message only — the JSON line itself contains all metadata
    fh.setFormatter(logging.Formatter("%(message)s"))
    _tl.addHandler(fh)
    return _tl

transcript_logger = _get_transcript_logger()

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
    "search_biorxiv": "Searching for relevant articles",
    "browse_biorxiv_recent": "Searching for relevant articles",
    "vocabulary_search": "Exploring the knowledge graph",
    "execute_cypher": "Exploring the knowledge graph",
    "fetch_abstract": "Reading article details",
    "get_fulltext": "Reading article details",
    "comprehensive_report": "Reading article details",
    "fetch_biorxiv_paper": "Reading article details",
    "get_biorxiv_fulltext": "Reading article details",
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


_EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


async def _fetch_epmc_citation_counts(pmids: List[str], timeout: float = 8.0) -> Dict[str, int]:
    """
    Look up citedByCount for a batch of PubMed IDs via Europe PMC.

    EPMC indexes PubMed (SRC:MED) and exposes a `citedByCount` field that
    NCBI EFetch does not return. We use this to backfill `n_citation` on
    reference entries that fell through the GLKB Neo4j enrichment path.

    Returns a dict mapping pmid -> citation count. PMIDs not found in EPMC
    are omitted.
    """
    if not pmids:
        return {}
    pmids = list(pmids)[:200]
    id_clause = " OR ".join(f"EXT_ID:{p}" for p in pmids)
    return await _query_epmc_counts(
        query=f"({id_clause}) AND SRC:MED",
        result_key="pmid",
        page_size=len(pmids),
        timeout=timeout,
    )


async def _fetch_epmc_preprint_citation_counts(dois: List[str], timeout: float = 8.0) -> Dict[str, int]:
    """
    Look up citedByCount for a batch of bioRxiv/medRxiv preprints via Europe
    PMC. EPMC indexes preprints under SRC:PPR and populates citedByCount the
    same way it does for peer-reviewed articles.

    Returns a dict mapping DOI -> citation count. DOIs not found in EPMC are
    omitted.
    """
    if not dois:
        return {}
    dois = list(dois)[:200]
    id_clause = " OR ".join(f'DOI:"{d}"' for d in dois)
    return await _query_epmc_counts(
        query=f"({id_clause}) AND SRC:PPR",
        result_key="doi",
        page_size=len(dois),
        timeout=timeout,
    )


async def _query_epmc_counts(query: str, result_key: str, page_size: int, timeout: float) -> Dict[str, int]:
    """Shared EPMC batch-count query. `result_key` is the field to use as the
    output-dict key (either "pmid" or "doi")."""
    params = {
        "query": query,
        "resultType": "lite",
        "pageSize": str(page_size),
        "format": "json",
    }
    url = f"{_EPMC_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    def _fetch() -> Dict[str, int]:
        req = urllib.request.Request(url, headers={
            "User-Agent": "glkb-agent-service/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out: Dict[str, int] = {}
        for item in data.get("resultList", {}).get("result", []) or []:
            key = str(item.get(result_key, ""))
            if not key:
                continue
            try:
                out[key] = int(item.get("citedByCount") or 0)
            except (TypeError, ValueError):
                out[key] = 0
        return out

    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=timeout + 2)
    except asyncio.TimeoutError:
        logger.warning("EPMC citation-count lookup timed out (query=%s)", query[:80])
        return {}
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        logger.warning(f"EPMC citation-count lookup failed: {e}")
        return {}


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

    if tool_name == "search_biorxiv":
        query = inp.get("query", "")
        server = inp.get("server", "biorxiv")
        count = out.get("count", "?")
        returned = len(out.get("articles", []))
        return {"tool": tool_name, "summary": f"Searched {server} for: {query}", "result": f"Found {count} preprints ({returned} shown)"}

    if tool_name == "browse_biorxiv_recent":
        days = inp.get("days", 7)
        server = inp.get("server", "biorxiv")
        count = out.get("count", "?")
        return {"tool": tool_name, "summary": f"Browsed recent {server} preprints (last {days} days)", "result": f"{count} preprints"}

    if tool_name == "fetch_biorxiv_paper":
        doi = inp.get("doi", "")
        title = out.get("title", "") if out.get("success") else ""
        result = {"tool": tool_name, "summary": f"Read preprint {doi}"}
        if title:
            result["result"] = title
        return result

    if tool_name == "get_biorxiv_fulltext":
        doi = inp.get("doi", "")
        word_count = out.get("word_count", "")
        result = {"tool": tool_name, "summary": f"Read full text of preprint {doi}"}
        if word_count:
            result["result"] = f"{word_count} words"
        return result

    # cite_evidence is aggregated separately, but handle individual if needed
    if tool_name == "cite_evidence":
        pmid = inp.get("pmid", "")
        ctx = inp.get("context_type", "abstract")
        label = f"preprint {pmid}" if "/" in str(pmid) else f"PMID {pmid}"
        return {"tool": tool_name, "summary": f"Selected evidence from {label} ({ctx})", "pmid": pmid, "context_type": ctx}

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
        label = f"preprint {pmid}" if "/" in str(pmid) else f"PMID {pmid}"
        phase_actions["Selecting supporting evidence"].append({
            "tool": "cite_evidence",
            "summary": f"Selected {info['count']} passage{'s' if info['count'] > 1 else ''} from {label} ({ctx_str})",
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
                evidence_map = {}  # pmid OR preprint DOI -> list of {quote, context_type}
                preprint_metadata = {}  # preprint DOI -> article metadata dict
                trajectory_events = []  # raw tool calls for trajectory builder
                transcript_events = []  # per-request event log for transcript

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

                # Use a queue + keepalive pattern to prevent worker/proxy timeouts
                # during long agent runs (e.g. PubMed searches, Cypher queries)
                KEEPALIVE_INTERVAL = 15  # seconds between heartbeat comments
                _SENTINEL = object()
                event_queue = asyncio.Queue()

                async def _produce_events():
                    """Push agent events into the queue, then signal completion."""
                    try:
                        async for ev in runner.run_stream(
                            app_name=app_name,
                            user_id=user_id,
                            session_id=session_id,
                            message=question
                        ):
                            await event_queue.put(ev)
                    except Exception as exc:
                        await event_queue.put(exc)
                    finally:
                        await event_queue.put(_SENTINEL)

                producer_task = asyncio.create_task(_produce_events())

                while True:
                    try:
                        item = await asyncio.wait_for(
                            event_queue.get(), timeout=KEEPALIVE_INTERVAL
                        )
                    except asyncio.TimeoutError:
                        # No event within the interval — send SSE comment as keepalive
                        yield ": keepalive\n\n"
                        continue

                    if item is _SENTINEL:
                        break
                    if isinstance(item, Exception):
                        raise item

                    event_dict = item
                    # Extract event information
                    agent_name = event_dict.get("agent_name", "")
                    event_type = event_dict.get("type", "")
                    content = event_dict.get("content", "")
                    tool_name = event_dict.get("tool_name", "")
                    tool_input = event_dict.get("tool_input", "")
                    tool_output = event_dict.get("tool_output", "")
                    timestamp = event_dict.get("timestamp", "")

                    # Record event for transcript log
                    t_entry = {"ts": timestamp or datetime.utcnow().isoformat(), "agent": agent_name}
                    if tool_name:
                        t_entry["tool"] = tool_name
                        if tool_input:
                            t_entry["input"] = tool_input if isinstance(tool_input, dict) else str(tool_input)[:500]
                        if tool_output:
                            # Truncate large outputs (e.g. full abstracts) to keep log manageable
                            out = tool_output
                            if isinstance(out, dict):
                                out_str = json.dumps(out)
                                if len(out_str) > 1000:
                                    t_entry["output_preview"] = out_str[:1000] + "...[truncated]"
                                else:
                                    t_entry["output"] = out
                            else:
                                t_entry["output_preview"] = str(out)[:1000]
                    elif content:
                        t_entry["content_preview"] = str(content)[:500]
                    transcript_events.append(t_entry)

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

                    # Auto-capture abstracts + metadata from bioRxiv tool results.
                    # Preprint references are keyed by DOI (which the agent is
                    # instructed to pass to cite_evidence) rather than PMID.
                    if tool_name == "search_biorxiv" and isinstance(tool_output, dict):
                        for bx in tool_output.get("articles", []) or []:
                            bx_doi = str(bx.get("doi", ""))
                            bx_abstract = bx.get("abstract", "")
                            if bx_doi:
                                preprint_metadata[bx_doi] = bx
                                if bx_abstract and not evidence_map.get(bx_doi):
                                    evidence_map.setdefault(bx_doi, []).append({
                                        "quote": bx_abstract,
                                        "context_type": "abstract",
                                        "auto": True,
                                    })

                    if tool_name == "browse_biorxiv_recent" and isinstance(tool_output, dict):
                        for bx in tool_output.get("articles", []) or []:
                            bx_doi = str(bx.get("doi", ""))
                            if bx_doi:
                                preprint_metadata[bx_doi] = bx
                                bx_abstract = bx.get("abstract", "")
                                if bx_abstract and not evidence_map.get(bx_doi):
                                    evidence_map.setdefault(bx_doi, []).append({
                                        "quote": bx_abstract,
                                        "context_type": "abstract",
                                        "auto": True,
                                    })

                    if tool_name == "fetch_biorxiv_paper" and isinstance(tool_output, dict):
                        bx_doi = str(tool_output.get("doi", ""))
                        bx_abstract = tool_output.get("abstract", "")
                        if bx_doi and tool_output.get("success"):
                            preprint_metadata[bx_doi] = tool_output
                            if bx_abstract:
                                # Replace auto-captured entries with the
                                # directly-fetched abstract.
                                evidence_map[bx_doi] = [
                                    e for e in evidence_map.get(bx_doi, [])
                                    if not e.get("auto")
                                ]
                                evidence_map[bx_doi].append({
                                    "quote": bx_abstract,
                                    "context_type": "abstract",
                                    "auto": True,
                                })

                    if tool_name == "get_biorxiv_fulltext" and isinstance(tool_output, dict):
                        bx_doi = str(tool_output.get("doi", ""))
                        if bx_doi and tool_output.get("success"):
                            # Keep existing metadata, but record a fulltext flag so
                            # downstream knows full text was consulted.
                            meta = preprint_metadata.get(bx_doi, {})
                            if tool_output.get("title"):
                                meta.setdefault("title", tool_output["title"])
                            meta["has_fulltext"] = True
                            preprint_metadata[bx_doi] = meta

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

                # Extract article identifiers from the final response. PubMed
                # articles are referenced by numeric PMID; bioRxiv/medRxiv
                # preprints are referenced by DOI (10.1101/... or 10.64898/...).
                # Multiple regex patterns catch LLM deviations from the
                # instructed citation form.
                pmid_url_re = re.compile(r"(?:https?://)?pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?")
                pmid_md_re = re.compile(r"\[(\d+)\]\((?:https?://)?pubmed\.ncbi\.nlm\.nih\.gov/\d+/?\)")
                pmid_tag_re = re.compile(r"PMID[:\s#]*\s*(\d{4,9})", re.IGNORECASE)
                pmid_bracket_re = re.compile(r"\[(\d{4,9})\](?!\()")

                # bioRxiv / medRxiv DOI patterns — URLs and bare DOIs with the
                # biorxiv/medrxiv prefix.
                biorxiv_url_re = re.compile(
                    r"(?:https?://)?(?:www\.)?(biorxiv|medrxiv)\.org/content/(10\.\d+/[0-9.]+(?:v\d+)?)",
                    re.IGNORECASE,
                )
                biorxiv_tag_re = re.compile(
                    r"\b(bioRxiv|medRxiv)\s*[:#]?\s*(10\.\d+/[0-9.]+(?:v\d+)?)",
                    re.IGNORECASE,
                )

                scan_text = "\n".join([p for p in response_parts if p]) or (final_response or "")

                # PubMed IDs
                pmids_set = set(pmid_url_re.findall(scan_text))
                pmids_set.update(pmid_md_re.findall(scan_text))
                pmids_set.update(pmid_tag_re.findall(scan_text))
                pmids_set.update(pmid_bracket_re.findall(scan_text))
                pmids = sorted([p for p in pmids_set if p and p.isdigit()])

                # bioRxiv/medRxiv preprints: dict of doi -> server ("biorxiv"/"medrxiv")
                preprint_ids: Dict[str, str] = {}
                for server, doi in biorxiv_url_re.findall(scan_text):
                    doi_clean = re.sub(r"v\d+$", "", doi)
                    preprint_ids.setdefault(doi_clean, server.lower())
                for server, doi in biorxiv_tag_re.findall(scan_text):
                    doi_clean = re.sub(r"v\d+$", "", doi)
                    preprint_ids.setdefault(doi_clean, server.lower())

                # The SSE payload historically exposed the extracted ids as `pmids`
                # for logging; keep backwards compat by including preprint DOIs in
                # the count but leaving the variable name alone.
                citation_ids = pmids + sorted(preprint_ids.keys())

                # Get article references (list of dicts with evidence)
                references: List[Dict] = []
                # pmid -> abstract from Neo4j article rows, used by the post-hoc
                # evidence-enforcement step below when evidence_map has no entry
                # for a cited PMID (e.g. the agent named a PMID from its own
                # memory without calling a retrieval tool).
                abstract_by_pmid: Dict[str, str] = {}
                if pmids and _has_search_service:
                    try:
                        search_service = get_search_service()
                        article_rows = await search_service.search_articles_by_pmids(pmids)
                        if article_rows and isinstance(article_rows[0], dict):
                            for r in article_rows:
                                ref_pmid = str(r.get("pubmedid", r.get("pmid", "")))
                                # Fallback: extract PMID from URL if not in dict keys
                                if not ref_pmid:
                                    url = r.get("url", "")
                                    url_match = pmid_url_re.search(url)
                                    ref_pmid = url_match.group(1) if url_match else ""
                                abs_text = (r.get("abstract") or "").strip()
                                if ref_pmid and abs_text:
                                    abstract_by_pmid[ref_pmid] = abs_text
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

                # Fallback: ensure every inline-cited PMID has a reference entry, even if
                # search_articles_by_pmids dropped it (not in Neo4j) or the lookup failed
                # entirely (import error, Neo4j unavailable). Without this, inline citations
                # can appear in the answer with no matching entry in `references`.
                found_pmids = {str(r.get("pmid")) for r in references if r.get("pmid")}
                for pmid in pmids:
                    if pmid in found_pmids:
                        continue
                    references.append({
                        "pmid": pmid,
                        "title": f"PMID {pmid}",
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "n_citation": 0,
                        "date": None,
                        "journal": None,
                        "authors": [],
                        "evidence": evidence_map.get(pmid, []),
                    })

                # Append bioRxiv / medRxiv preprint references. These use the
                # same schema as PubMed references so the frontend renders them
                # through the same path — `pmid` is set to "N/A" (the frontend
                # does not key on it; it parses the trailing segment of `url`
                # for bookmarks), and `journal` is set to "bioRxiv" or
                # "medRxiv" so the badge shows the preprint source.
                for doi, server in sorted(preprint_ids.items()):
                    meta = preprint_metadata.get(doi, {}) or {}
                    server = (meta.get("server") or meta.get("source") or server or "biorxiv").lower()
                    journal_label = "medRxiv" if server == "medrxiv" else "bioRxiv"
                    url = meta.get("url") or f"https://www.{server}.org/content/{doi}"
                    title = meta.get("title") or f"{journal_label} preprint {doi}"
                    posted_date = meta.get("posted_date") or meta.get("date") or None
                    authors = meta.get("authors") or []
                    if isinstance(authors, str):
                        authors = [a.strip() for a in authors.split(";") if a.strip()]
                    # `citation_count` is populated by the EPMC-backed
                    # search_biorxiv path; fetch_biorxiv_paper (bioRxiv native
                    # API) doesn't expose one, so we backfill via EPMC below.
                    try:
                        n_citation = int(meta.get("citation_count") or 0)
                    except (TypeError, ValueError):
                        n_citation = 0
                    references.append({
                        "pmid": "N/A",
                        "title": title,
                        "url": url,
                        "n_citation": n_citation,
                        "date": posted_date,
                        "journal": journal_label,
                        "authors": authors,
                        "evidence": evidence_map.get(doi, []),
                    })

                # Post-hoc evidence enforcement.
                # If a cited PMID reached this point with no evidence (e.g. the
                # agent named a PMID from its own memory or called a tool that
                # isn't captured by evidence_map), fall back to the article
                # abstract. Prefer abstracts already loaded from Neo4j; for
                # anything still missing, fetch from NCBI in parallel with a
                # short timeout so a slow NCBI call can't stall the response.
                _needs_ev = [r for r in references if not r.get("evidence") and r.get("pmid")]
                for r in _needs_ev:
                    abs_text = abstract_by_pmid.get(str(r["pmid"]))
                    if abs_text:
                        r["evidence"] = [{"quote": abs_text, "context_type": "abstract"}]

                # PubMed metadata + evidence fallback. When GLKB's
                # search_articles_by_pmids could not fill in a reference (either
                # because `app.api.deps` failed to import on startup, or because
                # the PMID is not in GLKB Neo4j), we fall through to a stub with
                # `title="PMID X"` and empty `authors`. Fetch from NCBI EFetch
                # to backfill title/authors/journal/year — and opportunistically
                # backfill evidence in the same request so we only hit NCBI once
                # per PMID.
                def _pubmed_ref_gaps(r):
                    if not (r.get("pmid") and str(r.get("pmid", "")).isdigit()):
                        return None
                    gaps = {"title": False, "authors": False, "journal": False,
                            "date": False, "evidence": False}
                    t = (r.get("title") or "")
                    if not t or t.startswith("PMID "):
                        gaps["title"] = True
                    if not r.get("authors"):
                        gaps["authors"] = True
                    if not r.get("journal"):
                        gaps["journal"] = True
                    if not r.get("date"):
                        gaps["date"] = True
                    if not r.get("evidence"):
                        gaps["evidence"] = True
                    return gaps if any(gaps.values()) else None

                pubmed_fallbacks = [
                    (r, gaps)
                    for r in references
                    for gaps in [_pubmed_ref_gaps(r)]
                    if gaps is not None
                ]
                if pubmed_fallbacks:
                    try:
                        from my_agent.tools import fetch_abstract as _fetch_abs
                        fetched = await asyncio.wait_for(
                            asyncio.gather(
                                *(_fetch_abs(pmid=str(r["pmid"])) for r, _ in pubmed_fallbacks),
                                return_exceptions=True,
                            ),
                            timeout=15.0,
                        )
                        for (r, gaps), res in zip(pubmed_fallbacks, fetched):
                            if isinstance(res, Exception) or not isinstance(res, dict):
                                continue
                            if not res.get("success"):
                                continue
                            if gaps["title"]:
                                t = (res.get("title") or "").strip()
                                if t:
                                    r["title"] = t
                            if gaps["authors"]:
                                raw_auths = res.get("authors") or []
                                flat: List[str] = []
                                for a in raw_auths:
                                    if isinstance(a, dict):
                                        fn = (a.get("ForeName") or a.get("firstName") or a.get("initials") or "").strip()
                                        ln = (a.get("LastName") or a.get("lastName") or "").strip()
                                        name = f"{fn} {ln}".strip() or (a.get("fullName") or "").strip()
                                    elif isinstance(a, str):
                                        name = a.strip()
                                    else:
                                        name = ""
                                    if name:
                                        flat.append(name)
                                if flat:
                                    r["authors"] = flat
                            if gaps["journal"] and res.get("journal"):
                                r["journal"] = res["journal"]
                            if gaps["date"] and res.get("year"):
                                r["date"] = res["year"]
                            if gaps["evidence"]:
                                abs_text = (res.get("abstract") or "").strip()
                                if abs_text:
                                    r["evidence"] = [{"quote": abs_text, "context_type": "abstract"}]
                    except asyncio.TimeoutError:
                        logger.warning(
                            "NCBI metadata+evidence fallback timed out; %d reference(s) may be incomplete",
                            len(pubmed_fallbacks),
                        )
                    except Exception as e:
                        logger.warning(f"NCBI metadata+evidence fallback failed: {e}")

                # Citation counts for stub refs. NCBI EFetch does not return
                # citedByCount, so PMIDs that fell through the GLKB path have
                # n_citation=0 at this point. Europe PMC indexes PubMed
                # (SRC:MED) and exposes citation counts — one batched request
                # covers every stub PMID.
                pmids_needing_citations = [
                    str(r["pmid"]) for r in references
                    if str(r.get("pmid", "")).isdigit() and not r.get("n_citation")
                ]
                if pmids_needing_citations:
                    cit_counts = await _fetch_epmc_citation_counts(pmids_needing_citations)
                    if cit_counts:
                        for r in references:
                            pmid = str(r.get("pmid", ""))
                            if pmid in cit_counts:
                                r["n_citation"] = cit_counts[pmid]

                # Citation counts for preprint refs that didn't come in via
                # search_biorxiv (which already carries EPMC citedByCount).
                # fetch_biorxiv_paper hits the bioRxiv native API, which has
                # no citation count — so DOI-only preprints land here with
                # n_citation=0. Backfill via EPMC SRC:PPR.
                preprint_dois_needing_citations = [
                    doi for doi in preprint_ids
                    if not any(
                        r.get("n_citation") and doi in str(r.get("url", ""))
                        for r in references
                    )
                ]
                if preprint_dois_needing_citations:
                    cit_counts = await _fetch_epmc_preprint_citation_counts(
                        preprint_dois_needing_citations
                    )
                    if cit_counts:
                        for r in references:
                            url = str(r.get("url", ""))
                            m = biorxiv_url_re.search(url)
                            if not m:
                                continue
                            doi = re.sub(r"v\d+$", "", m.group(2))
                            if doi in cit_counts and not r.get("n_citation"):
                                r["n_citation"] = cit_counts[doi]

                # bioRxiv / medRxiv evidence fallback. Recover the DOI from the
                # reference URL (preprint entries have pmid="N/A"), then call
                # fetch_biorxiv_paper in parallel with a bounded timeout.
                preprint_needs_ev = []
                for r in references:
                    if r.get("evidence"):
                        continue
                    url = str(r.get("url") or "")
                    m = biorxiv_url_re.search(url)
                    if not m:
                        continue
                    doi = re.sub(r"v\d+$", "", m.group(2))
                    preprint_needs_ev.append((r, doi))

                if preprint_needs_ev:
                    try:
                        from my_agent.tools import fetch_biorxiv_paper as _fetch_bx
                        fetched = await asyncio.wait_for(
                            asyncio.gather(
                                *(_fetch_bx(doi=doi) for _, doi in preprint_needs_ev),
                                return_exceptions=True,
                            ),
                            timeout=15.0,
                        )
                        for (r, _), res in zip(preprint_needs_ev, fetched):
                            if isinstance(res, Exception) or not isinstance(res, dict):
                                continue
                            if not res.get("success"):
                                continue
                            abs_text = (res.get("abstract") or "").strip()
                            if abs_text:
                                r["evidence"] = [{"quote": abs_text, "context_type": "abstract"}]
                    except asyncio.TimeoutError:
                        logger.warning(
                            "bioRxiv abstract fallback timed out; %d preprint(s) remain without evidence",
                            len(preprint_needs_ev),
                        )
                    except Exception as e:
                        logger.warning(f"bioRxiv abstract fallback failed: {e}")

                # Apply max_articles cap at the end, preserving the order of first appearance
                # in the answer text so the cap doesn't silently drop cited items. For PubMed
                # articles we key on the pmid field; for preprints (pmid="N/A") we key on the
                # DOI extracted from the reference URL.
                if references and request.max_articles:
                    order = {p: i for i, p in enumerate(citation_ids)}

                    def _ref_order_key(r):
                        pmid = str(r.get("pmid", ""))
                        if pmid and pmid != "N/A":
                            return order.get(pmid, 10**9)
                        url = str(r.get("url") or "")
                        m = biorxiv_url_re.search(url)
                        if m:
                            doi = re.sub(r"v\d+$", "", m.group(2))
                            return order.get(doi, 10**9)
                        return 10**9

                    references.sort(key=_ref_order_key)
                    references = references[:request.max_articles]
                
                # Calculate execution time
                execution_time = time.time() - step_start_time

                # Build reasoning trajectory from collected tool events
                trajectory = _build_trajectory(trajectory_events)

                # Log completion BEFORE the final yield (generator may be
                # cancelled by client disconnect after the last yield)
                logger.info(f"[STREAM COMPLETE] question={question!r} session_id={session_id} time={execution_time:.1f}s refs={len(citation_ids)} (pmids={len(pmids)} preprints={len(preprint_ids)})")

                # Write per-request transcript
                transcript_record = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "session_id": session_id,
                    "question": question,
                    "execution_time": round(execution_time, 2),
                    "status": "complete",
                    "n_references": len(citation_ids),
                    "events": transcript_events,
                }
                try:
                    transcript_logger.info(json.dumps(transcript_record, default=str))
                except Exception:
                    pass

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

                # Write error transcript
                transcript_record = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "session_id": session_id,
                    "question": question,
                    "execution_time": round(time.time() - step_start_time, 2),
                    "status": "error",
                    "error": error_msg,
                    "events": transcript_events,
                }
                try:
                    transcript_logger.info(json.dumps(transcript_record, default=str))
                except Exception:
                    pass

                yield send_message({
                    'step': 'Error',
                    'content': error_msg,
                    'done': True
                })
            finally:
                # Ensure the producer task is cleaned up
                try:
                    if not producer_task.done():
                        producer_task.cancel()
                        try:
                            await producer_task
                        except (asyncio.CancelledError, Exception):
                            pass
                except NameError:
                    pass
        
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
