#!/usr/bin/env python3
"""
Strategic Literature Search - Reviews First, Then Research Articles.

This module implements a biologist's approach to literature exploration:
1. Start with review articles to understand the domain landscape
2. Identify key themes and seminal works from reviews
3. Drill down to research articles for specific details
4. Build a comprehensive understanding from general to specific
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

# Add utils to path
# sys.path removed for package imports
from .utils.helpers import build_api_params, get_current_year
from .utils.validators.parameter_validator import validate_query_param, ValidationError
from .utils.rate_limiter import throttle, report_success, report_error

from .search_pubmed import search_pubmed, build_advanced_query, fetch_summaries
from .fetch_article import fetch_abstract
from .find_similar import find_similar_articles
from .find_citations import get_citing_articles

logger = logging.getLogger(__name__)


def strategic_literature_search(
    topic: str,
    max_reviews: int = 5,
    max_research_per_review: int = 3,
    years_back: int = 5,
    include_seminal_works: bool = True,
    focus_areas: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Perform strategic literature search: reviews first, then research articles.

    This mimics how experienced biologists explore literature:
    1. Find authoritative review articles for domain overview
    2. Extract key themes and cited works from reviews
    3. Drill down to primary research for specific findings
    4. Identify seminal/highly-cited works in the field

    Args:
        topic: Main research topic/query
        max_reviews: Maximum review articles to analyze (default: 5)
        max_research_per_review: Research articles to find per review theme (default: 3)
        years_back: How many years back to search (default: 5)
        include_seminal_works: Include highly-cited foundational papers (default: True)
        focus_areas: Optional list of subtopics to focus on

    Returns:
        Dict containing:
        - success: bool
        - topic: Search topic
        - phase1_reviews: List of review articles with summaries
        - phase2_themes: Extracted themes from reviews
        - phase3_research: Research articles organized by theme
        - seminal_works: Highly-cited foundational papers
        - reading_order: Suggested order for reading
        - summary: Executive summary of the literature landscape

    Example:
        >>> result = strategic_literature_search("type 1 diabetes pathogenesis")
        >>> print(result['reading_order'])
        # Shows recommended reading sequence: reviews -> key research
    """
    # Validate input
    try:
        topic = validate_query_param(topic)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message,
                "suggestion": e.suggestion
            }
        }

    result = {
        "success": True,
        "topic": topic,
        "generated_at": datetime.now().isoformat(),
        "search_strategy": "reviews_first",
        "years_covered": years_back,
        "phases": {}
    }

    # ==========================================================================
    # PHASE 1: Find Review Articles (Domain Overview)
    # ==========================================================================
    logger.info(f"Phase 1: Searching for review articles on '{topic}'")

    current_year = get_current_year()
    min_year = current_year - years_back

    # Build query for reviews
    review_query = build_advanced_query(
        terms=[topic],
        article_types=["Review", "Systematic Review", "Meta-Analysis"]
    )

    reviews_result = search_pubmed(
        query=review_query,
        max_results=max_reviews * 2,  # Get extra to filter
        min_date=f"{min_year}/01/01",
        sort="relevance",
        include_summaries=True
    )

    if not reviews_result.get("success"):
        # Fallback: try simpler query
        review_query = f"({topic}) AND (review[pt] OR systematic review[pt])"
        reviews_result = search_pubmed(
            query=review_query,
            max_results=max_reviews * 2,
            min_date=f"{min_year}/01/01",
            sort="relevance",
            include_summaries=True
        )

    phase1_reviews = []
    if reviews_result.get("success") and reviews_result.get("articles"):
        # Score and rank reviews
        scored_reviews = _score_reviews(reviews_result["articles"])
        top_reviews = scored_reviews[:max_reviews]

        for review in top_reviews:
            pmid = review.get("pmid")

            # Fetch full abstract for each review
            abstract_result = fetch_abstract(pmid)

            review_info = {
                "pmid": pmid,
                "title": review.get("title"),
                "authors": review.get("authors"),
                "journal": review.get("journal"),
                "year": review.get("year"),
                "pub_types": review.get("pub_types", []),
                "relevance_score": review.get("_score", 0),
                "abstract": abstract_result.get("abstract") if abstract_result.get("success") else None,
                "mesh_terms": abstract_result.get("mesh_terms", []) if abstract_result.get("success") else [],
                "keywords": abstract_result.get("keywords", []) if abstract_result.get("success") else []
            }

            # Extract key themes from this review
            review_info["extracted_themes"] = _extract_themes_from_review(review_info)

            phase1_reviews.append(review_info)

    result["phases"]["phase1_reviews"] = {
        "description": "Review articles providing domain overview",
        "count": len(phase1_reviews),
        "articles": phase1_reviews
    }

    # ==========================================================================
    # PHASE 2: Extract Themes and Key Concepts
    # ==========================================================================
    logger.info("Phase 2: Extracting themes from reviews")

    all_themes = []
    all_mesh_terms = []

    for review in phase1_reviews:
        all_themes.extend(review.get("extracted_themes", []))
        all_mesh_terms.extend(review.get("mesh_terms", []))

    # Consolidate and rank themes
    theme_counts = {}
    for theme in all_themes:
        theme_lower = theme.lower()
        theme_counts[theme_lower] = theme_counts.get(theme_lower, 0) + 1

    # Top themes by frequency across reviews
    top_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Use focus areas if provided, otherwise use extracted themes
    search_themes = focus_areas if focus_areas else [t[0] for t in top_themes[:5]]

    result["phases"]["phase2_themes"] = {
        "description": "Key themes extracted from review articles",
        "all_themes": list(theme_counts.keys()),
        "top_themes": [{"theme": t[0], "frequency": t[1]} for t in top_themes],
        "mesh_terms_common": _get_common_terms(all_mesh_terms, min_count=2),
        "focus_themes": search_themes
    }

    # ==========================================================================
    # PHASE 3: Find Research Articles by Theme
    # ==========================================================================
    logger.info("Phase 3: Finding research articles by theme")

    phase3_research = {}

    for theme in search_themes[:5]:  # Limit to top 5 themes
        # Build query for original research on this theme
        research_query = build_advanced_query(
            terms=[topic, theme],
            article_types=None,  # All article types
            boolean_op="AND"
        )

        # Exclude reviews to get original research
        research_query = f"({research_query}) NOT (review[pt])"

        research_result = search_pubmed(
            query=research_query,
            max_results=max_research_per_review,
            min_date=f"{min_year}/01/01",
            sort="relevance",
            include_summaries=True
        )

        theme_articles = []
        if research_result.get("success") and research_result.get("articles"):
            for article in research_result["articles"]:
                pmid = article.get("pmid")

                # Get citation count for impact assessment
                citing_result = get_citing_articles(pmid, max_results=1, include_summaries=False)
                citation_count = citing_result.get("citation_count", 0) if citing_result.get("success") else 0

                theme_articles.append({
                    "pmid": pmid,
                    "title": article.get("title"),
                    "authors": article.get("authors"),
                    "journal": article.get("journal"),
                    "year": article.get("year"),
                    "citations": citation_count,
                    "pmc": article.get("pmc")
                })

        # Sort by citations within theme
        theme_articles.sort(key=lambda x: x.get("citations", 0), reverse=True)

        phase3_research[theme] = {
            "query_used": research_query,
            "count": len(theme_articles),
            "articles": theme_articles
        }

    result["phases"]["phase3_research"] = {
        "description": "Primary research articles organized by theme",
        "themes": phase3_research
    }

    # ==========================================================================
    # PHASE 4: Identify Seminal Works (Highly-Cited Foundational Papers)
    # ==========================================================================
    if include_seminal_works:
        logger.info("Phase 4: Identifying seminal works")

        # Search for highly-cited older papers
        seminal_query = f"({topic})"
        seminal_result = search_pubmed(
            query=seminal_query,
            max_results=20,
            max_date=f"{current_year - 3}/12/31",  # At least 3 years old
            sort="relevance",
            include_summaries=True
        )

        seminal_works = []
        if seminal_result.get("success") and seminal_result.get("articles"):
            for article in seminal_result["articles"]:
                pmid = article.get("pmid")

                # Get citation count
                citing_result = get_citing_articles(pmid, max_results=1, include_summaries=False)
                citation_count = citing_result.get("citation_count", 0) if citing_result.get("success") else 0

                # Only include if highly cited (>100 citations)
                if citation_count >= 100:
                    seminal_works.append({
                        "pmid": pmid,
                        "title": article.get("title"),
                        "authors": article.get("authors"),
                        "journal": article.get("journal"),
                        "year": article.get("year"),
                        "citations": citation_count,
                        "impact": _classify_impact(citation_count)
                    })

            # Sort by citations
            seminal_works.sort(key=lambda x: x.get("citations", 0), reverse=True)
            seminal_works = seminal_works[:10]  # Top 10 seminal works

        result["phases"]["phase4_seminal"] = {
            "description": "Highly-cited foundational papers in the field",
            "count": len(seminal_works),
            "articles": seminal_works
        }

    # ==========================================================================
    # Generate Reading Order and Summary
    # ==========================================================================
    reading_order = _generate_reading_order(result)
    result["reading_order"] = reading_order

    result["summary"] = _generate_strategic_summary(result)

    # Statistics
    total_reviews = len(phase1_reviews)
    total_research = sum(
        len(theme_data["articles"])
        for theme_data in phase3_research.values()
    )
    total_seminal = len(result.get("phases", {}).get("phase4_seminal", {}).get("articles", []))

    result["statistics"] = {
        "total_reviews": total_reviews,
        "total_research_articles": total_research,
        "total_seminal_works": total_seminal,
        "total_articles": total_reviews + total_research + total_seminal,
        "themes_identified": len(search_themes),
        "years_covered": years_back
    }

    return result


