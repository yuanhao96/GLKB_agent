#!/usr/bin/env python3
"""
Response validators for PubMed Reader skill.
Validates API responses and data quality.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import re
import logging

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """Severity levels for validation results."""
    CRITICAL = "critical"  # Must fix - data unusable
    WARNING = "warning"    # Should review - data may be incomplete
    INFO = "info"          # Informational - FYI


@dataclass
class ValidationResult:
    """Single validation check result."""
    check_name: str
    level: ValidationLevel
    passed: bool
    message: str
    details: Optional[Dict] = None


@dataclass
class ValidationReport:
    """Collection of validation results."""
    results: List[ValidationResult] = field(default_factory=list)

    def add(self, result: ValidationResult):
        """Add validation result."""
        self.results.append(result)

    def has_critical_issues(self) -> bool:
        """Check if any critical issues found."""
        return any(
            r.level == ValidationLevel.CRITICAL and not r.passed
            for r in self.results
        )

    def all_passed(self) -> bool:
        """Check if all validations passed."""
        return all(r.passed for r in self.results)

    def get_warnings(self) -> List[str]:
        """Get all warning messages."""
        return [
            r.message for r in self.results
            if r.level == ValidationLevel.WARNING and not r.passed
        ]

    def get_critical(self) -> List[str]:
        """Get all critical error messages."""
        return [
            r.message for r in self.results
            if r.level == ValidationLevel.CRITICAL and not r.passed
        ]

    def get_summary(self) -> str:
        """Get summary of validation results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        critical = sum(
            1 for r in self.results
            if r.level == ValidationLevel.CRITICAL and not r.passed
        )
        warnings = sum(
            1 for r in self.results
            if r.level == ValidationLevel.WARNING and not r.passed
        )

        return (
            f"Validation: {passed}/{total} passed "
            f"({critical} critical, {warnings} warnings)"
        )


class ResponseValidator:
    """Validates API responses."""

    def validate_response_basic(self, data: Any) -> ValidationReport:
        """
        Basic validation for any API response.

        Args:
            data: Raw API response

        Returns:
            ValidationReport with results
        """
        report = ValidationReport()

        # Check not empty
        report.add(ValidationResult(
            check_name="not_empty",
            level=ValidationLevel.CRITICAL,
            passed=data is not None and (
                (isinstance(data, (str, list, dict)) and len(data) > 0) or
                (isinstance(data, (int, float, bool)))
            ),
            message="Data is empty" if not data else "Data present"
        ))

        return report


def validate_esearch_response(data: Dict[str, Any]) -> ValidationReport:
    """
    Validate ESearch API response.

    Args:
        data: Parsed ESearch response

    Returns:
        ValidationReport
    """
    report = ValidationReport()

    # Check response structure
    report.add(ValidationResult(
        check_name="is_dict",
        level=ValidationLevel.CRITICAL,
        passed=isinstance(data, dict),
        message="Response is dict" if isinstance(data, dict) else "Response is not a dict"
    ))

    if not isinstance(data, dict):
        return report

    # Check for error
    if 'error' in data:
        report.add(ValidationResult(
            check_name="no_error",
            level=ValidationLevel.CRITICAL,
            passed=False,
            message=f"API error: {data.get('error', 'Unknown error')}"
        ))
        return report

    # Check esearchresult key
    esearch = data.get('esearchresult', {})
    report.add(ValidationResult(
        check_name="has_esearchresult",
        level=ValidationLevel.CRITICAL,
        passed='esearchresult' in data,
        message="Has esearchresult key" if 'esearchresult' in data else "Missing esearchresult"
    ))

    # Check count field
    count = esearch.get('count')
    report.add(ValidationResult(
        check_name="has_count",
        level=ValidationLevel.WARNING,
        passed=count is not None,
        message=f"Result count: {count}" if count else "Missing count field"
    ))

    # Check idlist
    idlist = esearch.get('idlist', [])
    report.add(ValidationResult(
        check_name="has_idlist",
        level=ValidationLevel.INFO,
        passed=isinstance(idlist, list),
        message=f"ID list has {len(idlist)} items" if isinstance(idlist, list) else "Missing idlist"
    ))

    # Validate IDs are numeric
    if idlist:
        all_numeric = all(str(id).isdigit() for id in idlist)
        report.add(ValidationResult(
            check_name="valid_ids",
            level=ValidationLevel.WARNING,
            passed=all_numeric,
            message="All IDs are numeric" if all_numeric else "Some IDs are not numeric"
        ))

    return report


