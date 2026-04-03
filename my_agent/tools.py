"""
REST API Tools for PubMed/PMC Article Retrieval and Neo4j Knowledge Graph

Uses the BioC API for PMC Open Access:
https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/

Citation: Comeau DC, Wei CH, Islamaj Doğan R, and Lu Z. 
PMC text mining subset in BioC: about 3 million full text articles and growing, 
Bioinformatics, btz070, 2019.
"""

import asyncio
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

# Use the shared agent logger (propagate=False, immune to root-logger reconfig)
logger = logging.getLogger("glkb_agent_service")

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
            logger.error(f"[TOOL ERROR] {tool_name} | Error: {str(e)}", exc_info=True)
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
async def cite_evidence(
    pmid: str,
    quote: str,
    context_type: str = "abstract",
) -> dict:
    """
    Register a specific evidence quote from an article that supports a claim
    in your answer. Call this BEFORE writing the final answer, once per
    article you plan to cite.

    Args:
        pmid: PubMed ID of the source article (e.g. "38743124")
        quote: The exact sentence or passage from the article that serves
               as evidence. Must be copied verbatim from tool output, not
               paraphrased.
        context_type: Where the quote came from — one of "abstract",
                      "fulltext", "kg_evidence" (from Cooccur evidence
                      field), or "title"

    Returns:
        dict: Confirmation with the registered evidence
    """
    return {
        "registered": True,
        "pmid": pmid,
        "quote": quote,
        "context_type": context_type,
    }


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
cite_evidence_tool = FunctionTool(cite_evidence)

# Export glkb tools
glkb_tools = [
    get_database_schema_tool,
    article_search_tool,
    vocabulary_search_tool,
    execute_cypher_tool,
    cite_evidence_tool,
]

### PUBMED READER TOOLS (via pubmed-reader-cskill) ###
# These tools wrap the synchronous cskill functions with async wrappers
# using asyncio.to_thread() to avoid blocking the event loop.

from scripts.pubmed_reader import (
    search_pubmed as _search_pubmed,
    fetch_abstract as _fetch_abstract,
    get_fulltext as _get_fulltext,
    find_similar_articles as _find_similar_articles,
    get_citing_articles as _get_citing_articles,
    comprehensive_article_report as _comprehensive_article_report,
)


@log_tool_call
async def search_pubmed(
    query: str,
    max_results: int = 20,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
    sort: str = "relevance",
) -> dict:
    """
    Search PubMed directly via NCBI E-utilities for articles matching a query.

    Use this for broader PubMed coverage, date/author/journal filtering,
    or when the GLKB article_search returns insufficient results.

    Args:
        query: Search query (supports PubMed syntax with field tags like [Title], [Author], [MeSH Terms])
        max_results: Maximum results to return (1-200, default 20)
        min_date: Minimum publication date (YYYY/MM/DD), e.g. "2023/01/01"
        max_date: Maximum publication date (YYYY/MM/DD), e.g. "2024/12/31"
        sort: Sort order - "relevance" (default) or "pub+date" (newest first)

    Returns:
        dict with keys: success, count, pmids, articles (list of summaries), query_info, error
    """
    return await asyncio.to_thread(
        _search_pubmed,
        query=query,
        max_results=min(max_results, 200),
        min_date=min_date,
        max_date=max_date,
        sort=sort,
        include_summaries=True,
        include_abstracts=True,
    )


@log_tool_call
async def fetch_abstract(pmid: str) -> dict:
    """
    Fetch the abstract, metadata, MeSH terms, and keywords for a specific PubMed article.

    Args:
        pmid: PubMed ID (e.g. "17299597")

    Returns:
        dict with keys: success, pmid, title, abstract, authors, journal, year, doi, mesh_terms, keywords, error
    """
    return await asyncio.to_thread(_fetch_abstract, pmid=pmid)


@log_tool_call
async def get_fulltext(article_id: str) -> dict:
    """
    Retrieve full-text sections from a PMC Open Access article.

    Only ~3 million Open Access articles are available. Falls back gracefully
    if the article is not in the OA subset.

    Args:
        article_id: PubMed ID (e.g. "17299597") or PMC ID (e.g. "PMC1790863")

    Returns:
        dict with keys: success, pmid, pmcid, title, sections (dict of section_name->text),
        full_text, figures, tables, word_count, error
    """
    return await asyncio.to_thread(_get_fulltext, article_id=article_id)


@log_tool_call
async def find_similar_articles(pmid: str, max_results: int = 20) -> dict:
    """
    Find articles similar to a given PMID using NCBI ELink.

    Discovers related papers based on shared MeSH terms, citations, and content similarity.

    Args:
        pmid: PubMed ID to find similar articles for
        max_results: Maximum number of similar articles (default 20)

    Returns:
        dict with keys: success, source_pmid, similar_count, articles (with title, pmid, score), error
    """
    return await asyncio.to_thread(
        _find_similar_articles,
        pmid=pmid,
        max_results=max_results,
        include_summaries=True,
    )


@log_tool_call
async def get_citing_articles(pmid: str, max_results: int = 50) -> dict:
    """
    Find articles that cite a given PubMed article.

    Args:
        pmid: PubMed ID to find citations for
        max_results: Maximum citing articles to return (default 50)

    Returns:
        dict with keys: success, source_pmid, citation_count, articles (sorted newest first),
        by_year (grouped), error
    """
    return await asyncio.to_thread(
        _get_citing_articles,
        pmid=pmid,
        max_results=max_results,
        include_summaries=True,
    )


@log_tool_call
async def comprehensive_report(pmid: str) -> dict:
    """
    Generate a comprehensive analysis of a single PubMed article, including
    metadata, abstract, full text (if OA), similar articles, citing articles,
    references, and citation metrics.

    Args:
        pmid: PubMed ID to analyze (e.g. "17299597")

    Returns:
        dict with keys: success, pmid, article, fulltext, similar_articles,
        citing_articles, references, metrics, summary, quick_stats, alerts, error
    """
    return await asyncio.to_thread(
        _comprehensive_article_report,
        pmid=pmid,
        include_fulltext=True,
        max_similar=5,
        max_citations=10,
        max_references=10,
        include_metrics=True,
    )


# Create FunctionTools for the pubmed-reader skill
search_pubmed_tool = FunctionTool(search_pubmed)
fetch_abstract_tool = FunctionTool(fetch_abstract)
get_fulltext_tool = FunctionTool(get_fulltext)
find_similar_articles_tool = FunctionTool(find_similar_articles)
get_citing_articles_tool = FunctionTool(get_citing_articles)
comprehensive_report_tool = FunctionTool(comprehensive_report)

# Export pubmed reader tools as a list for easy import
pubmed_tools = [
    search_pubmed_tool,
    fetch_abstract_tool,
    get_fulltext_tool,
    find_similar_articles_tool,
    get_citing_articles_tool,
    comprehensive_report_tool,
]

