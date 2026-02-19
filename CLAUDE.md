# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GLKB Agent — a biomedical Q&A system using Google ADK that queries the GLKB Neo4j knowledge graph (263M+ biomedical terms, 14.6M+ relationships) and retrieves PubMed literature to produce grounded, cited answers. Uses OpenAI GPT-4o via LiteLlm with ADK SkillToolset for on-demand instruction loading. Internal to University of Michigan Medical School.

## Commands

### Run the agent (development)
```bash
# ADK interactive CLI
adk run my_agent

# ADK web UI
adk web my_agent --port 8080

# Direct async runner with a single query
python my_agent/run_async.py --query "What is TP53?"
```

### Run the FastAPI service
```bash
# Production-style
uvicorn service.api:app --host 0.0.0.0 --port 8000 --reload

# Or directly (runs on port 5001 with debug logging)
python service/api.py
```

### Install dependencies
```bash
pip install 'google-adk>=1.25.0' python-dotenv neo4j httpx litellm loguru pyyaml
pip install -r service/requirements.txt
```

### Evaluate (no eval sets exist yet)
```bash
adk eval my_agent path/to/eval_set.json
```

## Architecture

### Agent

The root agent (`GLKBAgent`) is a single `LlmAgent` defined in `my_agent/agent.py`:

```
GLKBAgent (gpt-4o, single LLM session)
  ├── Tools (always registered):
  │     KG:     get_database_schema, execute_cypher, vocabulary_search, article_search
  │     PubMed: search_pubmed, fetch_abstract, get_fulltext,
  │             find_similar_articles, get_citing_articles, comprehensive_report
  ├── SkillToolset (on-demand instruction loading):
  │     ├── glkb-knowledge-graph  → Cypher workflow, schema, query patterns
  │     └── pubmed-reader         → Article retrieval strategy, tool selection
  └── Base instruction: routing + synthesis + citation formatting
```

The agent assesses each question, loads relevant skill instructions on-demand via `load_skill()`, uses the appropriate tools, and synthesizes a cited answer — all in one LLM session.

### ADK Skills (on-demand instruction loading)

Skills use ADK's experimental `SkillToolset` for incremental context loading:

| Level | Content | When loaded |
|-------|---------|-------------|
| L1 | Skill name + description | Always (system prompt) |
| L2 | SKILL.md body (instructions) | On-demand via `load_skill()` |
| L3 | references/ (schema, patterns) | On-demand via `load_skill_resource()` |

- `my_agent/skills/glkb_knowledge_graph/` — Cypher generation workflow, GLKB schema reference, common query patterns
- `my_agent/skills/pubmed_reader/` — Article retrieval strategy, tool selection guidance, PubMed API documentation

