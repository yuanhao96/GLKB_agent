#!/usr/bin/env python3
"""
Parameter validators for PubMed Reader skill.
Validates user inputs before making API calls.
"""

import re
from typing import Any, Optional, List
from datetime import datetime


class ValidationError(Exception):
    """Raised when validation fails."""

    def __init__(self, message: str, param_name: str = None,
                 suggestion: str = None):
        super().__init__(message)
        self.message = message
        self.param_name = param_name
        self.suggestion = suggestion


def validate_pmid_param(pmid: Any, param_name: str = "pmid") -> str:
    """
    Validate and normalize PMID parameter.

    Args:
        pmid: Value to validate
        param_name: Name for error messages

    Returns:
        Normalized PMID string

    Raises:
        ValidationError: If validation fails

    Example:
        >>> validate_pmid_param("12345678")
        "12345678"
        >>> validate_pmid_param("PMID: 12345678")
        "12345678"
    """
    if pmid is None:
        raise ValidationError(
            f"{param_name} cannot be None",
            param_name=param_name,
            suggestion="Provide a valid PubMed ID (1-8 digit number)"
        )

    pmid_str = str(pmid).strip()

    if not pmid_str:
        raise ValidationError(
            f"{param_name} cannot be empty",
            param_name=param_name,
            suggestion="Provide a valid PubMed ID"
        )

    # Remove common prefixes
    pmid_str = re.sub(r'^(PMID:?\s*)', '', pmid_str, flags=re.IGNORECASE)

    # Validate format
    if not re.match(r'^\d{1,8}$', pmid_str):
        raise ValidationError(
            f"Invalid PMID format: '{pmid}'",
            param_name=param_name,
            suggestion="PMID should be a 1-8 digit number (e.g., 12345678)"
        )

    return pmid_str


def validate_pmcid_param(pmcid: Any, param_name: str = "pmcid") -> str:
    """
    Validate and normalize PMC ID parameter.

    Args:
        pmcid: Value to validate
        param_name: Name for error messages

    Returns:
        Normalized PMC ID string (with PMC prefix)

    Raises:
        ValidationError: If validation fails

    Example:
        >>> validate_pmcid_param("1790863")
        "PMC1790863"
        >>> validate_pmcid_param("PMC1790863")
        "PMC1790863"
    """
    if pmcid is None:
        raise ValidationError(
            f"{param_name} cannot be None",
            param_name=param_name,
            suggestion="Provide a valid PMC ID (e.g., PMC1790863 or 1790863)"
        )

    pmcid_str = str(pmcid).strip().upper()

    if not pmcid_str:
        raise ValidationError(
            f"{param_name} cannot be empty",
            param_name=param_name
        )

    # Add PMC prefix if missing
    if re.match(r'^\d+$', pmcid_str):
        pmcid_str = f"PMC{pmcid_str}"

    # Validate format
    if not re.match(r'^PMC\d+$', pmcid_str):
        raise ValidationError(
            f"Invalid PMC ID format: '{pmcid}'",
            param_name=param_name,
            suggestion="PMC ID should be 'PMC' followed by digits (e.g., PMC1790863)"
        )

    return pmcid_str


def validate_query_param(query: Any, param_name: str = "query",
                         min_length: int = 2,
                         max_length: int = 10000) -> str:
    """
    Validate search query parameter.

    Args:
        query: Search query to validate
        param_name: Name for error messages
        min_length: Minimum query length
        max_length: Maximum query length

    Returns:
        Validated query string

    Raises:
        ValidationError: If validation fails
    """
    if query is None:
        raise ValidationError(
            f"{param_name} cannot be None",
            param_name=param_name,
            suggestion="Provide a search query"
        )

    query_str = str(query).strip()

    if len(query_str) < min_length:
        raise ValidationError(
            f"Query too short (minimum {min_length} characters)",
            param_name=param_name,
            suggestion=f"Provide a query with at least {min_length} characters"
        )

    if len(query_str) > max_length:
        raise ValidationError(
            f"Query too long (maximum {max_length} characters)",
            param_name=param_name,
            suggestion="Shorten your query or split into multiple searches"
        )

    # Check for potentially dangerous characters (basic injection prevention)
    dangerous_patterns = [
        r'<script',
        r'javascript:',
        r'data:',
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, query_str, re.IGNORECASE):
            raise ValidationError(
                "Query contains potentially dangerous content",
                param_name=param_name,
                suggestion="Remove script or data URLs from query"
            )

    return query_str


