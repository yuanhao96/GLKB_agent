# Design: Flatten Multi-Agent Pipeline to Single Agent + ADK Skills

**Date**: 2026-02-19
**Goal**: Reduce latency by eliminating unnecessary LLM round-trips
**Approach**: Single LlmAgent with on-demand skill loading via ADK SkillToolset

## Problem

The current 4-agent sequential pipeline requires 3-4+ LLM sessions per query:

```
QuestionRouter (1 LLM call)
  → ParallelEvidence [KgQueryAgent (1+ calls) | ArticleRetrievalAgent (1+ calls)]
    → FinalAnswerAgent (1 LLM call)
```

The FinalAnswerAgent and parallel evidence orchestration are the biggest latency bottlenecks. The router adds an unnecessary LLM call for a simple classification.

## Solution

Replace with a single `LlmAgent` that has all 10 tools and uses ADK `SkillToolset` for on-demand instruction loading.

### Architecture

```
GLKBAgent (single LlmAgent, 1 LLM session)
  ├── Tools: all 10 FunctionTools (always registered)
  │     KG:        get_database_schema, execute_cypher, vocabulary_search, article_search
  │     PubMed:    search_pubmed, fetch_abstract, get_fulltext,
  │                find_similar_articles, get_citing_articles, comprehensive_report
  ├── SkillToolset (adds load_skill + load_skill_resource tools)
  │     ├── glkb-knowledge-graph    # Cypher workflow instructions
  │     └── pubmed-literature       # Article retrieval strategy
  └── Base instruction: ~20 lines (routing + synthesis guidance)
```

### How ADK Skills Work

Skills use a 3-level structure for incremental context loading:

| Level | Content | When loaded | Context cost |
|-------|---------|-------------|--------------|
| L1 | Skill name + description | Always (system prompt) | ~2 lines per skill |
| L2 | SKILL.md body (instructions) | On-demand via `load_skill()` | ~50-70 lines per skill |
| L3 | references/, assets/ | On-demand via `load_skill_resource()` | Variable |

The LLM sees skill names/descriptions in every request. It calls `load_skill("glkb-knowledge-graph")` only when it needs KG query guidance, avoiding loading literature instructions for KG-only questions.

**Key constraint**: Skills are instruction-only. Tools must be registered separately on the agent. Skills tell the LLM *how* to use tools, not *what* tools exist.

### Base Agent Instruction (~20 lines, always loaded)

```
You are the GLKB biomedical QA assistant. GLKB integrates 263M+ biomedical
terms and 14.6M+ relationships from 38M PubMed abstracts.

You have access to skills for detailed workflows. Load them as needed:
- "glkb-knowledge-graph": Cypher query generation, schema navigation,
  vocabulary mapping for the GLKB Neo4j database
- "pubmed-literature": Article retrieval strategy using GLKB search
  and direct PubMed/PMC access

WORKFLOW:
1. Assess the question type:
   - KG-only (counts, lists, schema queries) -> load KG skill only
   - Needs biomedical explanation -> load both skills
   - Ambiguous -> load both skills
2. Load relevant skill(s) and follow their instructions
3. Synthesize a grounded answer with inline PubMed citations:
   [PMID](https://pubmed.ncbi.nlm.nih.gov/PMID)

CITATION RULES:
- Cite articles inline using [PMID](URL) format
- Do not cite when summarizing database/graph results
- Use markdown headers and bullet points for structure
- Refuse non-biomedical questions politely
```

### Skill 1: `glkb-knowledge-graph`

**Source**: Current `KgQueryAgent.instruction` (~70 lines)

**SKILL.md contents**:
- Cypher generation workflow (schema inspection, vocabulary search, OntologyMapping expansion)
- Query patterns for direct/indirect connections, Cooccur fallback
- Cypher efficiency guidelines (LIMIT, indexed properties, DISTINCT, aggregation)
- Output format (structural_evidence, article_ids, notes)

