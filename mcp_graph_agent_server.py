from mcp.server.fastmcp import FastMCP
from typing import List, Dict, Optional
import os
import json
import dotenv

from graph_agent import GraphAgent
from cypher.text2cypher_agent import Text2CypherAgent
from driver.neo4j_driver import Neo4jDriver

dotenv.load_dotenv()

# Initialize the MCP server
mcp = FastMCP("GLKB Graph Agent MCP Server")

# Initialize GraphAgent using environment variables
# Required env vars: NEO4J_URI, NEO4J_USER (or NEO4J_USERNAME), NEO4J_PASSWORD
_neo4j_uri = os.environ.get("URI")
_neo4j_user = os.environ.get("AUTH_USER")
_neo4j_password = os.environ.get("AUTH_PASSWORD")

if not _neo4j_uri or not _neo4j_user or not _neo4j_password:
    raise RuntimeError(
        "Missing Neo4j configuration. Please set NEO4J_URI, NEO4J_USER (or NEO4J_USERNAME), and NEO4J_PASSWORD."
    )

_agent = GraphAgent(uri=_neo4j_uri, user=_neo4j_user, password=_neo4j_password)
text2cypher_agent = Text2CypherAgent(formatted_output=True)
neo4j_driver = Neo4jDriver(uri=_neo4j_uri, user=_neo4j_user, password=_neo4j_password)

@mcp.tool()
async def graph_search(
    query: str,
    limit: int = 10,
    center_node_uuid: Optional[str] = None
) -> Dict:
    """Search GLKB for relevant literature evidence using hybrid retrieval.

    Args:
        query: A few keywords to search for. (e.g., "diabetes gene variant")
        limit: Maximum number of results to return
        center_node_uuid: Optional node UUID to bias search by proximity

    Returns:
        A dictionary with keys: edges, articles, sentences
    """
    edges, articles, sentences = await _agent.search(
        query=query,
        center_node_uuid=center_node_uuid,
        group_ids=None,
        num_results=limit,
        search_filter=None,
    )
    formatted_edges = []
    formatted_articles = []
    formatted_sentences = []

    unique_edges = set()
    for edge in edges:
        if edge.get('summary') in unique_edges:
            continue
        unique_edges.add(edge.get('summary'))
        formatted_edges.append({
            "summary": edge['summary'],
            "pubmedids": edge['pubmedids'],
            "relationship": edge['relationship'],
        })
    for article in articles:
        formatted_articles.append({
            "title": article['title'],
            "pubmedid": article['pubmedid'],
            "abstract": article['abstract'],
        })
    for sentence in sentences:
        formatted_sentences.append({
            "text": sentence['text'],
            "pubmedid": sentence['id'].split('_')[0][4:],
        })
    return {"edges": formatted_edges, "articles": formatted_articles, "sentences": formatted_sentences}

