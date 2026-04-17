#!/usr/bin/env python3
"""
bioRxiv/medRxiv full text retrieval.
Fetches and parses full text from JATS XML or HTML versions of preprints.
"""

import sys
from pathlib import Path
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import re
from typing import Optional, Dict, Any, List
import logging
import time

from .utils.validators.parameter_validator import (
    validate_biorxiv_doi_param,
    ValidationError,
)
from .utils.cache_manager import get_cache, CacheManager
from .utils.rate_limiter import throttle, report_success, report_error
from .fetch_biorxiv import fetch_biorxiv_paper

logger = logging.getLogger(__name__)
USER_AGENT = 'pubmed-reader-cskill/1.4.0 (literature search tool)'


def check_fulltext_availability(doi: str, server: Optional[str] = None) -> Dict[str, Any]:
    try:
        doi = validate_biorxiv_doi_param(doi)
    except ValidationError as e:
        return {"available": False, "error": e.message}

    result = fetch_biorxiv_paper(doi, server=server)
    if not result.get("success"):
        return {
            "available": False, "doi": doi,
            "error": result.get("error", {}).get("message", "Paper not found")
        }

    jatsxml_url = result.get("jatsxml", "")
    srv = result.get("server", "biorxiv")
    return {
        "available": True, "doi": doi,
        "jatsxml_url": jatsxml_url if jatsxml_url else None,
        "html_url": f"https://www.{srv}.org/content/{doi}.full",
        "pdf_url": f"https://www.{srv}.org/content/{doi}.full.pdf",
        "server": srv,
        "message": "Full text available via JATS XML and HTML"
    }


def get_biorxiv_fulltext(
    doi: str,
    server: Optional[str] = None,
    use_cache: bool = True,
    prefer_jats: bool = True
) -> Dict[str, Any]:
    """Retrieve full text of a bioRxiv/medRxiv preprint."""
    try:
        doi = validate_biorxiv_doi_param(doi)
    except ValidationError as e:
        return {
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": e.message, "suggestion": e.suggestion}
        }

    cache_key = f"biorxiv_fulltext:{doi}"
    if use_cache:
        cached = get_cache().get(cache_key)
        if cached:
            logger.info(f"Cache hit for bioRxiv full text: {doi}")
            return cached

    paper = fetch_biorxiv_paper(doi, server=server, use_cache=use_cache)
    if not paper.get("success"):
        return paper

    srv = paper.get("server", "biorxiv")
    jatsxml_url = paper.get("jatsxml", "")
    title = paper.get("title", "Untitled")

    result = None
    if prefer_jats and jatsxml_url:
        result = _fetch_and_parse_jats(jatsxml_url, doi, title, srv)
    if not result or not result.get("success"):
        html_url = f"https://www.{srv}.org/content/{doi}.full"
        result = _fetch_and_parse_html(html_url, doi, title, srv)

    if use_cache and result.get("success"):
        get_cache().set(cache_key, result, ttl=CacheManager.TTL_FULLTEXT)
    return result


def _fetch_and_parse_jats(url: str, doi: str, title: str, server: str) -> Dict[str, Any]:
    try:
        throttle()
        time.sleep(0.3)
        req = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT, 'Accept': 'application/xml',
        })
        with urllib.request.urlopen(req, timeout=60) as response:
            xml_data = response.read().decode('utf-8')
        report_success()
    except urllib.error.HTTPError as e:
        report_error()
        return {"success": False, "doi": doi,
                "error": {"code": "HTTP_ERROR", "message": f"HTTP error {e.code} fetching JATS XML"}}
    except urllib.error.URLError as e:
        report_error()
        return {"success": False, "doi": doi,
                "error": {"code": "NETWORK_ERROR", "message": f"Failed to fetch JATS XML: {e}",
                          "suggestion": "Check network connection and try again"}}
    return _parse_jats_xml(xml_data, doi, title, server)