def validate_date_param(date: Any, param_name: str = "date",
                        allow_future: bool = False) -> str:
    """
    Validate and normalize date parameter.

    Args:
        date: Date to validate (str, datetime, or dict)
        param_name: Name for error messages
        allow_future: Whether to allow future dates

    Returns:
        Date string in YYYY/MM/DD format

    Raises:
        ValidationError: If validation fails

    Example:
        >>> validate_date_param("2024/01/15")
        "2024/01/15"
        >>> validate_date_param("2024-01-15")
        "2024/01/15"
    """
    if date is None:
        raise ValidationError(
            f"{param_name} cannot be None",
            param_name=param_name
        )

    # Handle datetime objects
    if isinstance(date, datetime):
        date_str = date.strftime("%Y/%m/%d")
    else:
        date_str = str(date).strip()

    # Normalize separators
    date_str = re.sub(r'[-.]', '/', date_str)

    # Try to parse various formats
    formats = [
        "%Y/%m/%d",
        "%Y/%m",
        "%Y",
    ]

    parsed = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        raise ValidationError(
            f"Invalid date format: '{date}'",
            param_name=param_name,
            suggestion="Use format YYYY/MM/DD, YYYY/MM, or YYYY"
        )

    # Check for future dates
    if not allow_future and parsed > datetime.now():
        raise ValidationError(
            f"Future date not allowed: {date_str}",
            param_name=param_name,
            suggestion="Use a date in the past or present"
        )

    # Check for reasonable range
    min_year = 1800
    if parsed.year < min_year:
        raise ValidationError(
            f"Year too early: {parsed.year}",
            param_name=param_name,
            suggestion=f"Use a year after {min_year}"
        )

    return parsed.strftime("%Y/%m/%d")


def validate_max_results(max_results: Any, param_name: str = "max_results",
                         minimum: int = 1, maximum: int = 10000) -> int:
    """
    Validate max_results parameter.

    Args:
        max_results: Value to validate
        param_name: Name for error messages
        minimum: Minimum allowed value
        maximum: Maximum allowed value

    Returns:
        Validated integer

    Raises:
        ValidationError: If validation fails
    """
    if max_results is None:
        return 20  # Default value

    try:
        value = int(max_results)
    except (ValueError, TypeError):
        raise ValidationError(
            f"Invalid {param_name}: must be an integer",
            param_name=param_name
        )

    if value < minimum:
        raise ValidationError(
            f"{param_name} must be at least {minimum}",
            param_name=param_name
        )

    if value > maximum:
        raise ValidationError(
            f"{param_name} cannot exceed {maximum}",
            param_name=param_name,
            suggestion=f"Use {maximum} or less, or paginate results"
        )

    return value


def validate_sort_order(sort: Any, param_name: str = "sort") -> str:
    """
    Validate sort order parameter.

    Args:
        sort: Sort order to validate
        param_name: Name for error messages

    Returns:
        Validated sort string

    Raises:
        ValidationError: If validation fails
    """
    valid_sorts = [
        "relevance",
        "pub+date",
        "pub_date",
        "first_author",
        "journal",
        "title",
    ]

    if sort is None:
        return "relevance"

    sort_str = str(sort).strip().lower()

    # Normalize common variations
    sort_str = sort_str.replace("_", "+").replace("-", "+")
    sort_str = re.sub(r'\s+', '+', sort_str)

    if sort_str not in valid_sorts:
        raise ValidationError(
            f"Invalid sort order: '{sort}'",
            param_name=param_name,
            suggestion=f"Valid options: {', '.join(valid_sorts)}"
        )

    return sort_str


def validate_rettype(rettype: Any, param_name: str = "rettype") -> str:
    """
    Validate return type parameter.

    Args:
        rettype: Return type to validate
        param_name: Name for error messages

    Returns:
        Validated rettype string

    Raises:
        ValidationError: If validation fails
    """
    valid_rettypes = [
        "abstract",
        "medline",
        "xml",
        "uilist",
        "docsum",
        "full",
    ]

    if rettype is None:
        return "abstract"

    rettype_str = str(rettype).strip().lower()

    if rettype_str not in valid_rettypes:
        raise ValidationError(
            f"Invalid return type: '{rettype}'",
            param_name=param_name,
            suggestion=f"Valid options: {', '.join(valid_rettypes)}"
        )

    return rettype_str