@mcp.tool()
async def run_cypher_query(
    query: str
) -> Dict:
    """Run a Cypher query on the GLKB graph.
    
    Args:
        query: A Cypher query to run on the GLKB graph.

    Returns:
        A dictionary with keys: cypher, result
        cypher: The Cypher query that was run.
        result: Result dictionary from the Cypher query.
    """
    print("CYPHER_QUERY_START", {
        "query": query,
        "query_length": len(query)
    })
    
    try:
        # Step 1: Convert text to Cypher using Text2CypherAgent
        print("TEXT2CYPHER_START", {
            "query": query,
            "formatted_output": True
        })
        
        result = text2cypher_agent.respond(query)
        
        print("TEXT2CYPHER_RESULT", {
            "query": query,
            "result": result,
            "result_type": type(result).__name__
        })
        
        # Step 2: Extract Cypher query from result
        if isinstance(result, str):
            try:
                result_dict = json.loads(result)
            except json.JSONDecodeError as json_err:
                print("TEXT2CYPHER_JSON_PARSE_ERROR", {
                    "query": query,
                    "raw_result": result,
                    "error": str(json_err)
                }, error=json_err)
                return {"cypher": "", "result": f"Error: Failed to parse Text2Cypher response as JSON: {json_err}"}
        else:
            result_dict = result
            
        cypher = result_dict.get("cypher_query", '') if isinstance(result_dict, dict) else ''
        
        print("CYPHER_QUERY_EXTRACTED", {
            "cypher": cypher,
            "cypher_length": len(cypher),
            "in_scope": result_dict.get("in_scope", "unknown") if isinstance(result_dict, dict) else "unknown"
        })
        
        # Step 3: Check if query is in scope
        if len(cypher) == 0:
            print("CYPHER_QUERY_OUT_OF_SCOPE", {
                "query": query,
                "cypher": cypher,
                "in_scope": result_dict.get("in_scope", "unknown") if isinstance(result_dict, dict) else "unknown"
            })
            return {"cypher": cypher, "result": "Error: Query is out of scope"}
        
        # Step 4: Execute Cypher query on Neo4j
        print("NEO4J_QUERY_START", {
            "cypher": cypher,
            "cypher_length": len(cypher)
        })
        
        try:
            records, summary, keys = await neo4j_driver.execute_query(cypher)
            
            print("NEO4J_QUERY_SUCCESS", {
                "cypher": cypher,
                "record_count": len(records),
                "keys": keys,
                "summary": {
                    "result_available_after": summary.result_available_after,
                    "result_consumed_after": summary.result_consumed_after,
                    "query_type": summary.query_type,
                    "query_text": summary.query,
                    "parameters": summary.parameters
                } if summary else None
            })
            
            # Convert records to dictionaries
            result_list = [dict(record) for record in records]
            
            print("CYPHER_QUERY_COMPLETE", {
                "query": query,
                "cypher": cypher,
                "result_count": len(result_list),
                "success": True
            })
            
            return {"cypher": cypher, "result": result_list}
            
        except Exception as neo4j_error:
            print("NEO4J_QUERY_ERROR", {
                "cypher": cypher,
                "query": query,
                "error_type": type(neo4j_error).__name__,
                "error_message": str(neo4j_error)
            }, error=neo4j_error)
            
            return {"cypher": cypher, "result": f"Error executing Neo4j query: {neo4j_error}"}
            
    except Exception as e:
        print("CYPHER_QUERY_GENERAL_ERROR", {
            "query": query,
            "error_type": type(e).__name__,
            "error_message": str(e)
        }, error=e)
        
        return {"cypher": "", "result": f"Error: {e}"}

@mcp.tool()
async def vocabulary_search(
    query: str,
    limit: int = 10,
    center_node_uuid: Optional[str] = None
) -> List[Dict]:
    """Search GLKB vocabulary terms by names, definitions, and synonyms. 

    Args:
        query: a biomedical term to search for
        limit: Maximum number of results
        center_node_uuid: Optional node UUID to bias search by proximity

    Returns:
        A list of vocabulary node dicts
    """
    results = await _agent.search_vocabulary(
        query=query,
        center_node_uuid=center_node_uuid,
        group_ids=None,
        num_results=limit,
        search_filter=None,
    )
    formatted_results = []
    for result in results:
        formatted_results.append({
            "id": result['id'],
            "name": result['name'],
            "description": result['description'],
            "labels": result['labels'],
            "n_citation": result.get('n_citation', 0),
        })
    return formatted_results


@mcp.tool()
async def get_article_by_id(id: str) -> Dict:
    """Fetch an article by its internal id."""
    article = await _agent.get_article_by_id(id)
    return dict(article)

@mcp.tool()
async def get_article_by_pubmed_id(pubmed_id: str) -> Dict:
    """Fetch an article by its pubmed id."""
    article = await _agent.get_article_by_pubmed_id(pubmed_id)
    return dict(article)


@mcp.tool()
async def get_sentence_by_id(id: str) -> Dict:
    """Fetch a sentence by its internal id."""
    sentence = await _agent.get_sentence_by_id(id)
    return dict(sentence)


@mcp.tool()
async def get_vocabulary_by_id(id: str) -> Dict:
    """Fetch a vocabulary node by its internal id."""
    vocab = await _agent.get_vocabulary_by_id(id)
    return dict(vocab)


# Execute the server
if __name__ == "__main__":
    mcp.run(transport="stdio") 