Skills are constructed programmatically via `load_skill_from_directory()` helper in `agent.py` (ADK's `load_skill_from_dir` does not exist in 1.25.1).

### Key Design Patterns

- **Single agent with skills**: One `LlmAgent` handles routing, evidence gathering, and answer synthesis. Detailed workflow instructions are loaded on-demand via SkillToolset.
- **Tool functions are async**, decorated with `@log_tool_call`, and wrapped with `FunctionTool()`.
- **execute_cypher blocks write operations** (CREATE/DELETE/SET/REMOVE/MERGE/DROP).
- Memory tools (`my_agent/memory.py`, Mem0+Qdrant) are defined but inactive.

### Service Layer (`service/`)

- `api.py` — FastAPI app with two API styles: (1) RESTful session-scoped endpoints under `/apps/{app}/users/{user}/sessions/...` and (2) a simplified `POST /stream` SSE endpoint compatible with the existing GLKB backend.
- `runner.py` — `AgentRunner` bridges SQLite persistence with ADK's `InMemorySessionService`. Reconstructs ADK sessions from stored messages on each request, then syncs state back.
- `session_service.py` — Async SQLite session store (`aiosqlite`) with `sessions` and `messages` tables.
- `models.py` — Pydantic v2 request/response models.
- The `/stream` endpoint optionally integrates with `reorg_glkb_backend` (separate project) for article metadata enrichment.

### GLKB Knowledge Graph Schema

Node types: `Article`, `Journal`, `Gene`, `DiseaseOrPhenotypicFeature`, `ChemicalEntity`, `SequenceVariant`, `MeshTerm`, `AnatomicalEntity`, `Pathway`, `BiologicalProcess`, `CellularComponent`, `MolecularFunction`. All biomedical entities are subtypes of `Vocabulary`.

Key relationships: `ContainTerm` (Article→Vocabulary), `GeneToDiseaseAssociation`, `GeneToGeneAssociation`, `GeneToPathwayAssociation`, `Cooccur`, `OntologyMapping`, `HierarchicalStructure`, `Cite` (Article→Article).

Full-text indexes: `vocabulary_Names` (on Vocabulary.name), `article_Title` (on Article.title). The complete schema is hardcoded in `get_database_schema()` in `tools.py`.

### Article Ranking

`article_search` implements two scoring modes (default: impact-prioritized; optional: recent-prioritized) combining full-text score, citation count, journal impact factor, and publication recency.

### PubMed Reader Skill (`my_agent/skills/pubmed_reader/`)

Integrated from [pubmed-reader-cskill](https://github.com/yuanhao96/pubmed-reader-cskill). Provides direct NCBI E-utilities access via synchronous functions wrapped with `asyncio.to_thread()` in `tools.py`.

| Tool | Function | Purpose |
|------|----------|---------|
| `search_pubmed_tool` | `search_pubmed()` | Direct NCBI ESearch with date/author/journal filters |
| `fetch_abstract_tool` | `fetch_abstract()` | Abstract + metadata + MeSH terms for a PMID |
| `get_fulltext_tool` | `get_fulltext()` | Full-text sections from PMC Open Access (~3M articles) |
| `find_similar_articles_tool` | `find_similar_articles()` | Related papers via NCBI ELink similarity |
| `get_citing_articles_tool` | `get_citing_articles()` | Papers that cite a given PMID |
| `comprehensive_report_tool` | `comprehensive_article_report()` | Full analysis: metadata + citations + full text |

The skill includes caching (`scripts/utils/cache_manager.py`) and adaptive rate limiting (`scripts/utils/rate_limiter.py`). Rate limits: 3 req/s without API key, 10 req/s with `NCBI_API_KEY`.

## Environment Variables

Stored in `my_agent/.env`:

| Variable | Required | Purpose |
|----------|----------|---------|
| `NEO4J_URI` | Yes | Bolt URI (e.g., `bolt://host:7687`) |
| `NEO4J_USER` | Yes | Neo4j username |
| `NEO4J_PASSWORD` | Yes | Neo4j password |
| `NEO4J_DATABASE` | Yes | Neo4j database name |
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT-4o/4o-mini |
| `AGENTS_LOG_DIR` | No | Custom log directory path |
| `NCBI_API_KEY` | No | NCBI API key for 10 req/s PubMed rate limit (3 req/s without) |
| `NCBI_EMAIL` | No | Contact email for NCBI E-utilities (recommended for production) |

## Models

Configured in `my_agent/agent.py`:
- `LLM_MODEL = LiteLlm(model="openai/gpt-4o")` — single agent (GLKBAgent)

## Conventions

- Python 3.11+ required.
- All tool functions must be `async`, use `@log_tool_call` decorator, and be exported as `FunctionTool()` instances.
- No tests or eval sets exist yet. No Dockerfile or CI/CD.
- ADK SkillToolset is experimental (`@experimental`). Requires `google-adk>=1.25.0`.
- Neo4j MCP toolset (`/opt/neo4j/neo4j-mcp/neo4j-mcp`) exists as an alternative to direct bolt tools but is not used in the active pipeline.