def _score_reviews(articles: List[Dict]) -> List[Dict]:
    """
    Score and rank review articles by relevance and quality signals.

    Scoring factors:
    - Recency (newer reviews more relevant)
    - Journal quality (Nature Reviews, Annual Reviews, etc.)
    - Article type (systematic reviews > narrative reviews)
    - Title relevance
    """
    high_quality_journals = [
        "nature reviews", "annual review", "lancet", "nejm", "jama",
        "cell", "science", "nat rev", "physiological reviews",
        "pharmacological reviews", "endocrine reviews", "diabetes care"
    ]

    current_year = get_current_year()
    scored = []

    for article in articles:
        score = 0

        # Recency score (max 30 points)
        year = article.get("year")
        if year:
            years_old = current_year - year
            score += max(0, 30 - (years_old * 5))

        # Journal quality score (max 30 points)
        journal = (article.get("journal") or "").lower()
        if any(hq in journal for hq in high_quality_journals):
            score += 30
        elif "review" in journal:
            score += 15

        # Article type score (max 20 points)
        pub_types = article.get("pub_types", [])
        pub_types_lower = [pt.lower() for pt in pub_types]
        if any("systematic" in pt for pt in pub_types_lower):
            score += 20
        elif any("meta-analysis" in pt for pt in pub_types_lower):
            score += 20
        elif any("review" in pt for pt in pub_types_lower):
            score += 10

        # Title signals (max 20 points)
        title = (article.get("title") or "").lower()
        if "comprehensive" in title or "systematic" in title:
            score += 10
        if "update" in title or "advances" in title or "recent" in title:
            score += 5
        if "overview" in title or "landscape" in title:
            score += 5

        article["_score"] = score
        scored.append(article)

    # Sort by score descending
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def _extract_themes_from_review(review: Dict) -> List[str]:
    """
    Extract key themes/topics from a review article.

    Sources:
    - MeSH terms (most reliable)
    - Keywords
    - Title keywords
    """
    themes = []

    # From MeSH terms
    mesh_terms = review.get("mesh_terms", [])
    for term in mesh_terms:
        # Extract main term (before any qualifiers)
        if isinstance(term, dict):
            term = term.get("term", "")
        main_term = term.split("/")[0].strip()
        if main_term and len(main_term) > 3:
            themes.append(main_term)

    # From keywords
    keywords = review.get("keywords", [])
    for kw in keywords:
        if kw and len(kw) > 3:
            themes.append(kw)

    # From title (extract noun phrases)
    title = review.get("title", "")
    if title:
        # Simple extraction: words that are likely concepts
        import re
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', title)
        themes.extend(words)

    # Deduplicate while preserving order
    seen = set()
    unique_themes = []
    for theme in themes:
        theme_lower = theme.lower()
        if theme_lower not in seen and len(theme) > 3:
            seen.add(theme_lower)
            unique_themes.append(theme)

    return unique_themes[:20]  # Max 20 themes per review


