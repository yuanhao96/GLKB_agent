#!/usr/bin/env python3
"""
Comprehensive article analysis combining all PubMed Reader capabilities.
Generates complete reports for articles including metadata, citations, similar articles, and full text.
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

# Add utils to path
# sys.path removed for package imports
from .utils.helpers import format_authors, clean_abstract
from .utils.validators.parameter_validator import validate_pmid_param, ValidationError

# Import all modules
from .fetch_article import fetch_abstract, format_article
from .fetch_fulltext import get_fulltext, check_oa_availability
from .find_similar import find_similar_articles
from .find_citations import get_citing_articles, get_references, get_citation_metrics
from .search_pubmed import search_pubmed

logger = logging.getLogger(__name__)


def comprehensive_article_report(
    pmid: str,
    include_fulltext: bool = True,
    max_similar: int = 5,
    max_citations: int = 10,
    max_references: int = 10,
    include_metrics: bool = True
) -> Dict[str, Any]:
    """
    Generate comprehensive report for a PubMed article.

    This is the "one-stop" function that combines ALL available analyses
    into a single comprehensive report.

    Args:
        pmid: PubMed ID to analyze
        include_fulltext: Attempt to fetch full text if available
        max_similar: Maximum similar articles to include
        max_citations: Maximum citing articles to include
        max_references: Maximum references to include
        include_metrics: Include citation metrics

    Returns:
        Dict containing:
        - success: bool
        - pmid: PubMed ID
        - article: Full article metadata
        - fulltext: Full text (if available)
        - similar_articles: Related papers
        - citing_articles: Papers that cite this
        - references: Papers this cites
        - metrics: Citation metrics
        - summary: Auto-generated summary
        - alerts: Important findings
        - generated_at: Timestamp

    Example:
        >>> report = comprehensive_article_report("17299597")
        >>> print(report['summary'])
    """
    # Validate PMID
    try:
        pmid = validate_pmid_param(pmid)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message,
                "suggestion": e.suggestion
            }
        }

    # Initialize report
    report = {
        "success": True,
        "pmid": pmid,
        "generated_at": datetime.now().isoformat(),
        "sections": {},
        "alerts": []
    }

    # 1. Fetch article metadata
    logger.info(f"Fetching article metadata for PMID {pmid}")
    article = fetch_abstract(pmid)

    if not article.get("success"):
        return {
            "success": False,
            "pmid": pmid,
            "error": article.get("error")
        }

    report["article"] = article
    report["sections"]["article"] = {
        "status": "success",
        "title": article.get("title"),
        "authors": article.get("authors"),
        "journal": article.get("journal"),
        "year": article.get("year"),
        "abstract": article.get("abstract"),
        "doi": article.get("doi"),
        "pmc": article.get("pmc"),
        "mesh_terms": article.get("mesh_terms"),
        "keywords": article.get("keywords")
    }

    # 2. Check and fetch full text
    if include_fulltext:
        logger.info(f"Checking full text availability")
        oa_status = check_oa_availability(pmid)

        if oa_status.get("available"):
            fulltext = get_fulltext(pmid)
            if fulltext.get("success"):
                report["sections"]["fulltext"] = {
                    "status": "success",
                    "available": True,
                    "pmcid": fulltext.get("pmcid"),
                    "word_count": fulltext.get("word_count"),
                    "sections": list(fulltext.get("sections", {}).keys()),
                    "figures": len(fulltext.get("figures", [])),
                    "tables": len(fulltext.get("tables", []))
                }
                report["fulltext"] = fulltext
            else:
                report["sections"]["fulltext"] = {
                    "status": "failed",
                    "available": False,
                    "error": fulltext.get("error", {}).get("message")
                }
        else:
            report["sections"]["fulltext"] = {
                "status": "unavailable",
                "available": False,
                "message": "Full text not in PMC Open Access"
            }
    else:
        report["sections"]["fulltext"] = {
            "status": "skipped"
        }

    # 3. Find similar articles
    logger.info(f"Finding similar articles")
    similar = find_similar_articles(pmid, max_results=max_similar)

    if similar.get("success"):
        report["sections"]["similar"] = {
            "status": "success",
            "count": similar.get("similar_count", 0),
            "articles": similar.get("articles", [])
        }
        report["similar_articles"] = similar.get("articles", [])
    else:
        report["sections"]["similar"] = {
            "status": "failed",
            "error": similar.get("error", {}).get("message")
        }

    # 4. Get citing articles
    logger.info(f"Finding citing articles")
    citing = get_citing_articles(pmid, max_results=max_citations)

    if citing.get("success"):
        report["sections"]["citing"] = {
            "status": "success",
            "total_count": citing.get("citation_count", 0),
            "returned": len(citing.get("articles", [])),
            "by_year": {str(k): len(v) for k, v in citing.get("by_year", {}).items()},
            "articles": citing.get("articles", [])
        }
        report["citing_articles"] = citing.get("articles", [])

        # Alert for highly cited articles
        total_citations = citing.get("citation_count", 0)
        if total_citations > 500:
            report["alerts"].append(
                f"Highly cited article: {total_citations:,} citations"
            )
        elif total_citations > 100:
            report["alerts"].append(
                f"Well-cited article: {total_citations:,} citations"
            )
    else:
        report["sections"]["citing"] = {
            "status": "failed",
            "error": citing.get("error", {}).get("message")
        }

    # 5. Get references
    logger.info(f"Finding references")
    refs = get_references(pmid, max_results=max_references)

    if refs.get("success"):
        report["sections"]["references"] = {
            "status": "success",
            "count": refs.get("reference_count", 0),
            "articles": refs.get("articles", [])
        }
        report["references"] = refs.get("articles", [])
    else:
        report["sections"]["references"] = {
            "status": "failed",
            "error": refs.get("error", {}).get("message")
        }

    # 6. Citation metrics
    if include_metrics:
        logger.info(f"Calculating citation metrics")
        metrics = get_citation_metrics(pmid)

        if metrics.get("success"):
            report["sections"]["metrics"] = {
                "status": "success",
                "total_citations": metrics.get("total_citations"),
                "citations_per_year": metrics.get("citations_per_year"),
                "recent_velocity": metrics.get("recent_velocity"),
                "publication_year": metrics.get("publication_year"),
                "years_since_publication": metrics.get("years_since_publication")
            }
            report["metrics"] = metrics

            # Alert for high citation velocity
            if metrics.get("recent_velocity", 0) > 50:
                report["alerts"].append(
                    f"High recent citation velocity: {metrics['recent_velocity']:.1f} citations/year"
                )
        else:
            report["sections"]["metrics"] = {
                "status": "failed",
                "error": metrics.get("error", {}).get("message")
            }
    else:
        report["sections"]["metrics"] = {
            "status": "skipped"
        }

    # 7. Generate summary
    report["summary"] = _generate_summary(report)

    # 8. Generate quick stats
    report["quick_stats"] = _generate_quick_stats(report)

    return report


def _generate_summary(report: Dict[str, Any]) -> str:
    """Generate human-readable summary from report."""
    article = report.get("sections", {}).get("article", {})
    citing = report.get("sections", {}).get("citing", {})
    metrics = report.get("sections", {}).get("metrics", {})
    fulltext = report.get("sections", {}).get("fulltext", {})

    title = article.get("title", "This article")
    year = article.get("year", "")
    journal = article.get("journal", "")
    citations = citing.get("total_count", 0)

    parts = []

    # Basic info
    if year and journal:
        parts.append(f"Published in {journal} ({year})")
    elif year:
        parts.append(f"Published in {year}")

    # Citation impact
    if citations > 0:
        if citations > 500:
            parts.append(f"highly cited with {citations:,} citations")
        elif citations > 100:
            parts.append(f"well-cited with {citations:,} citations")
        else:
            parts.append(f"cited {citations:,} times")

    # Citation velocity
    velocity = metrics.get("recent_velocity", 0)
    if velocity > 20:
        parts.append(f"receiving {velocity:.1f} citations/year recently")

    # Full text availability
    if fulltext.get("available"):
        parts.append("full text available")

    # Combine
    if parts:
        return f"{title}: {'; '.join(parts)}."
    return f"{title}."


def _generate_quick_stats(report: Dict[str, Any]) -> Dict[str, Any]:
    """Generate quick statistics summary."""
    article = report.get("sections", {}).get("article", {})
    citing = report.get("sections", {}).get("citing", {})
    similar = report.get("sections", {}).get("similar", {})
    refs = report.get("sections", {}).get("references", {})
    fulltext = report.get("sections", {}).get("fulltext", {})
    metrics = report.get("sections", {}).get("metrics", {})

    return {
        "publication_year": article.get("year"),
        "journal": article.get("journal"),
        "total_citations": citing.get("total_count", 0),
        "similar_articles_found": similar.get("count", 0),
        "references_in_pubmed": refs.get("count", 0),
        "fulltext_available": fulltext.get("available", False),
        "citations_per_year": metrics.get("citations_per_year", 0),
        "recent_velocity": metrics.get("recent_velocity", 0)
    }


def literature_overview(
    query: str,
    max_articles: int = 10,
    include_similar: bool = False
) -> Dict[str, Any]:
    """
    Generate overview of literature on a topic.

    Args:
        query: Search query
        max_articles: Maximum articles to analyze
        include_similar: Include similar articles for each

    Returns:
        Dict with literature overview
    """
    # Search for articles
    search_result = search_pubmed(query, max_results=max_articles, sort="relevance")

    if not search_result.get("success"):
        return search_result

    articles = search_result.get("articles", [])

    overview = {
        "success": True,
        "query": query,
        "generated_at": datetime.now().isoformat(),
        "total_found": search_result.get("count", 0),
        "analyzed": len(articles),
        "articles": [],
        "year_distribution": {},
        "top_journals": {},
        "common_authors": {}
    }

    # Analyze each article
    for article in articles:
        pmid = article.get("pmid")

        # Get citation count
        citing = get_citing_articles(pmid, max_results=1, include_summaries=False)
        citation_count = citing.get("citation_count", 0) if citing.get("success") else 0

        article_summary = {
            "pmid": pmid,
            "title": article.get("title"),
            "authors": article.get("authors"),
            "journal": article.get("journal"),
            "year": article.get("year"),
            "citations": citation_count
        }

        overview["articles"].append(article_summary)

        # Track year distribution
        year = article.get("year")
        if year:
            overview["year_distribution"][year] = overview["year_distribution"].get(year, 0) + 1

        # Track journals
        journal = article.get("journal")
        if journal:
            overview["top_journals"][journal] = overview["top_journals"].get(journal, 0) + 1

    # Sort journals by frequency
    overview["top_journals"] = dict(
        sorted(overview["top_journals"].items(), key=lambda x: x[1], reverse=True)[:10]
    )

    # Sort years
    overview["year_distribution"] = dict(
        sorted(overview["year_distribution"].items(), reverse=True)
    )

    # Sort articles by citations
    overview["articles"].sort(key=lambda x: x.get("citations", 0), reverse=True)

    # Generate insights
    overview["insights"] = _generate_literature_insights(overview)

    return overview


def _generate_literature_insights(overview: Dict[str, Any]) -> List[str]:
    """Generate insights from literature overview."""
    insights = []

    total = overview.get("total_found", 0)
    analyzed = overview.get("analyzed", 0)

    insights.append(f"Found {total:,} articles matching query")

    # Year trend
    years = overview.get("year_distribution", {})
    if years:
        most_recent = max(years.keys())
        insights.append(f"Most recent publication: {most_recent}")

    # Top journals
    journals = overview.get("top_journals", {})
    if journals:
        top_journal = list(journals.keys())[0]
        insights.append(f"Most common journal: {top_journal}")

    # Highly cited
    articles = overview.get("articles", [])
    highly_cited = [a for a in articles if a.get("citations", 0) > 100]
    if highly_cited:
        insights.append(f"{len(highly_cited)} highly cited articles (>100 citations)")

    return insights


def compare_articles(pmids: List[str]) -> Dict[str, Any]:
    """
    Compare multiple articles.

    Args:
        pmids: List of PMIDs to compare

    Returns:
        Dict with comparison data
    """
    if len(pmids) < 2:
        return {
            "success": False,
            "error": {
                "code": "INSUFFICIENT_ARTICLES",
                "message": "At least 2 PMIDs required for comparison"
            }
        }

    comparison = {
        "success": True,
        "pmids": pmids,
        "generated_at": datetime.now().isoformat(),
        "articles": [],
        "comparison_matrix": {}
    }

    for pmid in pmids:
        article = fetch_abstract(pmid)
        if article.get("success"):
            citing = get_citing_articles(pmid, max_results=1, include_summaries=False)

            comparison["articles"].append({
                "pmid": pmid,
                "title": article.get("title"),
                "year": article.get("year"),
                "journal": article.get("journal"),
                "citations": citing.get("citation_count", 0) if citing.get("success") else 0,
                "mesh_terms": article.get("mesh_terms", []),
                "keywords": article.get("keywords", [])
            })

    # Find shared MeSH terms
    if len(comparison["articles"]) >= 2:
        mesh_sets = [set(a.get("mesh_terms", [])) for a in comparison["articles"]]
        shared_mesh = mesh_sets[0]
        for ms in mesh_sets[1:]:
            shared_mesh &= ms

        comparison["shared_mesh_terms"] = list(shared_mesh)

    return comparison


def format_comprehensive_report(report: Dict[str, Any]) -> str:
    """
    Format comprehensive report for display.

    Args:
        report: Comprehensive report dict

    Returns:
        Formatted string for display
    """
    if not report.get("success"):
        error = report.get("error", {})
        return f"Error: {error.get('message', 'Unknown error')}"

    lines = []
    pmid = report.get("pmid", "")
    article = report.get("sections", {}).get("article", {})
    quick_stats = report.get("quick_stats", {})

    lines.append(f"## Comprehensive Report: PMID {pmid}")
    lines.append("")

    # Article info
    lines.append("### Article Information")
    lines.append("")
    lines.append(f"**Title**: {article.get('title', 'N/A')}")

    authors = article.get("authors", [])
    if authors:
        author_str = format_authors(authors, max_authors=5)
        lines.append(f"**Authors**: {author_str}")

    lines.append(f"**Journal**: {article.get('journal', 'N/A')}")
    lines.append(f"**Year**: {article.get('year', 'N/A')}")

    if article.get("doi"):
        lines.append(f"**DOI**: {article.get('doi')}")

    lines.append(f"**Citations**: {quick_stats.get('total_citations', 0):,}")
    lines.append("")

    # Abstract
    abstract = article.get("abstract")
    if abstract:
        lines.append("### Abstract")
        lines.append("")
        lines.append(abstract)
        lines.append("")

    # Full text status
    fulltext = report.get("sections", {}).get("fulltext", {})
    if fulltext.get("available"):
        lines.append("### Full Text")
        lines.append(f"Available in PMC ({fulltext.get('pmcid', '')})")
        lines.append(f"Word count: {fulltext.get('word_count', 0):,}")
        lines.append(f"Sections: {', '.join(fulltext.get('sections', []))}")
        lines.append("")

    # Metrics
    metrics = report.get("sections", {}).get("metrics", {})
    if metrics.get("status") == "success":
        lines.append("### Citation Metrics")
        lines.append(f"- Total citations: {metrics.get('total_citations', 0):,}")
        lines.append(f"- Citations/year: {metrics.get('citations_per_year', 0):.1f}")
        lines.append(f"- Recent velocity: {metrics.get('recent_velocity', 0):.1f} citations/year")
        lines.append(f"- Years since publication: {metrics.get('years_since_publication', 0)}")
        lines.append("")

    # Similar articles
    similar = report.get("similar_articles", [])
    if similar:
        lines.append(f"### Similar Articles (Top {len(similar)})")
        lines.append("")
        for i, art in enumerate(similar[:5], 1):
            score = art.get("score")
            score_str = f" (Score: {score})" if score else ""
            lines.append(f"{i}. {art.get('title', 'Untitled')[:70]}...{score_str}")
            lines.append(f"   PMID: {art.get('pmid')}")
        lines.append("")

    # Citing articles
    citing = report.get("citing_articles", [])
    if citing:
        lines.append(f"### Recent Citations (Top {len(citing)})")
        lines.append("")
        for i, art in enumerate(citing[:5], 1):
            lines.append(f"{i}. {art.get('title', 'Untitled')[:70]}...")
            lines.append(f"   {art.get('journal', '')}, {art.get('year', '')}")
            lines.append(f"   PMID: {art.get('pmid')}")
        lines.append("")

    # Alerts
    alerts = report.get("alerts", [])
    if alerts:
        lines.append("### Key Findings")
        for alert in alerts:
            lines.append(f"- {alert}")
        lines.append("")

    # Summary
    summary = report.get("summary")
    if summary:
        lines.append("### Summary")
        lines.append(summary)

    return "\n".join(lines)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test comprehensive report functionality."""
    print("Testing Comprehensive Report...\n")

    # Test comprehensive article report
    print("1. Comprehensive article report (PMID 17299597):")
    report = comprehensive_article_report("17299597", max_similar=3, max_citations=5)

    if report["success"]:
        print(f"   Title: {report['sections']['article'].get('title', '')[:50]}...")
        print(f"   Quick stats: {report.get('quick_stats', {})}")
        print(f"   Alerts: {report.get('alerts', [])}")
        print(f"   Summary: {report.get('summary', '')}")
    else:
        print(f"   Error: {report.get('error', {}).get('message')}")

    # Test formatted output
    print("\n2. Formatted comprehensive report:")
    formatted = format_comprehensive_report(report)
    # Print first 40 lines
    for line in formatted.split('\n')[:40]:
        print(line)
    print("...")

    # Test literature overview
    print("\n3. Literature overview (CRISPR):")
    overview = literature_overview("CRISPR gene editing", max_articles=5)

    if overview["success"]:
        print(f"   Total found: {overview['total_found']}")
        print(f"   Analyzed: {overview['analyzed']}")
        print(f"   Top journals: {list(overview.get('top_journals', {}).keys())[:3]}")
        print(f"   Insights: {overview.get('insights', [])}")
    else:
        print(f"   Error: {overview.get('error', {}).get('message')}")

    # Test article comparison
    print("\n4. Article comparison:")
    comparison = compare_articles(["17299597", "32756549"])

    if comparison["success"]:
        print(f"   Comparing {len(comparison['articles'])} articles")
        shared = comparison.get("shared_mesh_terms", [])
        print(f"   Shared MeSH terms: {shared[:5] if shared else 'None found'}")
    else:
        print(f"   Error: {comparison.get('error', {}).get('message')}")

    print("\nAll comprehensive report tests completed!")


if __name__ == "__main__":
    main()
