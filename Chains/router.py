from typing import Literal
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_openai import ChatOpenAI

import config

class RouteQuery(BaseModel):
    """Route a user query to the most relevant datasource."""

    datasource: Literal["vector search", "graph query"] = Field(
        ...,
        description="Given a user question choose to route it to vectorstore or graphdb.",
    )
    
llm = ChatOpenAI(
    model=config.AGENT_MODEL, 
    temperature=0.7,
    api_key=config.OPENAI_API_KEY,
)
structured_llm_router = llm.with_structured_output(RouteQuery)

system = """You are an expert at routing a user question to perform vector search or graph query. 
The vector store contains documents related article title and abstracts. Here are two routing situations:
If the user question is about content of articles or seach for associations between two specific concepts (e.g., relationships between specific concepts, or about specific article topics), perform vector search. 
If the user question requires screening all possible nodes or relationships (e.g., all nodes connected to a specific node, or the most cited article of a topic) or meta information about articles and biomedical concepts, use graph query.

Example questions of Vector Search Case: 
    Find articles about photosynthesis
    Find if a disease is related to a specific phenotype
    Find if a gene regulates another gene

Example questions of Graph QA Chain: 
    Find the most cited article published in a specific year about a specific topic and return it's title, authors
    Find all diseases related to a specific gene
    Find all genetic variants associated with a specific disease
"""
    
# Example questions of Graph DB Query: 
#     MATCH (n:Article) RETURN COUNT(n)
#     MATCH (n:Article) RETURN n.title

route_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system),
        ("human", "{question}")
    ]
)

question_router = route_prompt | structured_llm_router