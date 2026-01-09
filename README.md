# GLKB Multi-Agent System

A biomedical question-answering system built with [Google ADK (Agent Development Kit)](https://google.github.io/adk-docs/) that combines Neo4j knowledge graph querying with PubMed literature retrieval to provide grounded, evidence-based answers.

## Architecture

```
Root Agent (Sequential Pipeline)
├── QuestionRouterAgent        # Classifies questions → kg_only / full / auto
├── ParallelEvidenceGathering  # Runs in parallel:
│   ├── KgQueryAgent           # Neo4j/Cypher knowledge graph queries
│   └── ArticleRetrievalAgent  # PubMed article retrieval (conditional)
├── EvidenceMergeAgent         # Combines KG + literature evidence
└── FinalAnswerAgent           # Generates grounded answer with citations
```

## Features

- **Intelligent Routing**: Automatically determines whether to use KG-only or full retrieval based on question type
- **Knowledge Graph Integration**: Queries GLKB Neo4j database with auto-generated Cypher
- **Literature Retrieval**: Searches PubMed articles via GLKB's indexed collection
- **Evidence Grounding**: All answers cite specific articles with PubMed links
- **Comprehensive Logging**: Tracks all agent inputs/outputs and tool calls
- **REST API Service**: FastAPI-based web service with streaming support

## Project Structure

```
google_adk/
├── my_agent/                  # Agent definition
│   ├── agent.py               # Multi-agent pipeline definition
│   ├── tools.py               # Neo4j and PubMed tools
│   └── __init__.py
├── service/                   # FastAPI web service
│   ├── api.py                 # REST endpoints
│   ├── session_service.py     # SQLite session persistence
│   ├── runner.py              # Agent execution wrapper
│   ├── models.py              # Pydantic request/response models
│   └── requirements.txt       # Service dependencies
├── agent_logs/                # Runtime logs
│   └── agent.log
└── README.md
```

## Prerequisites

- Python 3.11+
- Neo4j database with GLKB data
- OpenAI API key (for LLM)

## Installation

1. **Install Google ADK and dependencies**:
   ```bash
   pip install google-adk python-dotenv neo4j httpx
   ```

2. **Install service dependencies** (for REST API):
   ```bash
   pip install -r service/requirements.txt
   ```

3. **Configure environment variables**:
   
   Create a `.env` file in the `my_agent/` directory:
   ```env
   # Neo4j Configuration
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=your_password
   NEO4J_DATABASE=glkb
   
   # OpenAI Configuration
   OPENAI_API_KEY=your_openai_api_key
   
   # Optional: Custom log directory
   AGENTS_LOG_DIR=/path/to/logs
   ```

## Usage

### Option 1: ADK CLI (Development)

Run the interactive chat interface:
```bash
cd google_adk
adk run my_agent
```

Example queries:
- "What is TP53?"
- "How many articles about CFTR were published since 2023?"
- "What genes are associated with diabetes?"

### Option 2: ADK Web UI

Run the built-in web interface:
```bash
adk web my_agent --port 8080
```

### Option 3: FastAPI REST Service (Production)

Start the REST API server:
```bash
cd google_adk
uvicorn service.api:app --host 0.0.0.0 --port 8000 --reload
```

API Documentation available at: `http://localhost:8000/docs`

#### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/apps/{app}/users/{user}/sessions` | Create session |
| `GET` | `/apps/{app}/users/{user}/sessions` | List sessions |
| `GET` | `/apps/{app}/users/{user}/sessions/{id}` | Get session |
| `DELETE` | `/apps/{app}/users/{user}/sessions/{id}` | Delete session |
| `POST` | `/apps/{app}/users/{user}/sessions/{id}/chat` | Chat (sync) |
| `POST` | `/apps/{app}/users/{user}/sessions/{id}/chat/stream` | Chat (SSE stream) |
| `GET` | `/apps/{app}/users/{user}/sessions/{id}/messages` | Get history |
| `GET` | `/health` | Health check |

#### Example API Usage

```bash
# Create a session
SESSION=$(curl -s -X POST http://localhost:8000/apps/glkb/users/user1/sessions | jq -r '.id')

# Send a message (non-streaming)
curl -X POST "http://localhost:8000/apps/glkb/users/user1/sessions/${SESSION}/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is TP53?"}'

# Send a message (streaming via SSE)
curl -N -X POST "http://localhost:8000/apps/glkb/users/user1/sessions/${SESSION}/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"message": "What genes are associated with breast cancer?"}'

# Get conversation history
curl "http://localhost:8000/apps/glkb/users/user1/sessions/${SESSION}/messages"
```

## Available Tools

The agent has access to the following tools:

| Tool | Description |
|------|-------------|
| `get_database_schema` | Retrieve GLKB Neo4j schema |
| `vocabulary_search` | Search for biomedical concepts/entities |
| `execute_cypher` | Execute read-only Cypher queries |
| `article_search` | Search PubMed articles by keywords |
| `fetch_pubmed_article` | Retrieve full article from PMC |
| `get_article_sections` | Get article sections (intro, methods, etc.) |

## Knowledge Graph Schema

The GLKB database contains:

**Node Types:**
- `Article` - PubMed articles with metadata
- `Journal` - Publication journals
- `Gene` - Gene entities (HGNC IDs)
- `DiseaseOrPhenotypicFeature` - Diseases and phenotypes
- `ChemicalEntity` - Drugs and chemicals
- `SequenceVariant` - Genetic variants
- `Pathway`, `BiologicalProcess`, `MolecularFunction`, `CellularComponent` - GO terms

**Relationship Types:**
- `ContainTerm` - Article mentions vocabulary term
- `GeneToDiseaseAssociation`, `GeneToGeneAssociation`, `GeneToPathwayAssociation`
- `ChemicalOrDrugOrTreatmentToDiseaseOrPhenotypicFeatureAssociation`
- `Cooccur` - Co-occurrence between vocabulary terms
- `OntologyMapping` - Cross-references between ontologies

## Logging

Logs are written to `agent_logs/agent.log` with the following format:
```
[AGENT START] AgentName
[AGENT INPUT] AgentName | User: ...
[TOOL CALL] tool_name | Input: {...}
[TOOL RESULT] tool_name | Output: {...}
[AGENT OUTPUT] AgentName | Key=output_key | Output: ...
[AGENT END] AgentName
```

## Configuration

### Question Routing Modes

The `QuestionRouterAgent` classifies queries into:

| Mode | Description | Example |
|------|-------------|---------|
| `kg_only` | KG queries only, no literature | "How many articles about X?" |
| `full` | Both KG and literature retrieval | "What is the role of TP53 in cancer?" |
| `auto` | Automatic fallback | Ambiguous questions |

### Model Configuration

Models are configured in `my_agent/agent.py`:
```python
LLM_MODEL = LiteLlm(model="openai/gpt-4o")      # Main agents
LITE_MODEL = LiteLlm(model="openai/gpt-4o-mini") # Router/Cypher generation
```

## Development

### Running Tests
```bash
adk eval my_agent path/to/eval_set.json
```

### Modifying Agents

Edit `my_agent/agent.py` to:
- Add new sub-agents
- Modify agent instructions
- Change tool assignments

### Adding Tools

Edit `my_agent/tools.py` to:
- Add new tool functions (must be async)
- Apply `@log_tool_call` decorator for logging
- Wrap with `FunctionTool()` for ADK

## Troubleshooting

**Neo4j Connection Failed**
- Verify `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` in `.env`
- Ensure Neo4j is running and accessible

**OpenAI API Errors**
- Check `OPENAI_API_KEY` is valid
- Verify API quota/billing

**Import Errors**
- Run from the `google_adk/` directory
- Ensure all dependencies are installed

## License

Internal use only - University of Michigan Medical School

## References

- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [GLKB Knowledge Base](https://github.com/...)
- [BioC PMC API](https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/)

