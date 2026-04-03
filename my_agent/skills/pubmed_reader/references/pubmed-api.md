# PubMed API Reference

## NCBI E-utilities

**Base URL**: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

| Utility | Endpoint | Purpose |
|---------|----------|---------|
| ESearch | `esearch.fcgi` | Search PubMed, return PMIDs |
| EFetch | `efetch.fcgi` | Retrieve abstracts and metadata |
| ESummary | `esummary.fcgi` | Get document summaries |
| ELink | `elink.fcgi` | Find related/citing articles |

**Rate limits**: 3 req/sec (no API key), 10 req/sec (with `NCBI_API_KEY` env var)

## BioC PMC API (Full Text)

~3 million Open Access articles available.

```
https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/[PMID_or_PMCID]/unicode
```

Only articles in the PMC Open Access Subset are available through this API.

## PubMed Query Syntax

### Field Tags
- `[Title]` — search in article titles only
- `[Title/Abstract]` — search in titles and abstracts
- `[Author]` — search by author name (e.g., `Zhang F[Author]`)
- `[Journal]` — search by journal name (e.g., `"Nature"[Journal]`)
- `[MeSH Terms]` — search by MeSH subject headings
- `[Publication Date]` — filter by date
- `[Article Type]` — filter by type (e.g., `Review[Article Type]`)

### Boolean Operators
- `AND` — both terms required
- `OR` — either term
- `NOT` — exclude term

### Date Formats
- `YYYY/MM/DD` — specific date (e.g., `2024/01/01`)
- Use `min_date` and `max_date` parameters for date range filtering

### Sort Orders
- `relevance` — best match first (default)
- `pub+date` — newest first

### Example Queries
- `CRISPR gene editing` — basic keyword search
- `(CRISPR[Title/Abstract]) AND (cancer[MeSH Terms])` — field-specific
- `Zhang F[Author] AND CRISPR` — author + keyword
- `"Nature"[Journal] AND CRISPR AND Review[Article Type]` — journal + type filter

## Error Codes

| Error | Meaning | Solution |
|-------|---------|----------|
| VALIDATION_ERROR | Invalid parameter format | Check PMID (numeric), dates (YYYY/MM/DD) |
| NETWORK_ERROR | Cannot reach NCBI servers | Check network, retry |
| NOT_FOUND | PMID does not exist | Verify PMID is correct |
| NOT_AVAILABLE | Article not in PMC Open Access | Use `fetch_abstract` instead of `get_fulltext` |
| API_ERROR | NCBI returned an error | Check query syntax, rate limits |
| PARSE_ERROR | Cannot parse API response | Retry, may be transient |
