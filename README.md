# GLKB Neo4j Agent

A sophisticated biomedical knowledge graph agent built on top of Neo4j that provides intelligent querying and analysis capabilities for the Genomic Literature Knowledge Base (GLKB). This agent combines natural language processing, graph traversal, and retrieval-augmented generation (RAG) to answer complex biomedical research questions.

## Overview

The GLKB Neo4j Agent is a comprehensive system that integrates over 263 million biomedical terms and more than 14.6 million biomedical relationships curated from 33 million PubMed abstracts and nine well-established biomedical repositories. It provides three main workflows for answering biomedical questions:

- **RAG Workflow**: For complex biomedical research questions requiring literature synthesis
- **Graph Query Workflow**: For statistical queries and direct graph traversal
- **General Workflow**: For general biomedical knowledge and GLKB capabilities

## Key Features

### 🤖 Multi-Agent Architecture
- **Routing Agent**: Intelligently routes queries to the most appropriate workflow
- **Graph Query Agent**: Handles Cypher query generation and graph traversal
- **RAG Agent**: Performs retrieval-augmented generation for complex research questions
- **General Agent**: Handles general biomedical knowledge and system capabilities

### 🔍 Advanced Search Capabilities
- **Semantic Search**: Vector-based similarity search across biomedical entities
- **Hybrid Search**: Combines multiple search strategies for optimal results
- **Cross-Encoder Reranking**: Uses advanced reranking models for result optimization
- **Graph Traversal**: Direct relationship exploration in the knowledge graph

### 📊 Comprehensive Data Model
- **Node Types**: Articles, Genes, Diseases, Drugs, Pathways, Anatomical Entities, and more
- **Relationship Types**: Gene-disease associations, drug interactions, pathway relationships
- **Rich Metadata**: Citations, descriptions, temporal information, and provenance

### 🛠️ MCP Integration
- **Model Context Protocol (MCP)**: Seamless integration with AI development tools
- **Tool-based Architecture**: Modular design for easy extension and customization
- **Server Registry**: Dynamic MCP server management and configuration

## Project Structure

```
neo4j_agent/
├── chatbot/                    # Main chatbot application
│   ├── main.py                # Entry point and chat loop
│   ├── prompts.py             # Agent prompts and instructions
│   ├── logger.py              # Logging utilities
│   └── mcpServers.json        # MCP server configuration
├── cypher/                    # Cypher query generation
│   ├── text2cypher_agent.py   # Natural language to Cypher conversion
│   ├── schema_loader.py       # Graph schema management
│   └── utils.py               # Cypher utilities
├── driver/                    # Database drivers
│   ├── neo4j_driver.py        # Neo4j connection management
│   └── driver.py              # Abstract driver interface
├── embedder/                  # Embedding services
│   ├── openai.py              # OpenAI embedding client
│   └── client.py              # Embedding interface
├── llm_client/                # Language model clients
│   ├── openai_client.py       # OpenAI integration
│   ├── anthropic_client.py    # Anthropic Claude integration
│   └── gemini_client.py       # Google Gemini integration
├── search/                    # Search functionality
│   ├── search.py              # Core search implementation
│   ├── search_config.py       # Search configuration
│   └── search_utils.py        # Search utilities
├── models/                    # Data models and schemas
│   ├── nodes/                 # Node type definitions
│   ├── edges/                 # Edge type definitions
│   ├── glkb_schema.json       # GLKB graph schema
│   └── glkb_schema_hints.json # Schema hints for LLM
├── prompts/                   # Prompt templates
│   ├── extract_nodes.py       # Node extraction prompts
│   ├── extract_edges.py       # Edge extraction prompts
│   └── eval.py                # Evaluation prompts
├── utils/                     # Utility functions
│   ├── maintenance/           # Graph maintenance operations
│   └── ontology_utils/        # Ontology utilities
├── cross_encoder/             # Reranking models
│   ├── openai_reranker_client.py
│   └── bge_reranker_client.py
├── graph_agent.py             # Core graph agent implementation
├── mcp_graph_agent_server.py  # MCP server implementation
└── examples/                  # Usage examples
    └── test.ipynb            # Jupyter notebook examples
```

## Installation

### Prerequisites

- Python 3.8+
- Neo4j database (version 4.0+)
- OpenAI API key (or other LLM provider)

