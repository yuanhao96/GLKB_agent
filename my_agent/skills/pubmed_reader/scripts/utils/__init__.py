"""
Utility modules for PubMed Reader skill.
"""

from .helpers import (
    validate_pmid,
    validate_pmcid,
    validate_doi,
    extract_pmid_from_text,
    get_current_year,
    get_current_date,
    format_pubmed_date,
    parse_pubmed_date,
    get_date_range,
    extract_year,
    format_authors,
    format_single_author,
    format_citation,
    clean_abstract,
    truncate_text,
    extract_structured_abstract,
    get_api_key,
    get_email,
    build_api_params,
    format_search_result,
    format_year_message,
)

from .cache_manager import (
    CacheManager,
    get_cache,
    cache_search_results,
    get_cached_search,
    cache_article_metadata,
    get_cached_metadata,
    cache_fulltext,
    get_cached_fulltext,
    cache_citations,
    get_cached_citations,
)

from .rate_limiter import (
    RateLimiter,
    AdaptiveRateLimiter,
    get_rate_limiter,
    throttle,
    report_success,
    report_error,
)

__all__ = [
    # Helpers
    'validate_pmid',
    'validate_pmcid',
    'validate_doi',
    'extract_pmid_from_text',
    'get_current_year',
    'get_current_date',
    'format_pubmed_date',
    'parse_pubmed_date',
    'get_date_range',
    'extract_year',
    'format_authors',
    'format_single_author',
    'format_citation',
    'clean_abstract',
    'truncate_text',
    'extract_structured_abstract',
    'get_api_key',
    'get_email',
    'build_api_params',
    'format_search_result',
    'format_year_message',
    # Cache
    'CacheManager',
    'get_cache',
    'cache_search_results',
    'get_cached_search',
    'cache_article_metadata',
    'get_cached_metadata',
    'cache_fulltext',
    'get_cached_fulltext',
    'cache_citations',
    'get_cached_citations',
    # Rate limiting
    'RateLimiter',
    'AdaptiveRateLimiter',
    'get_rate_limiter',
    'throttle',
    'report_success',
    'report_error',
]
