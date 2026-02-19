#!/usr/bin/env python3
"""
Article fetching functionality using NCBI E-utilities EFetch API.
Retrieves abstracts, metadata, and full bibliographic information.
"""

import sys
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Any
import logging

# Add utils to path
# sys.path removed for package imports
from .utils.helpers import (
    build_api_params,
    format_authors,
    clean_abstract,
    extract_year,
)
from .utils.validators.parameter_validator import (
    validate_pmid_param,
    validate_pmid_list,
    ValidationError,
)
from .utils.validators.response_validator import (
    validate_efetch_response,
    validate_article_metadata,
)
from .utils.cache_manager import cache_article_metadata, get_cached_metadata
from .utils.rate_limiter import throttle, report_success, report_error

logger = logging.getLogger(__name__)

# API Configuration
EFETCH_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def fetch_abstract(pmid: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Fetch article abstract for a given PMID.

    Args:
        pmid: PubMed ID
        use_cache: Whether to use cached data

    Returns:
        Dict containing:
        - success: bool
        - pmid: The PMID
        - title: Article title
        - abstract: Abstract text
        - authors: List of authors
        - journal: Journal name
        - year: Publication year
        - doi: DOI if available
        - mesh_terms: MeSH terms
        - keywords: Author keywords
        - error: Error info if failed

    Example:
        >>> result = fetch_abstract("17299597")
        >>> print(result['title'])
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

    # Check cache
    cache_key = f"abstract:{pmid}"
    if use_cache:
        cached = get_cached_metadata(pmid)
        if cached:
            logger.info(f"Cache hit for PMID: {pmid}")
            return cached

    # Build API request
    params = build_api_params({
        "db": "pubmed",
        "id": pmid,
        "rettype": "abstract",
        "retmode": "xml"
    })

    url = f"{EFETCH_BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()
        with urllib.request.urlopen(url, timeout=30) as response:
            xml_data = response.read().decode('utf-8')
        report_success()
    except urllib.error.URLError as e:
        report_error()
        return {
            "success": False,
            "pmid": pmid,
            "error": {
                "code": "NETWORK_ERROR",
                "message": f"Failed to fetch article: {e}",
                "suggestion": "Check network connection and try again"
            }
        }

    # Parse XML
    try:
        article = parse_pubmed_xml(xml_data)
    except Exception as e:
        return {
            "success": False,
            "pmid": pmid,
            "error": {
                "code": "PARSE_ERROR",
                "message": f"Failed to parse article data: {e}"
            }
        }

    if not article:
        return {
            "success": False,
            "pmid": pmid,
            "error": {
                "code": "NOT_FOUND",
                "message": f"Article not found: PMID {pmid}",
                "suggestion": "Verify the PMID is correct"
            }
        }

    # Validate parsed data
    validation = validate_article_metadata(article)

    result = {
        "success": True,
        **article,
        "validation": {
            "passed": validation.all_passed(),
            "warnings": validation.get_warnings()
        }
    }

    # Cache result
    if use_cache:
        cache_article_metadata(pmid, result)

    return result


def fetch_metadata(
    pmid: str,
    include_mesh: bool = True,
    include_keywords: bool = True,
    include_references: bool = False,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Fetch comprehensive metadata for an article.

    Args:
        pmid: PubMed ID
        include_mesh: Include MeSH terms
        include_keywords: Include author keywords
        include_references: Include reference count
        use_cache: Whether to use cached data

    Returns:
        Dict with full article metadata
    """
    # Start with basic abstract fetch
    result = fetch_abstract(pmid, use_cache=use_cache)

    if not result.get("success"):
        return result

    # Additional metadata fields are already included in parse_pubmed_xml
    # This function exists for API compatibility and future expansion

    return result


def batch_fetch(
    pmids: List[str],
    batch_size: int = 200,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Fetch multiple articles efficiently.

    Args:
        pmids: List of PubMed IDs
        batch_size: IDs per API request
        use_cache: Whether to use cached data

    Returns:
        Dict containing:
        - success: bool
        - articles: Dict mapping PMID to article data
        - failed: List of PMIDs that failed
        - stats: Fetch statistics
    """
    # Validate PMID list
    try:
        pmids = validate_pmid_list(pmids)
    except ValidationError as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": e.message
            }
        }

    articles = {}
    failed = []
    from_cache = 0
    from_api = 0

    # Check cache first
    uncached_pmids = []
    for pmid in pmids:
        if use_cache:
            cached = get_cached_metadata(pmid)
            if cached and cached.get("success"):
                articles[pmid] = cached
                from_cache += 1
                continue
        uncached_pmids.append(pmid)

    # Fetch uncached in batches
    for i in range(0, len(uncached_pmids), batch_size):
        batch = uncached_pmids[i:i + batch_size]

        params = build_api_params({
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "abstract",
            "retmode": "xml"
        })

        url = f"{EFETCH_BASE_URL}?{urllib.parse.urlencode(params)}"

        try:
            throttle()
            with urllib.request.urlopen(url, timeout=60) as response:
                xml_data = response.read().decode('utf-8')
            report_success()
        except urllib.error.URLError as e:
            report_error()
            failed.extend(batch)
            logger.warning(f"Batch fetch failed: {e}")
            continue

        # Parse batch results
        try:
            batch_articles = parse_pubmed_xml_batch(xml_data)
            for pmid, article in batch_articles.items():
                articles[pmid] = {"success": True, **article}
                from_api += 1
                if use_cache:
                    cache_article_metadata(pmid, articles[pmid])
        except Exception as e:
            logger.warning(f"Batch parse failed: {e}")
            failed.extend(batch)

    return {
        "success": len(articles) > 0,
        "articles": articles,
        "failed": failed,
        "stats": {
            "requested": len(pmids),
            "fetched": len(articles),
            "failed": len(failed),
            "from_cache": from_cache,
            "from_api": from_api
        }
    }


