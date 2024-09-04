# Import Python libraries
import os
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
import config

# Import Custom libraries
import config
from Chains.vector_graph_chain import get_vector_graph_chain
from Chains.graph_qa_chain import get_graph_qa_chain, get_graph_qa_chain_with_context
from Chains.rag_qa import answer_generator
from Chains.decompose import query_analyzer2
from Prompts.prompt_template import create_few_shot_prompt, create_few_shot_prompt_with_context
from Prompts.prompt_examples import examples
from Graph.state import GraphState
from Tools.parse_vector_search import DocumentModel


neo4j_url = config.GLKB_CONNECTION_URL
neo4j_user = config.GLKB_USERNAME
neo4j_pwd = config.GLKB_PASSWORD

graph = Neo4jGraph(
    url=neo4j_url,
    username=neo4j_user,
    password=neo4j_pwd,
    refresh_schema=False
)

llm = ChatOpenAI(
    model=config.AGENT_MODEL, 
    temperature=0,
    api_key=config.OPENAI_API_KEY
)

def decomposer(state: GraphState):
    
    '''Returns a dictionary of at least one of the GraphState'''    
    '''Decompose a given question to sub-queries'''
    
    question = state["question"]
    subqueries = query_analyzer2.invoke(question)
    return {"subqueries": subqueries, "question":question}
    
def vector_search(state: GraphState):
    
    ''' Returns a dictionary of at least one of the GraphState'''
    ''' Perform a vector similarity search and return article id as a parsed output'''

    question = state["question"]
    queries = state["subqueries"]
    
    k = 3
    vector_graph_chain = get_vector_graph_chain(k=k)
    
    article_ids = []
    extracted_data = []
    documents = []
    for q in queries:
        chain_result = vector_graph_chain.invoke({
            "query": q.sub_query},
        )
        # Convert the result to a list of DocumentModel instances
        documents += [DocumentModel(**doc.dict()) for doc in chain_result['source_documents']]
        extracted_data += [{"title": doc.extract_title(), "abstract":doc.extract_abstract(), "pubmedid": doc.metadata.article_id} for doc in documents]
        article_ids += [("pubmedid", doc.metadata.article_id) for doc in documents]
    
    return {"article_ids": article_ids, "documents": extracted_data, "question": question, "subqueries": queries}


def prompt_template(state: GraphState):
    
    '''Returns a dictionary of at least one of the GraphState'''
    '''Create a simple prompt tempalate for graph qa chain'''
    
    question = state["question"]

    # Create a prompt template
    prompt = create_few_shot_prompt()
    
    return {"prompt": prompt, "question":question}
    

def graph_qa(state: GraphState):
    
    ''' Returns a dictionary of at least one of the GraphState '''
    ''' Invoke a Graph QA Chain '''
    
    question = state["question"]
    
    graph_qa_chain = get_graph_qa_chain(state)
    
    result = graph_qa_chain.invoke(
        {
            #"context": graph.schema, 
            "query": question,
        },
    )
    return {"documents": result, "question":question}
    
def prompt_template_with_context(state: GraphState):
    
    '''Returns a dictionary of at least one of the GraphState'''
    '''Create a dynamic prompt template for graph qa with context chain'''
    
    question = state["question"]
    queries = state["subqueries"]

    # Create a prompt template
    prompt_with_context = create_few_shot_prompt_with_context(state)
    
    return {"prompt_with_context": prompt_with_context, "question":question, "subqueries": queries}



def graph_qa_with_context(state: GraphState):
    
    '''Returns a dictionary of at least one of the GraphState'''
    '''Invoke a Graph QA chain with dynamic prompt template'''
    
    queries = state["subqueries"]
    prompt_with_context = state["prompt_with_context"]

    # Instantiate graph_qa_chain_with_context
    # Pass the GraphState as 'state'. This chain uses state['prompt'] as input argument
    graph_qa_chain = get_graph_qa_chain_with_context(state)
    
    result = graph_qa_chain.invoke(
        {
            "query": queries[1].sub_query,
        },
    )
    return {"documents": result, "prompt_with_context":prompt_with_context, "subqueries": queries}

def generate_rag_answer(state: GraphState):
    """
    Generate answer using RAG on retrieved documents

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): New key added to state, generation, that contains LLM generation
    """
    question = state["question"]
    documents = state["documents"]
    article_ids = state["article_ids"]
    subqueries = state["subqueries"]

    # RAG generation
    generation = answer_generator.invoke({"documents": documents, "question": question}).content
    
    return {"article_ids": article_ids, "documents": documents, "question": question, "subqueries": subqueries, "answer":generation}


