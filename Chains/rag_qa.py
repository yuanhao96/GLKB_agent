import os
import datetime
from typing import Literal, Optional, Tuple

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain.output_parsers import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate

import config

llm = ChatOpenAI(
    model=config.AGENT_MODEL, 
    temperature=0,
    api_key=config.OPENAI_API_KEY,
)

system = """You are an expert at biomedical question answering. \

Task:Answer biomedical questions based on the contexts.
Instructions:
Don't try to make up an answer, if you don't know just say that you don't know.
Use only the following pieces of context to answer the question at the end.
The context contains sub-questions that required to answer the question, and the information that answers the sub-questions.
The information is in one of the two types:
1. dictionaries of PubMed articles, containing their titles, abstracts, and PubMed IDs.
2. returned values from graph query that answers the question
Refer to the corresponding PubMed IDs in the answering if necessary.

Note: 
If the question is not related to the contexts, just say that it is impossible to answer the question based on the contexts.
Do not include any text except the generated answer to the question.
"""
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system),
        ("human", "question: {question} context: {context}"),
    ]
)

answer_generator = prompt | llm