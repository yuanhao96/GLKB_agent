#!/usr/bin/env python3
"""
PubMed search functionality using NCBI E-utilities ESearch API.
Provides powerful search capabilities for biomedical literature.
"""

import sys
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error
import json
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Any
import logging

# Add utils to path
# sys.path removed for package imports
from .utils.helpers import (
    build_api_params,
    get_date_range,
    format_pubmed_date,
    get_current_year,
)
from .utils.validators.parameter_validator import (
    validate_query_param,
    validate_max_results,
    validate_date_param,
    validate_sort_order,
    ValidationError,
)
from .utils.validators.response_validator import validate_esearch_response
from .utils.cache_manager import cache_search_results, get_cached_search
from .utils.rate_limiter import throttle, report_success, report_error

logger = logging.getLogger(__name__)

# API Configuration
ESEARCH_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def search_pubmed(
    query: str,
    max_results: int = 20,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
    sort: str = "relevance",
    use_cache: bool = True,
    include_summaries: bool = True
) -> Dict[str, Any]:
    """
    Search PubMed for articles matching query.

    Args:
        query: Search query (supports PubMed syntax with field tags)
        max_results: Maximum results to return (1-10000)
        min_date: Minimum publication date (YYYY/MM/DD)
        max_date: Maximum publication date (YYYY/MM/DD)
        sort: Sort order (relevance, pub+date, first_author, journal)
        use_cache: Whether to use cached results
        include_summaries: Whether to fetch article summaries

    Returns:
        Dict containing:
        - success: bool
        - count: Total matching articles
        - pmids: List of PMIDs
        - articles: List of article summaries (if include_summaries=True)
        - query_info: Search metadata
        - error: Error info if failed

    Example:
        >>> result = search_pubmed("CRISPR gene editing", max_results=10)
        >>> print(f"Found {result['count']} articles")
    """
    # Validate parameters
    try:
        query = validate_query_param(query)
        max_results = validate_max_results(max_results, maximum=10000)
        sort = validate_sort_order(sort)
        if min_date:
            min_date = validate_date_param(min_date)
        if max_date:
            max_date = validate_date_param(max_date)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message,
                "param": e.param_name,
                "suggestion": e.suggestion
            }
        }

    # Check cache
    cache_key = f"{query}:{max_results}:{min_date}:{max_date}:{sort}"
    if use_cache:
        cached = get_cached_search(cache_key)
        if cached:
            logger.info(f"Cache hit for query: {query}")
            return cached

    # Build API request
    params = build_api_params({
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": sort,
        "usehistory": "y"
    })

    if min_date:
        params["mindate"] = min_date
        params["datetype"] = "pdat"  # Publication date
    if max_date:
        params["maxdate"] = max_date
        params["datetype"] = "pdat"

    # Make request
    url = f"{ESEARCH_BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()  # Respect rate limits
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        report_success()
    except urllib.error.URLError as e:
        report_error()
        return {
            "success": False,
            "error": {
                "code": "NETWORK_ERROR",
                "message": f"Failed to connect to PubMed: {e}",
                "suggestion": "Check network connection and try again"
            }
        }
    except json.JSONDecodeError as e:
        report_error()
        return {
            "success": False,
            "error": {
                "code": "PARSE_ERROR",
                "message": f"Failed to parse API response: {e}"
            }
        }

    # Validate response
    validation = validate_esearch_response(data)
    if validation.has_critical_issues():
        return {
            "success": False,
            "error": {
                "code": "API_ERROR",
                "message": validation.get_critical()[0] if validation.get_critical() else "Unknown API error"
            }
        }

    # Extract results
    esearch = data.get("esearchresult", {})
    count = int(esearch.get("count", 0))
    pmids = esearch.get("idlist", [])
    webenv = esearch.get("webenv")
    query_key = esearch.get("querykey")

    result = {
        "success": True,
        "count": count,
        "pmids": pmids,
        "query_info": {
            "query": query,
            "returned": len(pmids),
            "total": count,
            "sort": sort,
            "date_range": f"{min_date or 'any'} to {max_date or 'any'}"
        },
        "validation": {
            "passed": validation.all_passed(),
            "warnings": validation.get_warnings()
        }
    }

    # Fetch summaries if requested
    if include_summaries and pmids:
        summaries = fetch_summaries(pmids)
        result["articles"] = summaries

    # Cache results
    if use_cache:
        cache_search_results(cache_key, result)

    return result


