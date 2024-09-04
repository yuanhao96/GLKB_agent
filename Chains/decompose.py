import os
import datetime
from typing import Literal, Optional, Tuple

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain.output_parsers import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate

import config

class SubQuery2(BaseModel):
    """Decompose a given question/query into sub-queries"""

    sub_query: str = Field(
        ...,
        description="A unique paraphrasing of the original questions.",
    )

llm = ChatOpenAI(
    model=config.AGENT_MODEL, 
    temperature=0,
    api_key=config.OPENAI_API_KEY,
)

system = """You are an expert at decomposing users' queries. \

Perform query decomposition. Given a user question, break it down into no more than three distinct subqueries that \
you need to answer in order to answer the original question.

Here is example:
Question: Which credible set variants overlap islet cis-regulatory elements?
Answers:
sub_query1 : Find all islet cis-regulatory elements.
sub_query2 : Find all credible set variants that overlap with the identified elements.
"""
prompt2 = ChatPromptTemplate.from_messages(
    [
        ("system", system),
        ("human", "{question}"),
    ]
)

llm_with_tools2 = llm.bind_tools([SubQuery2])
parser2 = PydanticToolsParser(tools=[SubQuery2])
query_analyzer2 = prompt2 | llm_with_tools2 | parser2

class SubQuery(BaseModel):
    """Decompose a given question/query into sub-queries"""

    sub_query: str = Field(
        ...,
        description="A unique paraphrasing of the original questions.",
    )


llm = ChatOpenAI(
    model=config.AGENT_MODEL, 
    temperature=0,
    api_key=config.OPENAI_API_KEY,
)

system = """You are an expert at converting user questions into Neo4j Cypher queries. \

Perform query decomposition. Given a user question, break it down into two distinct subqueries that \
you need to answer in order to answer the original question.

For the given input question, create a query for similarity search and create a query to perform neo4j graph query.
Here is example:
Question: Find the articles about the photosynthesis and return their titles.
Answers:
sub_query1 : Find articles related to photosynthesis.
sub_query2 : Return titles of the articles
"""
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system),
        ("human", "{question}"),
    ]
)

llm_with_tools = llm.bind_tools([SubQuery])
parser = PydanticToolsParser(tools=[SubQuery])
query_analyzer = prompt | llm_with_tools | parser