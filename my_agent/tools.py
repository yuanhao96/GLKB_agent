"""
REST API Tools for PubMed/PMC Article Retrieval and Neo4j Knowledge Graph

Uses the BioC API for PMC Open Access:
https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/

Citation: Comeau DC, Wei CH, Islamaj Doğan R, and Lu Z. 
PMC text mining subset in BioC: about 3 million full text articles and growing, 
Bioinformatics, btz070, 2019.
"""

import httpx
import logging
import os
import functools
import json
from typing import Literal, Optional, List

from dotenv import load_dotenv
from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters, StdioConnectionParams
from neo4j import GraphDatabase, READ_ACCESS
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)

# -----------------------------------------
# Logging Decorator for Tools
# -----------------------------------------

def log_tool_call(func):
    """Decorator to log tool inputs and outputs."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        # Format input parameters
        input_params = {}
        if args:
            input_params["args"] = [str(a)[:200] for a in args]
        if kwargs:
            input_params["kwargs"] = {k: str(v)[:200] for k, v in kwargs.items()}
        
        logger.info(f"[TOOL CALL] {tool_name} | Input: {json.dumps(input_params, default=str)}")
        
        try:
            result = await func(*args, **kwargs)
            # Truncate result for logging
            result_str = json.dumps(result, default=str)
            if len(result_str) > 1000:
                result_str = result_str[:1000] + "... [truncated]"
            logger.info(f"[TOOL RESULT] {tool_name} | Output: {result_str}")
            return result
        except Exception as e:
            logger.error(f"[TOOL ERROR] {tool_name} | Error: {str(e)}")
            raise
    return wrapper

def get_neo4j_driver():
    """Get a Neo4j driver instance."""
    return GraphDatabase.driver(os.getenv("NEO4J_URI"), auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")))

def run_cypher_query(query: str, parameters: dict = None) -> list:
    """Execute a Cypher query and return results as a list of dicts."""
    driver = get_neo4j_driver()
    try:
        with driver.session(database=os.getenv("NEO4J_DATABASE"), default_access_mode=READ_ACCESS) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
    finally:
        driver.close()

@log_tool_call
async def get_database_schema() -> str:
    """
    Get the database schema.
    """
    schema = """Database Schema:
Available Node Labels:
1. Article: {{pubmedid: STRING, title: STRING, pubdate: INTEGER (YYYY), authors: LIST, journal: STRING, source: STRING, id: STRING, preferred_id: STRING, embedding: LIST, n_citation: INTEGER, doi: STRING, abstract: STRING, author_affiliations: LIST}}
2. Journal {{title: STRING, med_abbrevation: STRING, iso_abbrevation: STRING, issn_print: STRING, issn_online: STRING, jrid: STRING, id: STRING, impact_factor: FLOAT, preferred_id: STRING}}
3. Vocabulary
- Subtypes of Vocabulary that connect to Article:
  - Gene: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, rsid: STRING, ref: STRING, alt: STRING, source: STRING}}
  - DiseaseOrPhenotypicFeature: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, rsid: STRING, ref: STRING, alt: STRING, source: STRING}}
  - ChemicalEntity: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, rsid: STRING, ref: STRING, alt: STRING, source: STRING}}
  - SequenceVariant: {{id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, rsid: STRING, ref: STRING, alt: STRING, source: STRING}}
  - MeshTerm: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, rsid: STRING, ref: STRING, alt: STRING, source: STRING}}
  - AnatomicalEntity: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, rsid: STRING, ref: STRING, alt: STRING, source: STRING}}
- Subtypes of Vocabulary that connect only to other Vocabulary:
  - Pathway: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, source: STRING}}
  - BiologicalProcess: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, source: STRING}}
  - CellularComponent: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, source: STRING}}
  - MolecularFunction: {{name: STRING, id: STRING, preferred_id: STRING, n_citation: INTEGER, description: STRING, synonyms: LIST, embedding: LIST, source: STRING}}

Relationships:
- Article to Journal:
  - PublishedIn (no properties)
- Article to Vocabulary:
  - ContainTerm: source (STRING), normalized_name (STRING), type (STRING), prob (FLOAT)
- Article to Article:
  - Cite: source (STRING)
