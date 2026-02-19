# Skills Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Flatten the 4-agent sequential pipeline into a single LlmAgent with ADK SkillToolset for on-demand instruction loading, reducing per-query latency from 3-4+ LLM calls to 1.

**Architecture:** One `LlmAgent` ("GLKBAgent") with all 10 existing FunctionTools plus a `SkillToolset` containing two skills: `glkb-knowledge-graph` (Cypher workflow) and `pubmed-literature` (article retrieval strategy). The agent handles routing, evidence gathering, and answer synthesis in a single LLM session.

**Tech Stack:** google-adk >= 1.25.0 (SkillToolset), LiteLlm (OpenAI GPT-4o), Neo4j, NCBI E-utilities

**Design doc:** `docs/plans/2026-02-19-skills-refactoring-design.md`

---

### Task 1: Upgrade google-adk and verify SkillToolset availability

**Files:**
- None (dependency management only)

**Step 1: Check current version**

Run: `pip show google-adk | grep Version`
Expected: `Version: 1.20.0` (or similar < 1.25)

**Step 2: Upgrade google-adk**

Run: `pip install 'google-adk>=1.25.0'`
Expected: Successfully installed google-adk-1.25.x+

**Step 3: Verify SkillToolset is importable**

Run: `python -c "from google.adk.tools.skill_toolset import SkillToolset; print('OK')"`
Expected: `OK`

If this fails, try alternative import paths:
```python
python -c "from google.adk.skills import load_skill_from_dir; print('OK')"
```

If SkillToolset is not available in the installed version, check the latest ADK docs and adjust the import path. If it's genuinely unavailable, fall back to Approach B (single agent, no skills — see Task 7).

**Step 4: Commit**

```bash
# No files to commit — pip install doesn't change tracked files
# If there's a requirements.txt, update it:
echo "google-adk>=1.25.0" >> requirements.txt  # or update existing line
```

---

### Task 2: Create the `glkb-knowledge-graph` skill

**Files:**
- Create: `my_agent/skills/glkb_knowledge_graph/SKILL.md`
- Create: `my_agent/skills/glkb_knowledge_graph/references/schema.md`
- Create: `my_agent/skills/glkb_knowledge_graph/references/cypher-patterns.md`

**Step 1: Create skill directory**

Run: `mkdir -p my_agent/skills/glkb_knowledge_graph/references`

**Step 2: Write SKILL.md**

Create `my_agent/skills/glkb_knowledge_graph/SKILL.md` with:
- Frontmatter: `name: glkb-knowledge-graph`, `description: Cypher query generation...`
- Body: Extract from current `KgQueryAgent.instruction` in `my_agent/agent.py:229-291`
  - The Cypher generation workflow
  - Vocabulary search and OntologyMapping expansion patterns
  - Direct/indirect connection strategies with Cooccur fallback
  - Cypher efficiency guidelines (LIMIT, indexed properties, DISTINCT)
  - The iterative refinement loop (up to 10 tool calls)
- Remove the output_key/state references (no longer needed — agent returns answer directly)
- Keep the JSON output format guidance but frame it as "include this evidence in your answer" rather than "write to state key"

**Step 3: Write references/schema.md**

Create `my_agent/skills/glkb_knowledge_graph/references/schema.md` with the full GLKB schema. Copy from the `get_database_schema()` function return value in `my_agent/tools.py:78-119`. Format it cleanly as markdown.

**Step 4: Write references/cypher-patterns.md**

Create `my_agent/skills/glkb_knowledge_graph/references/cypher-patterns.md` with common Cypher patterns:
- Full-text search on vocabulary_Names index
- OntologyMapping expansion
- Direct association queries (GeneToDiseaseAssociation, etc.)
- Indirect path traversal
- Cooccurrence analysis via Cooccur relationship
- Article search via ContainTerm
- Aggregation patterns (COUNT, SUM with GROUP BY)

**Step 5: Verify skill loads**

Run:
```python
python -c "
from pathlib import Path
from google.adk.skills import load_skill_from_dir
skill = load_skill_from_dir(Path('my_agent/skills/glkb_knowledge_graph'))
print(f'Name: {skill.name}')
print(f'Description: {skill.frontmatter.description}')
print(f'Instructions length: {len(skill.instructions)} chars')
"
```
Expected: Prints skill name, description, and instruction length > 0.

