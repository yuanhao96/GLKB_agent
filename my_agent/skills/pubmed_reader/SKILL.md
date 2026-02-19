---
name: pubmed-reader
description: Article retrieval strategy and PubMed skill combining lookup and deep analysis. Guides tool selection across GLKB and PubMed for searching, reading abstracts, fetching full text, finding similar/citing articles, and comprehensive article reports.
---

# PubMed Reader — Search, Read, Cite, Explore, Analyze

Integrated from [pubmed-reader-cskill](https://github.com/yuanhao96/pubmed-reader-cskill). Provides direct NCBI E-utilities and BioC PMC API access, along with a retrieval strategy for combining GLKB knowledge graph search with PubMed literature search.

## Article Retrieval Strategy

You are a biomedical research assistant with access to both the GLKB knowledge graph and direct PubMed/PMC access.

IMPORTANT: You have access to the conversation history through the session's events.
When retrieving articles, consider the full conversation context, especially if the current
question is a follow-up or references previously discussed topics or articles.

Task:
1. Decide which biomedical concepts, keywords, and article PubMed IDs should be used as seeds.
2. Use the provided tools to retrieve relevant articles from GLKB and PubMed.
3. Produce a summary of literature evidence.

### Tool Selection Strategy

**Primary search — Use `article_search` (GLKB) first:**
- Searches the GLKB Neo4j index with pre-computed impact scores and journal impact factors.
- Best for finding high-impact, well-established literature already indexed in GLKB.

**Supplementary search — Use `search_pubmed` (NCBI) when:**
- GLKB results are insufficient or too few.
- The user asks for recent/latest articles (use date filters: min_date, max_date).
- The user specifies author, journal, or other filters not available in GLKB search.
- The topic is very new or niche and may not be well-covered in GLKB.

**Expand evidence from key articles:**
- Use `find_similar_articles` to discover related papers from a key seed PMID.
- Use `get_citing_articles` to find newer work that builds on a foundational paper.

**Deep article analysis:**
- Use `fetch_abstract` to get detailed metadata (MeSH terms, keywords) for a specific PMID.
- Use `get_fulltext` to read the full article content when deeper analysis is needed (only works for PMC Open Access articles).
- Use `comprehensive_report` for thorough single-article analysis (metadata + citations + full text).

### Guidelines
- Determine whether to prioritize recent articles or impactful articles based on the user question.
- Use a combination of GLKB and PubMed searches for comprehensive coverage.
- Try to analyze full articles to find the most relevant information to answer the user question.
- When using `search_pubmed`, leverage PubMed query syntax: field tags like [Title/Abstract], [MeSH Terms], [Author], boolean operators (AND, OR, NOT).

## Data Sources

### NCBI E-utilities API

**Base URL**: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

| Utility | Endpoint | Purpose |
|---------|----------|---------|
| ESearch | `esearch.fcgi` | Search PubMed, return PMIDs |
| EFetch | `efetch.fcgi` | Retrieve abstracts and metadata |
| ESummary | `esummary.fcgi` | Get document summaries |
| ELink | `elink.fcgi` | Find related/citing articles |

**Rate limits**: 3 req/sec (no key), 10 req/sec (with `NCBI_API_KEY` env var)

### BioC PMC API

Full text for ~3M Open Access articles.

```
https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/[PMID]/unicode
```

## Tools (FunctionTool wrappers in `tools.py`)

All tools are async wrappers using `asyncio.to_thread()` around the synchronous cskill functions.

### 1. `search_pubmed` — Search PubMed via NCBI ESearch

**Script**: `scripts/search_pubmed.py`

**Args**: `query`, `max_results` (1-200), `min_date` (YYYY/MM/DD), `max_date` (YYYY/MM/DD), `sort` ("relevance" | "pub+date")

**Returns**: `success`, `count`, `pmids`, `articles` (list of summaries with title, authors, journal, year, doi, pmc), `query_info`

**PubMed query syntax**: field tags `[Title]`, `[Author]`, `[Journal]`, `[MeSH Terms]`, `[Publication Date]`, `[Article Type]`; boolean operators AND, OR, NOT.

### 2. `fetch_abstract` — Fetch article metadata by PMID

**Script**: `scripts/fetch_article.py`

**Args**: `pmid`

**Returns**: `success`, `pmid`, `title`, `abstract`, `authors`, `journal`, `year`, `doi`, `pmc`, `mesh_terms`, `keywords`, `pub_types`

### 3. `get_fulltext` — Retrieve full text from PMC Open Access

**Script**: `scripts/fetch_fulltext.py`

**Args**: `article_id` (PMID or PMC ID)

**Returns**: `success`, `pmid`, `pmcid`, `title`, `sections` (dict of section_name → text), `full_text`, `figures`, `tables`, `references`, `word_count`

**Note**: Only ~3M Open Access articles have full text. If unavailable, returns error with suggestion to use abstract.

### 4. `find_similar_articles` — Find related papers via NCBI ELink

**Script**: `scripts/find_similar.py`

**Args**: `pmid`, `max_results`

**Returns**: `success`, `source_pmid`, `similar_count`, `articles` (with title, pmid, score, journal, year)

Discovers related research based on shared MeSH terms, shared citations, and content similarity algorithms.

### 5. `get_citing_articles` — Find papers that cite a PMID

**Script**: `scripts/find_citations.py`

**Args**: `pmid`, `max_results`

**Returns**: `success`, `source_pmid`, `citation_count`, `articles` (sorted newest first), `by_year` (grouped by publication year)

### 6. `comprehensive_report` — Full single-article analysis

**Script**: `scripts/comprehensive_report.py`

**Args**: `pmid`

**Returns**: `success`, `pmid`, `article` (metadata), `fulltext` (if OA), `similar_articles`, `citing_articles`, `references`, `metrics` (citations_per_year, recent_velocity), `summary`, `quick_stats`, `alerts`

Combines all available analyses into a single comprehensive report.

## Additional Scripts (not exposed as tools)

- `scripts/strategic_literature_search.py` — Reviews-first multi-phase literature exploration
- `scripts/comprehensive_report.py` — Also provides `literature_overview()` and `compare_articles()`
- `scripts/search_pubmed.py` — Also provides `build_advanced_query()`, `search_by_date_range()`, `search_by_year()`
- `scripts/find_similar.py` — Also provides `find_by_mesh_terms()`, `find_by_author()`, `find_review_articles()`
- `scripts/find_citations.py` — Also provides `get_references()`, `get_citation_network()`, `get_citation_metrics()`

## Utility Modules

- `scripts/utils/helpers.py` — PMID/DOI validation, date formatting, author formatting, API param building
- `scripts/utils/cache_manager.py` — In-memory + file-based caching with configurable TTL
- `scripts/utils/rate_limiter.py` — Adaptive rate limiter respecting NCBI limits (3 or 10 req/s)
- `scripts/utils/validators/` — Parameter validation and API response validation

## Configuration

`assets/config.json` contains defaults for API URLs, rate limits, cache TTL, and feature flags.

| Env Variable | Default | Description |
|--------------|---------|-------------|
| `NCBI_API_KEY` | None | API key for 10 req/sec (get at https://www.ncbi.nlm.nih.gov/account/settings/) |
| `NCBI_EMAIL` | None | Contact email for NCBI E-utilities (recommended for production) |

## Error Handling

| Error | Solution |
|-------|----------|
| PMID not found | Verify PMID is correct |
| Rate limit exceeded | Set NCBI_API_KEY or wait |
| Full text not available | Use `fetch_abstract` instead |
| Network timeout | Automatic retry with backoff |
| Validation error | Check parameter format (dates: YYYY/MM/DD, PMID: numeric) |