- Article to Sentence:
  - ContainSentence (no properties)
- Vocabulary to Vocabulary (Associations):
  - Vocabulary -> Vocabulary: HierarchicalStructure: source, type
  - Vocabulary -> Vocabulary: OntologyMapping: source, score
  - Gene -> DiseaseOrPhenotypicFeature: GeneToDiseaseAssociation: source, type
  - DiseaseOrPhenotypicFeature -> DiseaseOrPhenotypicFeature: DiseaseToPhenotypicFeatureAssociation: source, type
  - ChemicalEntity -> DiseaseOrPhenotypicFeature: ChemicalOrDrugOrTreatmentToDiseaseOrPhenotypicFeatureAssociation: source, type
  - Gene -> Gene: GeneToGeneAssociation: source, type
  - Gene -> Vocabulary: GeneToExpressionSiteAssociation: source, type
  - Gene -> Pathway: GeneToPathwayAssociation: source, type
  - Gene -> BiologicalProcess | MolecularFunction | CellularComponent: GeneToGoTermAssociation: source, type
  - ChemicalEntity -> ChemicalEntity: ChemicalAffectsGeneAssociation: source, type
  - ChemicalEntity -> ChemicalEntity: ChemicalToChemicalAssociation: source, type
  - SequenceVariant -> Gene: VariantToGeneAssociation: source, type, risk allele
  - SequenceVariant -> DiseaseOrPhenotypicFeature: VariantToDiseaseAssociation: source, type, risk allele, from_article
  - Vocabulary -> Vocabulary: Cooccur: evidence (LIST), source, n_article"""
    return schema

@log_tool_call
async def article_search(
    keywords: Optional[List[str]] = None,
    pubmed_ids: Optional[List[str]] = None,
    limit: int = 20,
    prioritize_recent: bool = False
) -> dict:
    """
    Search for PubMed articles in the GLKB Neo4j knowledge graph using keywords or PubMed IDs.
    
    Args:
        keywords: a list of key words to search for
        pubmed_ids: a list of PubMed IDs to search for
        limit: Maximum number of results to return (default: 10)
        prioritize_recent: Whether to prioritize recent articles or to prioritize impactful articles. If True, recent articles will be prioritized. If False, impactful articles will be prioritized. Default is False.
    Returns:
        dict: Contains search results or error information
            - success: bool indicating if search was successful
            - count: number of results found
            - results: list of matching articles with their properties
            - error: error message (if unsuccessful)
    """
    try:
        if keywords and pubmed_ids:
            return {
                "success": False,
                "error": "Both keywords and PubMed IDs provided, please provide only one"
            }
        if keywords:
            if prioritize_recent:
                order_by = """ORDER BY 
    log(1 + 5 * score) +
    log(1 + a.n_citation) * exp(-0.05 * (date().year - a.pubdate)) +
    (0.5 * j.impact_factor) * exp(-0.20 * (date().year - a.pubdate)) +
    2.0 * exp(-0.10 * (date().year - a.pubdate))