def _parse_jats_xml(xml_data: str, doi: str, title: str, server: str) -> Dict[str, Any]:
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        return {"success": False, "doi": doi,
                "error": {"code": "PARSE_ERROR", "message": f"Failed to parse JATS XML: {e}"}}

    ns: Dict[str, str] = {}
    if root.tag.startswith('{'):
        ns_end = root.tag.find('}')
        ns['jats'] = root.tag[1:ns_end]

    def find_with_ns(elem, path):
        result = elem.find(path)
        if result is None and ns.get('jats'):
            ns_path = path.replace('/', '/{' + ns['jats'] + '}')
            if not ns_path.startswith('{'):
                ns_path = '{' + ns['jats'] + '}' + ns_path
            result = elem.find(ns_path)
        return result

    def findall_with_ns(elem, path):
        results = elem.findall(path)
        if not results and ns.get('jats'):
            ns_path = './/' + '{' + ns['jats'] + '}' + path.split('/')[-1]
            results = elem.findall(ns_path)
        return results

    if title == "Untitled":
        title_elem = find_with_ns(root, './/article-title')
        if title_elem is not None:
            title = _get_element_text(title_elem)

    abstract = ""
    abstract_elem = find_with_ns(root, './/abstract')
    if abstract_elem is not None:
        abstract = _get_element_text(abstract_elem)

    sections: Dict[str, str] = {}
    if abstract:
        sections["Abstract"] = abstract

    body = find_with_ns(root, './/body')
    if body is not None:
        for sec in (body.findall('.//sec') if not ns.get('jats') else body.findall('.//{' + ns['jats'] + '}sec')):
            sec_title_elem = sec.find('title') if not ns.get('jats') else sec.find('{' + ns['jats'] + '}title')
            if sec_title_elem is not None:
                sec_title = _get_element_text(sec_title_elem).strip()
                sec_content = _get_section_text(sec)
                if sec_title and sec_content:
                    sections[sec_title] = sec_content

    figures: List[Dict[str, str]] = []
    for fig in findall_with_ns(root, './/fig'):
        fig_id = fig.get('id', '')
        caption_elem = fig.find('.//caption') if not ns.get('jats') else fig.find('.//{' + ns['jats'] + '}caption')
        caption = _get_element_text(caption_elem) if caption_elem is not None else ""
        figures.append({"id": fig_id, "caption": caption[:500]})

    references: List[str] = []
    ref_list = find_with_ns(root, './/ref-list')
    if ref_list is not None:
        for ref in (ref_list.findall('.//ref') if not ns.get('jats') else ref_list.findall('.//{' + ns['jats'] + '}ref')):
            ref_text = _get_element_text(ref)
            if ref_text and len(ref_text) > 10:
                references.append(ref_text)

    full_text_parts = []
    for sec_name, content in sections.items():
        if sec_name.lower() != "references":
            full_text_parts.append(content)
    full_text = "\n\n".join(full_text_parts)
    word_count = len(full_text.split()) if full_text else 0

    if word_count < 50 and not sections:
        return {"success": False, "doi": doi,
                "error": {"code": "PARSE_ERROR", "message": "Could not extract meaningful content from JATS XML",
                          "suggestion": f"Try the HTML version or PDF at https://www.{server}.org/content/{doi}.full.pdf"}}

    return {
        "success": True, "doi": doi, "title": title,
        "sections": sections, "full_text": full_text,
        "figures": figures, "references": references,
        "word_count": word_count,
        "html_url": f"https://www.{server}.org/content/{doi}.full",
        "pdf_url": f"https://www.{server}.org/content/{doi}.full.pdf",
        "source": server, "format": "jats"
    }


def _fetch_and_parse_html(url: str, doi: str, title: str, server: str) -> Dict[str, Any]:
    try:
        throttle()
        time.sleep(0.3)
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html'})
        with urllib.request.urlopen(req, timeout=60) as response:
            html_data = response.read().decode('utf-8')
        report_success()
    except urllib.error.HTTPError as e:
        report_error()
        if e.code == 404:
            return {"success": False, "doi": doi,
                    "error": {"code": "NOT_AVAILABLE", "message": f"HTML full text not available for {doi}",
                              "suggestion": f"Try the PDF at https://www.{server}.org/content/{doi}.full.pdf"}}
        return {"success": False, "doi": doi,
                "error": {"code": "HTTP_ERROR", "message": f"HTTP error {e.code} fetching HTML"}}
    except urllib.error.URLError as e:
        report_error()
        return {"success": False, "doi": doi,
                "error": {"code": "NETWORK_ERROR", "message": f"Failed to fetch HTML: {e}",
                          "suggestion": "Check network connection and try again"}}
    return _parse_html_fulltext(html_data, doi, title, server)


