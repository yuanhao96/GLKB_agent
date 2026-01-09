# agent.py
#
# Root definition for the GLKB multi-agent system:
# - Parallel KG + Literature evidence gathering
# - Evidence merging
# - Final grounded answer generation
# Agent architecture:
# Root (Sequential)
#  ├── QuestionRouterAgent
#  ├── ConditionalParallelEvidenceGathering
#  │     ├── KgQueryAgent
#  │     └── ArticleRetrievalAgent (runs only if mode == "full")
#  ├── # EvidenceMergeAgent
#  └── FinalAnswerAgent

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
import os
import json
from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.models.lite_llm import LiteLlm  # For multi-model support
from typing import AsyncGenerator, Any
from google.genai import types
import dotenv

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# -----------------------------------------
# Logging (standard Python logging per ADK guide)
# -----------------------------------------

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
    force=True,  # Override ADK CLI's prior config
)

# Suppress verbose LiteLLM logging
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# -----------------------------------------
# Logging Agent Wrapper
# -----------------------------------------

class LoggingAgentWrapper(BaseAgent):
    """Wrapper that logs input/output for any LlmAgent."""
    
    # Declare wrapped_agent as a Pydantic field
    wrapped_agent: Any = None
    skip_output_log: bool = False
    
    def __init__(self, wrapped_agent: LlmAgent, skip_output_log: bool = False, **kwargs):
        super().__init__(
            name=wrapped_agent.name,
            description=wrapped_agent.description,
            wrapped_agent=wrapped_agent,
            skip_output_log=skip_output_log,
            **kwargs
        )
    
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        agent_name = self.wrapped_agent.name
        
        # Log agent input
        user_content = str(ctx.user_content) if ctx.user_content else ""
        if len(user_content) > 500:
            user_content = user_content[:500] + "... [truncated]"
        
        # Get relevant state keys for this agent
        state_snapshot = {}
        for key in list(ctx.session.state.keys())[:10]:  # Limit to first 10 keys
            val = str(ctx.session.state.get(key, ""))
            if len(val) > 300:
                val = val[:300] + "... [truncated]"
            state_snapshot[key] = val
        
        logger.info(f"[AGENT START] {agent_name}")
        logger.info(f"[AGENT INPUT] {agent_name} | User: {user_content}")
        logger.info(f"[AGENT STATE] {agent_name} | State: {json.dumps(state_snapshot, default=str)}")
        
        try:
            async for event in self.wrapped_agent.run_async(ctx):
                yield event
        except Exception as e:
            logger.error(f"[AGENT ERROR] {agent_name} | Error: {str(e)}")
            raise
        
        # Log agent output (check for output_key if exists)
        # Skip output logging if skip_output_log is True (useful for final answer agent)
        if not self.skip_output_log:
            output_key = getattr(self.wrapped_agent, 'output_key', None)
            if output_key and output_key in ctx.session.state:
                output = str(ctx.session.state[output_key])
                if len(output) > 1000:
                    output = output[:1000] + "... [truncated]"
                logger.info(f"[AGENT OUTPUT] {agent_name} | Key={output_key} | Output: {output}")
            
            logger.info(f"[AGENT END] {agent_name}")


def wrap_agent(agent: LlmAgent, skip_output_log: bool = False) -> LoggingAgentWrapper:
    """Convenience function to wrap an LlmAgent with logging.
    
    Args:
        agent: The LlmAgent to wrap with logging.
        skip_output_log: If True, skip logging the output after agent completes.
                         Useful for final answer agent to avoid display issues in CLI.
    """
    return LoggingAgentWrapper(wrapped_agent=agent, skip_output_log=skip_output_log)

# All custom tools live in tools.py (per your assumption)
from tools import (
    get_database_schema_tool,      # tool: check / summarize Neo4j schema
    execute_cypher_tool,     # tool: execute Cypher on GLKB / Neo4j
    article_search_tool,    # tool: retrieve PubMed articles from GLKB
    vocabulary_search_tool,    # tool: map mention -> GLKB vocab / IDs
    # grounded_output_formatter, # tool: format answer + evidence bundle
    fetch_pubmed_article_tool, # tool: retrieve PubMed Central full articles
    get_article_sections_tool, # tool: retrieve PubMed Central article sections
)

# Memory tools for persisting and retrieving Cypher query patterns
# from memory import (
#     add_cypher_memory_tool,        # tool: store successful Cypher queries for future reference
#     search_memory_tool,     # tool: retrieve relevant past queries/patterns
# )