### Environment Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd neo4j_agent
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
# Required
export OPENAI_API_KEY="your-openai-api-key"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password"

# Optional
export OPENAI_API_MODEL="gpt-4o-mini"
export OPENAI_API_BASE_URL="https://api.openai.com/v1"
```

## Usage

### Running the Chatbot

Start the interactive chatbot:

```bash
cd chatbot
python main.py
```

The chatbot will initialize the MCP app, load the graph agent server, and start an interactive session where you can ask biomedical questions.

### Example Queries

**Graph Query Examples:**
- "How many articles are there in the graph?"
- "What is the most important gene related to cancer?"
- "Show me all diseases related to gene TP53"

**RAG Query Examples:**
- "What is the role of gene ABC1 in disease XYZ?"
- "Find articles supporting the association between gene ABC1 and drug XYZ"
- "How do different drugs interact with pathway ABC?"

**General Query Examples:**
- "What is GLKB?"
- "What types of data are available in the knowledge graph?"
- "How does the knowledge graph work?"

### MCP Server Usage

The agent can also be used as an MCP server for integration with other tools:

```bash
python mcp_graph_agent_server.py
```

Available MCP tools:
- `graph_search`: Semantic search across the knowledge graph
- `run_cypher_query`: Execute Cypher queries directly
- `vocabulary_search`: Search for specific biomedical terms
- `article_search`: Search for research articles
- `get_article_by_pubmed_id`: Retrieve specific articles by PubMed ID

## Configuration

### MCP Server Configuration

Edit `chatbot/mcpServers.json` to configure MCP servers:

```json
{
  "mcpServers": {
    "glkb_search": {
      "command": "python",
      "args": ["/path/to/mcp_graph_agent_server.py"]
    }
  }
}
```

### Search Configuration

The system supports various search configurations:
- **Hybrid Search**: Combines multiple search strategies
- **Cross-Encoder Reranking**: Advanced result reranking
- **Node Distance Search**: Graph-based proximity search
- **MMR (Maximal Marginal Relevance)**: Diversity-aware search

## Data Schema

The GLKB knowledge graph includes the following node types:

- **Article**: Research papers with metadata (title, abstract, authors, journal, etc.)
- **Gene**: Genetic entities with identifiers and descriptions
- **DiseaseOrPhenotypicFeature**: Diseases and phenotypic features
- **ChemicalEntity**: Drugs and chemical compounds
- **Pathway**: Biological pathways and processes
- **AnatomicalEntity**: Anatomical structures
- **BiologicalProcess**: Biological processes
- **CellularComponent**: Cellular components
- **MolecularFunction**: Molecular functions
- **OrganismEntity**: Organisms and species
- **MeshTerm**: MeSH (Medical Subject Headings) terms

## Development

### Adding New Node Types

1. Define the node class in `nodes.py`
2. Add database queries in `models/nodes/node_db_queries.py`
3. Update the schema in `models/glkb_schema.json`
4. Add extraction prompts in `prompts/extract_nodes.py`

### Adding New Edge Types

1. Define the edge class in `edges.py`
2. Add database queries in `models/edges/edge_db_queries.py`
3. Update the schema in `models/glkb_schema.json`
4. Add extraction prompts in `prompts/extract_edges.py`

### Customizing Prompts

Edit the prompt files in the `prompts/` directory to customize how the LLM processes different types of queries and data.

## API Reference

### GraphAgent Class

The main `GraphAgent` class provides the core functionality:

```python
from graph_agent import GraphAgent

agent = GraphAgent(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password",
    llm_client=llm_client,
    embedder=embedder_client
)
```

### Search Functions

```python
# Semantic search
results = await search(
    clients=graph_clients,
    query="cancer treatment",
    config=search_config,
    search_filter=search_filters
)

# Vocabulary search
vocab_results = await vocabulary_search(
    clients=graph_clients,
    query="BRCA1",
    config=search_config
)
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

Copyright 2024, Zep Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

## Support

For questions, issues, or contributions, please refer to the project repository or contact the development team.

## Acknowledgments

This project builds upon the GLKB (Genomic Literature Knowledge Base) and integrates with various biomedical databases and repositories to provide comprehensive biomedical knowledge graph capabilities.
