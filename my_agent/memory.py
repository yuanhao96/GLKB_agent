"""
Memory Tools for GLKB Agent System

Provides persistent memory capabilities using Mem0 for:
- Storing conversation context and user preferences
- Retrieving relevant past interactions
- Managing memory lifecycle (add, search, delete)
"""

import logging
import os
from typing import Optional, List
from dotenv import load_dotenv
from google.adk.tools import FunctionTool

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------
# Memory Configuration and Initialization
# -----------------------------------------

# Ensure the memory directory exists before initializing Mem0
MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", ".mem0")
os.makedirs(MEMORY_DIR, exist_ok=True)
logger.info(f"Memory directory ensured at: {MEMORY_DIR}")

# Mem0 configuration
config = {
    # Override where the history database file lives
    "history_db_path": os.path.join(MEMORY_DIR, "history.db"),

    # Configure vector store for persistent storage (not /tmp)
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "glkb_agent_memory",
            "path": os.path.join(MEMORY_DIR, "qdrant"),  # Persistent path
            "on_disk": True,  # Enable disk persistence
        }
    },

    # Optionally customize the LLM used by Mem0
    "llm": {
        "provider": "openai",
        "config": {
            "model": "gpt-4o-mini",
            "temperature": 0.3,
            "max_tokens": 1024
        }
    },

    # Optionally configure your embedding model
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "text-embedding-3-small"
        }
    }
}

# Lazy initialization of Memory to avoid import-time errors
_memory_instance = None

def get_memory():
    """Get or initialize the Mem0 memory instance."""
    global _memory_instance
    if _memory_instance is None:
        from mem0 import Memory
        _memory_instance = Memory.from_config(config)
        logger.info("Mem0 Memory instance initialized successfully")
    return _memory_instance


# -----------------------------------------
# Memory Tool Functions
# -----------------------------------------

async def add_memory(
    content: str,
    # user_id: str = "default_user",
    metadata: Optional[dict] = None
) -> dict:
    """
    Add a new memory to the persistent memory store.
    
    Use this to store important information from conversations that should be 
    remembered for future interactions, such as:
    - User preferences and research interests
    - Key findings from previous queries
    - Important entities or concepts the user frequently asks about
    
    Args:
        content: The text content to store as a memory. Should be a clear, 
                 self-contained statement or fact.
        metadata: Optional dictionary of additional metadata to attach to the memory.
    
    Returns:
        dict: Contains status information
            - success: bool indicating if memory was stored
            - memory_id: ID of the created memory (if successful)
            - message: Description of what was stored
            - error: Error message (if unsuccessful)
    
    Example:
        add_memory(
            content="User is researching TP53 gene mutations in breast cancer",
            metadata={"topic": "oncology", "gene": "TP53"}
        )
    """
    log = logging.getLogger(f"{__name__}.memory")
    user_id = "default_user"

    try:
        memory = get_memory()
        
        # Prepare messages format for Mem0
        messages = [{"role": "user", "content": content}]
        
        # Add memory with optional metadata
        result = memory.add(
            messages=messages,
            user_id=user_id,
            metadata=metadata or {}
        )
        
        log.info(f"Memory added for user {user_id}: {content[:50]}...")
        
        # Extract memory IDs from result
        memory_ids = []
        if isinstance(result, dict) and "results" in result:
            memory_ids = [r.get("id") for r in result.get("results", []) if r.get("id")]
        
        return {
            "success": True,
            "memory_ids": memory_ids,
            "message": f"Successfully stored memory for user '{user_id}'",
            "content_preview": content[:100] + "..." if len(content) > 100 else content
        }
        
    except Exception as e:
        log.error(f"Error adding memory: {str(e)}")
        return {
            "success": False,
            "error": f"Failed to add memory: {str(e)}"
        }