DESC"""
            else:
                order_by = "order by log(1+5*score) + log(1+a.n_citation) + 0.5*j.impact_factor*exp(-0.15*date().year-a.pubdate) desc"
            # Build the Cypher query
            query = f"""
            CALL db.index.fulltext.queryNodes("article_Title", $keywords) YIELD node, score WITH node as a, score LIMIT 100
            WITH a, score
            MATCH (a)-[:PublishedIn]->(j:Journal)
            RETURN a.pubmedid as pubmedid, a.n_citation as n_citation, a.pubdate as pubdate, a.title as title, a.abstract as abstract, a.journal as journal, a.authors as authors, score as score
            {order_by} LIMIT $limit
            """
            params = {"keywords": ' '.join(keywords), "limit": limit}
            results = run_cypher_query(query, params)
            return {
                "success": True,
                "keywords": keywords,
                "count": len(results),
                "results": results
            }
        elif pubmed_ids:
            # Build the Cypher query
            query = f"""
            MATCH (a:Article) WHERE a.pubmedid IN $pubmed_ids RETURN a.pubmedid as pubmedid, a.n_citation as n_citation, a.pubdate as pubdate, a.title as title, a.abstract as abstract, a.journal as journal, a.authors as authors
            """
            params = {"pubmed_ids": pubmed_ids}
            results = run_cypher_query(query, params)
            return {
                "success": True,
                "pubmed_ids": pubmed_ids,
                "count": len(results),
                "results": results
            }
        else:
            return {
                "success": False,
                "error": "No keywords or PubMed IDs provided"
            }
    except Exception as e:
        return {
            "success": False,
            "keywords": keywords,
            "error": f"Failed to search articles: {str(e)}"
        }

@log_tool_call
async def vocabulary_search(name: str, limit: int = 5) -> dict:
    """
    Search for possibly matching vocabulary nodes in the GLKB Neo4j knowledge graph.
    
    Args:
        name: The name of the biological concept to search for
        limit: Maximum number of results to return (default: 5)
    """
    try:
        query = """
        CALL db.index.fulltext.queryNodes("vocabulary_Names", $name) YIELD node, score WITH node as n, score LIMIT 30 WHERE n.connected is not null RETURN n.id as id, n.name as name, n.n_citation as n_citation, n.description as description ORDER BY CASE WHEN n.n_citation IS NOT NULL THEN n.n_citation ELSE 0 END DESC
        """
        params = {"name": name}
        results = run_cypher_query(query, params)

        query = """
        MATCH (v:Vocabulary)-[:OntologyMapping]-(v2:Vocabulary) WHERE v.id IN $ids RETURN v2.id as id, v2.name as name, v2.n_citation as n_citation, v2.description as description ORDER BY CASE WHEN v2.n_citation IS NOT NULL THEN v2.n_citation ELSE 0 END DESC
        """
        params = {"ids": [result["id"] for result in results]}
        related_vocabulary = run_cypher_query(query, params)
        # remove duplicates
        for result in related_vocabulary:
            if result["id"] not in [result["id"] for result in results]:
                results.append(result)
        # order by n_citation descending
        results.sort(key=lambda x: x.get("n_citation", 0), reverse=True)
        return {
            "success": True,
            "name": name,
            "limit": limit,
            "related_vocabulary": results[:limit]
        }
    except Exception as e:
        return {
            "success": False,
            "name": name,
            "limit": limit,
            "error": f"Failed to search vocabulary: {str(e)}"
        }

# async def get_node_labels() -> dict:
#     """
#     Get all node labels in the GLKB database.
    
#     Returns:
#         dict: Contains list of node labels
#             - success: bool
#             - labels: list of label names
#             - error: error message (if unsuccessful)
#     """
#     log = logger.bind(agent="neo4j_tool")
    
#     try:
#         query = "CALL db.labels() YIELD label RETURN label"
#         results = run_cypher_query(query)
#         labels = [r["label"] for r in results]
        
#         log.success(f"Found {len(labels)} node labels")
#         return {
#             "success": True,
#             "count": len(labels),
#             "labels": labels
#         }
#     except Exception as e:
#         log.error(f"Error getting labels: {str(e)}")
#         return {
#             "success": False,
#             "error": f"Failed to get labels: {str(e)}"
#         }


@log_tool_call
async def execute_cypher(query: str) -> dict:
    """
    Execute a read-only Cypher query on the GLKB database.
    
    Args:
        query: A Cypher query string (read-only, no CREATE/DELETE/SET)
    
    Returns:
        dict: Query results
            - success: bool
            - count: number of records returned
            - results: list of result records
            - error: error message (if unsuccessful)
    
    Example queries:
        - "MATCH (a:Article) RETURN a.title, a.pubmedid LIMIT 5"
        - "MATCH (g:Gene)-[r]->(d:Disease) RETURN g.name, type(r), d.name LIMIT 10"
    """
    # Basic safety check - block write operations
    query_upper = query.upper()
    if any(word in query_upper for word in ["CREATE", "DELETE", "SET", "REMOVE", "MERGE", "DROP"]):
        return {
            "success": False,
            "error": "Write operations are not allowed. Only read queries (MATCH, RETURN) are permitted."
        }
    
    try:
        results = run_cypher_query(query)
        return {
            "success": True,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        return {
            "success": False,
            "query": query,
            "error": f"Query failed: {str(e)}"
        }


### NEO4J MCP TOOLSET (for agent-based access) ###
neo4j_toolset = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="/opt/neo4j/neo4j-mcp/neo4j-mcp",
            args=[
                "--neo4j-uri", os.getenv("NEO4J_URI"),
                "--neo4j-username", os.getenv("NEO4J_USER"),
                "--neo4j-password", os.getenv("NEO4J_PASSWORD"),
                "--neo4j-database", os.getenv("NEO4J_DATABASE"),
                "--neo4j-read-only", "true",
                "--neo4j-schema-sample-size", "20"
            ]
        )
    ),
    tool_filter=['get_neo4j_schema', 'read_neo4j_cypher']
)