def _get_common_terms(terms: List[str], min_count: int = 2) -> List[Dict]:
    """Get terms that appear multiple times across reviews."""
    term_counts = {}
    for term in terms:
        term_lower = term.lower() if isinstance(term, str) else str(term).lower()
        term_counts[term_lower] = term_counts.get(term_lower, 0) + 1

    common = [
        {"term": term, "count": count}
        for term, count in term_counts.items()
        if count >= min_count
    ]

    return sorted(common, key=lambda x: x["count"], reverse=True)[:20]


def _classify_impact(citation_count: int) -> str:
    """Classify paper impact based on citation count."""
    if citation_count >= 1000:
        return "landmark"
    elif citation_count >= 500:
        return "highly influential"
    elif citation_count >= 200:
        return "influential"
    elif citation_count >= 100:
        return "well-cited"
    else:
        return "cited"


def _generate_reading_order(result: Dict) -> List[Dict]:
    """
    Generate suggested reading order for the literature.

    Strategy:
    1. Start with most comprehensive/recent review
    2. Read 1-2 more reviews for different perspectives
    3. Read seminal works for foundational understanding
    4. Dive into research articles by theme of interest
    """
    reading_order = []
    order_num = 1

    # Phase 1: Reviews (start here)
    reviews = result.get("phases", {}).get("phase1_reviews", {}).get("articles", [])
    for i, review in enumerate(reviews[:3]):  # Top 3 reviews
        reading_order.append({
            "order": order_num,
            "phase": "overview",
            "pmid": review.get("pmid"),
            "title": review.get("title"),
            "type": "review",
            "reason": "Start with domain overview" if i == 0 else "Additional perspective",
            "priority": "high" if i == 0 else "medium"
        })
        order_num += 1

    # Phase 2: Seminal works (foundational understanding)
    seminal = result.get("phases", {}).get("phase4_seminal", {}).get("articles", [])
    for i, work in enumerate(seminal[:5]):  # Top 5 seminal
        reading_order.append({
            "order": order_num,
            "phase": "foundational",
            "pmid": work.get("pmid"),
            "title": work.get("title"),
            "type": "seminal",
            "citations": work.get("citations"),
            "reason": f"Foundational paper ({work.get('citations'):,} citations)",
            "priority": "high" if i < 2 else "medium"
        })
        order_num += 1

    # Phase 3: Research by theme (detailed exploration)
    research_by_theme = result.get("phases", {}).get("phase3_research", {}).get("themes", {})
    for theme, theme_data in research_by_theme.items():
        for i, article in enumerate(theme_data.get("articles", [])[:2]):  # Top 2 per theme
            reading_order.append({
                "order": order_num,
                "phase": "deep_dive",
                "pmid": article.get("pmid"),
                "title": article.get("title"),
                "type": "research",
                "theme": theme,
                "reason": f"Primary research on {theme}",
                "priority": "medium" if i == 0 else "low"
            })
            order_num += 1

    return reading_order


