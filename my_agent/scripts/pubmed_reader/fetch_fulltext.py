#!/usr/bin/env python3
"""
Full text retrieval using BioC PMC API.
Provides access to ~3 million Open Access articles from PubMed Central.
"""

import sys
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Optional, Dict, Any, List
import logging

# Add utils to path
# sys.path removed for package imports
from .utils.helpers import build_api_params, clean_abstract
from .utils.validators.parameter_validator import (
    validate_pmid_param,
    validate_pmcid_param,
    ValidationError,
)
from .utils.validators.response_validator import validate_bioc_response
from .utils.cache_manager import cache_fulltext, get_cached_fulltext
from .utils.rate_limiter import throttle, report_success, report_error

logger = logging.getLogger(__name__)

# API Configuration
BIOC_BASE_URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"
ID_CONVERTER_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"


def check_oa_availability(pmid: str) -> Dict[str, Any]:
    """
    Check if article is available in PMC Open Access subset.

    Args:
        pmid: PubMed ID

    Returns:
        Dict with availability info:
        - available: bool
        - pmcid: PMC ID if available
        - license: License info if available
    """
    try:
        pmid = validate_pmid_param(pmid)
    except ValidationError as e:
        return {
            "available": False,
            "error": e.message
        }

    # Try to convert PMID to PMCID
    params = {
        "ids": pmid,
        "format": "json",
        "idtype": "pmid"
    }

    url = f"{ID_CONVERTER_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        report_success()
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        report_error()
        return {
            "available": False,
            "error": f"Failed to check availability: {e}"
        }

    # Parse response
    records = data.get("records", [])
    if not records:
        return {
            "available": False,
            "pmid": pmid,
            "message": "PMID not found in PMC"
        }

    record = records[0]
    pmcid = record.get("pmcid")

    if pmcid:
        return {
            "available": True,
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": record.get("doi"),
            "message": "Full text available in PMC Open Access"
        }
    else:
        return {
            "available": False,
            "pmid": pmid,
            "doi": record.get("doi"),
            "message": "Article exists but full text not in Open Access"
        }


def pmid_to_pmcid(pmid: str) -> Optional[str]:
    """
    Convert PMID to PMC ID.

    Args:
        pmid: PubMed ID

    Returns:
        PMC ID or None if not available
    """
    result = check_oa_availability(pmid)
    return result.get("pmcid")


def pmcid_to_pmid(pmcid: str) -> Optional[str]:
    """
    Convert PMC ID to PMID.

    Args:
        pmcid: PMC ID

    Returns:
        PMID or None if not found
    """
    try:
        pmcid = validate_pmcid_param(pmcid)
    except ValidationError:
        return None

    params = {
        "ids": pmcid,
        "format": "json",
        "idtype": "pmcid"
    }

    url = f"{ID_CONVERTER_URL}?{urllib.parse.urlencode(params)}"

    try:
        throttle()
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        report_success()
    except (urllib.error.URLError, json.JSONDecodeError):
        report_error()
        return None

    records = data.get("records", [])
    if records:
        return records[0].get("pmid")
    return None