def fetch_summaries(pmids: List[str]) -> List[Dict[str, Any]]:
    """
    Fetch article summaries for list of PMIDs.

    Args:
        pmids: List of PubMed IDs

    Returns:
        List of article summary dicts
    """
    if not pmids:
        return []

    params = build_api_params({
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
        "version": "2.0"
    })

    url = f"{ESUMMARY_BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        report_success()
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to fetch summaries: {e}")
        return []

    # Parse summaries
    result_data = data.get("result", {})
    articles = []

    for pmid in pmids:
        doc = result_data.get(pmid, {})
        if not doc or "error" in doc:
            continue

        article = {
            "pmid": pmid,
            "title": doc.get("title", ""),
            "authors": _parse_authors(doc.get("authors", [])),
            "journal": doc.get("source", ""),
            "pub_date": doc.get("pubdate", ""),
            "year": _extract_year(doc.get("pubdate", "")),
            "volume": doc.get("volume", ""),
            "issue": doc.get("issue", ""),
            "pages": doc.get("pages", ""),
            "doi": _extract_doi(doc.get("articleids", [])),
            "pmc": _extract_pmcid(doc.get("articleids", [])),
            "pub_types": doc.get("pubtype", []),
        }
        articles.append(article)

    return articles


def _parse_authors(authors_data: List[Dict]) -> List[Dict[str, str]]:
    """Parse authors from ESummary response."""
    authors = []
    for author in authors_data:
        name = author.get("name", "")
        parts = name.split(" ", 1)
        if len(parts) == 2:
            authors.append({
                "LastName": parts[0],
                "Initials": parts[1] if len(parts[1]) <= 5 else parts[1][:5]
            })
        else:
            authors.append({"LastName": name, "Initials": ""})
    return authors


def _extract_year(pubdate: str) -> Optional[int]:
    """Extract year from publication date string."""
    import re
    match = re.search(r'\b(19|20)\d{2}\b', pubdate)
    if match:
        return int(match.group())
    return None


def _extract_doi(articleids: List[Dict]) -> Optional[str]:
    """Extract DOI from article IDs."""
    for aid in articleids:
        if aid.get("idtype") == "doi":
            return aid.get("value")
    return None


def _extract_pmcid(articleids: List[Dict]) -> Optional[str]:
    """Extract PMC ID from article IDs."""
    for aid in articleids:
        if aid.get("idtype") == "pmc":
            value = aid.get("value", "")
            if not value.upper().startswith("PMC"):
                value = f"PMC{value}"
            return value
    return None


def build_advanced_query(
    terms: List[str],
    title_only: bool = False,
    author: Optional[str] = None,
    journal: Optional[str] = None,
    mesh_terms: Optional[List[str]] = None,
    article_types: Optional[List[str]] = None,
    boolean_op: str = "AND"
) -> str:
    """
    Build advanced PubMed query with field tags.

    Args:
        terms: Main search terms
        title_only: Search only in titles
        author: Author name filter
        journal: Journal name filter
        mesh_terms: MeSH term filters
        article_types: Article type filters (Review, Clinical Trial, etc.)
        boolean_op: Operator between main terms (AND, OR)

    Returns:
        Formatted query string

    Example:
        >>> query = build_advanced_query(
        ...     terms=["CRISPR", "cancer"],
        ...     author="Zhang F",
        ...     journal="Nature"
        ... )
        >>> print(query)
        "(CRISPR AND cancer) AND Zhang F[Author] AND Nature[Journal]"
    """
    parts = []

    # Main terms
    if terms:
        field_tag = "[Title]" if title_only else "[Title/Abstract]"
        term_parts = [f"{term}{field_tag}" for term in terms]
        parts.append(f"({f' {boolean_op} '.join(term_parts)})")

    # Author filter
    if author:
        parts.append(f"{author}[Author]")

    # Journal filter
    if journal:
        parts.append(f'"{journal}"[Journal]')

    # MeSH terms
    if mesh_terms:
        mesh_parts = [f"{term}[MeSH Terms]" for term in mesh_terms]
        parts.append(f"({' OR '.join(mesh_parts)})")

    # Article types
    if article_types:
        type_parts = [f"{atype}[Publication Type]" for atype in article_types]
        parts.append(f"({' OR '.join(type_parts)})")

    return " AND ".join(parts)


