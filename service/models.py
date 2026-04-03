"""
Pydantic request/response models for the GLKB Agent FastAPI service.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# -----------------------------------------
# Request Models
# -----------------------------------------

class CreateSessionRequest(BaseModel):
    """Request body for creating a new session."""
    session_id: Optional[str] = Field(
        default=None,
        description="Optional custom session ID. If not provided, a UUID will be generated."
    )
    state: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional initial state for the session."
    )


class ChatRequest(BaseModel):
    """Request body for sending a chat message."""
    message: str = Field(
        ...,
        description="The user's message to send to the agent."
    )


class RewindRequest(BaseModel):
    """Request body for rewinding a session to a previous state."""
    invocation_id: str = Field(
        ...,
        description="The invocation ID to rewind before. Removes this invocation and all subsequent ones."
    )


# -----------------------------------------
# Response Models
# -----------------------------------------

class MessageInfo(BaseModel):
    """Information about a single message in a conversation."""
    id: int
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    invocation_id: Optional[str] = None


class SessionInfo(BaseModel):
    """Information about a session."""
    id: str
    app_name: str
    user_id: str
    state: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionListResponse(BaseModel):
    """Response for listing sessions."""
    sessions: List[SessionInfo]
    total: int


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""
    id: str
    app_name: str
    user_id: str
    created_at: datetime


class ChatResponse(BaseModel):
    """Response for a non-streaming chat request."""
    session_id: str
    response: str
    events: List[Dict[str, Any]] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)


class EventData(BaseModel):
    """Represents a single event from the agent execution."""
    type: str
    agent_name: Optional[str] = None
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RewindResponse(BaseModel):
    """Response after rewinding a session."""
    session_id: str
    rewound_invocation_ids: List[str] = Field(default_factory=list)
    remaining_message_count: int
    messages: List[MessageInfo] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None