def _parse_html_fulltext(html: str, doi: str, title: str, server: str) -> Dict[str, Any]:
    html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html_clean, flags=re.DOTALL | re.IGNORECASE)
    if title == "Untitled":
        title = _extract_html_title(html_clean)

    abstract = _extract_html_abstract(html_clean)
    sections = _extract_html_sections(html_clean)
    if abstract:
        sections = {"Abstract": abstract, **sections}

    figures = _extract_html_figures(html_clean)
    references = _extract_html_references(html_clean)

    full_text_parts = []
    for section_name, content in sections.items():
        if section_name.lower() != "references":
            full_text_parts.append(content)
    full_text = "\n\n".join(full_text_parts)
    word_count = len(full_text.split()) if full_text else 0

    if word_count < 50 and not sections:
        return {"success": False, "doi": doi,
                "error": {"code": "PARSE_ERROR", "message": "Could not extract meaningful content from HTML",
                          "suggestion": f"Try the PDF at https://www.{server}.org/content/{doi}.full.pdf"}}

    return {
        "success": True, "doi": doi, "title": title,
        "sections": sections, "full_text": full_text,
        "figures": figures, "references": references,
        "word_count": word_count,
        "html_url": f"https://www.{server}.org/content/{doi}.full",
        "pdf_url": f"https://www.{server}.org/content/{doi}.full.pdf",
        "source": server, "format": "html"
    }


def _get_element_text(elem) -> str:
    if elem is None:
        return ""
    text_parts = []
    if elem.text:
        text_parts.append(elem.text)
    for child in elem:
        text_parts.append(_get_element_text(child))
        if child.tail:
            text_parts.append(child.tail)
    return ' '.join(text_parts).strip()


def _get_section_text(sec_elem) -> str:
    text_parts = []
    for child in sec_elem:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag in ('sec', 'title'):
            continue
        text_parts.append(_get_element_text(child))
    return ' '.join(text_parts).strip()