async def get_all_memories(
    user_id: str = "default_user"
) -> dict:
    """
    Retrieve all stored memories for a specific user.
    
    Use this to get a complete overview of what has been stored for a user,
    useful for context building at the start of a session or for debugging.
    
    Args:
        user_id: Identifier for the user/session (default: "default_user").
    
    Returns:
        dict: Contains all memories
            - success: bool indicating if retrieval was successful
            - count: Total number of memories
            - memories: List of all memories with their content and metadata
            - error: Error message (if unsuccessful)
    """
    log = logging.getLogger(f"{__name__}.memory")
    
    try:
        memory = get_memory()
        
        # Get all memories for user
        results = memory.get_all(user_id=user_id)
        
        # Parse results
        memories = []
        if isinstance(results, dict) and "results" in results:
            for r in results.get("results", []):
                memories.append({
                    "id": r.get("id"),
                    "content": r.get("memory"),
                    "metadata": r.get("metadata", {}),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at")
                })
        elif isinstance(results, list):
            for r in results:
                memories.append({
                    "id": r.get("id"),
                    "content": r.get("memory"),
                    "metadata": r.get("metadata", {}),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at")
                })
        
        log.info(f"Retrieved {len(memories)} total memories for user {user_id}")
        
        return {
            "success": True,
            "user_id": user_id,
            "count": len(memories),
            "memories": memories
        }
        
    except Exception as e:
        log.error(f"Error getting all memories: {str(e)}")
        return {
            "success": False,
            "user_id": user_id,
            "error": f"Failed to get memories: {str(e)}"
        }

async def search_memory(
    query: str,
    # user_id: str = "default_user",
    limit: int = 5
) -> dict:
    """
    Search for relevant memories based on a query.
    
    Use this to retrieve past context that may be relevant to the current 
    conversation or query. The search uses semantic similarity to find 
    the most relevant stored memories.
    
    Args:
        query: The search query to find relevant memories. Can be a question,
               topic, or any text that describes what you're looking for.
        limit: Maximum number of memories to return (default: 5).
    
    Returns:
        dict: Contains search results
            - success: bool indicating if search was successful
            - count: Number of memories found
            - memories: List of relevant memories with their content and metadata
            - error: Error message (if unsuccessful)
    
    Example:
        search_memory(
            query="What genes has the user asked about before?",
            user_id="researcher_001",
            limit=10
        )
    """
    log = logging.getLogger(f"{__name__}.memory")
    user_id = "default_user"

    try:
        memory = get_memory()
        
        # Search memories
        results = memory.search(
            query=query,
            user_id=user_id,
            limit=limit
        )
        
        # Parse results
        memories = []
        if isinstance(results, dict) and "results" in results:
            for r in results.get("results", []):
                memories.append({
                    "id": r.get("id"),
                    "content": r.get("memory"),
                    "score": r.get("score"),
                    "metadata": r.get("metadata", {}),
                    "created_at": r.get("created_at")
                })
        elif isinstance(results, list):
            for r in results:
                memories.append({
                    "id": r.get("id"),
                    "content": r.get("memory"),
                    "score": r.get("score"),
                    "metadata": r.get("metadata", {}),
                    "created_at": r.get("created_at")
                })
        
        log.info(f"Found {len(memories)} memories for query: {query[:50]}...")
        
        return {
            "success": True,
            "query": query,
            "user_id": user_id,
            "count": len(memories),
            "memories": memories
        }
        
    except Exception as e:
        log.error(f"Error searching memory: {str(e)}")
        return {
            "success": False,
            "query": query,
            "error": f"Failed to search memory: {str(e)}"
        }

async def delete_memory(
    memory_id: str
) -> dict:
    """
    Delete a specific memory by its ID.
    
    Use this to remove outdated, incorrect, or no longer relevant memories.
    
    Args:
        memory_id: The unique identifier of the memory to delete.
    
    Returns:
        dict: Contains deletion status
            - success: bool indicating if deletion was successful
            - memory_id: ID of the deleted memory
            - message: Confirmation message
            - error: Error message (if unsuccessful)
    """
    log = logging.getLogger(f"{__name__}.memory")
    
    try:
        memory = get_memory()
        
        # Delete the memory
        memory.delete(memory_id=memory_id)
        
        log.info(f"Deleted memory: {memory_id}")
        
        return {
            "success": True,
            "memory_id": memory_id,
            "message": f"Successfully deleted memory '{memory_id}'"
        }
        
    except Exception as e:
        log.error(f"Error deleting memory: {str(e)}")
        return {
            "success": False,
            "memory_id": memory_id,
            "error": f"Failed to delete memory: {str(e)}"
        }