def search_by_date_range(
    query: str,
    days_back: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Search PubMed for recent articles.

    Args:
        query: Search query
        days_back: Number of days to search back
        **kwargs: Additional arguments for search_pubmed

    Returns:
        Search results
    """
    min_date, max_date = get_date_range(days_back)
    return search_pubmed(query, min_date=min_date, max_date=max_date, **kwargs)


def search_by_year(
    query: str,
    year: int,
    **kwargs
) -> Dict[str, Any]:
    """
    Search PubMed for articles from specific year.

    Args:
        query: Search query
        year: Publication year
        **kwargs: Additional arguments for search_pubmed

    Returns:
        Search results
    """
    min_date = format_pubmed_date(year, 1, 1)
    max_date = format_pubmed_date(year, 12, 31)
    return search_pubmed(query, min_date=min_date, max_date=max_date, **kwargs)


def format_search_results(results: Dict[str, Any]) -> str:
    """
    Format search results for display.

    Args:
        results: Search results dict

    Returns:
        Formatted string for display
    """
    if not results.get("success"):
        error = results.get("error", {})
        return f"Search failed: {error.get('message', 'Unknown error')}"

    lines = []
    query_info = results.get("query_info", {})
    count = results.get("count", 0)
    articles = results.get("articles", [])

    lines.append(f"## PubMed Search Results: \"{query_info.get('query', '')}\"")
    lines.append("")
    lines.append(f"Found {count:,} articles. Showing {len(articles)}:")
    lines.append("")

    for i, article in enumerate(articles, 1):
        title = article.get("title", "Untitled")
        authors = article.get("authors", [])
        if authors:
            author_str = authors[0].get("LastName", "")
            if len(authors) > 1:
                author_str += " et al."
        else:
            author_str = "Unknown authors"

        journal = article.get("journal", "")
        year = article.get("year", "")
        pmid = article.get("pmid", "")
        pmc = article.get("pmc", "")

        lines.append(f"{i}. **{title}**")
        lines.append(f"   Authors: {author_str}")
        if journal:
            lines.append(f"   Journal: {journal}, {year}" if year else f"   Journal: {journal}")
        lines.append(f"   PMID: {pmid}")
        if pmc:
            lines.append(f"   Full text: {pmc}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test PubMed search functionality."""
    print("Testing PubMed Search...\n")

    # Test basic search
    print("1. Basic search (CRISPR):")
    results = search_pubmed("CRISPR gene editing", max_results=5)

    if results["success"]:
        print(f"   Found {results['count']} total articles")
        print(f"   Retrieved {len(results.get('articles', []))} summaries")
        for article in results.get("articles", [])[:3]:
            print(f"   - {article['pmid']}: {article['title'][:60]}...")
    else:
        print(f"   Error: {results.get('error', {}).get('message')}")

    # Test advanced query
    print("\n2. Advanced query (title only, 2024):")
    results = search_by_year("mRNA vaccine", year=2024, max_results=5)

    if results["success"]:
        print(f"   Found {results['count']} articles from 2024")

    # Test query building
    print("\n3. Query builder:")
    query = build_advanced_query(
        terms=["CRISPR", "cancer"],
        author="Zhang F",
        article_types=["Review"]
    )
    print(f"   Built query: {query}")

    # Test formatted output
    print("\n4. Formatted output:")
    results = search_pubmed("COVID-19 vaccine", max_results=3)
    if results["success"]:
        formatted = format_search_results(results)
        print(formatted)

    print("\nAll search tests completed!")


if __name__ == "__main__":
    main()
