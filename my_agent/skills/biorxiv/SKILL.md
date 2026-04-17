---
name: biorxiv
description: bioRxiv/medRxiv preprint search, retrieval, and full-text access. Use whenever a question could benefit from preprint evidence — especially recent/cutting-edge biology or medicine topics, when a user mentions a bioRxiv/medRxiv DOI (10.1101/..., 10.64898/...), a biorxiv.org or medrxiv.org URL, or asks for "preprints", "recent papers", "the latest work on X". Complements the pubmed-reader skill; both can be queried in parallel.
---

# bioRxiv/medRxiv — Search, Read & Full Text

Use this skill for all bioRxiv and medRxiv operations: keyword search, date browsing, reading a preprint by DOI, and retrieving full text.

Preprints are welcome evidence for any question in GLKB. When the user asks about recent or emerging topics, prefer to query bioRxiv/medRxiv alongside PubMed rather than instead of it — the two skills are complementary.

## When to Use This Skill

- **Search bioRxiv**: "Search bioRxiv for CRISPR delivery", "Find biology preprints on gene therapy"
- **Search medRxiv**: "Search medRxiv for COVID-19 vaccines", "Find medical preprints on..."
- **Browse recent**: "Show recent bioRxiv preprints on gene therapy from last week"
- **Read preprint**: "Read bioRxiv 10.1101/2024.01.15.575889"
- **Full text**: "Get full text of bioRxiv preprint 10.1101/..."
- **Identifiers**: Any query containing a bioRxiv/medRxiv DOI (`10.1101/...`, `10.64898/...`), or biorxiv.org/medrxiv.org URL
- **Recency / cutting edge**: Questions about the latest findings, ongoing debates, or pre-publication work

### Keywords that commonly warrant querying preprints

`biorxiv`, `bioRxiv`, `medrxiv`, `medRxiv`, `biology preprint`, `medical preprint`, `life sciences preprint`, `10.1101`, `10.64898`, `search biorxiv`, `read biorxiv`, `search medrxiv`, `read medrxiv`, `gene therapy preprint`, `COVID preprint`, `biorxiv.org`, `medrxiv.org`, `latest`, `recent`, `preprint`, `cutting edge`

## Data Source: bioRxiv/medRxiv API

**Details endpoint**: `https://api.biorxiv.org/details/[server]/[DOI]/na/json`
- `server`: `biorxiv` or `medrxiv`
- `DOI`: Full DOI, e.g. `10.1101/2024.01.15.575889`

**Browse endpoint**: `https://api.biorxiv.org/details/[server]/[start_date]/[end_date]/[cursor]/json`
- Returns 100 papers per page, use cursor for pagination

**DOI formats**:
- Legacy: `10.1101/YYYY.MM.DD.XXXXXX`
- New: `10.64898/YYYY.MM.DD.XXXXXX`

**Full text**: JATS XML via `jatsxml` field, HTML at `biorxiv.org/content/[DOI].full`

**Rate limits**: No documented limit; use reasonable delays between requests.

## Available Tools

| Tool | Purpose |
|---|---|
| `search_biorxiv(query, max_results, server)` | Keyword search on bioRxiv or medRxiv. `server` is `"biorxiv"` (default) or `"medrxiv"`. |
| `browse_biorxiv_recent(days, server, category)` | Browse preprints posted in the last N days. |
| `fetch_biorxiv_paper(doi, server)` | Retrieve metadata + abstract for one DOI. `server` optional — auto-detects bioRxiv vs medRxiv. |
| `get_biorxiv_fulltext(doi, server)` | Retrieve sectioned full text (JATS XML preferred, HTML fallback). |

## Workflow 1: Search bioRxiv/medRxiv

**User says**: "Search bioRxiv for CRISPR delivery systems"

Steps:
1. Identify server — `medrxiv` for medical/clinical topics, otherwise `biorxiv` (default).
2. Call `search_biorxiv(query, max_results=10, server=...)`.
3. Filter results by relevance and recency as needed.
4. Select the best few preprints to cite.

## Workflow 2: Browse recent

**User says**: "Show recent preprints on gene therapy"

1. Call `browse_biorxiv_recent(days=14, server="biorxiv", category=None)`.
2. Optionally filter by `category` (e.g., `"Genetics"`, `"Neuroscience"`).
3. Rank by recency and topic match.

## Workflow 3: Read a specific preprint

**User provides**: `10.1101/2024.01.15.575889`

1. Call `fetch_biorxiv_paper(doi)`.
2. Use returned `abstract`, `title`, `authors`, `posted_date`, `category`, `published` (if the preprint has a journal version) in your answer.
3. If you need more than the abstract, call `get_biorxiv_fulltext(doi)`.

## Workflow 4: Full text deep read

1. Call `get_biorxiv_fulltext(doi)`.
2. Read the returned `sections` dict (Abstract, Introduction, Methods, Results, Discussion).
3. Cite specific sentences verbatim as evidence.

## Citing preprints in your final answer

Preprints do **not** have PMIDs. Cite them with their DOI and link to the bioRxiv/medRxiv page, e.g.:

`[bioRxiv:10.1101/2024.01.15.575889](https://www.biorxiv.org/content/10.1101/2024.01.15.575889)`

or for medRxiv:

`[medRxiv:10.1101/2024.02.03.123456](https://www.medrxiv.org/content/10.1101/2024.02.03.123456)`

Before writing the final answer, call `cite_evidence` for each preprint you plan to cite. Pass the **DOI** in the `pmid` argument (the argument is named `pmid` for legacy reasons but accepts any article identifier). Use `context_type="abstract"` or `"fulltext"` depending on where the quote came from.

## Dedup: preprint already published?

If `fetch_biorxiv_paper` returns a non-empty `published` field, the preprint has a peer-reviewed journal version. Prefer citing the journal version (via PubMed) unless the user specifically asked for the preprint or the user's question concerns pre-publication timing.

## Error Handling

| Error | Solution |
|-------|----------|
| `NOT_FOUND` on one server | `fetch_biorxiv_paper` auto-retries on the other server |
| Invalid DOI format | Expected `10.1101/YYYY.MM.DD.XXXXXX` or `10.64898/YYYY.MM.DD.XXXXXX` |
| Full text not available | Fall back to abstract only |
| Server error | Retry; biorxiv.org may be temporarily slow |