# -----------------------------------------
# Constants
# -----------------------------------------

LLM_MODEL = LiteLlm(model="openai/gpt-4o")
LITE_MODEL = LiteLlm(model="openai/gpt-4o-mini")

# Shared state keys (session.state[...] keys)
STATE_KG_EVIDENCE = "kg_evidence"               # structured KG paths + any article nodes
STATE_DOC_EVIDENCE = "doc_evidence"             # retrieved articles / snippets
STATE_MERGED_EVIDENCE = "merged_evidence"       # unified evidence bundle
STATE_FINAL_ANSWER = "final_answer"             # final formatted answer

# -----------------------------------------
# Question Router Agent
# -----------------------------------------

MODE_KEY = "retrieval_mode"

_question_router_agent = LlmAgent(
    name="QuestionRouterAgent",
    model=LITE_MODEL,
    description="Classifies the user's question into retrieval modes: kg_only, full, or auto.",
    instruction=f"""
You are the retrieval mode router for the GLKB QA system.

IMPORTANT: You have access to the conversation history through the session's events. When classifying questions, consider the full conversation context, especially for follow-up questionsthat may reference previous topics or entities.

Your job is to classify the user's question into one of:

1. "kg_only"
   Use this when the question is purely about counts, lists, schema navigation,
   or graph-structured queries like:
     - "how many articles were published in 2024"
     - "list all genes regulated by TP53"
     - "show me the cypher query for..."
     - "count nodes with label X"
   These require **only KG query**. No literature retrieval needed.

2. "full"
   Use this when the question requires biomedical explanation or evidence:
     - "what is the role of TP53 in apoptosis"
     - "mechanisms of disease X"
     - "what pathways are involved"
     - "what genes are associated with disease X"
   These require **both KG + literature**.

3. "auto"
   Use this if ambiguous. This will run KG + literature but allow fallback automatically.

Output format (strict JSON):
{{
  "mode": "kg_only" | "full" | "auto",
  "reason": "very short explanation"
}}
    """,
    tools=[],
    output_key=MODE_KEY,
)
question_router_agent = wrap_agent(_question_router_agent)

# -----------------------------------------
# KG Evidence Pipeline (single LlmAgent in this skeleton;
# you can later wrap this in a LoopAgent for true iterative refinement)
# -----------------------------------------


