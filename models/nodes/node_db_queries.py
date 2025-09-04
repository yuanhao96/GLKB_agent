"""
Copyright 2024, Zep Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from typing import Any

from driver.driver import GraphProvider

ARTICLE_NODE_SAVE = """
    MERGE (n:Article:Entity:InformationContentEntity:JournalArticle:NamedThing:Publication:PubmedArticle {id: $id})
    SET n = {n_citation: $n_citation, doi: $doi, journal: $journal, pubdate: $pubdate, authors: $authors, pubmedid: $pubmedid, title: $title, abstract: $abstract, embedding: $embedding, openai_embedding: $openai_embedding}
    RETURN n.id AS id
"""

ARTICLE_NODE_SAVE_BULK = """
    UNWIND $articles AS article
    MERGE (n:Article:Entity:InformationContentEntity:JournalArticle:NamedThing:Publication:PubmedArticle {id: article.id})
    SET n = {n_citation: article.n_citation, doi: article.doi, journal: article.journal, pubdate: article.pubdate, authors: article.authors, pubmedid: article.pubmedid, title: article.title, abstract: article.abstract, embedding: article.embedding, openai_embedding: article.openai_embedding}
    RETURN n.id AS id
"""

ARTICLE_NODE_RETURN = """
    n.id AS id,
    n.n_citation AS n_citation,
    n.doi AS doi,
    n.journal AS journal,
    n.pubdate AS pubdate,
    n.authors AS authors,
    n.pubmedid AS pubmedid,
    n.title AS title,
    n.abstract AS abstract,
    n.embedding AS embedding,
    n.openai_embedding AS openai_embedding,
    n.source AS source
"""


def get_vocabulary_node_save_query(provider: GraphProvider, labels: str) -> str:
    return f"""
        MERGE (n:Vocabulary {{id: $entity_data.id}})
        SET n:{labels}
        SET n = $entity_data
        RETURN n.id AS id
    """


def get_vocabulary_node_save_bulk_query(provider: GraphProvider, nodes: list[dict]) -> str | Any:
    return """
        UNWIND $nodes AS node
        MERGE (n:Vocabulary {id: node.id})
        SET n = node
        RETURN n.id AS id
    """


VOCABULARY_NODE_RETURN = """
    n.id AS id,
    n.name AS name,
    n.description AS description,
    n.embedding AS embedding,
    n.n_citation AS n_citation,
    labels(n) AS labels,
    properties(n) AS attributes
"""


# def get_community_node_save_query(provider: GraphProvider) -> str:
#     if provider == GraphProvider.FALKORDB:
#         return """
#             MERGE (n:Community {uuid: $uuid})
#             SET n = {uuid: $uuid, name: $name, group_id: $group_id, summary: $summary, created_at: $created_at, name_embedding: $name_embedding}
#             RETURN n.uuid AS uuid
#         """

#     return """
#         MERGE (n:Community {uuid: $uuid})
#         SET n = {uuid: $uuid, name: $name, group_id: $group_id, summary: $summary, created_at: $created_at}
#         WITH n CALL db.create.setNodeVectorProperty(n, "name_embedding", $name_embedding)
#         RETURN n.uuid AS uuid
#     """


# COMMUNITY_NODE_RETURN = """
#     n.uuid AS uuid,
#     n.name AS name,
#     n.name_embedding AS name_embedding,
#     n.group_id AS group_id,
#     n.summary AS summary,
#     n.created_at AS created_at
# """

# Sentence node queries
SENTENCE_NODE_SAVE = """
    MERGE (n:Sentence:Entity:InformationContentEntity:NamedThing:StudyResult:TextMiningResult {id: $id})
    SET n = {text: $text, informative: $informative}
    RETURN n.id AS id
"""

SENTENCE_NODE_RETURN = """
    n.id AS id,
    n.text AS text,
    n.informative AS informative
"""
