from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from agent import root_agent
from loguru import logger
import sys
import asyncio
import argparse
from typing import Iterable

# Configure loguru
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[agent]}</cyan> | {message}",
    level="DEBUG"
)
logger.add(
    "agent_logs/{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[agent]} | {message}",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)

# Session and Runner
APP_NAME = "summary_agent"
USER_ID = "user1234"
SESSION_ID = "1234"


async def setup_session_and_runner():
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
    logger.bind(agent="system").info(f"Session created: app={APP_NAME}, user={USER_ID}, session={SESSION_ID}")
    return session, runner


def get_event_details(event, verbose=False):
    """Extract detailed information from an event."""
    agent_name = getattr(event, 'author', None) or getattr(event, 'agent_name', 'unknown')
    is_final = event.is_final_response()
    
    content_info = {"type": "empty", "details": None, "full_response": None}
    if event.content and event.content.parts:
        part = event.content.parts[0]
        if hasattr(part, 'text') and part.text:
            content_info = {
                "type": "text", 
                "details": part.text[:100] + "..." if len(part.text) > 100 else part.text,
                "full_response": part.text
            }
        elif hasattr(part, 'function_call') and part.function_call:
            args_str = str(part.function_call.args)[:200] if verbose else ""
            content_info = {
                "type": "function_call", 
                "details": part.function_call.name,
                "args": args_str,
                "full_response": None
            }
        elif hasattr(part, 'function_response') and part.function_response:
            response = part.function_response.response
            # Extract meaningful info from response
            response_preview = ""
            if isinstance(response, dict):
                if 'error' in response:
                    response_preview = f"ERROR: {response['error'][:100]}"
                elif 'result' in response:
                    response_preview = str(response['result'])[:150]
                elif 'abstract' in response:
                    response_preview = f"Abstract: {response['abstract'][:100]}..."
                elif 'sections' in response:
                    response_preview = f"Sections: {list(response.get('available_sections', []))}"
            content_info = {
                "type": "function_response", 
                "details": part.function_response.name,
                "response_preview": response_preview,
                "full_response": response
            }
    
    return agent_name, is_final, content_info


async def call_agent_async(query: str, verbose: bool = False):
    """
    Call the agent with a query and stream all events.
    Set verbose=True to see detailed sub-agent activity.
    """
    log = logger.bind(agent="user")
    log.info(f"Query: {query[:80]}..." if len(query) > 80 else f"Query: {query}")
    
    content = types.Content(role='user', parts=[types.Part(text=query)])
    session, runner = await setup_session_and_runner()
    events = runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=content)

    final_response = None
    event_count = 0
    
    try:
        async for event in events:
            event_count += 1
            agent_name, is_final, content_info = get_event_details(event, verbose=verbose)
            log = logger.bind(agent=agent_name)

            # Reduced logging unless verbose=True
            if verbose:
                if content_info["type"] == "function_call":
                    log.info(f"→ Calling: {content_info['details']}")
                    if content_info.get("args"):
                        log.debug(f"  Args: {content_info['args']}")
                elif content_info["type"] == "function_response":
                    response_preview = content_info.get("response_preview", "")
                    if "ERROR" in response_preview:
                        log.error(f"← {content_info['details']}: {response_preview}")
                    else:
                        log.success(f"← {content_info['details']}: {response_preview[:100]}")
                elif content_info["type"] == "text":
                    log.info(f"💬 {content_info['details']}")
                else:
                    log.debug(f"Event #{event_count}: {content_info['type']}")
            else:
                if content_info["type"] == "function_response":
                    response_preview = content_info.get("response_preview", "")
                    if "ERROR" in response_preview:
                        log.error(f"← {content_info['details']}: {response_preview}")

            if is_final:
                log.info("✓ Final response received")
                if event.content and event.content.parts:
                    part = event.content.parts[0]
                    if hasattr(part, 'text') and part.text:
                        final_response = part.text
                    elif hasattr(part, 'function_response') and part.function_response:
                        response = part.function_response.response
                        if isinstance(response, dict) and 'result' in response:
                            final_response = response['result']
                break
    except BaseExceptionGroup as exc_group:
        # Allow TaskGroup/GeneratorExit noise to be swallowed while preserving any final_response captured
        if _is_only_generator_exit(exc_group):
            logger.bind(agent="system").warning("Ignored GeneratorExit during shutdown")
        else:
            raise
    
    log = logger.bind(agent="system")
    log.info(f"Total events: {event_count}")
    
    if final_response:
        log.success(f"Response: {final_response}")
        return final_response
    else:
        log.error("No response received")
        return None

def _is_only_generator_exit(exc_group: BaseExceptionGroup) -> bool:
    """Return True if the exception group (recursively) only contains GeneratorExit."""
    def _iter_excs(group: BaseExceptionGroup) -> Iterable[BaseException]:
        for exc in group.exceptions:
            if isinstance(exc, BaseExceptionGroup):
                yield from _iter_excs(exc)
            else:
                yield exc

    return all(isinstance(exc, GeneratorExit) for exc in _iter_excs(exc_group))


if __name__ == "__main__":
    logger.bind(agent="system").info("Starting agent...")
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    args = parser.parse_args()
    # try:
    result = asyncio.run(call_agent_async(args.query))
    # except BaseExceptionGroup as exc_group:
    #     if _is_only_generator_exit(exc_group):
    #         logger.bind(agent="system").warning("Ignored GeneratorExit during shutdown")
    #         result = None
    #     else:
    #         raise
    logger.bind(agent="system").info("Agent finished")