def validate_pmid_list(pmids: Any, param_name: str = "pmids",
                       max_items: int = 200) -> List[str]:
    """
    Validate list of PMIDs.

    Args:
        pmids: List of PMIDs or comma-separated string
        param_name: Name for error messages
        max_items: Maximum number of PMIDs allowed

    Returns:
        List of validated PMID strings

    Raises:
        ValidationError: If validation fails
    """
    if pmids is None:
        raise ValidationError(
            f"{param_name} cannot be None",
            param_name=param_name
        )

    # Handle string input
    if isinstance(pmids, str):
        pmids = [p.strip() for p in pmids.split(',')]

    # Handle single item
    if not isinstance(pmids, (list, tuple)):
        pmids = [pmids]

    if len(pmids) == 0:
        raise ValidationError(
            f"{param_name} cannot be empty",
            param_name=param_name
        )

    if len(pmids) > max_items:
        raise ValidationError(
            f"Too many PMIDs (maximum {max_items})",
            param_name=param_name,
            suggestion="Split into multiple requests"
        )

    # Validate each PMID
    validated = []
    for i, pmid in enumerate(pmids):
        try:
            validated.append(validate_pmid_param(pmid, f"{param_name}[{i}]"))
        except ValidationError:
            # Skip invalid PMIDs but track them
            pass

    if len(validated) == 0:
        raise ValidationError(
            "No valid PMIDs provided",
            param_name=param_name,
            suggestion="Provide at least one valid PMID"
        )

    return validated


def validate_arxiv_id_param(arxiv_id: Any, param_name: str = "arxiv_id") -> str:
    """
    Validate and normalize arXiv ID parameter.

    Supports modern IDs (YYMM.NNNNN[vN]) and legacy IDs (archive/NNNNNNN[vN]).
    Also accepts full arXiv URLs and arXiv: prefixed IDs.

    Args:
        arxiv_id: Value to validate
        param_name: Name for error messages

    Returns:
        Normalized arXiv ID string

    Raises:
        ValidationError: If validation fails

    Example:
        >>> validate_arxiv_id_param("2602.04557v1")
        "2602.04557v1"
        >>> validate_arxiv_id_param("https://arxiv.org/abs/2602.04557v1")
        "2602.04557v1"
    """
    if arxiv_id is None:
        raise ValidationError(
            f"{param_name} cannot be None",
            param_name=param_name,
            suggestion="Provide a valid arXiv ID (e.g., 2602.04557 or 2602.04557v1)"
        )

    id_str = str(arxiv_id).strip()

    if not id_str:
        raise ValidationError(
            f"{param_name} cannot be empty",
            param_name=param_name,
            suggestion="Provide a valid arXiv ID"
        )

    # Remove URL prefixes
    id_str = re.sub(r'^https?://(www\.)?arxiv\.org/(abs|html|pdf)/', '', id_str)
    # Remove arXiv: prefix
    id_str = re.sub(r'^arXiv:\s*', '', id_str, flags=re.IGNORECASE)
    # Remove trailing .pdf
    id_str = re.sub(r'\.pdf$', '', id_str)

    # Validate format
    modern_pattern = r'^\d{4}\.\d{4,5}(v\d+)?$'
    legacy_pattern = r'^[a-z-]+/\d{7}(v\d+)?$'

    if not (re.match(modern_pattern, id_str) or re.match(legacy_pattern, id_str)):
        raise ValidationError(
            f"Invalid arXiv ID format: '{arxiv_id}'",
            param_name=param_name,
            suggestion="arXiv ID should be YYMM.NNNNN[vN] (e.g., 2602.04557v1) or archive/NNNNNNN (e.g., hep-ex/0307015)"
        )

    return id_str