_kg_query_agent = LlmAgent(
    name="KgQueryAgent",
    model=LLM_MODEL,
    description=(
        "Generates read-only Cypher queries for GLKB, executes them, "
        "and summarizes the resulting graph evidence (nodes / relationships / any Article nodes)."
    ),
    generate_content_config=types.GenerateContentConfig(
        temperature=0, # More deterministic output
    ),
    instruction="""
You are a Cypher generator and Neo4j graph expert connected to the GLKB database.
The database contains information about PubMed/PMC articles, topics (vocabularies), and their relationships.

IMPORTANT: You have access to the conversation history through the session's events.
When the user's question references previous topics, entities, or asks follow-up questions,
use the conversation history to understand the context and generate appropriate queries.

Inputs:
- User question (from conversation)
- You may call tools to inspect schema, find vocabularies, or execute queries.

Task:
1) **First, search schema** to understand available nodes and relationships in the GLKB database.
2) Propose **read-only** Cypher queries (MATCH/RETURN only) to answer the question.
3) Keep each query bounded with LIMIT (50-100) and explicit labels/relationship types.
4) NEVER include write operations (CREATE/DELETE/SET/MERGE/DROP).
5) Check the syntax of the queries before executing them.
6) Execute the Cypher against GLKB and summarize the results.
7) Filter results after each tool call to keep relevant and important (e.g., high number of citations, or high number of cooccurrences) items.

Goal:
Given the user's biomedical question, you must:
  1. Understand which GLKB vocabularies are relevant.
  2. Generate and execute Cypher queries to retrieve relevant information from the database.
     - Use the vocabulary search tool to map the user's question to GLKB IDs.
     - Generate Cypher queries based on the question and schema.
     - Execute the Cypher against GLKB.
  3. If the information is insufficient, you may revise the Cypher queries and execute them no more than 10 times to get more information.
  4. Return a **compact JSON summary** of the graph evidence.

Workflow for graph evidence retrieval:
1. Inspect the schema to understand the available nodes and relationships in the GLKB database.
2. If the question mentions free-text concepts, use the vocabulary search tool to map them to GLKB ids first. When searching for vocabulary nodes, use the full name of the biological concept and consider its synonyms for better search results.
3. Use the OntologyMapping relationship for each vocabulary node to expand target id to lists of candidates that contain synonym ids: (v:Vocabulary {{id: "..."}})-[:OntologyMapping]-(synonym:Vocabulary)
4. Generate and execute Cypher queries to search for connections between the lists of candidates ids. In this step, you may call the execute_cypher_tool to execute the Cypher queries multiple times if necessary:
    - Search for direct connections between the lists of candidates that contain synonym ids: (v:Vocabulary)-[:OntologyMapping]-(synonym:Vocabulary) WHERE v.id IN ["..."] AND synonym.id IN ["..."]
    - When direct connection (e.g., GeneToDiseaseAssociation) is missing between two nodes, try indirect connections through graph traversal (e.g., GeneToGeneAssociation -> GeneToDiseaseAssociation) or fallback to cooccurrence analysis (e.g., Cooccur relationship, or graph traversal with ContainTerm relationship).
    - If no indirect connection is found, fallback to cooccurrence analysis (e.g., Cooccur relationship, or graph traversal with ContainTerm relationship).
5. If the KG has no relevant results, output a JSON object with empty lists but still explain what you *tried*.

Cypher Guidelines:
- When creating Cypher queries, focus on creating efficient and precise queries:
    - Always specify node labels and relationship types in the query to reduce the result set.
    - Always use LIMIT clauses (typically 50-100) with WITH clause to prevent large result sets, combined with ORDER BY clause to sort results by importance.
    - Use DISTINCT in your query to avoid duplicates.
    - Choose appropriate aggregation functions to summarize the results if necessary (e.g., COUNT or SUM when the question asks 'how many' or 'what is the total').
- Always use indexed properties to create efficient queries if possible, including:
    - Vocabulary node: id
    - Article node: pubmedid, pubdate, n_citation, doi

Output content:
- Include in the JSON:
  - `structural_evidence`: important nodes, relationships, and paths relevant to the question.
  - `article_ids`: any PubMed articles nodes returned from GLKB, each with its pubmedid, title, and abstract properties.

Output format (MUST be valid JSON):
{
  "structural_evidence": [...],
  "article_ids": [...],
  "notes": "short description of what the query found or why it was empty"
}
""",
    tools=[
        get_database_schema_tool,
        execute_cypher_tool,
        vocabulary_search_tool,
    ],
    # The JSON string goes to session.state[STATE_KG_EVIDENCE]
    output_key=STATE_KG_EVIDENCE,
)
kg_query_agent = wrap_agent(_kg_query_agent)

# -----------------------------------------
# Literature Evidence Pipeline
# -----------------------------------------

_article_retrieval_agent = LlmAgent(
    name="ArticleRetrievalAgent",
    model=LLM_MODEL,
    description=(
        "Retrieves PubMed articles from GLKB relevant to the question using keywords or article PubMed IDs, "
        "and summarizes them as literature evidence."
    ),
    instruction=f"""
You are a biomedical research assistant with access to PubMed/PMC articles.

IMPORTANT: You have access to the conversation history through the session's events.
When retrieving articles, consider the full conversation context, especially if the current
question is a follow-up or references previously discussed topics or articles.

Inputs available in state:
- The original user question (from the conversation).

Task:
1. Decide which biomedical concepts, keywords, and article PubMed IDs should be used as seeds.
2. Use the provided tools to retrieve relevant articles/snippets from GLKB (via article retrieval).
3. Produce a **JSON summary** of literature evidence, including:
   - `articles`: a list of objects with at least:
       - `id` (e.g. PubMed ID),
       - `title`,
       - `snippet` or `key_sentences`,
       - any scores or reasons for relevance you can infer.
   - `notes`: a short description of retrieval strategy.

Guidelines:
- Determine whether to prioritize recent articles or to prioritize impactful articles based on the user question.
- Try to analyze full articles to find the most relevant information to answerthe user question.

Output format (MUST be valid JSON):
{{
  "articles": [...],
  "notes": "short description of retrieval and ranking"
}}
""",
    tools=[
        article_search_tool,
        # fetch_pubmed_article_tool,
        # get_article_sections_tool,
    ],
    # JSON string with literature evidence -> session.state[STATE_DOC_EVIDENCE]
    output_key=STATE_DOC_EVIDENCE,
)
article_retrieval_agent = wrap_agent(_article_retrieval_agent)

