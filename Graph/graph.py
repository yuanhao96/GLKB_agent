# Import Python Libraries
from dotenv import load_dotenv
from langgraph.graph import START, END, StateGraph

# Import Custom Libraries
import config
from Chains.router import question_router
from Graph.state import GraphState
from Graph.labels import *
from Graph.nodes import planner, router, retrieve_context, graph_qa, prompt_template, generate_rag_answer
load_dotenv()

# def route_question(state: GraphState):
#     print("---ROUTE QUESTION---")
#     question = state["question"]
#     source = question_router.invoke({"question": question})
#     if source.datasource == "vector search":
#         print("---ROUTE QUESTION TO VECTOR SEARCH---")
#         return "decomposer"
#     elif source.datasource == "graph query":
#         print("---ROUTE QUESTION TO GRAPH QA---")
#         return "prompt_template"
#     # elif source.datasource == "llm":
#     #     print("---ROUTE QUESTION TO LLM---")
#     #     return "llm"

workflow = StateGraph(GraphState)

# Nodes for graph qa
# workflow.add_node(PROMPT_TEMPLATE, prompt_template)
# workflow.add_node(GRAPH_QA, graph_qa)

# Nodes for graph qa with vector search
workflow.add_node(PLANNER, planner)
workflow.add_node(ROUTER, router)
workflow.add_node(RETRIEVE_CONTEXT, retrieve_context)
workflow.add_node(GENERATE_RAG_ANSWER, generate_rag_answer)

# Set conditional entry point for vector search or graph qa
# workflow.set_conditional_entry_point(
#     route_question,
#     {
#         'decomposer': DECOMPOSER, # vector search
#         'prompt_template': PROMPT_TEMPLATE # for graph qa
#     },
# )
workflow.add_edge(START, PLANNER)

# Edges for graph qa with vector search
workflow.add_edge(PLANNER, ROUTER)
workflow.add_edge(ROUTER, RETRIEVE_CONTEXT)
workflow.add_edge(RETRIEVE_CONTEXT, GENERATE_RAG_ANSWER)
workflow.add_edge(GENERATE_RAG_ANSWER, END)

# Edges for graph qa
# workflow.add_edge(PROMPT_TEMPLATE, GRAPH_QA)
# workflow.add_edge(GRAPH_QA, END)

app = workflow.compile()

#app.get_graph().draw_mermaid_png(output_file_path="graph.png")