# Backend Rewind & Regenerate Support

## Goal

Allow users to **edit a previous message** or **regenerate an answer** in the chat UI. This requires rewinding the conversation to a previous turn, removing everything after it, and then re-running the agent from that point.

The agent service (ADK, port 5000) already supports rewind. The backend (`reorg_glkb_backend`) needs changes to expose this to the frontend and keep its own chat history in sync.

## What's already done (agent service)

### 1. Invocation ID tracking

Every agent turn now produces an `invocation_id` (e.g. `e-65c85070-d145-4a07-8286-8246ed204a4a`). One user message + one assistant response share the same invocation ID. This ID is:

- Included in every SSE event streamed from `/stream`
- Stored alongside each message in the agent's SQLite DB
- Returned in the `Complete` SSE event as `invocation_id`

### 2. Rewind endpoint

```
POST /apps/{app_name}/users/{user_id}/sessions/{session_id}/rewind
Content-Type: application/json

{ "invocation_id": "e-65c85070-..." }
```

This removes the specified turn and all subsequent turns from both ADK's in-memory session (so the LLM forgets them) and the agent's SQLite message store.

Response:
```json
{
  "session_id": "...",
  "rewound_invocation_ids": ["e-65c85070-...", "e-abc123-..."],
  "remaining_message_count": 4,
  "messages": [
    { "id": 1, "role": "user", "content": "...", "invocation_id": "e-...", "timestamp": "..." },
    { "id": 2, "role": "assistant", "content": "...", "invocation_id": "e-...", "timestamp": "..." }
  ]
}
```

### 3. Complete event now includes invocation_id

The `/stream` endpoint's final `Complete` SSE event now includes:
```json
{ "step": "Complete", "response": "...", "session_id": "...", "invocation_id": "e-..." }
```

---

## What needs to change (backend)

### 1. DB model: add `invocation_id` to `ChatMessageRecord`

**File:** `app/db/models.py`

```python
# In ChatMessageRecord, add:
invocation_id = Column(String(60), nullable=True)
```

Run an Alembic migration or manual `ALTER TABLE chat_messages ADD COLUMN invocation_id VARCHAR(60)`.

### 2. DB model: add `session_id` to `ChatHistory`

**File:** `app/db/models.py`

The backend currently receives `session_id` from the agent but doesn't persist it. We need it to know which ADK session to rewind.

```python
# In ChatHistory, add:
session_id = Column(String(100), nullable=True)
```

### 3. Update `save_exchange()` to store `invocation_id` and `session_id`

**File:** `app/services/chat_history_service.py`

```python
def save_exchange(
    self,
    user_id,
    history_id,
    prompt_content,
    answer_content,
    references=None,
    invocation_id=None,   # NEW
    session_id=None,       # NEW
):
    # ... existing logic ...

    # Store invocation_id on both messages
    prompt_msg = ChatMessageRecord(
        history_id=history.hid,
        pair_index=next_pair,
        role="user",
        content=prompt_content,
        invocation_id=invocation_id,
    )
    answer_msg = ChatMessageRecord(
        history_id=history.hid,
        pair_index=next_pair,
        role="assistant",
        content=answer_content,
        references_json=json.dumps(references) if references else None,
        invocation_id=invocation_id,
    )

    # Persist session_id on the history (set on first exchange, or update)
    if session_id and not history.session_id:
        history.session_id = session_id
```

### 4. Add `rewind_to_pair()` method

**File:** `app/services/chat_history_service.py`

```python
def rewind_to_pair(self, user_id: int, hid: int, pair_index: int) -> ChatHistory:
    """Delete all messages with pair_index >= the given value."""
    history = self.get_history(user_id, hid)
    self.db.query(ChatMessageRecord).filter(
        ChatMessageRecord.history_id == hid,
        ChatMessageRecord.pair_index >= pair_index,
    ).delete()
    history.last_accessed_time = datetime.utcnow()
    self.db.commit()
    self.db.refresh(history)
    return history
```

### 5. Update schemas

**File:** `app/schemas/chat_history.py`

```python
# Add invocation_id to ChatMessageResponse
class ChatMessageResponse(BaseModel):
    id: int
    pair_index: int
    role: str
    content: str
    references: Optional[Any] = None
    invocation_id: Optional[str] = None   # NEW
    created_at: datetime
```

**File:** `app/schemas/llm_agent.py`

