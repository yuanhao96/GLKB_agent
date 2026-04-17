#!/usr/bin/env python3
"""
bioRxiv/medRxiv search functionality.

bioRxiv's own TDM API (https://api.biorxiv.org/, see https://www.biorxiv.org/tdm)
exposes date-range browsing and publisher/funder filtering, but **no keyword
search**. The bioRxiv website search is HTML-only and frequently 403s for
non-browser clients.

This module implements keyword search via Europe PMC
(https://europepmc.org/RestfulWebService), which indexes bioRxiv and medRxiv
under `SRC:PPR` with a `PUBLISHER:"bioRxiv"` / `PUBLISHER:"medRxiv"` discriminator
and returns a JSON document with the DOI, title, authors, abstract, date, and
citation count. We normalize the response to match the output of bioRxiv's
native API.

Date browsing (`browse_biorxiv_recent`) continues to use the native bioRxiv
API, which is keyword-free but returns full metadata including the JATS XML URL
needed for full-text retrieval.
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging
import time

from .utils.helpers import format_biorxiv_citation, extract_year
from .utils.validators.parameter_validator import (
    validate_query_param,
    validate_max_results,
    ValidationError,
)
from .utils.cache_manager import cache_search_results, get_cached_search
from .utils.rate_limiter import throttle, report_success, report_error

logger = logging.getLogger(__name__)

BIORXIV_API_URL = "https://api.biorxiv.org"
EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

USER_AGENT = 'pubmed-reader-cskill/1.4.0 (literature search tool)'


def search_biorxiv(
    query: str,
    max_results: int = 20,
    server: str = "biorxiv",
    sort_by: str = "relevance_rank",
    use_cache: bool = True,
    include_summaries: bool = True
) -> Dict[str, Any]:
    """
    Keyword-search bioRxiv or medRxiv via Europe PMC.

    Europe PMC indexes both preprint servers under `SRC:PPR` and returns
    structured metadata (DOI, title, authors, abstract, posting date,
    citation count). We normalize the response to match the shape produced
    by the native bioRxiv API so downstream code is identifier-agnostic.

    Args:
        query: Free-text search query. Supports Europe PMC query syntax;
               any user-supplied terms are combined with the preprint-source
               filter via AND.
        max_results: 1-200 (EPMC allows up to 1000 per page, but we cap to
                     200 to stay consistent with the other skill tools).
        server: "biorxiv" (default) or "medrxiv".
        sort_by: "relevance_rank" (default; EPMC's native relevance ranking)
                 or "publication_date" (newest first).
        use_cache: Use the local TTL cache.
        include_summaries: Include abstracts in the returned `articles` list.

    Returns:
        Same shape as the previous implementation:
        {success, count, articles: [...], query_info: {...}, validation}
    """
    try:
        query = validate_query_param(query)
        max_results = validate_max_results(max_results, maximum=200)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message,
                "param": e.param_name,
                "suggestion": e.suggestion,
            },
        }

    server = server.lower()
    if server not in ("biorxiv", "medrxiv"):
        server = "biorxiv"
    publisher_label = "medRxiv" if server == "medrxiv" else "bioRxiv"

    cache_key = f"biorxiv_search_epmc:{server}:{query}:{max_results}:{sort_by}"
    if use_cache:
        cached = get_cached_search(cache_key)
        if cached:
            logger.info(f"Cache hit for {server} query: {query}")
            return cached

    # EPMC query: scope to preprints from the requested server, AND the user's
    # free-text terms. Wrap the user query so multi-word phrases are treated
    # as a single group by EPMC's parser.
    epmc_query = f'SRC:PPR AND PUBLISHER:"{publisher_label}" AND ({query})'
    params = {
        "query": epmc_query,
        "resultType": "core" if include_summaries else "lite",
        "pageSize": str(min(max_results, 1000)),
        "format": "json",
    }
    if sort_by == "publication_date":
        params["sort"] = "FIRST_PDATE_D desc"

    url = f"{EPMC_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()
        time.sleep(0.1)
        req = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        report_success()
    except urllib.error.URLError as e:
        report_error()
        return {
            "success": False,
            "error": {
                "code": "NETWORK_ERROR",
                "message": f"Failed to connect to Europe PMC: {e}",
                "suggestion": "Check network connection and try again",
            },
        }
    except json.JSONDecodeError as e:
        report_error()
        return {
            "success": False,
            "error": {
                "code": "PARSE_ERROR",
                "message": f"Failed to parse Europe PMC response: {e}",
            },
        }

    total_count = int(data.get("hitCount", 0))
    raw_results = data.get("resultList", {}).get("result", []) or []

    articles: List[Dict[str, Any]] = []
    for item in raw_results[:max_results]:
        article = _parse_epmc_result(item, server)
        if article:
            if not include_summaries:
                article["abstract"] = ""
            articles.append(article)

    result = {
        "success": True,
        "count": total_count,
        "articles": articles,
        "query_info": {
            "query": query,
            "returned": len(articles),
            "total": total_count,
            "sort_by": sort_by,
            "server": server,
            "source": "europepmc",
        },
        "validation": {"passed": True, "warnings": []},
    }

    if use_cache:
        cache_search_results(cache_key, result)

    return result


def _parse_epmc_result(item: Dict[str, Any], server: str) -> Optional[Dict[str, Any]]:
    """Normalize one Europe PMC result into the bioRxiv article schema."""
    doi = item.get("doi", "") or ""
    if not doi:
        return None

    # Authors: EPMC returns a joined author string ("Smith J, Jones M, ...")
    # plus an optional structured list. Prefer the structured list when present.
    authors: List[str] = []
    author_list = (item.get("authorList") or {}).get("author") or []
    for a in author_list:
        name = (a.get("fullName") or "").strip()
        if name:
            authors.append(name)
    if not authors and item.get("authorString"):
        authors = [
            part.strip()
            for part in re.split(r",\s*", item["authorString"])
            if part.strip()
        ]

    posted_date = (
        item.get("firstPublicationDate")
        or item.get("dateOfCreation")
        or item.get("firstIndexDate")
        or ""
    )
    year = None
    if posted_date:
        m = re.search(r"(\d{4})", posted_date)
        if m:
            year = int(m.group(1))
    if not year and item.get("pubYear"):
        try:
            year = int(item["pubYear"])
        except (TypeError, ValueError):
            pass

    abstract = item.get("abstractText", "") or ""
    # EPMC sometimes wraps abstracts in <h4>Section</h4> headers; strip the
    # tags so the abstract reads cleanly when quoted as evidence.
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = re.sub(r"\s+", " ", abstract).strip()

    try:
        citation_count = int(item.get("citedByCount") or 0)
    except (TypeError, ValueError):
        citation_count = 0

    return {
        "doi": doi,
        "title": item.get("title", "Untitled") or "Untitled",
        "authors": authors,
        "year": year,
        "posted_date": posted_date,
        "abstract": abstract,
        "category": "",
        "version": "",
        "license": item.get("license", "") or "",
        "citation_count": citation_count,
        "epmc_id": item.get("id", ""),
        "url": f"https://www.{server}.org/content/{doi}",
        "pdf_url": f"https://www.{server}.org/content/{doi}.full.pdf",
        "source": server,
    }


def browse_biorxiv_recent(
    days: int = 7,
    server: str = "biorxiv",
    category: Optional[str] = None,
    max_results: int = 100,
    use_cache: bool = True
) -> Dict[str, Any]:
    """Browse recent bioRxiv/medRxiv preprints using the official API."""
    days = max(1, min(30, days))
    server = server.lower()
    if server not in ("biorxiv", "medrxiv"):
        server = "biorxiv"

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    cache_key = f"biorxiv_browse:{server}:{start_str}:{end_str}:{category}:{max_results}"
    if use_cache:
        cached = get_cached_search(cache_key)
        if cached:
            logger.info(f"Cache hit for {server} browse: {start_str} to {end_str}")
            return cached

    all_articles: List[Dict[str, Any]] = []
    cursor = 0

    while len(all_articles) < max_results:
        try:
            throttle()
            time.sleep(0.3)
            current_url = f"{BIORXIV_API_URL}/details/{server}/{start_str}/{end_str}/{cursor}/json"
            req = urllib.request.Request(current_url, headers={
                'User-Agent': USER_AGENT,
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=30) as response:
                json_data = response.read().decode('utf-8')
            report_success()

            data = json.loads(json_data)
            messages = data.get('messages', [])
            if messages:
                for msg in messages:
                    if msg.get('status') == 'no posts found':
                        break

            collection = data.get('collection', [])
            if not collection:
                break

            for item in collection:
                article = _parse_api_article(item, server)
                if category:
                    article_cat = article.get('category', '').lower()
                    if category.lower() not in article_cat:
                        continue
                all_articles.append(article)
                if len(all_articles) >= max_results:
                    break

            messages = data.get('messages', [{}])
            if messages:
                total_str = messages[0].get('total', '0')
                try:
                    total = int(total_str)
                except (ValueError, TypeError):
                    total = 0
            else:
                total = 0
            cursor += len(collection)
            if cursor >= total:
                break

        except urllib.error.URLError as e:
            report_error()
            if not all_articles:
                return {
                    "success": False,
                    "error": {
                        "code": "NETWORK_ERROR",
                        "message": f"Failed to connect to {server} API: {e}",
                        "suggestion": "Check network connection and try again"
                    }
                }
            break
        except json.JSONDecodeError as e:
            report_error()
            if not all_articles:
                return {
                    "success": False,
                    "error": {
                        "code": "PARSE_ERROR",
                        "message": f"Failed to parse {server} API response: {e}"
                    }
                }
            break

    result = {
        "success": True,
        "count": len(all_articles),
        "articles": all_articles[:max_results],
        "query_info": {
            "browse_type": "recent",
            "days": days,
            "start_date": start_str,
            "end_date": end_str,
            "category": category,
            "returned": len(all_articles[:max_results]),
            "server": server,
            "source": server
        },
        "validation": {"passed": True, "warnings": []}
    }

    if use_cache:
        cache_search_results(cache_key, result)

    return result


def _parse_api_article(item: Dict[str, Any], server: str) -> Dict[str, Any]:
    doi = item.get('doi', '')
    posted_date = item.get('date', '')
    year = None
    if posted_date:
        year_match = re.search(r'(\d{4})', posted_date)
        if year_match:
            year = int(year_match.group(1))

    authors_str = item.get('authors', '')
    authors: List[str] = []
    if authors_str:
        for part in authors_str.split(';'):
            name = part.strip()
            if name:
                authors.append(name)

    return {
        "doi": doi,
        "title": item.get('title', 'Untitled'),
        "authors": authors,
        "year": year,
        "posted_date": posted_date,
        "abstract": item.get('abstract', ''),
        "category": item.get('category', ''),
        "version": item.get('version', '1'),
        "type": item.get('type', 'preprint'),
        "license": item.get('license', ''),
        "published": item.get('published', ''),
        "jatsxml": item.get('jatsxml', ''),
        "url": f"https://www.{server}.org/content/{doi}",
        "pdf_url": f"https://www.{server}.org/content/{doi}.full.pdf",
        "source": server
    }


def format_biorxiv_search_results(results: Dict[str, Any]) -> str:
    if not results.get("success"):
        error = results.get("error", {})
        return f"Search failed: {error.get('message', 'Unknown error')}"

    lines = []
    query_info = results.get("query_info", {})
    count = results.get("count", 0)
    articles = results.get("articles", [])
    server = query_info.get("server", "biorxiv")

    if query_info.get("browse_type") == "recent":
        lines.append(f"## Recent {server.title()} Preprints")
        lines.append("")
        lines.append(f"Last {query_info.get('days', 7)} days. Showing {len(articles)} of {count}:")
    else:
        query = query_info.get("query", "")
        lines.append(f"## {server.title()} Search Results: \"{query}\"")
        lines.append("")
        lines.append(f"Found {count:,} preprints. Showing {len(articles)}:")
    lines.append("")

    for i, article in enumerate(articles, 1):
        citation = format_biorxiv_citation(article, style="vancouver")
        lines.append(f"{i}. {citation}")
        if article.get("abstract"):
            abstract = article["abstract"][:200] + "..." if len(article.get("abstract", "")) > 200 else article.get("abstract", "")
            lines.append(f"   Abstract: {abstract}")
        lines.append("")

    return "\n".join(lines)