**Step 6: Commit**

```bash
git add my_agent/skills/glkb_knowledge_graph/
git commit -m "feat: add glkb-knowledge-graph skill with Cypher workflow instructions"
```

---

### Task 3: Update the `pubmed-reader` skill for article retrieval strategy

**Files:**
- Modify: `my_agent/skills/pubmed_reader/SKILL.md`

**Step 1: Update SKILL.md**

The existing `my_agent/skills/pubmed_reader/SKILL.md` documents the tool APIs. Prepend the retrieval *strategy* instructions from `ArticleRetrievalAgent.instruction` in `my_agent/agent.py:313-367`:
- Tool selection strategy (GLKB article_search first, search_pubmed as supplement)
- When to use each PubMed tool (recent articles → date filters, author/journal filters, citation tracking, deep analysis)
- Expansion strategies (find_similar_articles, get_citing_articles)
- PubMed query syntax tips
- Keep the existing tool API documentation as-is (it serves as L2 reference)
- Remove state/output_key references

**Step 2: Verify skill loads**

Run:
```python
python -c "
from pathlib import Path
from google.adk.skills import load_skill_from_dir
skill = load_skill_from_dir(Path('my_agent/skills/pubmed_reader'))
print(f'Name: {skill.name}')
print(f'Instructions length: {len(skill.instructions)} chars')
"
```

**Step 3: Commit**

```bash
git add my_agent/skills/pubmed_reader/SKILL.md
git commit -m "feat: add article retrieval strategy to pubmed-reader skill"
```

---

### Task 4: Rewrite agent.py to single agent + SkillToolset

**Files:**
- Modify: `my_agent/agent.py` (complete rewrite, keep old version as `agent.py.bak`)

**Step 1: Back up current agent.py**

Run: `cp my_agent/agent.py my_agent/agent.py.bak`

**Step 2: Write new agent.py**

Replace `my_agent/agent.py` with the new single-agent definition. Key structure:

```python
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
import os
from pathlib import Path
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
import dotenv

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Logging setup (keep existing logging config from old agent.py)
LOG_DIR = os.getenv(
    "AGENTS_LOG_DIR",
    os.path.join(os.path.dirname(__file__), "..", "agent_logs"),
)
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "agent.log")),
        logging.StreamHandler(),
    ],
    force=True,
)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)

from tools import glkb_tools, pubmed_tools

LLM_MODEL = LiteLlm(model="openai/gpt-4o")

# Load skills
kg_skill = load_skill_from_dir(Path(__file__).parent / "skills" / "glkb_knowledge_graph")
lit_skill = load_skill_from_dir(Path(__file__).parent / "skills" / "pubmed_reader")

BASE_INSTRUCTION = """
You are the GLKB biomedical QA assistant. The Genomic Literature Knowledge Base (GLKB) integrates over 263 million biomedical terms and more than 14.6 million biomedical relationships curated from 38 million PubMed abstracts and nine biomedical repositories.

You have access to skills for detailed workflows. Load them as needed:
- "glkb-knowledge-graph": Cypher query generation, schema navigation, vocabulary mapping for the GLKB Neo4j database
- "pubmed-literature": Article retrieval strategy using GLKB search and direct PubMed/PMC access

WORKFLOW:
1. Assess the question type:
   - KG-only (counts, lists, schema queries) → load KG skill only
   - Needs biomedical explanation or evidence → load both skills
   - Ambiguous → load both skills
2. Load relevant skill(s) via load_skill and follow their instructions to query tools
3. Synthesize a grounded answer using the evidence gathered

IMPORTANT:
- You have access to the full conversation history. For follow-up questions, use context from previous exchanges.
- Filter results after each tool call to keep relevant and important items (e.g., high citations, high cooccurrences).
- If information is insufficient after querying, acknowledge limitations.

CITATION FORMAT:
- When referencing a specific article, cite inline: [PMID](https://pubmed.ncbi.nlm.nih.gov/PMID)
- When summarizing database/graph structure results (not articles), do not cite.
- Use markdown headers and bullet points for well-structured answers.
- Refuse non-biomedical questions politely.
"""

root_agent = LlmAgent(
    name="GLKBAgent",
    model=LLM_MODEL,
    description=(
        "GLKB biomedical QA agent that queries the Neo4j knowledge graph "
        "and retrieves PubMed literature to produce grounded, cited answers."
    ),
    instruction=BASE_INSTRUCTION,
    tools=[
        *glkb_tools,
        *pubmed_tools,
        SkillToolset(skills=[kg_skill, lit_skill]),
    ],
)
```

