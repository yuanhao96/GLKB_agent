# PubMed Reader Tool Reference

## article_search (GLKB)

Searches the GLKB Neo4j knowledge graph full-text index for articles.

**Args**: `keywords` (list of strings), `pubmed_ids` (list of PMIDs), `limit` (default 20), `prioritize_recent` (bool, default False)

**Returns**: `success`, `count`, `results` (list with pubmedid, title, abstract, journal, authors, n_citation, pubdate, score)

**Notes**:
- Only one of `keywords` or `pubmed_ids` should be provided
- Has pre-computed impact scores and journal impact factors
- Two scoring modes: impact-prioritized (default) and recent-prioritized

## search_pubmed (NCBI)

Searches PubMed directly via NCBI E-utilities ESearch + ESummary.

**Args**: `query` (PubMed query string), `max_results` (1-200, default 20), `min_date` (YYYY/MM/DD), `max_date` (YYYY/MM/DD), `sort` ("relevance" or "pub+date")

**Returns**: `success`, `count` (total matches), `pmids`, `articles` (list with pmid, title, authors, journal, pub_date, year, doi, pmc, pub_types), `query_info`

**Notes**:
- Supports full PubMed query syntax (field tags, boolean operators)
- Covers all of PubMed (broader than GLKB)
- Results include article summaries automatically

## fetch_abstract

Fetches abstract, metadata, MeSH terms, and keywords for a single PMID.

**Args**: `pmid` (string)

**Returns**: `success`, `pmid`, `title`, `abstract`, `authors`, `journal`, `year`, `volume`, `issue`, `pages`, `doi`, `pmc`, `mesh_terms`, `keywords`, `pub_types`

**Notes**:
- Uses NCBI EFetch XML API
- Results are cached for faster repeated access

## get_fulltext

Retrieves full-text sections from PMC Open Access articles.

**Args**: `article_id` (PMID or PMC ID string)

**Returns**: `success`, `pmid`, `pmcid`, `title`, `sections` (dict: section_name → text), `full_text` (concatenated), `figures`, `tables`, `references`, `word_count`

**Notes**:
- Only ~3M Open Access articles available
- Automatically converts PMID ↔ PMCID
- If not available, returns error with suggestion to use `fetch_abstract`
- Sections typically include: Abstract, Introduction, Methods, Results, Discussion, Conclusions

## find_similar_articles

Finds articles similar to a given PMID via NCBI ELink similarity algorithm.

**Args**: `pmid` (string), `max_results` (default 20)

**Returns**: `success`, `source_pmid`, `similar_count`, `articles` (list with pmid, title, score, authors, journal, year)

**Notes**:
- Similarity based on shared MeSH terms, shared citations, and content similarity
- Results sorted by similarity score (highest first)
- Useful for expanding evidence from a key seed article

## get_citing_articles

Finds articles that cite a given PMID.

**Args**: `pmid` (string), `max_results` (default 50)

**Returns**: `success`, `source_pmid`, `citation_count` (total), `returned_count`, `articles` (sorted newest first), `by_year` (dict: year → list of articles)

**Notes**:
- Uses NCBI ELink "pubmed_pubmed_citedin" link
- Useful for tracking research impact and finding newer follow-up work
- `citation_count` may be larger than `returned_count` when limited

## comprehensive_report

Generates a comprehensive analysis of a single article combining all capabilities.

**Args**: `pmid` (string)

**Returns**: `success`, `pmid`, `article` (metadata), `fulltext` (if OA available), `similar_articles`, `citing_articles`, `references`, `metrics` (total_citations, citations_per_year, recent_velocity), `summary`, `quick_stats`, `alerts`

**Notes**:
- Combines: fetch_abstract + get_fulltext + find_similar + get_citing + get_references + citation_metrics
- Makes multiple API calls — use judiciously for important articles
- Alerts flag highly cited articles (>100 citations) and high citation velocity
