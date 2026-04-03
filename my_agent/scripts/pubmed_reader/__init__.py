"""
PubMed Reader scripts package.

Provides comprehensive access to PubMed literature through NCBI E-utilities and BioC APIs.
"""

from .search_pubmed import (
    search_pubmed,
    fetch_summaries,
    build_advanced_query,
    search_by_date_range,
    search_by_year,
    format_search_results,
)

from .fetch_article import (
    fetch_abstract,
    fetch_metadata,
    batch_fetch,
    parse_pubmed_xml,
    format_article,
)

from .fetch_fulltext import (
    check_oa_availability,
    get_fulltext,
    pmid_to_pmcid,
    pmcid_to_pmid,
    extract_sections,
    format_fulltext,
)

from .find_similar import (
    find_similar_articles,
    find_by_mesh_terms,
    find_by_author,
    find_review_articles,
    format_similar_results,
)

from .find_citations import (
    get_citing_articles,
    get_references,
    get_citation_network,
    get_citation_metrics,
    format_citation_results,
)

from .comprehensive_report import (
    comprehensive_article_report,
    literature_overview,
    compare_articles,
    format_comprehensive_report,
)

__all__ = [
    # Search
    'search_pubmed',
    'fetch_summaries',
    'build_advanced_query',
    'search_by_date_range',
    'search_by_year',
    'format_search_results',
    # Fetch
    'fetch_abstract',
    'fetch_metadata',
    'batch_fetch',
    'parse_pubmed_xml',
    'format_article',
    # Full text
    'check_oa_availability',
    'get_fulltext',
    'pmid_to_pmcid',
    'pmcid_to_pmid',
    'extract_sections',
    'format_fulltext',
    # Similar
    'find_similar_articles',
    'find_by_mesh_terms',
    'find_by_author',
    'find_review_articles',
    'format_similar_results',
    # Citations
    'get_citing_articles',
    'get_references',
    'get_citation_network',
    'get_citation_metrics',
    'format_citation_results',
    # Comprehensive
    'comprehensive_article_report',
    'literature_overview',
    'compare_articles',
    'format_comprehensive_report',
]