```python
# Add new request model
class RewindChatRequest(BaseModel):
    history_id: int = Field(..., description="Chat history ID")
    invocation_id: str = Field(..., description="ADK invocation ID to rewind before")
```

### 6. Update `stream_chat()` to capture and store `invocation_id`

**File:** `app/api/v1/new_llm_agent.py`

In `stream_and_save()`, capture `invocation_id` from the `Complete` event:

```python
if data.get("step") == "Complete":
    final_answer = data.get("response") or data.get("answer", "")
    final_references = data.get("references", [])
    final_session_id = data.get("session_id")
    final_invocation_id = data.get("invocation_id")  # NEW
    # ...
```

Pass it to `save_exchange()`:

```python
history, _ = service.save_exchange(
    user_id=user_id,
    history_id=request.history_id,
    prompt_content=request.question,
    answer_content=final_answer,
    references=final_references,
    invocation_id=final_invocation_id,   # NEW
    session_id=final_session_id,         # NEW
)
```

Include it in the `Saved` event so the frontend has it:

```python
yield f"data: {json.dumps({
    'step': 'Saved',
    'history_id': history.hid,
    'session_id': final_session_id,
    'invocation_id': final_invocation_id,  # NEW
    # ...
})}\n\n"
```

### 7. Add `POST /rewind` endpoint

**File:** `app/api/v1/new_llm_agent.py`

```python
@router.post("/rewind")
async def rewind_chat(
    request: RewindChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Rewind a chat to before a given turn.

    1. Looks up the chat history to find the session_id and target pair_index
    2. Calls the agent service rewind endpoint
    3. Deletes messages from chat history at and after that pair
    4. Returns the updated message list

    Frontend flow:
      1. POST /rewind  { history_id, invocation_id }
      2. POST /stream   { question: "edited msg", history_id, session_id }
    """
    service = ChatHistoryService(db)
    history = service.get_history(user_id, request.history_id)

    if not history.session_id:
        raise HTTPException(400, "This chat has no active agent session to rewind")

    # Find the pair_index for this invocation_id
    target_msg = (
        db.query(ChatMessageRecord)
        .filter(
            ChatMessageRecord.history_id == history.hid,
            ChatMessageRecord.invocation_id == request.invocation_id,
        )
        .first()
    )
    if not target_msg:
        raise HTTPException(404, "Invocation not found in this chat history")

    # Call agent service rewind
    agent_url = get_agent_url()
    app_name = "glkb"
    agent_user_id = "stream_user"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{agent_url}/apps/{app_name}/users/{agent_user_id}"
            f"/sessions/{history.session_id}/rewind",
            json={"invocation_id": request.invocation_id},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Agent rewind failed: {resp.text}")

    # Delete messages from backend DB
    service.rewind_to_pair(user_id, history.hid, target_msg.pair_index)

    # Return updated history
    updated = service.get_history(user_id, history.hid)
    return {
        "history_id": updated.hid,
        "session_id": history.session_id,
        "remaining_message_count": len(updated.messages),
        "messages": [
            {
                "id": m.id,
                "pair_index": m.pair_index,
                "role": m.role,
                "content": m.content,
                "invocation_id": m.invocation_id,
                "references": json.loads(m.references_json) if m.references_json else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in updated.messages
        ],
    }
```

---

## Frontend usage

### Edit a previous message
1. User clicks edit on a message with `invocation_id: "e-abc123"`
2. `POST /api/v1/new-llm-agent/rewind` with `{ history_id: 42, invocation_id: "e-abc123" }`
3. Response returns truncated message list
4. `POST /api/v1/new-llm-agent/stream` with `{ question: "edited text", history_id: 42, session_id: "stream_xxx" }`
5. UI updates with new response

### Regenerate last answer
Same flow — use the `invocation_id` of the last turn, then re-send the same question.

---

## Summary of files to modify

| File | Change |
|------|--------|
| `app/db/models.py` | Add `invocation_id` to `ChatMessageRecord`, `session_id` to `ChatHistory` |
| `app/services/chat_history_service.py` | Update `save_exchange()`, add `rewind_to_pair()` |
| `app/schemas/chat_history.py` | Add `invocation_id` to `ChatMessageResponse` |
| `app/schemas/llm_agent.py` | Add `RewindChatRequest` |
| `app/api/v1/new_llm_agent.py` | Capture `invocation_id` in stream, add `POST /rewind` |