class ConditionalLiteratureAgent(BaseAgent):
    name: str = "ConditionalLiteratureAgent"
    description: str = "Executes literature retrieval only if retrieval_mode != 'kg_only'."

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        mode_info = ctx.session.state.get(MODE_KEY, {})
        
        # Handle both JSON string and dict formats
        if isinstance(mode_info, str):
            try:
                mode_info = json.loads(mode_info)
            except json.JSONDecodeError:
                mode_info = {}
        
        mode = mode_info.get("mode", "auto") if isinstance(mode_info, dict) else "auto"
        logger.info(f"[AGENT CHECK] ConditionalLiteratureAgent | retrieval_mode={mode}")

        if mode == "kg_only":
            # Skip literature retrieval completely
            logger.info("[AGENT SKIP] ConditionalLiteratureAgent | Skipping (kg_only mode)")
            ctx.session.state[STATE_DOC_EVIDENCE] = '{"articles": [], "notes": "Skipped (kg_only)"}'
            return

        # Otherwise run the true literature agent (use wrapped version for logging)
        async for event in article_retrieval_agent.run_async(ctx):
            yield event


conditional_literature_agent = ConditionalLiteratureAgent()

# -----------------------------------------
# Parallel Evidence Gathering (KG + Literature)
# -----------------------------------------

evidence_parallel_agent = ParallelAgent(
    name="ParallelEvidenceGathering",
    description=(
        "Runs KG querying and literature retrieval in parallel so that every question "
        "collects both structured graph evidence and text-based article evidence."
    ),
    sub_agents=[
        kg_query_agent,
        conditional_literature_agent,
    ],
)

# -----------------------------------------
# Evidence Merge Agent
# -----------------------------------------

_evidence_merge_agent = LlmAgent(
    name="EvidenceMergeAgent",
    model=LITE_MODEL,
    description=(
        "Reads KG evidence and literature evidence from state, de-duplicates articles, "
        "and produces a unified evidence bundle for the final answer agent."
    ),
    instruction=f"""
You are the **GLKB evidence merger**.

State inputs:
- `{{{{{STATE_KG_EVIDENCE}}}}}`: JSON string with keys like `structural_evidence`, `article_ids`, `notes`.
- `{{{{{STATE_DOC_EVIDENCE}}}}}`: JSON string with keys like `articles`, `notes`.
- If literature evidence is empty (e.g. due to kg_only mode), proceed with only KG.
- If KG evidence is empty but literature exists, treat literature as fallback.

Task:
1. Parse both JSON blobs.
2. Merge them into a single unified evidence structure:
   - Deduplicate articles by their IDs.
   - For each article, track whether it came from:
       - KG only,
       - literature retrieval only,
       - or both.
   - Preserve important KG structural paths/edges separately from article-level evidence.

3. Output a **single JSON object**:
{{
  "kg_paths": [...],           // derived from structural_evidence
  "articles": [
     {{
       "id": "...",
       "title": "...",
       "snippet": "...",
       "source": ["kg", "literature"],
       "provenance": {{
          "kg_notes": "...",
          "retrieval_notes": "..."
       }}
     }},
     ...
  ],
  "merge_notes": "brief notes about how evidence was combined"
}}

If one side is missing (e.g. no KG or no literature evidence), still produce a valid structure
and explain the situation in `merge_notes`.

Output MUST be valid JSON as described above.
    """,
    tools=[],
    output_key=STATE_MERGED_EVIDENCE,
)
evidence_merge_agent = wrap_agent(_evidence_merge_agent)


# -----------------------------------------
# Final Answer Agent (uses merged evidence + formatter tool)
# -----------------------------------------