# Create FunctionTools for Neo4j direct access
article_search_tool = FunctionTool(article_search)
vocabulary_search_tool = FunctionTool(vocabulary_search)
execute_cypher_tool = FunctionTool(execute_cypher)
get_database_schema_tool = FunctionTool(get_database_schema)

# Export glkb tools
glkb_tools = [
    get_database_schema_tool,
    article_search_tool,
    vocabulary_search_tool,
    # get_node_labels_tool,
    execute_cypher_tool,
]

### PUBMED TOOLS ###
# Base URL for the BioC PMC API
BIOC_PMC_BASE_URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"

@log_tool_call
async def fetch_pubmed_article(
    article_id: str,
    format: Literal["json", "xml"] = "json",
    encoding: Literal["unicode", "ascii"] = "unicode"
) -> dict:
    """
    Fetch a PubMed or PMC article in BioC format.
    
    This tool retrieves full-text articles from PubMed Central Open Access subset
    using the BioC API. Articles are returned in a structured format suitable for
    text mining and information retrieval.
    
    Args:
        article_id: The PubMed ID (e.g., "17299597") or PMC ID (e.g., "PMC1790863")
        format: Output format - "json" or "xml" (default: "json")
        encoding: Character encoding - "unicode" or "ascii" (default: "unicode")
    
    Returns:
        dict: Contains article data or error information
            - success: bool indicating if retrieval was successful
            - data: The article content (if successful)
            - error: Error message (if unsuccessful)
            - article_id: The requested article ID
            - format: The format used
    
    Note:
        Only articles in the PMC Open Access Subset and PMC Author Manuscript 
        Collection are available through this API.
    """
    # Construct the API URL
    url = f"{BIOC_PMC_BASE_URL}/BioC_{format}/{article_id}/{encoding}"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response_text = response.text
            
            if response.status_code == 200:
                # Check if response looks like valid JSON (starts with '[' or '{')
                if not response_text.strip() or response_text.strip()[0] not in '[{':
                    return {
                        "success": False,
                        "article_id": article_id,
                        "error": f"Article {article_id} is not available in PMC Open Access subset. "
                                 "Only PMC Open Access articles can be retrieved."
                    }
                
                if format == "json":
                    data = response.json()
                    result = {
                        "success": True,
                        "article_id": article_id,
                        "format": format,
                        "data": data
                    }
                else:
                    result = {
                        "success": True,
                        "article_id": article_id,
                        "format": format,
                        "data": response_text
                    }
                return result
            else:
                return {
                    "success": False,
                    "article_id": article_id,
                    "error": f"Article not available. Status code: {response.status_code}. "
                             "Note: Only PMC Open Access articles are available through this API."
                }
    except httpx.TimeoutException:
        return {
            "success": False,
            "article_id": article_id,
            "error": "Request timed out. Please try again."
        }
    except Exception as e:
        return {
            "success": False,
            "article_id": article_id,
            "error": f"Failed to fetch article: {str(e)}"
        }


