"""
SQLite-backed session service for the GLKB Agent FastAPI service.

Implements session CRUD operations with persistent storage.
"""

import aiosqlite
import json
import uuid
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

# Database file path
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "sessions.db")


@dataclass
class Session:
    """Represents a session with its state and metadata."""
    id: str
    app_name: str
    user_id: str
    state: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "app_name": self.app_name,
            "user_id": self.user_id,
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class Message:
    """Represents a message in a conversation."""
    id: int
    session_id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }


class SQLiteSessionService:
    """
    SQLite-backed session service for managing agent sessions.
    
    Provides CRUD operations for sessions and messages with
    persistent storage using SQLite.
    """
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._initialized = False
    
    async def initialize(self):
        """Initialize the database schema."""
        if self._initialized:
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            # Create sessions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    app_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    state TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index on app_name and user_id for faster lookups
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_app_user 
                ON sessions(app_name, user_id)
            """)
            
            # Create messages table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            
            # Create index on session_id for faster message lookups
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session 
                ON messages(session_id)
            """)
            
            await db.commit()
        
        self._initialized = True
    
    async def create_session(
        self,
        app_name: str,
        user_id: str,
        session_id: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None
    ) -> Session:
        """
        Create a new session.
        
        Args:
            app_name: Name of the application/agent
            user_id: User identifier
            session_id: Optional custom session ID (UUID generated if not provided)
            state: Optional initial state dictionary
            
        Returns:
            The created Session object
        """
        await self.initialize()
        
        session_id = session_id or str(uuid.uuid4())
        state = state or {}
        now = datetime.utcnow()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO sessions (id, app_name, user_id, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, app_name, user_id, json.dumps(state), now, now)
            )
            await db.commit()
        
        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=state,
            created_at=now,
            updated_at=now
        )
    
    async def get_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str
    ) -> Optional[Session]:
        """
        Get a session by ID.
        
        Args:
            app_name: Name of the application/agent
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            Session object if found, None otherwise
        """
        await self.initialize()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, app_name, user_id, state, created_at, updated_at
                FROM sessions
                WHERE id = ? AND app_name = ? AND user_id = ?
                """,
                (session_id, app_name, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                
                if row is None:
                    return None
                
                return Session(
                    id=row["id"],
                    app_name=row["app_name"],
                    user_id=row["user_id"],
                    state=json.loads(row["state"]) if row["state"] else {},
                    created_at=datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"],
                    updated_at=datetime.fromisoformat(row["updated_at"]) if isinstance(row["updated_at"], str) else row["updated_at"]
                )
    
    async def update_session(self, session: Session) -> Session:
        """
        Update an existing session's state.
        
        Args:
            session: Session object with updated state
            
        Returns:
            Updated Session object
        """
        await self.initialize()
        
        session.updated_at = datetime.utcnow()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE sessions
                SET state = ?, updated_at = ?
                WHERE id = ? AND app_name = ? AND user_id = ?
                """,
                (json.dumps(session.state), session.updated_at, 
                 session.id, session.app_name, session.user_id)
            )
            await db.commit()
        
        return session
    
    async def delete_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str
    ) -> bool:
        """
        Delete a session and its messages.
        
        Args:
            app_name: Name of the application/agent
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            True if session was deleted, False if not found
        """
        await self.initialize()
        
        async with aiosqlite.connect(self.db_path) as db:
            # Delete messages first (cascade should handle this but being explicit)
            await db.execute(
                "DELETE FROM messages WHERE session_id = ?",
                (session_id,)
            )
            
            # Delete session
            cursor = await db.execute(
                """
                DELETE FROM sessions
                WHERE id = ? AND app_name = ? AND user_id = ?
                """,
                (session_id, app_name, user_id)
            )
            await db.commit()
            
            return cursor.rowcount > 0
    
    async def list_sessions(
        self,
        app_name: str,
        user_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Session]:
        """
        List sessions for a user.
        
        Args:
            app_name: Name of the application/agent
            user_id: User identifier
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip
            
        Returns:
            List of Session objects
        """
        await self.initialize()
        
        sessions = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, app_name, user_id, state, created_at, updated_at
                FROM sessions
                WHERE app_name = ? AND user_id = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (app_name, user_id, limit, offset)
            ) as cursor:
                async for row in cursor:
                    sessions.append(Session(
                        id=row["id"],
                        app_name=row["app_name"],
                        user_id=row["user_id"],
                        state=json.loads(row["state"]) if row["state"] else {},
                        created_at=datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"],
                        updated_at=datetime.fromisoformat(row["updated_at"]) if isinstance(row["updated_at"], str) else row["updated_at"]
                    ))
        
        return sessions
    
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> Message:
        """
        Add a message to a session's conversation history.
        
        Args:
            session_id: Session identifier
            role: Message role ("user" or "assistant")
            content: Message content
            
        Returns:
            Created Message object
        """
        await self.initialize()
        
        now = datetime.utcnow()
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO messages (session_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, now)
            )
            await db.commit()
            message_id = cursor.lastrowid
        
        return Message(
            id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            timestamp=now
        )
    
    async def get_messages(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[Message]:
        """
        Get messages for a session.
        
        Args:
            session_id: Session identifier
            limit: Maximum number of messages to return
            
        Returns:
            List of Message objects ordered by timestamp
        """
        await self.initialize()
        
        messages = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, session_id, role, content, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (session_id, limit)
            ) as cursor:
                async for row in cursor:
                    messages.append(Message(
                        id=row["id"],
                        session_id=row["session_id"],
                        role=row["role"],
                        content=row["content"],
                        timestamp=datetime.fromisoformat(row["timestamp"]) if isinstance(row["timestamp"], str) else row["timestamp"]
                    ))
        
        return messages
    
    async def get_message_count(self, session_id: str) -> int:
        """
        Get the number of messages in a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Number of messages
        """
        await self.initialize()
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0


# Global singleton instance
_session_service: Optional[SQLiteSessionService] = None


def get_session_service(db_path: str = DEFAULT_DB_PATH) -> SQLiteSessionService:
    """Get the global session service instance."""
    global _session_service
    if _session_service is None:
        _session_service = SQLiteSessionService(db_path)
    return _session_service

