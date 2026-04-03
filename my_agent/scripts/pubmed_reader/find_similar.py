#!/usr/bin/env python3
"""
Find similar/related articles using NCBI E-utilities ELink API.
Discovers related research based on content similarity, shared citations, and MeSH terms.
"""

import sys
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Optional, List, Dict, Any
import logging

# Add utils to path
# sys.path removed for package imports
from .utils.helpers import build_api_params, format_authors
from .utils.validators.parameter_validator import (
    validate_pmid_param,
    validate_max_results,
    ValidationError,
)
from .utils.validators.response_validator import validate_elink_response
from .utils.rate_limiter import throttle, report_success, report_error

# Import for fetching summaries
from .search_pubmed import fetch_summaries

logger = logging.getLogger(__name__)

# API Configuration
ELINK_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"


def find_similar_articles(
    pmid: str,
    max_results: int = 20,
    include_scores: bool = True,
    include_summaries: bool = True
) -> Dict[str, Any]:
    """
    Find articles similar to the given PMID.

    Uses NCBI's "pubmed_pubmed" link which finds articles with
    similar content based on:
    - Shared MeSH terms
    - Shared citations
    - Content similarity algorithms

    Args:
        pmid: PubMed ID to find similar articles for
        max_results: Maximum number of similar articles to return
        include_scores: Include similarity scores (requires neighbor_score)
        include_summaries: Fetch article summaries for results

    Returns:
        Dict containing:
        - success: bool
        - source_pmid: Original PMID
        - similar_count: Total similar articles found
        - articles: List of similar articles with scores
        - error: Error info if failed

    Example:
        >>> result = find_similar_articles("17299597", max_results=10)
        >>> for article in result['articles']:
        ...     print(f"{article['pmid']}: {article['title']}")
    """
    # Validate parameters
    try:
        pmid = validate_pmid_param(pmid)
        max_results = validate_max_results(max_results, maximum=500)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message,
                "suggestion": e.suggestion
            }
        }

    # Build API request
    cmd = "neighbor_score" if include_scores else "neighbor"

    params = build_api_params({
        "dbfrom": "pubmed",
        "db": "pubmed",
        "id": pmid,
        "cmd": cmd,
        "linkname": "pubmed_pubmed",
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
                "message": f"Failed to find similar articles: {e}",
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
    if validation.has_critical_issues():
        return {
            "success": False,
            "source_pmid": pmid,
            "error": {
                "code": "API_ERROR",
                "message": validation.get_critical()[0] if validation.get_critical() else "No similar articles found"
            }
        }

    # Parse results
    linksets = data.get("linksets", [])
    if not linksets:
        return {
            "success": True,
            "source_pmid": pmid,
            "similar_count": 0,
            "articles": [],
            "message": "No similar articles found"
        }

    # Extract linked IDs with scores
    similar_articles = []
    linksetdbs = linksets[0].get("linksetdbs", [])

    for linksetdb in linksetdbs:
        if linksetdb.get("linkname") == "pubmed_pubmed":
            links = linksetdb.get("links", [])

            for link in links[:max_results]:
                if isinstance(link, dict):
                    # Has score
                    similar_articles.append({
                        "pmid": str(link.get("id", "")),
                        "score": link.get("score", 0)
                    })
                else:
                    # Just ID
                    similar_articles.append({
                        "pmid": str(link),
                        "score": None
                    })

    # Sort by score if available
    if include_scores and similar_articles:
        similar_articles.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Fetch summaries if requested
    if include_summaries and similar_articles:
        pmids = [a["pmid"] for a in similar_articles]
        summaries = fetch_summaries(pmids)

        # Merge summaries with scores
        summary_dict = {s["pmid"]: s for s in summaries}
        for article in similar_articles:
            summary = summary_dict.get(article["pmid"], {})
            article.update(summary)

    return {
        "success": True,
        "source_pmid": pmid,
        "similar_count": len(similar_articles),
        "articles": similar_articles,
        "validation": {
            "passed": validation.all_passed(),
            "warnings": validation.get_warnings()
        }
    }


def find_by_mesh_terms(
    pmid: str,
    max_results: int = 20
) -> Dict[str, Any]:
    """
    Find articles sharing MeSH terms with the given article.

    Args:
        pmid: PubMed ID
        max_results: Maximum results

    Returns:
        Dict with articles sharing MeSH terms
    """
    # This uses the same ELink but we'll filter/display differently
    result = find_similar_articles(pmid, max_results=max_results * 2)

    if not result.get("success"):
        return result

    # Add context about shared MeSH terms
    result["match_type"] = "mesh_terms"
    result["articles"] = result["articles"][:max_results]

    return result


def find_by_author(
    pmid: str,
    max_results: int = 20
) -> Dict[str, Any]:
    """
    Find other articles by the same authors.

    Args:
        pmid: PubMed ID
        max_results: Maximum results

    Returns:
        Dict with articles by same authors
    """
    # First, get the original article's authors
    from fetch_article import fetch_abstract

    article = fetch_abstract(pmid)
    if not article.get("success"):
        return {
            "success": False,
            "error": article.get("error")
        }

    authors = article.get("authors", [])
    if not authors:
        return {
            "success": False,
            "error": {
                "code": "NO_AUTHORS",
                "message": "Could not find authors for this article"
            }
        }

    # Search by first author
    first_author = authors[0]
    author_name = first_author.get("LastName", "")
    if first_author.get("Initials"):
        author_name += f" {first_author['Initials']}"

    from search_pubmed import search_pubmed

    results = search_pubmed(
        query=f"{author_name}[Author]",
        max_results=max_results + 1,  # +1 to exclude source article
        sort="pub+date"
    )

    if not results.get("success"):
        return results

    # Filter out source article
    articles = [
        a for a in results.get("articles", [])
        if a.get("pmid") != pmid
    ][:max_results]

    return {
        "success": True,
        "source_pmid": pmid,
        "author": author_name,
        "match_type": "same_author",
        "article_count": len(articles),
        "articles": articles
    }


def find_review_articles(
    pmid: str,
    max_results: int = 10
) -> Dict[str, Any]:
    """
    Find review articles related to the given article's topic.

    Args:
        pmid: PubMed ID
        max_results: Maximum results

    Returns:
        Dict with related review articles
    """
    # Get original article to extract keywords/MeSH
    from fetch_article import fetch_abstract

    article = fetch_abstract(pmid)
    if not article.get("success"):
        return {
            "success": False,
            "error": article.get("error")
        }

    # Build query from MeSH terms or keywords
    mesh_terms = article.get("mesh_terms", [])[:3]
    keywords = article.get("keywords", [])[:3]

    search_terms = mesh_terms if mesh_terms else keywords
    if not search_terms:
        # Fall back to title words
        title = article.get("title", "")
        words = [w for w in title.split() if len(w) > 4][:3]
        search_terms = words

    if not search_terms:
        return {
            "success": False,
            "error": {
                "code": "NO_TERMS",
                "message": "Could not extract search terms from article"
            }
        }

    from search_pubmed import search_pubmed

    query = f"({' OR '.join(search_terms)}) AND Review[Publication Type]"

    results = search_pubmed(
        query=query,
        max_results=max_results,
        sort="relevance"
    )

    if not results.get("success"):
        return results

    return {
        "success": True,
        "source_pmid": pmid,
        "search_terms": search_terms,
        "match_type": "related_reviews",
        "article_count": len(results.get("articles", [])),
        "articles": results.get("articles", [])
    }


def format_similar_results(result: Dict[str, Any]) -> str:
    """
    Format similar articles results for display.

    Args:
        result: Similar articles result dict

    Returns:
        Formatted string for display
    """
    if not result.get("success"):
        error = result.get("error", {})
        return f"Error: {error.get('message', 'Unknown error')}"

    lines = []
    source_pmid = result.get("source_pmid", "")
    match_type = result.get("match_type", "similar")
    articles = result.get("articles", [])

    if match_type == "same_author":
        author = result.get("author", "")
        lines.append(f"## Articles by {author}")
        lines.append(f"(Other papers by author of PMID {source_pmid})")
    elif match_type == "related_reviews":
        lines.append(f"## Review Articles Related to PMID {source_pmid}")
        terms = result.get("search_terms", [])
        lines.append(f"Based on: {', '.join(terms)}")
    else:
        lines.append(f"## Similar Articles to PMID {source_pmid}")
        lines.append("Based on shared MeSH terms, citations, and content similarity")

    lines.append("")
    lines.append(f"Found {len(articles)} articles:")
    lines.append("")

    for i, article in enumerate(articles, 1):
        title = article.get("title", "Untitled")
        pmid = article.get("pmid", "")
        score = article.get("score")
        authors = article.get("authors", [])

        score_str = f" (Score: {score})" if score else ""

        lines.append(f"{i}. **{title}**{score_str}")

        if authors:
            author_str = authors[0].get("LastName", "")
            if len(authors) > 1:
                author_str += " et al."
            lines.append(f"   Authors: {author_str}")

        journal = article.get("journal", "")
        year = article.get("year", "")
        if journal:
            lines.append(f"   Journal: {journal}, {year}" if year else f"   Journal: {journal}")

        lines.append(f"   PMID: {pmid}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test similar article finding functionality."""
    print("Testing Find Similar Articles...\n")

    # Test basic similar articles
    print("1. Find similar articles (PMID 17299597):")
    result = find_similar_articles("17299597", max_results=5)

    if result["success"]:
        print(f"   Found {result['similar_count']} similar articles")
        for i, article in enumerate(result.get("articles", [])[:3], 1):
            score = article.get("score", "N/A")
            print(f"   {i}. {article.get('pmid')}: {article.get('title', '')[:50]}... (score: {score})")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test find by author
    print("\n2. Find by same author:")
    result = find_by_author("17299597", max_results=5)

    if result["success"]:
        author = result.get("author", "")
        print(f"   Author: {author}")
        print(f"   Found {result['article_count']} articles")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test find review articles
    print("\n3. Find related reviews:")
    result = find_review_articles("17299597", max_results=5)

    if result["success"]:
        print(f"   Search terms: {result.get('search_terms', [])}")
        print(f"   Found {result['article_count']} reviews")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test formatted output
    print("\n4. Formatted output:")
    result = find_similar_articles("17299597", max_results=5)
    if result["success"]:
        formatted = format_similar_results(result)
        print(formatted)

    print("\nAll similar article tests completed!")


if __name__ == "__main__":
    main()
