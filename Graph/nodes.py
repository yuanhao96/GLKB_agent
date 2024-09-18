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
from Chains.decompose import query_analyzer, question_planner
from Chains.router import question_router
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

def planner(state: GraphState):
    '''Returns a dictionary of at least one of the GraphState'''    
    '''Break down a given question to steps'''
    
    question = state["question"]
    steps = question_planner.invoke(question)
    return {"steps": steps, "question":question}

def router(state: GraphState):
    '''Returns a dictionary of at least one of the GraphState'''    
    '''Route question to graph query or vector search'''

    steps = state["steps"]
    query_types = []
    for step in steps.steps:
        query_types.append(question_router.invoke(step))
    steps.query_types = query_types
    return {'steps': steps}

# def decomposer(state: GraphState):
#     '''Returns a dictionary of at least one of the GraphState'''    
#     '''Decompose a given step to sub-queries'''
    
#     question = state["question"]
#     subqueries = query_analyzer.invoke(question)
#     return {"subqueries": subqueries, "question":question}

def retrieve_context(state: GraphState):
    '''Returns a dictionary of at least one of the GraphState'''    
    '''Retrieve context of each step according to their types'''

    steps = state["steps"]
    
    k = 3
    vector_graph_chain = get_vector_graph_chain(k=k)
    state['prompt'] = create_few_shot_prompt()
    # state['prompt_context'] = []
    # state['prompt_with_context'] = create_few_shot_prompt_with_context(state)
    graph_qa_chain = get_graph_qa_chain(state)
    graph_qa_chain_context = get_graph_qa_chain_with_context(state)

    contexts = dict()

    for step, qtype in zip(steps.steps, steps.query_types):
        if qtype.datasource == "vector search":
            chain_result = vector_graph_chain.invoke({
                "query": step},
            )
            documents = [DocumentModel(**doc.dict()) for doc in chain_result['source_documents']]
            extracted_data = [{"title": doc.extract_title(), "abstract":doc.extract_abstract(), "pubmedid": doc.metadata.article_id} for doc in documents]
            contexts[step] = extracted_data
        # elif qtype.datasource == "graph query":
        #     subqueries = query_analyzer.invoke(step).sub_query
        #     for sub in subqueries:
        #         if len(prompt_context) == 0: # no context
        #             res = graph_qa_chain.invoke(sub)
        #         else:
        #             res = graph_qa_chain_context.invoke(sub)
        #         state['prompt_context'].append((sub, res))
        #     contexts[step] = res
    return {'context': contexts}



# def vector_search(state: GraphState):
    
#     ''' Returns a dictionary of at least one of the GraphState'''
#     ''' Perform a vector similarity search and return article id as a parsed output'''

#     question = state["question"]
#     queries = state["subqueries"]
    
#     k = 3
#     vector_graph_chain = get_vector_graph_chain(k=k)
    
#     extracted_data = []
#     documents = []
#     for q in queries:
#         chain_result = vector_graph_chain.invoke({
#             "query": q.sub_query},
#         )
#         # Convert the result to a list of DocumentModel instances
#         documents += [DocumentModel(**doc.dict()) for doc in chain_result['source_documents']]
#         extracted_data += [{"title": doc.extract_title(), "abstract":doc.extract_abstract(), "pubmedid": doc.metadata.article_id} for doc in documents]
#         # article_ids += [("pubmedid", doc.metadata.article_id) for doc in documents]
    
#     return {"documents": extracted_data, "question": question, "subqueries": queries}


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
    context = state["context"]

    # RAG generation
    generation = answer_generator.invoke({"context": context, "question": question}).content
    
    return {"answer": generation}


