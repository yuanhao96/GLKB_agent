# agent.py - Single-agent GLKB system with on-demand skill loading
#
# Replaces the previous multi-agent pipeline (QuestionRouter -> Parallel KG+Lit -> FinalAnswer)
# with a single LlmAgent that has all tools plus SkillToolset for loading
# detailed skill instructions on demand.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
import os
import yaml
from pathlib import Path
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.skills import Skill
from google.adk.skills.models import Frontmatter, Resources
from google.adk.tools.skill_toolset import SkillToolset
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
# Tools (from tools.py)
# -----------------------------------------
from tools import glkb_tools, pubmed_tools, biorxiv_tools

# -----------------------------------------
# Model
# -----------------------------------------
LLM_MODEL = LiteLlm(model="openai/gpt-5.2")

# -----------------------------------------
# Skill Loading Helper
# -----------------------------------------

def load_skill_from_directory(skill_dir: Path) -> Skill:
    """Load a skill from a directory containing SKILL.md and optional references/."""
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text()

    # Parse YAML frontmatter between --- markers
    parts = text.split("---", 2)
    if len(parts) >= 3:
        frontmatter_data = yaml.safe_load(parts[1])
        instructions = parts[2].strip()
    else:
        frontmatter_data = {"name": skill_dir.name, "description": ""}
        instructions = text

    frontmatter = Frontmatter(
        name=frontmatter_data.get("name", skill_dir.name),
        description=frontmatter_data.get("description", ""),
    )

    # Load references if they exist (dict[str, str]: name -> content)
    references = {}
    refs_dir = skill_dir / "references"
    if refs_dir.exists():
        for ref_file in sorted(refs_dir.glob("*.md")):
            references[ref_file.stem] = ref_file.read_text()

    resources = Resources(references=references)

    return Skill(
        frontmatter=frontmatter,
        instructions=instructions,
        resources=resources,
    )

# -----------------------------------------
# Load Skills
# -----------------------------------------
SKILLS_DIR = Path(__file__).parent / "skills"
kg_skill = load_skill_from_directory(SKILLS_DIR / "glkb_knowledge_graph")
lit_skill = load_skill_from_directory(SKILLS_DIR / "pubmed_reader")
biorxiv_skill = load_skill_from_directory(SKILLS_DIR / "biorxiv")

logger.info(f"Loaded skill: {kg_skill.frontmatter.name}")
logger.info(f"Loaded skill: {lit_skill.frontmatter.name}")
logger.info(f"Loaded skill: {biorxiv_skill.frontmatter.name}")

# -----------------------------------------
# Base Instruction
# -----------------------------------------
BASE_INSTRUCTION = """
You are the GLKB biomedical QA assistant. The Genomic Literature Knowledge Base (GLKB) integrates over 263 million biomedical terms and more than 14.6 million biomedical relationships curated from 38 million PubMed abstracts and nine biomedical repositories.

You have access to skills for detailed workflows. Load them as needed:
- "glkb-knowledge-graph": Cypher query generation, schema navigation, vocabulary mapping for the GLKB Neo4j database
- "pubmed-reader": Article retrieval strategy using GLKB search and direct PubMed/PMC access
- "biorxiv": bioRxiv/medRxiv preprint search, metadata retrieval, and full text

WORKFLOW:
1. Assess the question type:
   - KG-only (counts, lists, schema queries) -> load KG skill only
   - Needs biomedical explanation or evidence -> load pubmed-reader; also load biorxiv whenever preprint evidence could help (recency, cutting-edge topics, or when the user provides a bioRxiv/medRxiv DOI/URL)
   - Ambiguous -> load KG skill and pubmed-reader; add biorxiv if the topic could benefit from preprint coverage
2. Load relevant skill(s) via load_skill and follow their instructions to query tools
3. Synthesize a grounded answer using the evidence gathered. Preprints and peer-reviewed articles may be cited together.

IMPORTANT:
- You have access to the full conversation history. For follow-up questions, use context from previous exchanges.
- Filter results after each tool call to keep relevant and important items (e.g., high citations, high cooccurrences).
- If information is insufficient after querying, acknowledge limitations.
- Kindly refuse to answer questions that are not related to biomedical research, the GLKB database, or the GLKB agent system.

EVIDENCE AND CITATION WORKFLOW:
1. After gathering evidence from tools, identify the specific sentences or passages
   that directly support your answer.
2. For each article you will cite, call `cite_evidence` with:
   - pmid: the article's identifier — PubMed ID for PubMed articles, or the DOI
     for bioRxiv/medRxiv preprints (the argument name is historical; it accepts
     either)
   - quote: the EXACT sentence(s) from the tool output (abstract, full text, or
     KG evidence field) — do NOT paraphrase
   - context_type: "abstract", "fulltext", "kg_evidence", or "title"
3. You MUST call cite_evidence before referencing an article in your answer.
   Do not cite articles without registering evidence first.
   If you cannot find a specific supporting quote, the system will fall back to
   the article abstract automatically — but specific quotes are always preferred.
4. Then write your final answer, citing articles inline:
   - PubMed article:
     `[PMID](https://pubmed.ncbi.nlm.nih.gov/PMID)`
     Example: "TP53 plays a key role in apoptosis [38743124](https://pubmed.ncbi.nlm.nih.gov/38743124)."
   - bioRxiv preprint:
     `[bioRxiv:DOI](https://www.biorxiv.org/content/DOI)`
     Example: "Lipid nanoparticles enable efficient CRISPR delivery [bioRxiv:10.1101/2024.01.15.575889](https://www.biorxiv.org/content/10.1101/2024.01.15.575889)."
   - medRxiv preprint:
     `[medRxiv:DOI](https://www.medrxiv.org/content/DOI)`
5. If a preprint has a peer-reviewed journal version (`published` field non-empty),
   prefer the journal version (via PubMed) unless the user explicitly asked for
   the preprint.
6. When summarizing database/graph structure results (not articles), do not cite.
7. Use markdown headers and bullet points for well-structured answers.
"""

# -----------------------------------------
# Root Agent
# -----------------------------------------
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
        *biorxiv_tools,
        SkillToolset(skills=[kg_skill, lit_skill, biorxiv_skill]),
    ],
)