def validate_efetch_response(data: Dict[str, Any],
                            expected_fields: Optional[List[str]] = None) -> ValidationReport:
    """
    Validate EFetch API response.

    Args:
        data: Parsed EFetch response
        expected_fields: Fields that should be present

    Returns:
        ValidationReport
    """
    report = ValidationReport()

    # Check response structure
    report.add(ValidationResult(
        check_name="is_dict",
        level=ValidationLevel.CRITICAL,
        passed=isinstance(data, dict),
        message="Response is dict" if isinstance(data, dict) else "Response is not a dict"
    ))

    if not isinstance(data, dict):
        return report

    # Check for PubmedArticle or PubmedArticleSet
    has_article = (
        'PubmedArticle' in data or
        'PubmedArticleSet' in data or
        'pmid' in data or
        'title' in data
    )
    report.add(ValidationResult(
        check_name="has_article_data",
        level=ValidationLevel.CRITICAL,
        passed=has_article,
        message="Has article data" if has_article else "Missing article data"
    ))

    # Check expected fields
    if expected_fields:
        for field in expected_fields:
            has_field = field in data
            report.add(ValidationResult(
                check_name=f"has_{field}",
                level=ValidationLevel.WARNING,
                passed=has_field,
                message=f"Has '{field}'" if has_field else f"Missing '{field}'"
            ))

    return report


def validate_elink_response(data: Dict[str, Any]) -> ValidationReport:
    """
    Validate ELink API response.

    Args:
        data: Parsed ELink response

    Returns:
        ValidationReport
    """
    report = ValidationReport()

    # Check response structure
    report.add(ValidationResult(
        check_name="is_dict",
        level=ValidationLevel.CRITICAL,
        passed=isinstance(data, dict),
        message="Response is dict" if isinstance(data, dict) else "Response is not a dict"
    ))

    if not isinstance(data, dict):
        return report

    # Check for linksets
    linksets = data.get('linksets', [])
    report.add(ValidationResult(
        check_name="has_linksets",
        level=ValidationLevel.CRITICAL,
        passed=isinstance(linksets, list) and len(linksets) > 0,
        message=f"Has {len(linksets)} linkset(s)" if linksets else "No linksets found"
    ))

    # Check for linked IDs
    if linksets:
        first_linkset = linksets[0]
        linksetdbs = first_linkset.get('linksetdbs', [])
        total_links = 0
        for linksetdb in linksetdbs:
            links = linksetdb.get('links', [])
            total_links += len(links)

        report.add(ValidationResult(
            check_name="has_links",
            level=ValidationLevel.INFO,
            passed=total_links > 0,
            message=f"Found {total_links} linked IDs" if total_links else "No linked IDs found"
        ))

    return report


def validate_bioc_response(data: Dict[str, Any]) -> ValidationReport:
    """
    Validate BioC PMC API response.

    Args:
        data: Parsed BioC response

    Returns:
        ValidationReport
    """
    report = ValidationReport()

    # Check response structure
    report.add(ValidationResult(
        check_name="is_dict",
        level=ValidationLevel.CRITICAL,
        passed=isinstance(data, dict),
        message="Response is dict" if isinstance(data, dict) else "Response is not a dict"
    ))

    if not isinstance(data, dict):
        return report

    # Check for documents
    documents = data.get('documents', [])
    report.add(ValidationResult(
        check_name="has_documents",
        level=ValidationLevel.CRITICAL,
        passed=isinstance(documents, list) and len(documents) > 0,
        message=f"Has {len(documents)} document(s)" if documents else "No documents found"
    ))

    if not documents:
        return report

    # Validate first document
    doc = documents[0]

    # Check for passages (text content)
    passages = doc.get('passages', [])
    report.add(ValidationResult(
        check_name="has_passages",
        level=ValidationLevel.WARNING,
        passed=len(passages) > 0,
        message=f"Has {len(passages)} passage(s)" if passages else "No passages found"
    ))

    # Check for infons (metadata)
    infons = doc.get('infons', {})
    report.add(ValidationResult(
        check_name="has_infons",
        level=ValidationLevel.INFO,
        passed=bool(infons),
        message="Has metadata (infons)" if infons else "Missing metadata"
    ))

    # Check text content quality
    if passages:
        total_text_length = sum(
            len(p.get('text', '')) for p in passages
        )
        report.add(ValidationResult(
            check_name="text_length",
            level=ValidationLevel.INFO,
            passed=total_text_length > 100,
            message=f"Total text: {total_text_length} chars"
        ))

    return report


