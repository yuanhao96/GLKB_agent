"""
Database query utilities for different graph database backends.

This module provides database-agnostic query generation for Neo4j and FalkorDB,
supporting index creation, fulltext search, and bulk operations.
"""

from typing_extensions import LiteralString

from driver.driver import GraphProvider


# def get_range_indices(provider: GraphProvider) -> list[LiteralString]:

#     return [
#         'CREATE INDEX entity_uuid IF NOT EXISTS FOR (n:Entity) ON (n.uuid)',
#         'CREATE INDEX episode_uuid IF NOT EXISTS FOR (n:Episodic) ON (n.uuid)',
#         'CREATE INDEX community_uuid IF NOT EXISTS FOR (n:Community) ON (n.uuid)',
#         'CREATE INDEX relation_uuid IF NOT EXISTS FOR ()-[e:RELATES_TO]-() ON (e.uuid)',
#         'CREATE INDEX mention_uuid IF NOT EXISTS FOR ()-[e:MENTIONS]-() ON (e.uuid)',
#         'CREATE INDEX has_member_uuid IF NOT EXISTS FOR ()-[e:HAS_MEMBER]-() ON (e.uuid)',
#         'CREATE INDEX entity_group_id IF NOT EXISTS FOR (n:Entity) ON (n.group_id)',
#         'CREATE INDEX episode_group_id IF NOT EXISTS FOR (n:Episodic) ON (n.group_id)',
#         'CREATE INDEX community_group_id IF NOT EXISTS FOR (n:Community) ON (n.group_id)',
#         'CREATE INDEX relation_group_id IF NOT EXISTS FOR ()-[e:RELATES_TO]-() ON (e.group_id)',
#         'CREATE INDEX mention_group_id IF NOT EXISTS FOR ()-[e:MENTIONS]-() ON (e.group_id)',
#         'CREATE INDEX name_entity_index IF NOT EXISTS FOR (n:Entity) ON (n.name)',
#         'CREATE INDEX created_at_entity_index IF NOT EXISTS FOR (n:Entity) ON (n.created_at)',
#         'CREATE INDEX created_at_episodic_index IF NOT EXISTS FOR (n:Episodic) ON (n.created_at)',
#         'CREATE INDEX valid_at_episodic_index IF NOT EXISTS FOR (n:Episodic) ON (n.valid_at)',
#         'CREATE INDEX name_edge_index IF NOT EXISTS FOR ()-[e:RELATES_TO]-() ON (e.name)',
#         'CREATE INDEX created_at_edge_index IF NOT EXISTS FOR ()-[e:RELATES_TO]-() ON (e.created_at)',
#         'CREATE INDEX expired_at_edge_index IF NOT EXISTS FOR ()-[e:RELATES_TO]-() ON (e.expired_at)',
#         'CREATE INDEX valid_at_edge_index IF NOT EXISTS FOR ()-[e:RELATES_TO]-() ON (e.valid_at)',
#         'CREATE INDEX invalid_at_edge_index IF NOT EXISTS FOR ()-[e:RELATES_TO]-() ON (e.invalid_at)',
#     ]


# def get_fulltext_indices() -> list[LiteralString]:

#     return [
#         """CREATE FULLTEXT INDEX episode_content IF NOT EXISTS
#         FOR (e:Episodic) ON EACH [e.content, e.source, e.source_description, e.group_id]""",
#         """CREATE FULLTEXT INDEX node_name_and_summary IF NOT EXISTS
#         FOR (n:Entity) ON EACH [n.name, n.summary, n.group_id]""",
#         """CREATE FULLTEXT INDEX community_name IF NOT EXISTS
#         FOR (n:Community) ON EACH [n.name, n.group_id]""",
#         """CREATE FULLTEXT INDEX edge_name_and_fact IF NOT EXISTS
#         FOR ()-[e:RELATES_TO]-() ON EACH [e.name, e.fact, e.group_id]""",
#     ]


def get_nodes_query(provider: GraphProvider, name: str = '', query: str | None = None) -> str:
    return f'CALL db.index.fulltext.queryNodes("{name}", {query}, {{limit: $limit}})'


def get_vector_cosine_func_query(vec1, vec2) -> str:
    return f'vector.similarity.cosine({vec1}, {vec2})'

def get_nodes_similarity_query(name: str = '', query_vector: list[float] | None = None, limit: int = 10) -> str:
    return f"CALL db.index.vector.queryNodes('{name}', {limit}, {query_vector})"

def get_relationships_query(name: str) -> str:
    return f'CALL db.index.fulltext.queryRelationships("{name}", $query, {{limit: $limit}})'
