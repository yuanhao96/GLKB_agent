# Import Python Libraries
import os
import openai
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQA, GraphCypherQAChain
from langchain_community.graphs import Neo4jGraph
import json

# Import Custom Libraries
# from Prompts.prompt_template import create_few_shot_prompt, create_few_shot_prompt_with_context
from Graph.state import GraphState
import config

GLKB_CONNECTION_URI = config.GLKB_CONNECTION_URL
GLKB_USERNAME = config.GLKB_USERNAME
GLKB_PASSWORD = config.GLKB_PASSWORD

# Instantiate a Neo4j graph
graph = Neo4jGraph(
    url=GLKB_CONNECTION_URI,
    username=GLKB_USERNAME,
    password=GLKB_PASSWORD,
    refresh_schema=False
)
schema = json.load(open(config.GLKB_SCHEMA))
graph.structured_schema = schema

# Instantiate a openai model
llm = ChatOpenAI(
    model=config.AGENT_MODEL, 
    temperature=0.7,
    api_key=config.OPENAI_API_KEY,
)

def get_graph_qa_chain(state: GraphState):
    
    """Create a Neo4j Graph Cypher QA Chain"""
    
    prompt = state["prompt"]
    
    graph_qa_chain = GraphCypherQAChain.from_llm(
            cypher_llm = llm, #should use gpt-4 for production
            qa_llm = llm,
            validate_cypher= True,
            graph=graph,
            verbose=True,
            cypher_prompt = prompt,
            # return_intermediate_steps = True,
            return_direct = True,
            allow_dangerous_requests = True,
            include_types=['Article', 
                'Journal', 
                'Vocabulary', 
                'Cite', 
                'ContainTerm', 
                'Contain', 
                'PublishedIn',
                'ChemicalAffectsGeneAssociation',
                'ChemicalOrDrugOrTreatmentToDiseaseOrPhenotypicFeatureAssociation',
                'ChemicalToChemicalAssociation',
                'DiseaseToPhenotypicFeatureAssociation',
                'ExposureEventToOutcomeAssociation',
                'GeneToDiseaseAssociation',
                'GeneToExpressionSiteAssociation',
                'GeneToGeneAssociation',
                'GeneToGoTermAssociation',
                'GeneToPathwayAssociation',
                'HierarchicalStructure',
                'VariantToDiseaseAssociation',
                'VariantToGeneAssociation',
                'OntologyMapping'],
            exclude_types=[]
        )
    return graph_qa_chain

def get_graph_qa_chain_with_context(state: GraphState):
    
    """Create a Neo4j Graph Cypher QA Chain. Using this as GraphState so it can access state['prompt']"""
    
    prompt_with_context = state["prompt_with_context"] 
    
    graph_qa_chain = GraphCypherQAChain.from_llm(
            cypher_llm = llm, #should use gpt-4 for production
            qa_llm = llm,
            validate_cypher= True,
            graph=graph,
            verbose=False,
            cypher_prompt = prompt_with_context,
            # return_intermediate_steps = True,
            return_direct = True,
        )
    return graph_qa_chain