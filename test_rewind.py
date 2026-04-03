"""
Quick test to verify ADK session rewind mechanics.
Uses a minimal echo agent with gpt-4o-mini.
"""

import asyncio
from dotenv import load_dotenv
load_dotenv("my_agent/.env")
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents import LlmAgent
from google.genai.types import Content, Part
from google.adk.models.lite_llm import LiteLlm

APP_NAME = "test-rewind"
USER_ID = "test-user"


async def main():
    # 1. Setup: minimal agent + in-memory session
    agent = LlmAgent(
        name="echo_agent",
        model=LiteLlm(model="openai/gpt-4o-mini"),
        instruction="You are a test agent. Reply with exactly: 'Echo: <user message>'",
    )
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID
    )
    runner = Runner(
        agent=agent, app_name=APP_NAME, session_service=session_service
    )

    print(f"Session ID: {session.id}")
    print("=" * 60)

    # 2. Send 3 messages, collect invocation IDs
    invocation_ids = []
    for i, msg in enumerate(["Hello", "What is TP53?", "Tell me about BRCA1"], 1):
        print(f"\n--- Turn {i}: '{msg}' ---")
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=Content(role="user", parts=[Part(text=msg)]),
        ):
            # Capture invocation_id from events
            if event.invocation_id and event.invocation_id not in invocation_ids:
                invocation_ids.append(event.invocation_id)
            # Print final text response
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        print(f"  Agent: {part.text[:100]}")

    # 3. Inspect session events before rewind
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"\n{'=' * 60}")
    print(f"Invocation IDs collected: {invocation_ids}")
    print(f"Total events before rewind: {len(session.events)}")
    for e in session.events:
        role = e.content.role if e.content else "?"
        text = ""
        if e.content and e.content.parts:
            for p in e.content.parts:
                if hasattr(p, "text") and p.text:
                    text = p.text[:60]
        print(f"  [{e.invocation_id}] {role}: {text}")

    # 4. Rewind to before turn 3 (BRCA1 question)
    rewind_target = invocation_ids[2]  # 3rd invocation
    print(f"\n{'=' * 60}")
    print(f"Rewinding before invocation: {rewind_target}")

    await runner.rewind_async(
        user_id=USER_ID,
        session_id=session.id,
        rewind_before_invocation_id=rewind_target,
    )

    # 5. Inspect session events after rewind
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"Total events after rewind: {len(session.events)}")
    for e in session.events:
        role = e.content.role if e.content else "?"
        text = ""
        if e.content and e.content.parts:
            for p in e.content.parts:
                if hasattr(p, "text") and p.text:
                    text = p.text[:60]
        print(f"  [{e.invocation_id}] {role}: {text}")

    # 6. Verify: send a new message after rewind (should work, agent has no memory of turn 3)
    print(f"\n{'=' * 60}")
    print("Sending new message after rewind...")
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=Content(role="user", parts=[Part(text="What is MYC?")]),
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    print(f"  Agent: {part.text[:100]}")

    # 7. Final event count
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"\nFinal event count: {len(session.events)}")
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