**references/**:
- `schema.md`: Full GLKB schema (node labels, properties, relationships, indexes)
- `cypher-patterns.md`: Common Cypher query patterns and examples

### Skill 2: `pubmed-literature`

**Source**: Current `ArticleRetrievalAgent.instruction` (~60 lines) + existing `pubmed_reader/SKILL.md`

**SKILL.md contents**:
- Tool selection strategy (GLKB article_search first, search_pubmed as supplement)
- When to use each tool (recent articles, author filters, citation tracking, deep analysis)
- PubMed query syntax tips (field tags, boolean operators)
- Output format (articles list with id, title, snippet, source, relevance)

**references/**: Existing pubmed_reader documentation

### File Structure

```
my_agent/
├── __init__.py
├── agent.py                        # Single LlmAgent + SkillToolset (~40 lines)
├── tools.py                        # All 10 FunctionTools (unchanged)
├── skills/
│   ├── glkb_knowledge_graph/
│   │   ├── SKILL.md                # KG query workflow
│   │   └── references/
│   │       ├── schema.md           # Full GLKB schema
│   │       └── cypher-patterns.md  # Common patterns
│   └── pubmed_reader/              # Already exists, enhance SKILL.md
│       ├── SKILL.md                # Article retrieval strategy (updated)
│       ├── scripts/                # Existing sync functions
│       └── assets/                 # Existing config
```

### Agent Definition (new `agent.py`)

```python
from pathlib import Path
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from tools import glkb_tools, pubmed_tools

LLM_MODEL = LiteLlm(model="openai/gpt-4o")

kg_skill = load_skill_from_dir(Path(__file__).parent / "skills" / "glkb_knowledge_graph")
lit_skill = load_skill_from_dir(Path(__file__).parent / "skills" / "pubmed_reader")

root_agent = LlmAgent(
    name="GLKBAgent",
    model=LLM_MODEL,
    instruction=BASE_INSTRUCTION,
    tools=[
        *glkb_tools,
        *pubmed_tools,
        SkillToolset(skills=[kg_skill, lit_skill]),
    ],
)
```

## What Gets Removed

| Component | Action |
|-----------|--------|
| `QuestionRouterAgent` | Removed. Routing in base instruction |
| `KgQueryAgent` | Removed. Instruction -> `glkb_knowledge_graph/SKILL.md` |
| `ArticleRetrievalAgent` | Removed. Instruction -> updated `pubmed_reader/SKILL.md` |
| `ConditionalLiteratureAgent` | Removed. Agent decides inline |
| `FinalAnswerAgent` | Removed. Synthesis in base instruction |
| `EvidenceMergeAgent` | Already inactive. Removed |
| `LoggingAgentWrapper` | Removed (use ADK built-in logging or `@log_tool_call` on tools) |
| `SequentialAgent`, `ParallelAgent` | Removed. Single agent |
| State keys (`kg_evidence`, `doc_evidence`, etc.) | Removed. No inter-agent state passing |

## Latency Impact

| Scenario | Current | Proposed |
|----------|---------|----------|
| Simple KG query | 3 LLM calls | 1 LLM call (~3 tool rounds) |
| Full biomedical question | 4+ LLM calls | 1 LLM call (~6-8 tool rounds) |
| Follow-up question | 3-4 LLM calls | 1 LLM call (~2-4 tool rounds) |

## Prerequisites

1. **Upgrade google-adk**: `pip install google-adk>=1.25.0` (SkillToolset is experimental, added after 1.20.0)
2. **Verify LiteLlm + SkillToolset compatibility**: SkillToolset is experimental; needs testing with OpenAI via LiteLlm
3. **Service layer**: Minor update to `service/runner.py` to import the new single `root_agent`

## Risks

- **SkillToolset is experimental** (`@experimental` decorator). API may change.
- **LiteLlm compatibility**: SkillToolset injects system instructions and tool definitions that must work with OpenAI function calling via LiteLlm.
- **Single agent complexity**: One agent handling both KG and literature in one session may produce longer, more expensive LLM outputs per call. Monitor token usage.
- **Tool overload**: 10 tools + 2 skill tools = 12 tools for the LLM to choose from. GPT-4o handles this well, but watch for tool selection accuracy.

## Fallback Plan

If SkillToolset doesn't work with LiteLlm, fall back to **Approach B**: single agent with all instructions in one prompt (no skills). This still achieves the primary goal of eliminating multi-agent latency.