def get_fulltext(
    article_id: str,
    format: str = "json",
    encoding: str = "unicode",
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Retrieve full text for an Open Access article.

    Args:
        article_id: PMID or PMC ID
        format: Response format ("json" or "xml")
        encoding: Text encoding ("unicode" or "ascii")
        use_cache: Whether to use cached data

    Returns:
        Dict containing:
        - success: bool
        - pmid: PubMed ID
        - pmcid: PMC ID
        - title: Article title
        - sections: Dict of section name -> text
        - full_text: Complete text
        - figures: List of figure references
        - tables: List of table references
        - references: Reference list
        - error: Error info if failed

    Example:
        >>> result = get_fulltext("17299597")
        >>> print(result['sections']['Introduction'])
    """
    # Determine if input is PMID or PMCID
    article_id_str = str(article_id).strip()

    if article_id_str.upper().startswith("PMC"):
        pmcid = article_id_str.upper()
        pmid = pmcid_to_pmid(pmcid)
    else:
        try:
            pmid = validate_pmid_param(article_id_str)
        except ValidationError as e:
            return {
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": e.message,
                    "suggestion": e.suggestion
                }
            }
        pmcid = pmid_to_pmcid(pmid)

    if not pmcid:
        return {
            "success": False,
            "pmid": pmid,
            "error": {
                "code": "NOT_AVAILABLE",
                "message": "Article not available in PMC Open Access",
                "suggestion": "Only ~3 million Open Access articles are available. Try the abstract instead."
            }
        }

    # Check cache
    cache_key = pmcid
    if use_cache:
        cached = get_cached_fulltext(cache_key)
        if cached:
            logger.info(f"Cache hit for full text: {pmcid}")
            return cached

    # Build BioC API URL
    url = f"{BIOC_BASE_URL}/BioC_{format}/{pmcid}/{encoding}"

    try:
        throttle()
        with urllib.request.urlopen(url, timeout=60) as response:
            if format == "json":
                data = json.loads(response.read().decode('utf-8'))
            else:
                data = response.read().decode('utf-8')
        report_success()
    except urllib.error.HTTPError as e:
        report_error()
        if e.code == 404:
            return {
                "success": False,
                "pmid": pmid,
                "pmcid": pmcid,
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Full text not found for {pmcid}",
                    "suggestion": "The article may exist in PMC but not in the BioC Open Access subset"
                }
            }
        return {
            "success": False,
            "pmid": pmid,
            "pmcid": pmcid,
            "error": {
                "code": "API_ERROR",
                "message": f"API error: HTTP {e.code}"
            }
        }
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        report_error()
        return {
            "success": False,
            "pmid": pmid,
            "pmcid": pmcid,
            "error": {
                "code": "NETWORK_ERROR",
                "message": f"Failed to fetch full text: {e}"
            }
        }

    # Parse BioC response
    if format == "json":
        result = parse_bioc_json(data)
    else:
        result = parse_bioc_xml(data)

    result["pmid"] = pmid
    result["pmcid"] = pmcid

    # Validate response
    if format == "json":
        validation = validate_bioc_response(data)
        result["validation"] = {
            "passed": validation.all_passed(),
            "warnings": validation.get_warnings()
        }

    # Cache result
    if use_cache and result.get("success"):
        cache_fulltext(cache_key, result)

    return result


def parse_bioc_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse BioC JSON response.

    Args:
        data: BioC JSON response

    Returns:
        Parsed full text dict
    """
    # BioC API may return a list (documents array) or a dict with a "documents" key
    if isinstance(data, list):
        documents = data
    else:
        documents = data.get("documents", [])
    if not documents:
        return {
            "success": False,
            "error": {
                "code": "NO_CONTENT",
                "message": "No documents in response"
            }
        }

    doc = documents[0]
    infons = doc.get("infons", {})
    passages = doc.get("passages", [])

    # Extract metadata
    title = infons.get("title", "")

    # Parse passages into sections
    sections = {}
    full_text_parts = []
    figures = []
    tables = []
    references = []

    current_section = "Front Matter"

    for passage in passages:
        p_infons = passage.get("infons", {})
        p_type = p_infons.get("type", "").lower()
        section_type = p_infons.get("section_type", "").lower()
        text = passage.get("text", "")

        # Determine section
        if "title" in p_type and "abstract" not in p_type:
            if text:
                current_section = text.strip()
                continue

        # Handle different passage types
        if p_type == "title" or p_type == "article-title":
            if not title:
                title = text
            continue

        if p_type == "abstract":
            current_section = "Abstract"

        if "introduction" in section_type or "introduction" in p_type:
            current_section = "Introduction"
        elif "method" in section_type or "method" in p_type:
            current_section = "Methods"
        elif "result" in section_type or "result" in p_type:
            current_section = "Results"
        elif "discussion" in section_type or "discussion" in p_type:
            current_section = "Discussion"
        elif "conclusion" in section_type or "conclusion" in p_type:
            current_section = "Conclusions"
        elif "reference" in section_type or "ref" in p_type:
            current_section = "References"
            references.append(text)
            continue

        # Handle figures and tables
        if "fig" in p_type or "figure" in p_type:
            figures.append({
                "id": p_infons.get("id", ""),
                "caption": text
            })
            continue

        if "table" in p_type:
            tables.append({
                "id": p_infons.get("id", ""),
                "content": text
            })
            continue

        # Add to section
        if text.strip():
            if current_section not in sections:
                sections[current_section] = []
            sections[current_section].append(text)
            full_text_parts.append(text)

    # Combine section texts
    for section in sections:
        sections[section] = "\n\n".join(sections[section])

    return {
        "success": True,
        "title": title,
        "sections": sections,
        "full_text": "\n\n".join(full_text_parts),
        "figures": figures,
        "tables": tables,
        "references": references,
        "word_count": len(" ".join(full_text_parts).split())
    }


def parse_bioc_xml(xml_data: str) -> Dict[str, Any]:
    """
    Parse BioC XML response.

    Args:
        xml_data: BioC XML string

    Returns:
        Parsed full text dict
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        return {
            "success": False,
            "error": {
                "code": "PARSE_ERROR",
                "message": f"Failed to parse XML: {e}"
            }
        }

    # Find document
    doc = root.find('.//document')
    if doc is None:
        return {
            "success": False,
            "error": {
                "code": "NO_CONTENT",
                "message": "No document in response"
            }
        }

    # Extract text from passages
    sections = {}
    full_text_parts = []

    for passage in doc.findall('.//passage'):
        text_elem = passage.find('text')
        if text_elem is not None and text_elem.text:
            text = text_elem.text.strip()
            if text:
                full_text_parts.append(text)

    return {
        "success": True,
        "sections": sections,
        "full_text": "\n\n".join(full_text_parts),
        "word_count": len(" ".join(full_text_parts).split())
    }


def extract_sections(bioc_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract named sections from parsed BioC data.

    Args:
        bioc_data: Parsed BioC response

    Returns:
        Dict mapping section name to content
    """
    return bioc_data.get("sections", {})


def format_fulltext(result: Dict[str, Any], max_words: Optional[int] = None) -> str:
    """
    Format full text for display.

    Args:
        result: Full text result dict
        max_words: Optional word limit per section

    Returns:
        Formatted string for display
    """
    if not result.get("success"):
        error = result.get("error", {})
        return f"Error: {error.get('message', 'Unknown error')}"

    lines = []
    pmid = result.get("pmid", "")
    pmcid = result.get("pmcid", "")
    title = result.get("title", "Untitled")

    lines.append(f"## Full Text: PMID {pmid} ({pmcid})")
    lines.append("")
    lines.append(f"**Title**: {title}")
    lines.append("")
    lines.append(f"**Word Count**: {result.get('word_count', 0):,} words")
    lines.append("")

    # Display sections in order
    section_order = [
        "Abstract", "Introduction", "Methods",
        "Results", "Discussion", "Conclusions"
    ]

    sections = result.get("sections", {})

    for section_name in section_order:
        if section_name in sections:
            content = sections[section_name]
            if max_words:
                words = content.split()
                if len(words) > max_words:
                    content = " ".join(words[:max_words]) + "..."
            lines.append(f"### {section_name}")
            lines.append("")
            lines.append(content)
            lines.append("")

    # Display any remaining sections
    for section_name, content in sections.items():
        if section_name not in section_order:
            if max_words:
                words = content.split()
                if len(words) > max_words:
                    content = " ".join(words[:max_words]) + "..."
            lines.append(f"### {section_name}")
            lines.append("")
            lines.append(content)
            lines.append("")

    # Figures and tables summary
    figures = result.get("figures", [])
    if figures:
        lines.append(f"### Figures ({len(figures)} total)")
        for fig in figures[:5]:
            caption = fig.get("caption", "")[:100]
            lines.append(f"- {fig.get('id', 'Fig')}: {caption}...")
        lines.append("")

    tables = result.get("tables", [])
    if tables:
        lines.append(f"### Tables ({len(tables)} total)")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test full text retrieval."""
    print("Testing Full Text Retrieval...\n")

    # Test availability check
    print("1. Check OA availability:")
    test_pmids = ["17299597", "32756549", "12345"]

    for pmid in test_pmids:
        result = check_oa_availability(pmid)
        status = "" if result.get("available") else " (not available)"
        pmcid = result.get("pmcid", "N/A")
        print(f"   PMID {pmid}: {pmcid}{status}")

    # Test full text retrieval
    print("\n2. Fetch full text (known OA article):")
    result = get_fulltext("17299597")

    if result["success"]:
        print(f"   Title: {result.get('title', '')[:60]}...")
        print(f"   Word count: {result.get('word_count', 0)}")
        print(f"   Sections: {list(result.get('sections', {}).keys())}")
        print(f"   Figures: {len(result.get('figures', []))}")
    else:
        print(f"   Error: {result.get('error', {}).get('message')}")

    # Test with PMC ID
    print("\n3. Fetch using PMC ID:")
    result = get_fulltext("PMC1790863")

    if result["success"]:
        print(f"   PMID: {result.get('pmid')}")
        print(f"   PMCID: {result.get('pmcid')}")
        print(f"   Word count: {result.get('word_count', 0)}")

    # Test formatted output
    print("\n4. Formatted output (truncated):")
    result = get_fulltext("17299597")
    if result["success"]:
        formatted = format_fulltext(result, max_words=50)
        for line in formatted.split('\n')[:25]:
            print(line)
        print("...")

    # Test unavailable article
    print("\n5. Unavailable article handling:")
    result = get_fulltext("99999999")
    print(f"   Error: {result.get('error', {}).get('message')}")

    print("\nAll full text tests completed!")


if __name__ == "__main__":
    main()