def _generate_strategic_summary(result: Dict) -> str:
    """Generate executive summary of the literature search."""
    topic = result.get("topic", "")
    stats = result.get("statistics", {})

    reviews = result.get("phases", {}).get("phase1_reviews", {}).get("articles", [])
    themes = result.get("phases", {}).get("phase2_themes", {}).get("top_themes", [])
    seminal = result.get("phases", {}).get("phase4_seminal", {}).get("articles", [])

    parts = []

    # Overview
    parts.append(f"Literature search on '{topic}' identified {stats.get('total_articles', 0)} key articles.")

    # Reviews insight
    if reviews:
        top_review = reviews[0]
        parts.append(
            f"Start with '{top_review.get('title', '')[:60]}...' "
            f"({top_review.get('journal')}, {top_review.get('year')}) for domain overview."
        )

    # Themes
    if themes:
        top_theme_names = [t["theme"] for t in themes[:3]]
        parts.append(f"Key themes: {', '.join(top_theme_names)}.")

    # Seminal works
    if seminal:
        top_seminal = seminal[0]
        parts.append(
            f"Most cited foundational work: '{top_seminal.get('title', '')[:50]}...' "
            f"with {top_seminal.get('citations', 0):,} citations."
        )

    return " ".join(parts)


def format_strategic_search_results(result: Dict) -> str:
    """
    Format strategic search results for display.

    Args:
        result: Strategic search result dict

    Returns:
        Formatted markdown string
    """
    if not result.get("success"):
        error = result.get("error", {})
        return f"Search failed: {error.get('message', 'Unknown error')}"

    lines = []
    topic = result.get("topic", "")
    stats = result.get("statistics", {})

    lines.append(f"# Strategic Literature Search: {topic}")
    lines.append("")
    lines.append(f"*Generated: {result.get('generated_at', '')}*")
    lines.append("")

    # Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(result.get("summary", ""))
    lines.append("")

    # Statistics
    lines.append("## Search Statistics")
    lines.append("")
    lines.append(f"- **Total articles identified**: {stats.get('total_articles', 0)}")
    lines.append(f"- **Review articles**: {stats.get('total_reviews', 0)}")
    lines.append(f"- **Research articles**: {stats.get('total_research_articles', 0)}")
    lines.append(f"- **Seminal works**: {stats.get('total_seminal_works', 0)}")
    lines.append(f"- **Key themes identified**: {stats.get('themes_identified', 0)}")
    lines.append(f"- **Years covered**: {stats.get('years_covered', 0)}")
    lines.append("")

    # Phase 1: Reviews
    lines.append("## Phase 1: Review Articles (Start Here)")
    lines.append("")
    lines.append("*Read these first for domain overview*")
    lines.append("")

    reviews = result.get("phases", {}).get("phase1_reviews", {}).get("articles", [])
    for i, review in enumerate(reviews, 1):
        lines.append(f"### {i}. {review.get('title', 'Untitled')}")
        lines.append("")

        authors = review.get("authors", [])
        if authors:
            author_str = authors[0].get("LastName", "") if isinstance(authors[0], dict) else str(authors[0])
            if len(authors) > 1:
                author_str += " et al."
            lines.append(f"**Authors**: {author_str}")

        lines.append(f"**Journal**: {review.get('journal', 'N/A')}, {review.get('year', '')}")
        lines.append(f"**PMID**: {review.get('pmid', '')}")

        if review.get("extracted_themes"):
            lines.append(f"**Key themes**: {', '.join(review['extracted_themes'][:5])}")

        if review.get("abstract"):
            lines.append("")
            lines.append(f"**Abstract**: {review['abstract'][:500]}...")

        lines.append("")

    # Phase 2: Themes
    themes_data = result.get("phases", {}).get("phase2_themes", {})
    if themes_data.get("top_themes"):
        lines.append("## Phase 2: Key Themes Identified")
        lines.append("")
        for theme_info in themes_data["top_themes"][:10]:
            lines.append(f"- **{theme_info['theme']}** (mentioned in {theme_info['frequency']} reviews)")
        lines.append("")

    # Phase 3: Research by Theme
    research_data = result.get("phases", {}).get("phase3_research", {}).get("themes", {})
    if research_data:
        lines.append("## Phase 3: Primary Research by Theme")
        lines.append("")

        for theme, theme_articles in research_data.items():
            if theme_articles.get("articles"):
                lines.append(f"### Theme: {theme.title()}")
                lines.append("")

                for i, article in enumerate(theme_articles["articles"], 1):
                    citations = article.get("citations", 0)
                    citation_str = f" ({citations:,} citations)" if citations > 0 else ""

                    lines.append(f"{i}. **{article.get('title', 'Untitled')}**{citation_str}")
                    lines.append(f"   {article.get('journal', '')}, {article.get('year', '')} | PMID: {article.get('pmid', '')}")

                lines.append("")

    # Phase 4: Seminal Works
    seminal_data = result.get("phases", {}).get("phase4_seminal", {})
    if seminal_data.get("articles"):
        lines.append("## Phase 4: Seminal Works (Foundational Papers)")
        lines.append("")
        lines.append("*Highly-cited papers that shaped the field*")
        lines.append("")

        for i, work in enumerate(seminal_data["articles"], 1):
            lines.append(
                f"{i}. **{work.get('title', 'Untitled')}** "
                f"({work.get('citations', 0):,} citations - {work.get('impact', 'cited')})"
            )
            lines.append(f"   {work.get('journal', '')}, {work.get('year', '')} | PMID: {work.get('pmid', '')}")

        lines.append("")

    # Reading Order
    reading_order = result.get("reading_order", [])
    if reading_order:
        lines.append("## Suggested Reading Order")
        lines.append("")

        current_phase = None
        for item in reading_order:
            phase = item.get("phase", "")
            if phase != current_phase:
                phase_name = {
                    "overview": "**Start with Overview**",
                    "foundational": "**Foundational Papers**",
                    "deep_dive": "**Deep Dive by Theme**"
                }.get(phase, phase)
                lines.append("")
                lines.append(phase_name)
                current_phase = phase

            priority_marker = "⭐" if item.get("priority") == "high" else "○"
            lines.append(
                f"{priority_marker} {item.get('order')}. [{item.get('type', '')}] "
                f"PMID {item.get('pmid', '')} - {item.get('title', '')[:50]}..."
            )
            if item.get("reason"):
                lines.append(f"   *{item['reason']}*")

        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================

