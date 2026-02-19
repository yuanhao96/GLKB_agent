#!/usr/bin/env python3
"""
Citation discovery using NCBI E-utilities ELink API.
Find articles that cite a given paper and explore citation networks.
"""

import sys
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Optional, List, Dict, Any
from collections import defaultdict
import logging

# Add utils to path
# sys.path removed for package imports
from .utils.helpers import build_api_params, format_authors, extract_year
from .utils.validators.parameter_validator import (
    validate_pmid_param,
    validate_max_results,
    ValidationError,
)
from .utils.validators.response_validator import validate_elink_response
from .utils.rate_limiter import throttle, report_success, report_error
from .utils.cache_manager import cache_citations, get_cached_citations

# Import for fetching summaries
from .search_pubmed import fetch_summaries

logger = logging.getLogger(__name__)

# API Configuration
ELINK_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"


def get_citing_articles(
    pmid: str,
    max_results: int = 100,
    sort_by_date: bool = True,
    include_summaries: bool = True,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Get articles that cite the given PMID.

    Args:
        pmid: PubMed ID to find citations for
        max_results: Maximum number of citing articles to return
        sort_by_date: Sort by publication date (newest first)
        include_summaries: Fetch article summaries for results
        use_cache: Whether to use cached data

    Returns:
        Dict containing:
        - success: bool
        - source_pmid: Original PMID
        - citation_count: Total citing articles
        - articles: List of citing articles
        - by_year: Articles grouped by publication year
        - error: Error info if failed

    Example:
        >>> result = get_citing_articles("17299597", max_results=50)
        >>> print(f"Cited by {result['citation_count']} articles")
    """
    # Validate parameters
    try:
        pmid = validate_pmid_param(pmid)
        max_results = validate_max_results(max_results, maximum=10000)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message,
                "suggestion": e.suggestion
            }
        }

    # Check cache
    cache_key = f"citing:{pmid}"
    if use_cache:
        cached = get_cached_citations(pmid)
        if cached:
            logger.info(f"Cache hit for citations: {pmid}")
            # Still respect max_results for cached data
            if len(cached.get("articles", [])) > max_results:
                cached["articles"] = cached["articles"][:max_results]
            return cached

    # Build API request for "cited by" links
    params = build_api_params({
        "dbfrom": "pubmed",
        "db": "pubmed",
        "id": pmid,
        "linkname": "pubmed_pubmed_citedin",
        "retmode": "json"
    })

    url = f"{ELINK_BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        report_success()
    except urllib.error.URLError as e:
        report_error()
        return {
            "success": False,
            "source_pmid": pmid,
            "error": {
                "code": "NETWORK_ERROR",
                "message": f"Failed to find citing articles: {e}",
                "suggestion": "Check network connection and try again"
            }
        }
    except json.JSONDecodeError as e:
        report_error()
        return {
            "success": False,
            "source_pmid": pmid,
            "error": {
                "code": "PARSE_ERROR",
                "message": f"Failed to parse API response: {e}"
            }
        }

    # Validate response
    validation = validate_elink_response(data)

    # Parse results
    linksets = data.get("linksets", [])
    citing_pmids = []

    if linksets:
        linksetdbs = linksets[0].get("linksetdbs", [])
        for linksetdb in linksetdbs:
            if linksetdb.get("linkname") == "pubmed_pubmed_citedin":
                citing_pmids = [str(link) for link in linksetdb.get("links", [])]

    total_citations = len(citing_pmids)

    if not citing_pmids:
        return {
            "success": True,
            "source_pmid": pmid,
            "citation_count": 0,
            "articles": [],
            "by_year": {},
            "message": "No citing articles found"
        }

    # Limit results
    citing_pmids = citing_pmids[:max_results]

    # Fetch summaries if requested
    articles = []
    if include_summaries and citing_pmids:
        summaries = fetch_summaries(citing_pmids)
        articles = summaries

    # Sort by date if requested
    if sort_by_date and articles:
        articles.sort(key=lambda x: x.get("year", 0) or 0, reverse=True)

    # Group by year
    by_year = defaultdict(list)
    for article in articles:
        year = article.get("year") or "Unknown"
        by_year[year].append(article)

    # Convert to regular dict and sort years
    by_year = dict(sorted(by_year.items(), reverse=True))

    result = {
        "success": True,
        "source_pmid": pmid,
        "citation_count": total_citations,
        "returned_count": len(articles),
        "articles": articles,
        "by_year": by_year,
        "validation": {
            "passed": validation.all_passed(),
            "warnings": validation.get_warnings()
        }
    }

    # Cache result
    if use_cache:
        cache_citations(pmid, result)

    return result


def get_references(
    pmid: str,
    max_results: int = 100,
    include_summaries: bool = True
) -> Dict[str, Any]:
    """
    Get articles referenced by (cited in) the given PMID.

    Args:
        pmid: PubMed ID to get references from
        max_results: Maximum references to return
        include_summaries: Fetch article summaries

    Returns:
        Dict with referenced articles
    """
    # Validate parameters
    try:
        pmid = validate_pmid_param(pmid)
        max_results = validate_max_results(max_results, maximum=1000)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message,
                "suggestion": e.suggestion
            }
        }

    # Build API request for references (articles this paper cites)
    params = build_api_params({
        "dbfrom": "pubmed",
        "db": "pubmed",
        "id": pmid,
        "linkname": "pubmed_pubmed_refs",
        "retmode": "json"
    })

    url = f"{ELINK_BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        report_success()
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        report_error()
        return {
            "success": False,
            "source_pmid": pmid,
            "error": {
                "code": "NETWORK_ERROR",
                "message": f"Failed to get references: {e}"
            }
        }

    # Parse results
    linksets = data.get("linksets", [])
    ref_pmids = []

    if linksets:
        linksetdbs = linksets[0].get("linksetdbs", [])
        for linksetdb in linksetdbs:
            if linksetdb.get("linkname") == "pubmed_pubmed_refs":
                ref_pmids = [str(link) for link in linksetdb.get("links", [])]

    if not ref_pmids:
        return {
            "success": True,
            "source_pmid": pmid,
            "reference_count": 0,
            "articles": [],
            "message": "No references found in PubMed"
        }

    # Limit results
    ref_pmids = ref_pmids[:max_results]

    # Fetch summaries if requested
    articles = []
    if include_summaries and ref_pmids:
        summaries = fetch_summaries(ref_pmids)
        articles = summaries

    # Sort by year (oldest first for references)
    articles.sort(key=lambda x: x.get("year", 9999) or 9999)

    return {
        "success": True,
        "source_pmid": pmid,
        "reference_count": len(ref_pmids),
        "articles": articles
    }


def get_citation_network(
    pmid: str,
    depth: int = 1,
    max_per_level: int = 10
) -> Dict[str, Any]:
    """
    Build a citation network around the given article.

    Args:
        pmid: Central PMID
        depth: Levels of citations to follow (1 or 2)
        max_per_level: Maximum articles per level

    Returns:
        Dict with citation network structure
    """
    # Validate
    try:
        pmid = validate_pmid_param(pmid)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message
            }
        }

    depth = min(max(depth, 1), 2)  # Limit to 1-2

    network = {
        "center": pmid,
        "citing": {},      # Papers that cite center
        "cited_by": {},    # Papers cited by center
    }

    # Get first-level citations
    citing = get_citing_articles(pmid, max_results=max_per_level)
    if citing.get("success"):
        for article in citing.get("articles", []):
            article_pmid = article.get("pmid")
            network["citing"][article_pmid] = {
                "title": article.get("title"),
                "year": article.get("year"),
                "authors": article.get("authors", []),
                "level": 1
            }

    # Get first-level references
    refs = get_references(pmid, max_results=max_per_level)
    if refs.get("success"):
        for article in refs.get("articles", []):
            article_pmid = article.get("pmid")
            network["cited_by"][article_pmid] = {
                "title": article.get("title"),
                "year": article.get("year"),
                "authors": article.get("authors", []),
                "level": 1
            }

    # If depth=2, get second-level citations
    if depth >= 2:
        # Get citations of citing articles
        for citing_pmid in list(network["citing"].keys())[:5]:  # Limit second level
            second_citing = get_citing_articles(citing_pmid, max_results=5)
            if second_citing.get("success"):
                for article in second_citing.get("articles", []):
                    article_pmid = article.get("pmid")
                    if article_pmid not in network["citing"]:
                        network["citing"][article_pmid] = {
                            "title": article.get("title"),
                            "year": article.get("year"),
                            "authors": article.get("authors", []),
                            "level": 2,
                            "via": citing_pmid
                        }

    return {
        "success": True,
        "source_pmid": pmid,
        "depth": depth,
        "network": network,
        "stats": {
            "citing_count": len(network["citing"]),
            "cited_by_count": len(network["cited_by"])
        }
    }


def get_citation_metrics(pmid: str) -> Dict[str, Any]:
    """
    Get citation metrics for an article.

    Args:
        pmid: PubMed ID

    Returns:
        Dict with citation metrics
    """
    # Validate
    try:
        pmid = validate_pmid_param(pmid)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message
            }
        }

    # Get citing articles
    citing = get_citing_articles(pmid, max_results=1000, include_summaries=True)

    if not citing.get("success"):
        return citing

    articles = citing.get("articles", [])
    total_citations = citing.get("citation_count", 0)

    # Get article publication year
    from fetch_article import fetch_abstract
    source_article = fetch_abstract(pmid)
    source_year = source_article.get("year", 2020) if source_article.get("success") else 2020

    # Calculate metrics
    from datetime import datetime
    current_year = datetime.now().year
    years_since_pub = max(current_year - source_year, 1)

    # Citations per year
    citations_per_year = total_citations / years_since_pub

    # Citation growth by year
    by_year = citing.get("by_year", {})
    yearly_counts = {}
    for year, arts in by_year.items():
        if isinstance(year, int):
            yearly_counts[year] = len(arts)

    # Recent citation velocity (last 2 years)
    recent_years = [current_year, current_year - 1]
    recent_citations = sum(
        yearly_counts.get(y, 0) for y in recent_years
    )
    recent_velocity = recent_citations / 2 if recent_citations else 0

    return {
        "success": True,
        "pmid": pmid,
        "publication_year": source_year,
        "total_citations": total_citations,
        "citations_per_year": round(citations_per_year, 2),
        "recent_velocity": round(recent_velocity, 2),
        "years_since_publication": years_since_pub,
        "yearly_breakdown": yearly_counts
    }


def format_citation_results(result: Dict[str, Any]) -> str:
    """
    Format citation results for display.

    Args:
        result: Citation results dict

    Returns:
        Formatted string for display
    """
    if not result.get("success"):
        error = result.get("error", {})
        return f"Error: {error.get('message', 'Unknown error')}"

    lines = []
    source_pmid = result.get("source_pmid", "")
    total = result.get("citation_count", 0)
    by_year = result.get("by_year", {})

    lines.append(f"## Articles Citing PMID {source_pmid}")
    lines.append("")
    lines.append(f"This article has been cited **{total:,} times**.")
    lines.append("")

    # Show by year
    for year, articles in by_year.items():
        lines.append(f"### {year} ({len(articles)} citations)")
        lines.append("")

        for i, article in enumerate(articles[:5], 1):  # Show max 5 per year
            title = article.get("title", "Untitled")
            authors = article.get("authors", [])
            journal = article.get("journal", "")
            pmid = article.get("pmid", "")

            if authors:
                author_str = authors[0].get("LastName", "")
                if len(authors) > 1:
                    author_str += " et al."
            else:
                author_str = "Unknown"

            lines.append(f"{i}. **{title[:80]}{'...' if len(title) > 80 else ''}**")
            lines.append(f"   {author_str}, {journal}")
            lines.append(f"   PMID: {pmid}")
            lines.append("")

        if len(articles) > 5:
            lines.append(f"   ... and {len(articles) - 5} more from {year}")
            lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test citation discovery functionality."""
    print("Testing Citation Discovery...\n")

    # Test get citing articles
    print("1. Get citing articles (PMID 17299597):")
    result = get_citing_articles("17299597", max_results=10)

    if result["success"]:
        print(f"   Total citations: {result['citation_count']}")
        print(f"   Returned: {len(result.get('articles', []))}")
        print(f"   By year: {list(result.get('by_year', {}).keys())[:5]}...")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test get references
    print("\n2. Get references (papers cited by 17299597):")
    result = get_references("17299597", max_results=10)

    if result["success"]:
        print(f"   Reference count: {result['reference_count']}")
        for article in result.get("articles", [])[:3]:
            print(f"   - {article.get('pmid')}: {article.get('title', '')[:40]}...")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test citation metrics
    print("\n3. Citation metrics:")
    metrics = get_citation_metrics("17299597")

    if metrics["success"]:
        print(f"   Total citations: {metrics['total_citations']}")
        print(f"   Citations/year: {metrics['citations_per_year']}")
        print(f"   Recent velocity: {metrics['recent_velocity']}")
    else:
        print(f"   Error: {metrics.get('error', {}).get('message')}")

    # Test formatted output
    print("\n4. Formatted output:")
    result = get_citing_articles("17299597", max_results=10)
    if result["success"]:
        formatted = format_citation_results(result)
        # Print first 30 lines
        for line in formatted.split('\n')[:30]:
            print(line)
        print("...")

    print("\nAll citation tests completed!")


if __name__ == "__main__":
    main()
