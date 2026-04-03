"""
Agent runner wrapper for the GLKB Agent FastAPI service.

Wraps ADK's Runner to execute agents with proper context,
collect events, and format responses.
"""

import sys
import os

# Add parent directory to path to import my_agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import json
from typing import AsyncGenerator, Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, field

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session as ADKSession
from google.adk.events import Event
from google.genai.types import Content, Part, UserContent

from .session_service import SQLiteSessionService, Session, get_session_service

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of an agent run."""
    response: str
    events: List[Dict[str, Any]] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)


def event_to_dict(event: Event) -> Dict[str, Any]:
    """
    Convert an ADK Event to a dictionary for JSON serialization.
    
    Args:
        event: ADK Event object
        
    Returns:
        Dictionary representation of the event
    """
    result = {
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Extract invocation_id
    if hasattr(event, 'invocation_id') and event.invocation_id:
        result["invocation_id"] = event.invocation_id

    # Extract event type
    if hasattr(event, '__class__'):
        result["type"] = event.__class__.__name__

    # Extract agent name if available
    if hasattr(event, 'author'):
        result["agent_name"] = event.author
    
    # Extract content if available
    if hasattr(event, 'content') and event.content:
        content = event.content
        if hasattr(content, 'parts'):
            parts_text = []
            for part in content.parts:
                # Check for function_call (tool call)
                if hasattr(part, 'function_call') and part.function_call:
                    result["tool_name"] = getattr(part.function_call, 'name', None)
                    result["tool_input"] = getattr(part.function_call, 'args', None)
                    # Don't set content for tool calls
                    continue
                
                # Check for function_response (tool result)
                if hasattr(part, 'function_response') and part.function_response:
                    result["tool_name"] = getattr(part.function_response, 'name', None)
                    result["tool_output"] = getattr(part.function_response, 'response', None)
                    # Don't set content for tool responses
                    continue
                
                # Regular text content
                if hasattr(part, 'text') and part.text:
                    parts_text.append(part.text)
            if parts_text:
                result["content"] = "\n".join(parts_text)
        elif hasattr(content, 'text'):
            result["content"] = content.text
    
    # Legacy: Extract tool information if available as direct attributes (fallback)
    if "tool_name" not in result and hasattr(event, 'tool_name'):
        result["tool_name"] = event.tool_name
    if "tool_input" not in result and hasattr(event, 'tool_input'):
        result["tool_input"] = event.tool_input
    if "tool_output" not in result and hasattr(event, 'tool_output'):
        result["tool_output"] = str(event.tool_output)[:1000]  # Truncate long outputs
    
    # Extract any actions
    if hasattr(event, 'actions'):
        result["actions"] = [str(a) for a in event.actions] if event.actions else []
    
    return result


class AgentRunner:
    """
    Wrapper around ADK's Runner for executing agents.
    
    Provides both streaming and non-streaming execution modes,
    integrating with SQLite session service for persistence.
    """
    
    def __init__(self, agent, session_service: Optional[SQLiteSessionService] = None):
        """
        Initialize the agent runner.
        
        Args:
            agent: The ADK agent to run (typically root_agent)
            session_service: Optional SQLite session service for persistence
        """
        self.agent = agent
        self.session_service = session_service or get_session_service()
        # In-memory session service for ADK Runner (we sync with SQLite)
        self._adk_session_service = InMemorySessionService()
    
    async def _get_or_create_adk_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str
    ) -> ADKSession:
        """
        Get or create an ADK session, syncing state and events from SQLite.
        
        According to ADK documentation, Sessions contain Events which represent
        the chronological sequence of messages. This method populates the session
        with historical events from SQLite messages.

        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session identifier

        Returns:
            ADK Session object with historical events populated
        """
        # Get session from SQLite
        db_session = await self.session_service.get_session(app_name, user_id, session_id)
        if db_session is None:
            raise ValueError(f"Session {session_id} not found")

        # Get chat history from SQLite
        messages = await self.session_service.get_messages(session_id)

        # Try to get existing ADK session
        adk_session = await self._adk_session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id
        )

        if adk_session is None:
            # Create new ADK session with state from SQLite
            adk_session = await self._adk_session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state=dict(db_session.state)
            )
            
            # Populate session with historical events from SQLite messages
            # This ensures the agent has access to conversation history through Events
            for msg in messages:
                event_content = Content(
                    role=msg.role,
                    parts=[Part(text=msg.content)]
                )
                # Use appropriate author: "user" for user messages, agent name for assistant
                author = "user" if msg.role == "user" else self.agent.name if hasattr(self.agent, 'name') else "assistant"
                event_kwargs = dict(author=author, content=event_content)
                if msg.invocation_id:
                    event_kwargs["invocation_id"] = msg.invocation_id
                event = Event(**event_kwargs)
                await self._adk_session_service.append_event(adk_session, event)
        else:
            # Update ADK session state from SQLite
            adk_session.state.update(db_session.state)
            
            # Check if we need to add missing events
            # Count existing events in ADK session
            existing_event_count = len(adk_session.events) if hasattr(adk_session, 'events') else 0
            
            # Only add events that aren't already in the session
            # (assuming messages are in chronological order)
            if existing_event_count < len(messages):
                # Add only the new messages as events
                for msg in messages[existing_event_count:]:
                    event_content = Content(
                        role=msg.role,
                        parts=[Part(text=msg.content)]
                    )
                    author = "user" if msg.role == "user" else self.agent.name if hasattr(self.agent, 'name') else "assistant"
                    event_kwargs = dict(author=author, content=event_content)
                    if msg.invocation_id:
                        event_kwargs["invocation_id"] = msg.invocation_id
                    event = Event(**event_kwargs)
                    await self._adk_session_service.append_event(adk_session, event)

        return adk_session
    
    async def _sync_state_to_sqlite(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        state: Dict[str, Any]
    ):
        """
        Sync ADK session state back to SQLite.
        
        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session identifier
            state: State dictionary to save
        """
        db_session = await self.session_service.get_session(app_name, user_id, session_id)
        if db_session:
            db_session.state = dict(state)
            await self.session_service.update_session(db_session)
    
    async def run(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        message: str
    ) -> RunResult:
        """
        Run the agent with a message and return the complete result.

        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session identifier
            message: User's message

        Returns:
            RunResult with response, events, and updated state
        """
        # Store user message (invocation_id will be updated after run)
        user_msg = await self.session_service.add_message(session_id, "user", message)

        # Get ADK session
        adk_session = await self._get_or_create_adk_session(app_name, user_id, session_id)

        # Create runner
        runner = Runner(
            agent=self.agent,
            app_name=app_name,
            session_service=self._adk_session_service
        )

        # Collect events and response
        events = []
        response_parts = []
        invocation_id = None

        # Format message as Content object
        user_content = Content(
            role="user",
            parts=[Part(text=message)]
        )

        # Run agent
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_content
        ):
            event_dict = event_to_dict(event)
            events.append(event_dict)

            # Capture invocation_id from the first event that has one
            if invocation_id is None and event_dict.get("invocation_id"):
                invocation_id = event_dict["invocation_id"]

            # Collect text content for final response
            if "content" in event_dict and event_dict.get("type") != "ToolCallEvent":
                response_parts.append(event_dict["content"])

        # Get final response (last non-empty content)
        response = ""
        for part in reversed(response_parts):
            if part and part.strip():
                response = part
                break

        # Update user message with invocation_id now that we have it
        if invocation_id:
            await self.session_service.update_message_invocation_id(
                user_msg.id, invocation_id
            )

        # Sync state back to SQLite
        updated_session = await self._adk_session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id
        )
        state = dict(updated_session.state) if updated_session else {}
        await self._sync_state_to_sqlite(app_name, user_id, session_id, state)

        # Store assistant response with invocation_id
        if response:
            await self.session_service.add_message(
                session_id, "assistant", response,
                invocation_id=invocation_id
            )

        return RunResult(
            response=response,
            events=events,
            state=state
        )
    
    async def run_stream(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        message: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent with streaming, yielding events as they occur.

        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session identifier
            message: User's message

        Yields:
            Event dictionaries as they occur
        """
        # Store user message (invocation_id will be updated after run)
        user_msg = await self.session_service.add_message(session_id, "user", message)

        # Get ADK session
        adk_session = await self._get_or_create_adk_session(app_name, user_id, session_id)

        # Create runner
        runner = Runner(
            agent=self.agent,
            app_name=app_name,
            session_service=self._adk_session_service
        )

        response_parts = []
        invocation_id = None

        # Format message as Content object
        user_content = Content(
            role="user",
            parts=[Part(text=message)]
        )

        # Run agent and stream events
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_content
        ):
            event_dict = event_to_dict(event)

            # Capture invocation_id from the first event that has one
            if invocation_id is None and event_dict.get("invocation_id"):
                invocation_id = event_dict["invocation_id"]

            # Collect text content for final response
            if "content" in event_dict and event_dict.get("type") != "ToolCallEvent":
                response_parts.append(event_dict["content"])

            yield event_dict

        # Get final response
        response = ""
        for part in reversed(response_parts):
            if part and part.strip():
                response = part
                break

        # Update user message with invocation_id now that we have it
        if invocation_id:
            await self.session_service.update_message_invocation_id(
                user_msg.id, invocation_id
            )

        # Sync state back to SQLite
        updated_session = await self._adk_session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id
        )
        if updated_session:
            await self._sync_state_to_sqlite(
                app_name, user_id, session_id,
                dict(updated_session.state)
            )

        # Store assistant response with invocation_id
        if response:
            await self.session_service.add_message(
                session_id, "assistant", response,
                invocation_id=invocation_id
            )


    async def rewind(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        invocation_id: str
    ) -> Dict[str, Any]:
        """
        Rewind a session to before a given invocation.

        Calls ADK's rewind_async to restore the agent's memory, then
        removes the corresponding messages from SQLite to keep them in sync.

        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session identifier
            invocation_id: The invocation ID to rewind before (inclusive)

        Returns:
            Dict with rewound_invocation_ids, remaining_message_count, and messages
        """
        # Ensure the ADK session exists in memory
        await self._get_or_create_adk_session(app_name, user_id, session_id)

        # Create runner and call ADK rewind
        runner = Runner(
            agent=self.agent,
            app_name=app_name,
            session_service=self._adk_session_service
        )
        await runner.rewind_async(
            user_id=user_id,
            session_id=session_id,
            rewind_before_invocation_id=invocation_id,
        )

        # Sync: delete messages from SQLite for the rewound invocations
        removed_ids = await self.session_service.delete_messages_from_invocation(
            session_id, invocation_id
        )

        # Sync ADK state back to SQLite
        updated_session = await self._adk_session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id
        )
        if updated_session:
            await self._sync_state_to_sqlite(
                app_name, user_id, session_id,
                dict(updated_session.state)
            )

        # Return updated message list
        remaining = await self.session_service.get_messages(session_id)
        return {
            "rewound_invocation_ids": removed_ids,
            "remaining_message_count": len(remaining),
            "messages": [msg.to_dict() for msg in remaining],
        }


# Global runner instance (initialized on first use)
_runner: Optional[AgentRunner] = None


def get_runner() -> AgentRunner:
    """
    Get the global agent runner instance.
    
    Lazily imports and initializes the agent to avoid import
    issues during module loading.
    """
    global _runner
    if _runner is None:
        # Import agent here to avoid circular imports
        from my_agent.agent import root_agent
        _runner = AgentRunner(agent=root_agent)
    return _runner