def quick_literature_overview(
    topic: str,
    max_reviews: int = 3
) -> Dict[str, Any]:
    """
    Quick literature overview - just reviews for fast domain understanding.

    Args:
        topic: Research topic
        max_reviews: Number of reviews to fetch (default: 3)

    Returns:
        Simplified result with just review articles
    """
    return strategic_literature_search(
        topic=topic,
        max_reviews=max_reviews,
        max_research_per_review=0,
        include_seminal_works=False
    )


def deep_literature_analysis(
    topic: str,
    focus_areas: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Deep literature analysis - comprehensive search with more articles.

    Args:
        topic: Research topic
        focus_areas: Specific subtopics to focus on

    Returns:
        Comprehensive result with many articles
    """
    return strategic_literature_search(
        topic=topic,
        max_reviews=10,
        max_research_per_review=5,
        years_back=10,
        include_seminal_works=True,
        focus_areas=focus_areas
    )


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test strategic literature search functionality."""
    print("Testing Strategic Literature Search...\n")

    # Test basic strategic search
    print("1. Strategic search for 'type 1 diabetes pathogenesis':")
    result = strategic_literature_search(
        topic="type 1 diabetes pathogenesis",
        max_reviews=3,
        max_research_per_review=2,
        years_back=5
    )

    if result["success"]:
        stats = result.get("statistics", {})
        print(f"   Total articles: {stats.get('total_articles', 0)}")
        print(f"   Reviews: {stats.get('total_reviews', 0)}")
        print(f"   Research: {stats.get('total_research_articles', 0)}")
        print(f"   Seminal: {stats.get('total_seminal_works', 0)}")
        print(f"   Themes: {stats.get('themes_identified', 0)}")
        print(f"\n   Summary: {result.get('summary', '')[:200]}...")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test formatted output
    print("\n2. Formatted output (first 50 lines):")
    formatted = format_strategic_search_results(result)
    for line in formatted.split('\n')[:50]:
        print(line)
    print("...")

    # Test quick overview
    print("\n3. Quick overview (reviews only):")
    quick = quick_literature_overview("CRISPR gene therapy", max_reviews=2)
    if quick["success"]:
        print(f"   Reviews found: {quick['statistics']['total_reviews']}")

    print("\nStrategic literature search tests completed!")


if __name__ == "__main__":
    main()
