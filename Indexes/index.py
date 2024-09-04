import os
import openai
from langchain.vectorstores import Neo4jVector
from langchain_openai import OpenAIEmbeddings
from langchain.embeddings.sentence_transformer import SentenceTransformerEmbeddings
#from neo4j import GraphDatabase

import config

# EMBEDDING_MODEL = OpenAIEmbeddings(openai_api_key=config.OPENAI_API_KEY)
model_kwargs = {'trust_remote_code': True}
EMBEDDING_MODEL = SentenceTransformerEmbeddings(model_name='Alibaba-NLP/gte-large-en-v1.5', model_kwargs=model_kwargs) # device_map="auto"

GLKB_CONNECTION_URI = config.GLKB_CONNECTION_URL
GLKB_USERNAME = config.GLKB_USERNAME
GLKB_PASSWORD = config.GLKB_PASSWORD

def get_neo4j_vector_index():   

    ''' Connect to vector index for article title and abstract'''
    retrieval_query = """
    RETURN node {.pubmedid, .title, .abstract} AS text, score, {article_id:node.pubmedid, pubdate:node.pubdate} AS metadata
    """
    neo4j_vector_index = Neo4jVector.from_existing_index(
        embedding = EMBEDDING_MODEL,
        url = GLKB_CONNECTION_URI,
        username = GLKB_USERNAME,
        password = GLKB_PASSWORD,
        index_name='abstract_vector',
        retrieval_query=retrieval_query,
    )
    return neo4j_vector_index

def get_neo4j_sentence_vector_index(): 
    
    ''' Create an sentence vector and Instantiate Neo4j vector from graph'''
    retrieval_query = """
    RETURN node {.id, .text} AS text, score, {} AS metadata
    """
    neo4j_abstract_vector_index = Neo4jVector.from_existing_index(
        embedding = EMBEDDING_MODEL,
        url = GLKB_CONNECTION_URI,
        username = GLKB_USERNAME,
        password = GLKB_PASSWORD,
        index_name='sentence_vector',
        retrieval_query=retrieval_query,
    )
    return neo4j_abstract_vector_index

# def get_neo4j_vocab_vector_index(): 
    
#     '''Create a vocab vector and Instantiate Neo4j vector from graph'''
    
#     neo4j_topic_vector_index = Neo4jVector.from_existing_index(
#         embedding = EMBEDDING_MODEL,
#         url = GLKB_CONNECTION_URI,
#         username = GLKB_USERNAME,
#         password = GLKB_PASSWORD,
#         index_name='abstract_vector',
#         retrieval_query=retrieval_query,
#     )
#     return neo4j_topic_vector_index