_final_answer_agent = LlmAgent(
    name="FinalAnswerAgent",
    model=LLM_MODEL,
    description=(
        "Produces the final natural-language answer to the user, grounded in both KG and "
        "literature evidence, and delegates formatting to the grounded_output_formatter tool."
    ),
    instruction=f"""
You are the **Genomic Literature Knowledge Base (GLKB) biomedical answering specialist**.
The Genomic Literature Knowledge Base (GLKB) is a comprehensive and powerful resource that integrates over 263 million biomedical terms and more than 14.6 million biomedical relationships. This collection is curated from 38 million PubMed abstracts and nine well-established biomedical repositories, offering an unparalleled wealth of knowledge for researchers and practitioners in the field.

IMPORTANT: You have access to the full conversation history through the session's events. The conversation history includes all previous messages in this conversation, including both user questions and your previous responses. When answering questions, consider the full context of the conversation:
- If a user asks about or refers to something mentioned previously, use the conversation history to understand what they're referring to.
- Maintain conversational coherence by connecting your answer to previous topics discussed.
- If the current question is a follow-up, reference the previous context appropriately.

Inputs:
- User question (from the conversation).
- Unified evidence JSON from state key `{STATE_KG_EVIDENCE}` and `{STATE_DOC_EVIDENCE}`.

Task:
Read and interpret the evidence from state key `{STATE_KG_EVIDENCE}` and `{STATE_DOC_EVIDENCE}`:
   - KG paths: explain the relationships (e.g., gene-disease-pathway).
   - Articles: highlight the most relevant ones and what they show.


IMPORTANT GUIDELINES:

1. Answer the user's question completely and concisely, based ONLY on the provided information
2. If the question is simple (e.g., "How many articles are published in 2024?"), answer concisely and directly. Otherwise (e.g., "What is the role of the gene ABC1 in the disease XYZ?"), structure your answer in a logical flow with clear paragraphs
3. Combine and connect information from all relevant retrieval steps
4. ALWAYS cite sources using the inline citation format described below
5. Be specific about genes, diseases, drugs, and pathways mentioned in the results
6. If the information is insufficient, acknowledge the limitations of the available data
7. Highlight areas of scientific consensus and controversy when apparent
8. Kindly refuse to answer questions that are not related to biomedical research, the GLKB database, or the GLKB agent system.

CITATION FORMAT:
- When you reference or rely on a specific article, cite it using this inline link format:
  [pubmedid](https://pubmed.ncbi.nlm.nih.gov/pubmedid)
  - pubmedid is the PubMed ID of the article
- Example 1: "The study found that beta cell function is impaired in Type 2 Diabetes, with RFX6 playing a regulatory role in insulin secretion [38743124](https://pubmed.ncbi.nlm.nih.gov/38743124)."
- Example 2 with multiple citations: "This gene has been linked to several pathways [38743124](https://pubmed.ncbi.nlm.nih.gov/38743124) [97533125](https://pubmed.ncbi.nlm.nih.gov/97533125)."
- When summarizing information from database results (not articles), do NOT include citations

EXPECTED ANSWER FORMAT:

1. Use clear markdown headers for organization
2. Start with a direct, concise answer to the question
3. Organize the answer into sections with clear headers
4. Use bullet points to list key findings
5. Provide supporting details organized into logical sections with proper citations using the inline link format
6. If applicable, include a concise summary of key findings at the end
7. Avoid technical jargon unless necessary, and explain specialized terms
8. Ensure citations appear throughout the text where information from specific articles is used

Remember, your goal is to synthesize information accurately while maintaining appropriate attribution to the original sources. 
""",
    # tools=[grounded_output_formatter],
    output_key=STATE_FINAL_ANSWER,
)
final_answer_agent = wrap_agent(_final_answer_agent, skip_output_log=True)


# -----------------------------------------
# Root Agent (Sequential pipeline)
# -----------------------------------------

# This is the entry point ADK looks for.
# It orchestrates:
#   1) Question routing to determine retrieval mode
#   2) Parallel KG + literature evidence gathering
#   3) Evidence merge
#   4) Final answer generation
root_agent = SequentialAgent(
    name="GLKBMultiAgentPipeline",
    description=(
        "GLKB multi-agent system that answers biomedical questions with coordinated "
        "Neo4j / KG queries and literature retrieval, then merges evidence and "
        "returns a grounded answer."
    ),
    sub_agents=[
        question_router_agent,    # Step 1: classify question -> kg_only / full / auto
        evidence_parallel_agent,  # Step 2: gather KG + literature evidence in parallel
        # evidence_merge_agent,     # Step 3: unify / de-dupe evidence
        final_answer_agent,       # Step 4: produce final grounded answer
    ],
)

test_agent = LlmAgent(
    name="TestAgent",
    model=LITE_MODEL,
    description="You are an assistant that can answer questions and maintain conversation context",
    instruction="""
You are an assistant that can answer questions about the GLKB knowledge base.

IMPORTANT: You have access to the full conversation history through the session's events.
The conversation history includes all previous messages in this conversation, including both user questions and your previous responses.

When answering questions, consider the full context of the conversation. If a user asks about "it" or refers to something mentioned previously, use the conversation history to understand what they're referring to.

The conversation history is automatically provided to you through the session's event history, which contains the chronological sequence of all messages in this conversation.
""",
    tools=[],
)