def validate_biorxiv_doi_param(doi: Any, param_name: str = "doi") -> str:
    """
    Validate and normalize bioRxiv/medRxiv DOI parameter.

    Supports both legacy (10.1101) and new (10.64898) DOI prefixes.
    Also accepts full URLs and doi: prefixed values.

    Args:
        doi: Value to validate
        param_name: Name for error messages

    Returns:
        Normalized DOI string

    Raises:
        ValidationError: If validation fails

    Example:
        >>> validate_biorxiv_doi_param("10.1101/2024.01.15.575889")
        "10.1101/2024.01.15.575889"
        >>> validate_biorxiv_doi_param("https://www.biorxiv.org/content/10.1101/2024.01.15.575889v1")
        "10.1101/2024.01.15.575889"
    """
    if doi is None:
        raise ValidationError(
            f"{param_name} cannot be None",
            param_name=param_name,
            suggestion="Provide a valid bioRxiv/medRxiv DOI (e.g., 10.1101/2024.01.15.575889)"
        )

    doi_str = str(doi).strip()

    if not doi_str:
        raise ValidationError(
            f"{param_name} cannot be empty",
            param_name=param_name,
            suggestion="Provide a valid bioRxiv/medRxiv DOI"
        )

    # Remove URL prefixes
    doi_str = re.sub(r'^https?://(www\.)?(bio|med)rxiv\.org/content/', '', doi_str)
    doi_str = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi_str)
    doi_str = re.sub(r'^doi:\s*', '', doi_str, flags=re.IGNORECASE)

    # Remove version suffix (v1, v2, etc.)
    doi_str = re.sub(r'v\d+$', '', doi_str)

    # Remove trailing suffixes like .full, .abstract
    doi_str = re.sub(r'\.(full|abstract|pdf)$', '', doi_str, flags=re.IGNORECASE)

    # Validate format
    # bioRxiv DOI patterns:
    # Legacy: 10.1101/YYYY.MM.DD.XXXXXX
    # New: 10.64898/YYYY.MM.DD.XXXXXX
    biorxiv_pattern = r'^10\.(1101|64898)/\d{4}\.\d{2}\.\d{2}\.\d{6,8}$'

    if not re.match(biorxiv_pattern, doi_str):
        raise ValidationError(
            f"Invalid bioRxiv/medRxiv DOI format: '{doi}'",
            param_name=param_name,
            suggestion="DOI should be 10.1101/YYYY.MM.DD.XXXXXX (e.g., 10.1101/2024.01.15.575889)"
        )

    return doi_str


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test parameter validators."""
    print("Testing Parameter Validators...\n")

    # Test PMID validation
    print("1. Testing validate_pmid_param():")
    test_cases = [
        ("12345678", True),
        ("PMID: 12345678", True),
        ("PMID:12345678", True),
        ("invalid", False),
        ("123456789", False),  # Too long
        (None, False),
    ]
    for value, should_pass in test_cases:
        try:
            result = validate_pmid_param(value)
            status = "" if should_pass else " (UNEXPECTED SUCCESS)"
            print(f"   '{value}' -> '{result}'{status}")
        except ValidationError as e:
            status = "" if not should_pass else " (UNEXPECTED FAILURE)"
            print(f"   '{value}' -> ERROR: {e.message}{status}")

    # Test query validation
    print("\n2. Testing validate_query_param():")
    test_queries = [
        ("CRISPR gene editing", True),
        ("a", False),  # Too short
        ("<script>alert(1)</script>", False),
    ]
    for query, should_pass in test_queries:
        try:
            result = validate_query_param(query)
            status = "" if should_pass else " (UNEXPECTED SUCCESS)"
            print(f"   '{query}' -> OK{status}")
        except ValidationError as e:
            status = "" if not should_pass else " (UNEXPECTED FAILURE)"
            print(f"   '{query}' -> ERROR: {e.message}{status}")

    # Test date validation
    print("\n3. Testing validate_date_param():")
    test_dates = [
        ("2024/01/15", True),
        ("2024-01-15", True),
        ("2024", True),
        ("invalid", False),
        ("2050/01/01", False),  # Future
    ]
    for date, should_pass in test_dates:
        try:
            result = validate_date_param(date)
            status = "" if should_pass else " (UNEXPECTED SUCCESS)"
            print(f"   '{date}' -> '{result}'{status}")
        except ValidationError as e:
            status = "" if not should_pass else " (UNEXPECTED FAILURE)"
            print(f"   '{date}' -> ERROR: {e.message}{status}")

    # Test max_results validation
    print("\n4. Testing validate_max_results():")
    test_values = [
        (20, True),
        (100, True),
        (0, False),
        (50000, False),
        ("invalid", False),
    ]
    for value, should_pass in test_values:
        try:
            result = validate_max_results(value)
            status = "" if should_pass else " (UNEXPECTED SUCCESS)"
            print(f"   {value} -> {result}{status}")
        except ValidationError as e:
            status = "" if not should_pass else " (UNEXPECTED FAILURE)"
            print(f"   {value} -> ERROR: {e.message}{status}")

    print("\n All parameter validator tests passed!")


if __name__ == "__main__":
    main()
