import asyncio
import json
import os
import sys
import time
from pathlib import Path
from mcp_agent.app import MCPApp
from mcp_agent.agents.agent import Agent
from mcp_agent.workflows.llm.augmented_llm import RequestParams
from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM, OpenAISettings
from mcp_agent.workflows.router.router_llm_openai import OpenAILLMRouter
from mcp_agent.workflows.factory import (
    AgentSpec,
    load_agent_specs_from_file,
    create_llm,
    create_router_llm,
    # create_parallel_llm,
    # create_evaluator_optimizer_llm,
)
from mcp_agent.mcp.mcp_server_registry import MCPServerSettings
# from agent_state import get_agent_state
from dotenv import load_dotenv
from prompts import RAG_PROMPT, CYPHER_PROMPT, ROUTING_PROMPT, GENERAL_PROMPT, COMBINED_PROMPT
from logger import get_logger

load_dotenv()

async def main():
    # Initialize logger
    logger = get_logger()
    logger.enable()
    
    logger.log_step_start("CHATBOT_INITIALIZATION", {
        "message": "Starting GLKB chatbot",
        "version": "1.0.0"
    })
    
    try:
        # Initialize MCP App
        logger.log_step_start("MCP_APP_INITIALIZATION", {
            "app_name": "glkb_chatbot"
        })
        
        app_start_time = time.time()
        app = MCPApp(name="glkb_chatbot")
        await app.initialize()
        app_duration = time.time() - app_start_time
        
        logger.log_step_end("MCP_APP_INITIALIZATION", {
            "app_name": "glkb_chatbot",
            "status": "success"
        }, duration=app_duration, success=True)
        
    except Exception as e:
        logger.error("MCP_APP_INITIALIZATION", {
            "app_name": "glkb_chatbot",
            "error": "Failed to initialize MCP app"
        }, error=e)
        raise

    # Load MCP servers from env JSON or local file
    logger.log_step_start("MCP_SERVER_LOADING", {
        "message": "Loading MCP server configurations"
    })
    
    server_names: list[str] = []
    cfg_path = Path("/var/www/glkb/neo4j_agent/chatbot/mcpServers.json")
    
    logger.debug("MCP_CONFIG_PATH", {
        "config_path": str(cfg_path),
        "exists": cfg_path.exists()
    })
    
    cfg_obj = None
    if cfg_path.exists():
        try:
            config_start_time = time.time()
            cfg_obj = json.loads(cfg_path.read_text())
            config_duration = time.time() - config_start_time
            
            logger.info("MCP_CONFIG_LOADED", {
                "source": "file",
                "config_size_bytes": len(cfg_path.read_text()),
                "parse_duration": config_duration
            })
        except Exception as e:
            logger.error("MCP_CONFIG_PARSE_ERROR", {
                "source": "file",
                "config_path": str(cfg_path)
            }, error=e)
            cfg_obj = None
    else:
        logger.warning("MCP_CONFIG_NOT_FOUND", {
            "config_path": str(cfg_path),
            "message": "Using default empty configuration"
        })

    # Support either root mapping or nested under "mcpServers"
    servers_cfg = None
    if isinstance(cfg_obj, dict):
        servers_cfg = cfg_obj.get("mcpServers") if "mcpServers" in cfg_obj else cfg_obj
        logger.debug("MCP_CONFIG_STRUCTURE", {
            "has_mcpServers_key": "mcpServers" in cfg_obj,
            "config_type": "nested" if "mcpServers" in cfg_obj else "flat"
        })

    if isinstance(servers_cfg, dict):
        logger.info("MCP_SERVERS_PROCESSING", {
            "total_servers_in_config": len(servers_cfg),
            "server_names": list(servers_cfg.keys())
        })
        
        for name, entry in servers_cfg.items():
            if not isinstance(entry, dict):
                logger.warning("MCP_SERVER_SKIPPED", {
                    "server_name": name,
                    "reason": "Invalid entry format",
                    "entry_type": type(entry).__name__
                })
                continue
                
            command = entry.get("command")
            args = entry.get("args", [])
            transport = entry.get("transport", "stdio")
            url = entry.get("url")
            headers = entry.get("headers")
            env_vars = entry.get("env")

            try:
                settings = MCPServerSettings(
                    name=name,
                    transport=transport,
                    command=command,
                    args=args,
                    url=url,
                    headers=headers,
                    env=env_vars,
                )
                app.server_registry.registry[name] = settings
                server_names.append(name)
                
                logger.info("MCP_SERVER_ADDED", {
                    "server_name": name,
                    "transport": transport,
                    "command": command,
                    "args": args,
                    "has_url": url is not None,
                    "has_headers": headers is not None,
                    "has_env_vars": env_vars is not None
                })
            except Exception as e:
                logger.error("MCP_SERVER_ADD_ERROR", {
                    "server_name": name,
                    "transport": transport,
                    "command": command
                }, error=e)
    else:
        logger.warning("MCP_SERVERS_CONFIG_INVALID", {
            "config_type": type(servers_cfg).__name__,
            "message": "No valid server configuration found"
        })
    
    logger.log_step_end("MCP_SERVER_LOADING", {
        "total_servers_loaded": len(server_names),
        "server_names": server_names,
        "success": len(server_names) > 0
    }, success=len(server_names) > 0)

    # Get OpenAI configuration
    logger.log_step_start("OPENAI_CONFIGURATION", {
        "message": "Configuring OpenAI settings"
    })
    
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_API_MODEL", "gpt-4o-mini")

    if not api_key:
        error_msg = "Missing OPENAI_API_KEY environment variable. Set it and retry."
        logger.critical("OPENAI_CONFIG_ERROR", {
            "error": "missing_api_key",
            "message": error_msg,
            "model": model
        })
        print(error_msg)
        sys.exit(1)

    # Configure OpenAI settings
    try:
        openai_settings = OpenAISettings(
            api_key=api_key,
            default_model=model,
        )
        
        logger.log_step_end("OPENAI_CONFIGURATION", {
            "model": model,
            "api_key_exists": bool(api_key),
            "api_key_length": len(api_key) if api_key else 0
        }, success=True)
        
    except Exception as e:
        logger.error("OPENAI_CONFIGURATION_ERROR", {
            "model": model,
            "api_key_exists": bool(api_key)
        }, error=e)
        raise
    # Create LLM and agents
    logger.log_step_start("AGENT_CREATION", {
        "message": "Creating LLM and agent instances",
        "total_agents": 4
    })
    
    agents_created = []
    
    try:
        # 1) Create main LLM using factory function
        logger.log_step_start("MAIN_LLM_CREATION", {
            "agent_name": "main_llm",
            "provider": "openai",
            "model": model
        })
        
        llm_start_time = time.time()
        llm = create_llm(
            agent_name="main_llm",
            provider="openai",
            model=model,
            request_params=RequestParams(
                model=model,
            ),
        )
        llm_duration = time.time() - llm_start_time
        
        logger.log_step_end("MAIN_LLM_CREATION", {
            "agent_name": "main_llm",
            "status": "success"
        }, duration=llm_duration, success=True)
        agents_created.append("main_llm")

        # # 2) Create combined agent
        # logger.log_step_start("COMBINED_AGENT_CREATION", {
        #     "agent_name": "combined_agent",
        #     "provider": "openai",
        #     "model": model,
        #     "has_instruction": bool(COMBINED_PROMPT)
        # })
        
        # combined_agent_start_time = time.time()
        # combined_agent = create_llm(
        #     agent_name="combined_agent",
        #     instruction=COMBINED_PROMPT,
        #     server_names=server_names,
        #     provider="openai",
        #     model=model,
        #     request_params=RequestParams(
        #         model=model,
        #     ),
        # )
        # combined_agent_duration = time.time() - combined_agent_start_time

        # logger.log_step_end("COMBINED_AGENT_CREATION", {
        #     "agent_name": "combined_agent",
        #     "status": "success"
        # }, duration=combined_agent_duration, success=True)
        # agents_created.append("combined_agent")

        # 2) Create graph query agent
        logger.log_step_start("GRAPH_QUERY_AGENT_CREATION", {
            "agent_name": "graph_query_agent",
            "provider": "openai",
            "model": model,
            "has_instruction": bool(CYPHER_PROMPT),
            "server_count": len(server_names)
        })
        
        graph_agent_start_time = time.time()
        graph_query_agent = create_llm(
            agent_name="graph_query_agent",
            instruction=CYPHER_PROMPT,
            server_names=server_names,
            provider="openai",
            model=model,
            request_params=RequestParams(
                model=model,
            ),
        )
        graph_agent_duration = time.time() - graph_agent_start_time
        
        logger.log_step_end("GRAPH_QUERY_AGENT_CREATION", {
            "agent_name": "graph_query_agent",
            "status": "success"
        }, duration=graph_agent_duration, success=True)
        agents_created.append("graph_query_agent")

        # 3) Create general agent
        logger.log_step_start("GENERAL_AGENT_CREATION", {
            "agent_name": "general_agent",
            "provider": "openai",
            "model": model,
            "has_instruction": bool(GENERAL_PROMPT)
        })
        
        general_agent_start_time = time.time()
        general_agent = create_llm(
            agent_name="general_agent",
            instruction=GENERAL_PROMPT,
            server_names=server_names,
            provider="openai",
            model=model,
            request_params=RequestParams(
                model=model,
            ),
        )
        general_agent_duration = time.time() - general_agent_start_time
        
        logger.log_step_end("GENERAL_AGENT_CREATION", {
            "agent_name": "general_agent",
            "status": "success"
        }, duration=general_agent_duration, success=True)
        agents_created.append("general_agent")

        # 4) Create RAG agent
        logger.log_step_start("RAG_AGENT_CREATION", {
            "agent_name": "rag_agent",
            "provider": "openai",
            "model": model,
            "has_instruction": bool(RAG_PROMPT),
            "server_count": len(server_names)
        })
        
        rag_agent_start_time = time.time()
        rag_agent = create_llm(
            agent_name="rag_agent",
            instruction=RAG_PROMPT,
            server_names=server_names,
            provider="openai",
            model=model,
            request_params=RequestParams(
                model=model,
            ),
        )
        rag_agent_duration = time.time() - rag_agent_start_time
        
        logger.log_step_end("RAG_AGENT_CREATION", {
            "agent_name": "rag_agent",
            "status": "success"
        }, duration=rag_agent_duration, success=True)
        agents_created.append("rag_agent")

        # 5) Create routing agent
        logger.log_step_start("ROUTING_AGENT_CREATION", {
            "agent_name": "routing_agent",
            "provider": "openai",
            "model": model,
            "source_agents": ["rag_agent", "graph_query_agent", "general_agent"]
        })
        
        routing_agent_start_time = time.time()
        routing_agent = create_llm(
            agent_name="routing_agent",
            instruction=ROUTING_PROMPT,
            provider="openai",
            model=model,
            request_params=RequestParams(
                model=model,
            ),
        )
        routing_agent_duration = time.time() - routing_agent_start_time
        
        logger.log_step_end("ROUTING_AGENT_CREATION", {
            "agent_name": "routing_agent",
            "status": "success"
        }, duration=routing_agent_duration, success=True)
        agents_created.append("routing_agent")

        logger.log_step_end("AGENT_CREATION", {
            "total_agents_created": len(agents_created),
            "agent_names": agents_created,
            "status": "success"
        }, success=True)
        
    except Exception as e:
        logger.error("AGENT_CREATION_ERROR", {
            "agents_created": agents_created,
            "total_attempted": 5
        }, error=e)
        raise

    print("Simple CLI Chatbot. Type 'exit' or 'quit' to end.")
    logger.log_step_end("CHATBOT_INITIALIZATION", {
        "message": "Chatbot is ready for user input",
        "model": model,
        "total_agents": len(agents_created),
        "server_count": len(server_names)
    }, success=True)
    
    # Chat loop statistics
    conversation_stats = {
        "total_messages": 0,
        "successful_responses": 0,
        "failed_responses": 0,
        "total_response_time": 0.0
    }
    
    chat_history = []
    routing_agent.history.clear()
    graph_query_agent.history.clear()
    general_agent.history.clear()
    rag_agent.history.clear()

    routing_agent.history.extend(
        [
            {"role": "system", "content": routing_agent.instruction},
        ]
    )
    graph_query_agent.history.extend(
        [
            {"role": "system", "content": graph_query_agent.instruction},
        ]
    )
    general_agent.history.extend(
        [
            {"role": "system", "content": general_agent.instruction},
        ]
    )
    rag_agent.history.extend(
        [
            {"role": "system", "content": rag_agent.instruction},
        ]
    )

    
    while True:
        try:
            prompt = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            logger.warning("CHATBOT_INTERRUPT", {
                "interrupt_type": "keyboard_interrupt",
                "message": "User interrupted the chatbot",
                "conversation_stats": conversation_stats
            })
            print()
            break

        if not prompt:
            logger.debug("EMPTY_INPUT", {
                "message": "User provided empty input, skipping"
            })
            continue

        if prompt.lower() in ("exit", "quit"):
            logger.info("CHATBOT_EXIT", {
                "exit_command": prompt.lower(),
                "message": "User requested to exit",
                "conversation_stats": conversation_stats
            })
            break

        conversation_stats["total_messages"] += 1
        
        logger.info("USER_INPUT", {
            "prompt": prompt,
            "prompt_length": len(prompt),
            "message_number": conversation_stats["total_messages"]
        })

        try:
            # Use the routing agent to generate a response
            logger.debug("ROUTER_REQUEST_START", {
                "prompt": prompt,
                "model": model,
                "use_history": True
            })
            
            response_start_time = time.time()
            result = await routing_agent.generate(
                message=prompt,
                request_params=RequestParams(
                    use_history=True,
                    model=model,
                ),
            )
            resulting_workflow = result[-1].content

            if resulting_workflow == "graph_query_agent":
                result = await graph_query_agent.generate(
                    message=prompt,
                    request_params=RequestParams(
                        use_history=True,
                        model=model,
                    ),
                )
            elif resulting_workflow == "rag_agent":
                result = await rag_agent.generate(
                    message=prompt,
                    request_params=RequestParams(
                        use_history=True,
                        model=model,
                    ),
                )
            else:
                result = await general_agent.generate(
                    message=prompt,
                    request_params=RequestParams(
                        use_history=True,
                        model=model,
                    ),
                )
            chat_history.append({"role": "user", "content": prompt})
            chat_history.append({"role": "assistant", "content": result[-1].content})

            routing_agent.history.clear()
            graph_query_agent.history.clear()
            general_agent.history.clear()
            rag_agent.history.clear()

            routing_agent.history.extend(chat_history)
            graph_query_agent.history.extend(chat_history)
            general_agent.history.extend(chat_history)
            rag_agent.history.extend(chat_history)

            response_duration = time.time() - response_start_time
            
            conversation_stats["total_response_time"] += response_duration
            
            logger.info("ROUTER_RESPONSE_SUCCESS", {
                "response_length": len(result) if result else 0,
                "model": model,
                "response_duration": response_duration,
                "message_number": conversation_stats["total_messages"]
            })
            
            conversation_stats["successful_responses"] += 1
            
        except Exception as e:
            conversation_stats["failed_responses"] += 1
            
            logger.error("LLM_RESPONSE_ERROR", {
                "prompt": prompt,
                "prompt_length": len(prompt),
                "message_number": conversation_stats["total_messages"],
                "error_type": type(e).__name__
            }, error=e)
            
            print(f"Error: {e}")
            continue

        # Find the message with actual content (not tool calls)
        if result and len(result) > 0:
            response_content = result[-1].content
            print(response_content)
            
            logger.debug("RESPONSE_CONTENT", {
                "content_length": len(response_content),
                "content_preview": response_content[:100] + "..." if len(response_content) > 100 else response_content,
                "message_number": conversation_stats["total_messages"]
            })
        else:
            print("No result available")
            logger.warning("EMPTY_RESPONSE", {
                "message_number": conversation_stats["total_messages"],
                "result_length": len(result) if result else 0
            })
    
    # Calculate final statistics
    avg_response_time = conversation_stats["total_response_time"] / max(conversation_stats["successful_responses"], 1)
    success_rate = conversation_stats["successful_responses"] / max(conversation_stats["total_messages"], 1) * 100
    
    logger.log_step_end("CHATBOT_SHUTDOWN", {
        "message": "Chatbot shutting down",
        "conversation_stats": conversation_stats,
        "average_response_time": avg_response_time,
        "success_rate_percent": success_rate
    }, success=True)


if __name__ == "__main__":
    asyncio.run(main())