def validate_article_metadata(article: Dict[str, Any]) -> ValidationReport:
    """
    Validate parsed article metadata.

    Args:
        article: Parsed article dict

    Returns:
        ValidationReport
    """
    report = ValidationReport()

    # Required fields
    required = ['pmid', 'title']
    for field in required:
        has_field = field in article and article[field]
        report.add(ValidationResult(
            check_name=f"has_{field}",
            level=ValidationLevel.CRITICAL,
            passed=has_field,
            message=f"Has {field}" if has_field else f"Missing {field}"
        ))

    # Important fields
    important = ['authors', 'journal', 'year', 'abstract']
    for field in important:
        has_field = field in article and article[field]
        report.add(ValidationResult(
            check_name=f"has_{field}",
            level=ValidationLevel.WARNING,
            passed=has_field,
            message=f"Has {field}" if has_field else f"Missing {field}"
        ))

    # Validate PMID format
    pmid = article.get('pmid', '')
    valid_pmid = re.match(r'^\d{1,8}$', str(pmid)) is not None
    report.add(ValidationResult(
        check_name="valid_pmid_format",
        level=ValidationLevel.CRITICAL,
        passed=valid_pmid,
        message="PMID format valid" if valid_pmid else f"Invalid PMID: {pmid}"
    ))

    # Validate year if present
    year = article.get('year')
    if year:
        try:
            year_int = int(year)
            valid_year = 1800 <= year_int <= 2100
        except (ValueError, TypeError):
            valid_year = False

        report.add(ValidationResult(
            check_name="valid_year",
            level=ValidationLevel.WARNING,
            passed=valid_year,
            message=f"Year valid: {year}" if valid_year else f"Invalid year: {year}"
        ))

    return report


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test response validators."""
    print("Testing Response Validators...\n")

    # Test ESearch validation
    print("1. Testing validate_esearch_response():")
    valid_esearch = {
        "esearchresult": {
            "count": "10",
            "idlist": ["12345678", "87654321"]
        }
    }
    report = validate_esearch_response(valid_esearch)
    print(f"   Valid response: {report.get_summary()}")

    invalid_esearch = {"error": "Invalid query"}
    report = validate_esearch_response(invalid_esearch)
    print(f"   Error response: {report.get_summary()}")

    # Test EFetch validation
    print("\n2. Testing validate_efetch_response():")
    valid_efetch = {
        "pmid": "12345678",
        "title": "Test Article",
        "authors": [{"LastName": "Smith"}]
    }
    report = validate_efetch_response(valid_efetch, ['pmid', 'title', 'abstract'])
    print(f"   Valid response: {report.get_summary()}")

    # Test BioC validation
    print("\n3. Testing validate_bioc_response():")
    valid_bioc = {
        "documents": [{
            "passages": [
                {"text": "Introduction section with sufficient content..."},
                {"text": "Methods section..."}
            ],
            "infons": {"title": "Test Article"}
        }]
    }
    report = validate_bioc_response(valid_bioc)
    print(f"   Valid response: {report.get_summary()}")

    # Test article metadata validation
    print("\n4. Testing validate_article_metadata():")
    valid_article = {
        "pmid": "12345678",
        "title": "Test Article Title",
        "authors": [{"LastName": "Smith", "Initials": "J"}],
        "journal": "Nature",
        "year": 2024,
        "abstract": "This is the abstract..."
    }
    report = validate_article_metadata(valid_article)
    print(f"   Complete article: {report.get_summary()}")

    incomplete_article = {
        "pmid": "12345678",
        "title": "Test Article"
    }
    report = validate_article_metadata(incomplete_article)
    print(f"   Incomplete article: {report.get_summary()}")
    if report.get_warnings():
        print(f"   Warnings: {report.get_warnings()}")

    print("\n All response validator tests passed!")


if __name__ == "__main__":
    main()