def parse_pubmed_xml(xml_data: str) -> Optional[Dict[str, Any]]:
    """
    Parse PubMed XML response for single article.

    Args:
        xml_data: XML string from EFetch

    Returns:
        Parsed article dict or None
    """
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return None

    # Find PubmedArticle element
    article_elem = root.find('.//PubmedArticle')
    if article_elem is None:
        return None

    return _parse_article_element(article_elem)


def parse_pubmed_xml_batch(xml_data: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse PubMed XML response for multiple articles.

    Args:
        xml_data: XML string from EFetch

    Returns:
        Dict mapping PMID to article dict
    """
    articles = {}

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return articles

    for article_elem in root.findall('.//PubmedArticle'):
        article = _parse_article_element(article_elem)
        if article and article.get('pmid'):
            articles[article['pmid']] = article

    return articles


def _parse_article_element(article_elem: ET.Element) -> Dict[str, Any]:
    """Parse a single PubmedArticle XML element."""
    article = {}

    # PMID
    pmid_elem = article_elem.find('.//PMID')
    if pmid_elem is not None:
        article['pmid'] = pmid_elem.text

    # Citation element
    citation = article_elem.find('.//MedlineCitation')
    if citation is None:
        return article

    article_data = citation.find('.//Article')
    if article_data is None:
        return article

    # Title
    title_elem = article_data.find('.//ArticleTitle')
    if title_elem is not None:
        article['title'] = _get_element_text(title_elem)

    # Abstract
    abstract_elem = article_data.find('.//Abstract')
    if abstract_elem is not None:
        abstract_texts = []
        for abs_text in abstract_elem.findall('.//AbstractText'):
            label = abs_text.get('Label', '')
            text = _get_element_text(abs_text)
            if label:
                abstract_texts.append(f"{label}: {text}")
            else:
                abstract_texts.append(text)
        article['abstract'] = clean_abstract(' '.join(abstract_texts))

    # Authors
    authors = []
    for author_elem in article_data.findall('.//Author'):
        author = {}
        last_name = author_elem.find('LastName')
        fore_name = author_elem.find('ForeName')
        initials = author_elem.find('Initials')

        if last_name is not None:
            author['LastName'] = last_name.text
        if fore_name is not None:
            author['ForeName'] = fore_name.text
        if initials is not None:
            author['Initials'] = initials.text

        if author:
            authors.append(author)
    article['authors'] = authors

    # Journal
    journal_elem = article_data.find('.//Journal')
    if journal_elem is not None:
        title = journal_elem.find('.//Title')
        if title is not None:
            article['journal'] = title.text
        else:
            iso = journal_elem.find('.//ISOAbbreviation')
            if iso is not None:
                article['journal'] = iso.text

        # Volume, Issue
        ji = journal_elem.find('.//JournalIssue')
        if ji is not None:
            vol = ji.find('Volume')
            if vol is not None:
                article['volume'] = vol.text
            issue = ji.find('Issue')
            if issue is not None:
                article['issue'] = issue.text

            # Publication date
            pubdate = ji.find('.//PubDate')
            if pubdate is not None:
                year = pubdate.find('Year')
                month = pubdate.find('Month')
                day = pubdate.find('Day')

                if year is not None:
                    article['year'] = int(year.text)
                    date_parts = [year.text]
                    if month is not None:
                        date_parts.append(month.text)
                    if day is not None:
                        date_parts.append(day.text)
                    article['pub_date'] = ' '.join(date_parts)

    # Pages
    pagination = article_data.find('.//Pagination/MedlinePgn')
    if pagination is not None:
        article['pages'] = pagination.text

    # DOI
    for article_id in article_elem.findall('.//ArticleId'):
        if article_id.get('IdType') == 'doi':
            article['doi'] = article_id.text
        elif article_id.get('IdType') == 'pmc':
            pmc_value = article_id.text
            if not pmc_value.upper().startswith('PMC'):
                pmc_value = f"PMC{pmc_value}"
            article['pmc'] = pmc_value

    # MeSH Terms
    mesh_terms = []
    for mesh_heading in citation.findall('.//MeshHeading'):
        descriptor = mesh_heading.find('DescriptorName')
        if descriptor is not None:
            mesh_terms.append(descriptor.text)
    article['mesh_terms'] = mesh_terms

    # Keywords
    keywords = []
    for keyword_list in citation.findall('.//KeywordList'):
        for keyword in keyword_list.findall('Keyword'):
            if keyword.text:
                keywords.append(keyword.text)
    article['keywords'] = keywords

    # Publication types
    pub_types = []
    for pub_type in article_data.findall('.//PublicationType'):
        if pub_type.text:
            pub_types.append(pub_type.text)
    article['pub_types'] = pub_types

    return article


def _get_element_text(elem: ET.Element) -> str:
    """Get all text content from element including children."""
    return ''.join(elem.itertext())


def format_article(article: Dict[str, Any], include_abstract: bool = True) -> str:
    """
    Format article for display.

    Args:
        article: Article data dict
        include_abstract: Whether to include abstract

    Returns:
        Formatted string for display
    """
    if not article.get("success"):
        error = article.get("error", {})
        return f"Error: {error.get('message', 'Unknown error')}"

    lines = []
    pmid = article.get('pmid', '')

    lines.append(f"## Article: PMID {pmid}")
    lines.append("")

    # Title
    title = article.get('title', 'Untitled')
    lines.append(f"**Title**: {title}")
    lines.append("")

    # Authors
    authors = article.get('authors', [])
    if authors:
        author_str = format_authors(authors, max_authors=6, style='full')
        lines.append(f"**Authors**: {author_str}")
        lines.append("")

    # Journal info
    journal = article.get('journal', '')
    year = article.get('year', '')
    volume = article.get('volume', '')
    issue = article.get('issue', '')
    pages = article.get('pages', '')

    journal_info = journal
    if year:
        journal_info += f", {year}"
    if volume:
        journal_info += f";{volume}"
    if issue:
        journal_info += f"({issue})"
    if pages:
        journal_info += f":{pages}"

    if journal_info:
        lines.append(f"**Journal**: {journal_info}")
        lines.append("")

    # DOI
    doi = article.get('doi')
    if doi:
        lines.append(f"**DOI**: {doi}")
        lines.append("")

    # PMC (full text availability)
    pmc = article.get('pmc')
    if pmc:
        lines.append(f"**Full Text**: Available ({pmc})")
        lines.append("")

    # Abstract
    if include_abstract:
        abstract = article.get('abstract', '')
        if abstract:
            lines.append("**Abstract**:")
            lines.append(abstract)
            lines.append("")

    # Keywords
    keywords = article.get('keywords', [])
    if keywords:
        lines.append(f"**Keywords**: {', '.join(keywords)}")
        lines.append("")

    # MeSH Terms
    mesh = article.get('mesh_terms', [])
    if mesh:
        lines.append(f"**MeSH Terms**: {', '.join(mesh[:10])}")
        if len(mesh) > 10:
            lines.append(f"  ... and {len(mesh) - 10} more")
        lines.append("")

    # Publication types
    pub_types = article.get('pub_types', [])
    if pub_types:
        lines.append(f"**Publication Types**: {', '.join(pub_types)}")

    return "\n".join(lines)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test article fetching functionality."""
    print("Testing Article Fetch...\n")

    # Test single article fetch
    print("1. Fetch single article (PMID 17299597):")
    result = fetch_abstract("17299597")

    if result["success"]:
        print(f"   Title: {result.get('title', '')[:60]}...")
        print(f"   Authors: {format_authors(result.get('authors', []))}")
        print(f"   Journal: {result.get('journal', '')}")
        print(f"   Year: {result.get('year', '')}")
        print(f"   PMC: {result.get('pmc', 'N/A')}")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test formatted output
    print("\n2. Formatted article output:")
    formatted = format_article(result)
    # Only print first 30 lines
    for line in formatted.split('\n')[:30]:
        print(line)
    print("...")

    # Test batch fetch
    print("\n3. Batch fetch (3 articles):")
    pmids = ["17299597", "32756549", "11850928"]
    batch_result = batch_fetch(pmids)

    if batch_result["success"]:
        print(f"   Fetched: {batch_result['stats']['fetched']}")
        print(f"   Failed: {batch_result['stats']['failed']}")
        for pmid, article in batch_result["articles"].items():
            print(f"   - {pmid}: {article.get('title', '')[:50]}...")

    # Test invalid PMID
    print("\n4. Invalid PMID handling:")
    result = fetch_abstract("invalid")
    print(f"   Error: {result.get('error', {}).get('message')}")

    print("\nAll fetch tests completed!")


if __name__ == "__main__":
    main()