def _strip_tags(html: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _extract_html_title(html: str) -> str:
    match = re.search(r'<h1[^>]*class="[^"]*highwire-cite-title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
    if match:
        return _strip_tags(match.group(1))
    match = re.search(r'<title>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if match:
        title = _strip_tags(match.group(1))
        title = re.sub(r'\s*[\|\-]\s*(bioRxiv|medRxiv).*$', '', title, flags=re.IGNORECASE)
        return title
    return "Untitled"


def _extract_html_abstract(html: str) -> str:
    match = re.search(r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
    if match:
        content = match.group(1)
        content = re.sub(r'<h\d[^>]*>.*?Abstract.*?</h\d>', '', content, flags=re.DOTALL | re.IGNORECASE)
        return _strip_tags(content)
    match = re.search(r'<section[^>]*id="abstract"[^>]*>(.*?)</section>', html, re.DOTALL | re.IGNORECASE)
    if match:
        content = match.group(1)
        content = re.sub(r'<h\d[^>]*>.*?</h\d>', '', content, flags=re.DOTALL)
        return _strip_tags(content)
    return ""


def _extract_html_sections(html: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    main_content = html
    section_pattern = re.compile(
        r'<div[^>]*class="[^"]*section[^"]*"[^>]*>'
        r'.*?<h\d[^>]*>(.*?)</h\d>'
        r'(.*?)</div>',
        re.DOTALL | re.IGNORECASE
    )
    for match in section_pattern.finditer(main_content):
        heading = _strip_tags(match.group(1))
        content = _strip_tags(match.group(2))
        heading = re.sub(r'^\d+\.?\s*', '', heading).strip()
        if heading and content and len(content) > 20:
            sections[heading] = content
    if sections:
        return sections

    heading_pattern = re.compile(r'<h[23][^>]*>(.*?)</h[23]>', re.DOTALL | re.IGNORECASE)
    headings = list(heading_pattern.finditer(main_content))
    for i, heading_match in enumerate(headings):
        heading = _strip_tags(heading_match.group(1))
        heading = re.sub(r'^\d+\.?\s*', '', heading).strip()
        start = heading_match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(main_content)
        content = main_content[start:end]
        for stop_tag in ['<footer', '<nav', '</article', '</main', '<div class="ref-list']:
            stop_idx = content.lower().find(stop_tag)
            if stop_idx > 0:
                content = content[:stop_idx]
        content = _strip_tags(content)
        if heading and content and len(content) > 20:
            sections[heading] = content
    return sections


def _extract_html_figures(html: str) -> List[Dict[str, str]]:
    figures: List[Dict[str, str]] = []
    fig_pattern = re.compile(
        r'<div[^>]*class="[^"]*fig[^"]*"[^>]*id="([^"]*)"[^>]*>.*?'
        r'(?:<div[^>]*class="[^"]*caption[^"]*"[^>]*>(.*?)</div>)?',
        re.DOTALL | re.IGNORECASE
    )
    for match in fig_pattern.finditer(html):
        fig_id = match.group(1)
        caption = _strip_tags(match.group(2)) if match.group(2) else ""
        figures.append({"id": fig_id, "caption": caption[:500]})
    if figures:
        return figures

    fig_pattern2 = re.compile(
        r'<figure[^>]*>.*?(?:<figcaption[^>]*>(.*?)</figcaption>)?.*?</figure>',
        re.DOTALL | re.IGNORECASE
    )
    for i, match in enumerate(fig_pattern2.finditer(html)):
        caption = _strip_tags(match.group(1)) if match.group(1) else ""
        figures.append({"id": f"fig{i+1}", "caption": caption[:500]})
    return figures


def _extract_html_references(html: str) -> List[str]:
    references: List[str] = []
    ref_pattern = re.compile(r'<li[^>]*class="[^"]*ref-content[^"]*"[^>]*>(.*?)</li>', re.DOTALL | re.IGNORECASE)
    for match in ref_pattern.finditer(html):
        ref_text = _strip_tags(match.group(1))
        ref_text = re.sub(r'^\s*\d+\.?\s*', '', ref_text)
        if ref_text and len(ref_text) > 10:
            references.append(ref_text)
    if references:
        return references

    ref_section = re.search(
        r'(?:References|Bibliography|REFERENCES).*?(<ol[^>]*>.*?</ol>|<ul[^>]*>.*?</ul>)',
        html, re.DOTALL | re.IGNORECASE
    )
    if ref_section:
        li_pattern = re.compile(r'<li[^>]*>(.*?)</li>', re.DOTALL | re.IGNORECASE)
        for match in li_pattern.finditer(ref_section.group(1)):
            ref_text = _strip_tags(match.group(1))
            ref_text = re.sub(r'^\s*\d+\.?\s*', '', ref_text)
            if ref_text and len(ref_text) > 10:
                references.append(ref_text)
    return references


def format_biorxiv_fulltext(result: Dict[str, Any], max_words: Optional[int] = None) -> str:
    if not result.get("success"):
        error = result.get("error", {})
        return f"Error: {error.get('message', 'Unknown error')}"

    lines = []
    doi = result.get("doi", "")
    title = result.get("title", "Untitled")
    server = result.get("source", "biorxiv")

    lines.append(f"## Full Text: {server}:{doi}")
    lines.append("")
    lines.append(f"**Title**: {title}")
    lines.append(f"**Word Count**: {result.get('word_count', 0):,} words")
    lines.append(f"**Format**: {result.get('format', 'unknown').upper()}")
    lines.append("")

    section_order = [
        "Abstract", "Introduction", "Background",
        "Methods", "Materials and Methods", "Experimental",
        "Results", "Findings",
        "Discussion", "Conclusion", "Conclusions",
    ]
    sections = result.get("sections", {})
    displayed = set()
    for section_name in section_order:
        for actual_name, content in sections.items():
            if actual_name.lower() == section_name.lower() and actual_name not in displayed:
                if max_words:
                    words = content.split()
                    if len(words) > max_words:
                        content = " ".join(words[:max_words]) + "..."
                lines.append(f"### {actual_name}")
                lines.append("")
                lines.append(content)
                lines.append("")
                displayed.add(actual_name)
                break
    for section_name, content in sections.items():
        if section_name not in displayed:
            if max_words:
                words = content.split()
                if len(words) > max_words:
                    content = " ".join(words[:max_words]) + "..."
            lines.append(f"### {section_name}")
            lines.append("")
            lines.append(content)
            lines.append("")

    figures = result.get("figures", [])
    if figures:
        lines.append(f"### Figures ({len(figures)} total)")
        for fig in figures[:10]:
            caption = fig.get("caption", "")[:150]
            lines.append(f"- {fig.get('id', 'Fig')}: {caption}")
        lines.append("")

    references = result.get("references", [])
    if references:
        lines.append(f"### References ({len(references)} total)")
        for ref in references[:5]:
            lines.append(f"- {ref[:150]}...")
        if len(references) > 5:
            lines.append(f"- ... and {len(references) - 5} more")
        lines.append("")

    return "\n".join(lines)
