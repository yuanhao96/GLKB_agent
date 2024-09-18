import os
import datetime
from typing import Literal, Optional, Tuple, List

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain.output_parsers import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate

import config

class Steps(BaseModel):
    """break down a given task into steps"""

    steps: List[str] = Field(
        description="different steps to follow, should be in sorted order"
    )
    query_types: List[str] = Field(
        description="query types of each step, should be in sorted order"
    )

class SubQuery(BaseModel):
    """Decompose a given question/query into sub-queries"""

    sub_query: List[str] = Field(
        ...,
        description="A list of subqueries of the original questions.",
    )

llm = ChatOpenAI(
    model=config.AGENT_MODEL, 
    temperature=0,
    api_key=config.OPENAI_API_KEY,
)

# planner
system = """For the given question, come up with a simple step by step searching plan to retrieve its answer in a literature database.
This plan should involve individual tasks, that if executed correctly will yield the correct answer.
Each step aims to retrieve certain knowledge from the knowledge graph.
Meta data about articles and biomedical concepts (e.g., find the most cited article in a specific year, find all genes related to a disease) can be retrieved within a single step. Use as few steps as possible.
If the question can be answered in a single step, do not use multiple steps.

Here is example:
Question: How is RFX6 related to type 2 diabetes and MODY
step 1: Find if RFX6 is related to type 2 diabetes
step 2: Find if RFX6 is related to MODY
"""

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system),
        ("human", "{question}"),
    ]
)

question_planner = prompt | llm.with_structured_output(Steps)

# decomposer
system = """You are an expert at decomposing users' requests into Neo4j Cypher queries. \

For the given requests, decompose it into a series of step by step subqueries
Each subquery can be a query to perform neo4j graph query.
Always search for the node ids before specifying a new concept with its name in the graph.
Do not add any superfluous subqueries.
The result of the final subquery should be the final answer.

Here is example:
Question: Find all articles containing genes that regulate TP53 after 2010
Answers:
sub_query1 : Retrieve the node id of TP53 gene
sub_query2 : Find all gene ids that regulate the node with the identified TP53 id.
sub_query3 : Find articles related the identified gene ids published after 2010.
"""

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system),
        ("human", "{question}"),
    ]
)

query_analyzer = prompt | llm.with_structured_output(SubQuery)