Key changes from old agent.py:
- Remove all multi-agent classes: `LoggingAgentWrapper`, `ConditionalLiteratureAgent`, `wrap_agent()`
- Remove all agent definitions: `QuestionRouterAgent`, `KgQueryAgent`, `ArticleRetrievalAgent`, `FinalAnswerAgent`, `EvidenceMergeAgent`
- Remove `SequentialAgent`, `ParallelAgent` orchestration
- Remove state key constants (`STATE_KG_EVIDENCE`, etc.)
- Remove `test_agent`
- Keep: logging setup, dotenv loading, model constant, tool imports
- Add: skill loading, SkillToolset, single `root_agent`

**Step 3: Verify agent loads without errors**

Run: `python -c "from my_agent.agent import root_agent; print(f'Agent: {root_agent.name}, Tools: {len(root_agent.tools)}')"` from the project root.
Expected: `Agent: GLKBAgent, Tools: 13` (10 function tools + SkillToolset which exposes load_skill + load_skill_resource)

**Step 4: Commit**

```bash
git add my_agent/agent.py
git commit -m "refactor: flatten multi-agent pipeline to single agent with SkillToolset"
```

---

### Task 5: Smoke test with `adk run`

**Files:** None (testing only)

**Step 1: Test with adk CLI**

Run: `adk run my_agent`

Test with a simple KG-only query:
```
> How many Gene nodes are in the database?
```
Expected: Agent loads the KG skill, generates a COUNT Cypher query, executes it, returns the count.

**Step 2: Test with a full biomedical query**

```
> What is the role of TP53 in apoptosis?
```
Expected: Agent loads both skills, queries KG for TP53-apoptosis relationships, searches PubMed for articles, synthesizes answer with citations.

**Step 3: Test with the async runner**

Run: `python my_agent/run_async.py --query "What genes are associated with Type 2 Diabetes?"`
Expected: Produces a cited answer.

**Step 4: Check for regressions in service layer**

Run: `python -c "from service.runner import get_runner; r = get_runner(); print(f'Agent: {r.agent.name}')"` from project root.
Expected: `Agent: GLKBAgent`

If any test fails, debug and fix before proceeding.

---

### Task 6: Clean up

**Files:**
- Delete: `my_agent/agent.py.bak` (once verified)
- Modify: `my_agent/agent.py` (if any fixes needed from smoke testing)

**Step 1: Remove backup**

Run: `rm my_agent/agent.py.bak`

**Step 2: Update CLAUDE.md**

Update the Architecture section in `CLAUDE.md` to reflect the new single-agent architecture. Key changes:
- Replace the agent pipeline diagram with the new single-agent structure
- Update the "Key Design Patterns" section (remove LoggingAgentWrapper, state-passing)
- Note SkillToolset usage
- Update the Models section if needed

**Step 3: Commit**

```bash
git add CLAUDE.md my_agent/
git commit -m "docs: update CLAUDE.md for single-agent architecture"
```

---

### Task 7 (Fallback): Single agent without skills

**Only if Task 1 Step 3 fails** (SkillToolset unavailable or incompatible with LiteLlm).

**Files:**
- Modify: `my_agent/agent.py`

**Step 1: Write agent with inline instructions**

Instead of SkillToolset, put all instructions directly in the `instruction` parameter. Merge the KG workflow, literature strategy, and synthesis guidance into one ~150-line instruction.

```python
root_agent = LlmAgent(
    name="GLKBAgent",
    model=LLM_MODEL,
    instruction=FULL_INSTRUCTION,  # ~150 lines, all workflows inline
    tools=[*glkb_tools, *pubmed_tools],  # 10 tools, no SkillToolset
)
```

This still achieves the primary goal (1 LLM session instead of 4+) but without on-demand instruction loading.

---

## Execution Order

```
Task 1 (upgrade adk)
  ├── Success → Task 2 → Task 3 → Task 4 → Task 5 → Task 6
  └── Fail    → Task 7 (fallback) → Task 5 → Task 6
```

Tasks 2 and 3 are independent and can be done in parallel.