async def add_cypher_memory(
    natural_language_query: str,
    query_type: str,
    cypher_query: str,
    outcome: str,
    error_message: Optional[str] = None,
    count: Optional[int] = None
) -> dict:
    """
    Add a new memory to the persistent memory store.

    Args:
        natural_language_query: The natural language query to execute.
        query_type: The type of query (e.g. "find relationships between genes and diseases", "count number of articles").
        cypher_query: The generated Cypher query by the LLM.
        outcome: The outcome of the Cypher query execution (success or error).
        error_message: The error message of the Cypher query execution (if any) (default: None).
        count: The number of records returned by the Cypher query execution (if any) (default: None).
    
    Returns:
        dict: Contains status information
            - success: bool indicating if memory was stored
            - memory_id: ID of the created memory (if successful)
            - message: Description of what was stored
            - error: Error message (if unsuccessful)

    Example:
        add_cypher_memory(
            natural_language_query="Find articles that contain the term 'breast cancer' in 2024",
            cypher_query="MATCH (a:Article)-[:ContainTerm]->(v:Vocabulary {id: 'doid:10652'}) WHERE a.pubdate = 2024 RETURN DISTINCT a.title, a.abstract, a.pubmedid, a.n_citation, a.pubdate, a.authors LIMIT 100",
            outcome="success",
            count=100
        )
    """
    log = logging.getLogger(f"{__name__}.memory")
    user_id = "default_user"

    try:
        memory = get_memory()

        # Prepare messages format for Mem0
        messages = [
            {
                "role": "user",
                "content": natural_language_query
            }
        ]
        result = memory.add(
            messages=messages,
            user_id=user_id,
            metadata={
                "query_type": query_type,
                "cypher_query": cypher_query,
                "outcome": outcome,
                "error_message": error_message,
                "count": count
            },
            infer=False
        )

        log.info(f"Cypher memory added for user {user_id}: {natural_language_query[:50]}...")

        # Extract memory IDs from result
        memory_ids = []
        if isinstance(result, dict) and "results" in result:
            memory_ids = [r.get("id") for r in result.get("results", []) if r.get("id")]
        
        return {
            "success": True,
            "memory_ids": memory_ids,
            "message": f"Successfully stored Cypher memory for user '{user_id}'",
            "content_preview": natural_language_query[:100] + "..." if len(natural_language_query) > 100 else natural_language_query
        }
        
    except Exception as e:
        log.error(f"Error adding memory: {str(e)}")
        return {
            "success": False,
            "error": f"Failed to add memory: {str(e)}"
        }

# -----------------------------------------
# Create FunctionTools for Google ADK
# -----------------------------------------

add_memory_tool = FunctionTool(add_memory)
search_memory_tool = FunctionTool(search_memory)
add_cypher_memory_tool = FunctionTool(add_cypher_memory)
# delete_memory_tool = FunctionTool(delete_memory)

# Export all memory tools as a list for easy import
memory_tools = [
    add_memory_tool,
    search_memory_tool,
    # delete_memory_tool,
    add_cypher_memory_tool,
]

# For backwards compatibility and testing
if __name__ == "__main__":
    import asyncio
    
    async def test_memory():
        # Test adding a memory
        print("Testing add_memory...")
        result = await add_memory(
            content="User is interested in TP53 gene and its role in cancer.",
            user_id="test_user"
        )
        print(f"Add result: {result}")
        
        # Test searching memory
        print("\nTesting search_memory...")
        result = await search_memory(
            query="What genes is the user interested in?",
            user_id="test_user"
        )
        print(f"Search result: {result}")
        
        # Test getting all memories
        print("\nTesting get_all_memories...")
        result = await get_all_memories(user_id="test_user")
        print(f"Get all result: {result}")
    
    asyncio.run(test_memory())