@log_tool_call
async def get_article_abstract(article_id: str) -> dict:
    """
    Fetch and extract the abstract from a PubMed/PMC article.
    
    This is a convenience function that retrieves an article and extracts
    just the abstract section for quick summarization tasks.
    
    Args:
        article_id: The PubMed ID (e.g., "17299597") or PMC ID (e.g., "PMC1790863")
    
    Returns:
        dict: Contains abstract text or error information
            - success: bool indicating if retrieval was successful
            - article_id: The requested article ID
            - title: Article title (if available)
            - abstract: The abstract text (if successful)
            - error: Error message (if unsuccessful)
    """
    result = await fetch_pubmed_article(article_id, format="json")
    
    if not result["success"]:
        return result
    
    try:
        data = result["data"]
        title = ""
        abstract = ""
        
        # BioC JSON is an array at the top level
        collections = data if isinstance(data, list) else [data]
        
        for collection in collections:
            documents = collection.get("documents", [])
            for doc in documents:
                passages = doc.get("passages", [])
                for passage in passages:
                    infons = passage.get("infons", {})
                    section_type = infons.get("section_type", "").upper()
                    passage_type = infons.get("type", "").lower()
                    text = passage.get("text", "")
                    
                    # Extract title (section_type=TITLE or type contains "front")
                    if section_type == "TITLE" or passage_type == "front":
                        if text and not title:
                            title = text
                    
                    # Extract abstract (section_type=ABSTRACT and type=abstract, not title)
                    if section_type == "ABSTRACT" and passage_type == "abstract":
                        abstract += text + " "
        
        if abstract:
            return {
                "success": True,
                "article_id": article_id,
                "title": title.strip(),
                "abstract": abstract.strip()
            }
        else:
            return {
                "success": False,
                "article_id": article_id,
                "error": "Abstract not found in article. The article may not have an abstract section."
            }
            
    except Exception as e:
        return {
            "success": False,
            "article_id": article_id,
            "error": f"Failed to parse article: {str(e)}"
        }


@log_tool_call
async def get_article_sections(article_id: str) -> dict:
    """
    Fetch and extract all sections from a PubMed/PMC article.
    
    Retrieves the full article and organizes it by sections (title, abstract,
    introduction, methods, results, discussion, etc.)
    
    Args:
        article_id: The PubMed ID (e.g., "17299597") or PMC ID (e.g., "PMC1790863")
    
    Returns:
        dict: Contains organized article sections or error information
            - success: bool indicating if retrieval was successful
            - article_id: The requested article ID
            - sections: dict mapping section names to their text content
            - error: Error message (if unsuccessful)
    """
    
    result = await fetch_pubmed_article(article_id, format="json")
    
    if not result["success"]:
        return result
    
    try:
        data = result["data"]
        sections = {}
        
        # BioC JSON is an array at the top level
        collections = data if isinstance(data, list) else [data]
        
        # Map section types to readable names
        section_map = {
            "TITLE": "title",
            "ABSTRACT": "abstract", 
            "INTRO": "introduction",
            "METHODS": "methods",
            "RESULTS": "results",
            "DISCUSS": "discussion",
            "CONCL": "conclusion",
            "REF": "references",
            "FIG": "figures",
            "TABLE": "tables",
            "SUPPL": "supplementary",
            "ACK_FUND": "acknowledgments",
        }
        
        for collection in collections:
            documents = collection.get("documents", [])
            for doc in documents:
                passages = doc.get("passages", [])
                for passage in passages:
                    infons = passage.get("infons", {})
                    section_type = infons.get("section_type", "").upper()
                    passage_type = infons.get("type", "").lower()
                    text = passage.get("text", "")
                    
                    if not text or not section_type:
                        continue
                    
                    # Skip section headers/titles within sections
                    if "title" in passage_type and section_type != "TITLE":
                        continue
                    
                    # Map to readable section name
                    section_key = section_map.get(section_type, section_type.lower())
                    
                    if section_key in sections:
                        sections[section_key] += "\n\n" + text
                    else:
                        sections[section_key] = text
        
        return {
            "success": True,
            "article_id": article_id,
            "sections": sections,
            "available_sections": list(sections.keys())
        }
            
    except Exception as e:
        return {
            "success": False,
            "article_id": article_id,
            "error": f"Failed to parse article because it is not in PMC Open Access subset: {str(e)}"
        }


# Create FunctionTools for Google ADK
fetch_pubmed_article_tool = FunctionTool(fetch_pubmed_article)
get_article_abstract_tool = FunctionTool(get_article_abstract)
get_article_sections_tool = FunctionTool(get_article_sections)

# Export all tools as a list for easy import
pubmed_tools = [
    fetch_pubmed_article_tool,
    get_article_abstract_tool,
    get_article_sections_tool,
]

