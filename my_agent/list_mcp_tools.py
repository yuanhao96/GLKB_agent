"""List available tools from Neo4j MCP server."""
import asyncio
from tools import neo4j_toolset

async def list_tools():
    print("Loading MCP tools...")
    tools = await neo4j_toolset.load_tools()
    print(f"\n=== Available MCP Tools ({len(tools)}) ===")
    for tool in tools:
        name = getattr(tool, 'name', getattr(tool, '_name', str(tool)))
        desc = getattr(tool, 'description', '')[:100] if hasattr(tool, 'description') else ''
        print(f"  - {name}")
        if desc:
            print(f"    {desc}")
    return tools

if __name__ == "__main__":
    asyncio.run(list_tools())
