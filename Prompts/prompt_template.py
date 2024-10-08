import os


from langchain_openai import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain_core.prompts import FewShotPromptTemplate, PromptTemplate
from langchain_core.example_selectors import SemanticSimilarityExampleSelector, MaxMarginalRelevanceExampleSelector
from Prompts.prompt_examples import examples
import config

# Import Custom Libraries
from Graph.state import GraphState

EMBEDDING_MODEL = OpenAIEmbeddings(openai_api_key=config.OPENAI_API_KEY)

# Instantiate a example selector
example_selector = MaxMarginalRelevanceExampleSelector.from_examples(
    examples = examples,
    embeddings = EMBEDDING_MODEL,
    vectorstore_cls = Chroma,
    k=5,   
)

# Configure a formatter
example_prompt = PromptTemplate(
    input_variables=["question", "query"],
    template="Question: {question}\nCypher query: {query}"
)


def create_few_shot_prompt():
    '''Create a prompt template without context variable. The suffix provides dynamically selected prompt examples using similarity search'''
    
    prefix = """
Task:Generate Cypher statement to query a graph database.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.
Schema:
{schema}

Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Do not include any text except the generated Cypher statement.

Examples: Here are a few examples of generated Cypher statements for particular questions:
    """

    FEW_SHOT_PROMPT = FewShotPromptTemplate(
        example_selector = example_selector,
        example_prompt = example_prompt,
        prefix=prefix,
        suffix="Question: {question}, \nCypher Query: ",
        input_variables =["question","query","schema"],
    ) 
    return FEW_SHOT_PROMPT

def create_few_shot_prompt():
    '''Create a prompt template without context variable. The suffix provides dynamically selected prompt examples using similarity search'''
    
    prefix = """
Task:Generate Cypher statement to query a graph database.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.
Schema:
{schema}

Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Do not include any text except the generated Cypher statement.

Examples: Here are a few examples of generated Cypher statements for particular questions:
    """

    FEW_SHOT_PROMPT = FewShotPromptTemplate(
        example_selector = example_selector,
        example_prompt = example_prompt,
        prefix=prefix,
        suffix="Question: {question}, \nCypher Query: ",
        input_variables =["question","query","schema"],
    ) 
    return FEW_SHOT_PROMPT

def create_few_shot_prompt_with_context(state: GraphState):
    '''Create a prompt template with context variable. The context variable will be based on the output from vector qa chain'''
    '''The output of vector qa is list of node ids against which to perform graph query'''
    
    context = state['prompt_context']

    prefix = f"""
Task:Generate Cypher statement to query a graph database.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.
Schema:
{schema}

Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Do not include any text except the generated Cypher statement.

A context is provided in a list of tuples (query, result) 
Here are the contexts: {context}

Using node id from the context above, create cypher statements and use that to query with the graph.
Examples: Here are a few examples of generated Cypher statements for some question examples:
    """

    FEW_SHOT_PROMPT = FewShotPromptTemplate(
        example_selector = example_selector,
        example_prompt = example_prompt,
        prefix=prefix,
        suffix="Question: {question}, \nCypher Query: ",
        input_variables =["question", "query"],
    ) 
    return FEW_SHOT_PROMPT