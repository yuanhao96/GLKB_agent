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

import logging
from datetime import datetime
from time import time
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict
from typing_extensions import LiteralString
from graphagent_client import GraphAgentClients

from cross_encoder.client import CrossEncoderClient
from cross_encoder.openai_reranker_client import OpenAIRerankerClient
from driver.driver import GraphDriver
from driver.neo4j_driver import Neo4jDriver
from edges import (
    SemanticEdge,
    Edge,
)
from embedder import EmbedderClient, OpenAIEmbedder
from helpers import (
    # get_default_group_id,
    semaphore_gather,
    validate_excluded_entity_types,
    # validate_group_id,
)
from llm_client import LLMClient, OpenAIClient
from nodes import (
    VocabularyNode,
    ArticleNode,
    SentenceNode,
    Node,
    create_vocabulary_node_embeddings,
)
from search.search import SearchConfig, search, vocabulary_search
from search.search_config import DEFAULT_SEARCH_LIMIT, SearchResults
from search.search_config_recipes import (
    COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    EDGE_HYBRID_SEARCH_RRF,
    COMBINED_HYBRID_SEARCH_RRF,
    COMBINED_HYBRID_SEARCH_NODE_DISTANCE,
    NODE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_MMR,
)
from search.search_filters import SearchFilters
from search.search_utils import (
    RELEVANT_SCHEMA_LIMIT,
    # get_edge_invalidation_candidates,
    # get_mentioned_nodes,
    # get_relevant_edges,
)
from telemetry import capture_event
# from utils.bulk_utils import (
#     RawEpisode,
#     add_nodes_and_edges_bulk,
#     dedupe_edges_bulk,
#     dedupe_nodes_bulk,
#     extract_nodes_and_edges_bulk,
#     resolve_edge_pointers,
#     retrieve_previous_episodes_bulk,
# )
from utils.datetime_utils import utc_now
# from utils.maintenance.community_operations import (
#     build_communities,
#     remove_communities,
#     update_community,
# )
# from utils.maintenance.edge_operations import (
#     build_duplicate_of_edges,
#     build_episodic_edges,
#     extract_edges,
#     resolve_extracted_edge,
#     resolve_extracted_edges,
# )
# from utils.maintenance.graph_data_operations import (
#     EPISODE_WINDOW_LEN,
#     build_indices_and_constraints,
#     retrieve_episodes,
# )
# from utils.maintenance.node_operations import (
#     extract_attributes_from_nodes,
#     extract_nodes,
#     resolve_extracted_nodes,
# )
from utils.ontology_utils.entity_types_utils import validate_entity_types

logger = logging.getLogger(__name__)

load_dotenv()

class GraphAgent:
    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        llm_client: LLMClient | None = None,
        embedder: EmbedderClient | None = None,
        cross_encoder: CrossEncoderClient | None = None,
        # store_raw_episode_content: bool = True,
        graph_driver: GraphDriver | None = None,
        max_coroutines: int | None = None,
        ensure_ascii: bool = False,
    ):
        """
        Initialize a Graphiti instance.

        This constructor sets up a connection to a graph database and initializes
        the LLM client for natural language processing tasks.

        Parameters
        ----------
        uri : str
            The URI of the Neo4j database.
        user : str
            The username for authenticating with the Neo4j database.
        password : str
            The password for authenticating with the Neo4j database.
        llm_client : LLMClient | None, optional
            An instance of LLMClient for natural language processing tasks.
            If not provided, a default OpenAIClient will be initialized.
        embedder : EmbedderClient | None, optional
            An instance of EmbedderClient for embedding tasks.
            If not provided, a default OpenAIEmbedder will be initialized.
        cross_encoder : CrossEncoderClient | None, optional
            An instance of CrossEncoderClient for reranking tasks.
            If not provided, a default OpenAIRerankerClient will be initialized.
        # store_raw_episode_content : bool, optional
        #     Whether to store the raw content of episodes. Defaults to True.
        graph_driver : GraphDriver | None, optional
            An instance of GraphDriver for database operations.
            If not provided, a default Neo4jDriver will be initialized.
        max_coroutines : int | None, optional
            The maximum number of concurrent operations allowed. Overrides SEMAPHORE_LIMIT set in the environment.
            If not set, the Graphiti default is used.
        ensure_ascii : bool, optional
            Whether to escape non-ASCII characters in JSON serialization for prompts. Defaults to False.
            Set as False to preserve non-ASCII characters (e.g., Korean, Japanese, Chinese) in their
            original form, making them readable in LLM logs and improving model understanding.

        Returns
        -------
        None

        Notes
        -----
        This method establishes a connection to a graph database (Neo4j by default) using the provided
        credentials. It also sets up the LLM client, either using the provided client
        or by creating a default OpenAIClient.

        The default database name is defined during the driver's construction. If a different database name
        is required, it should be specified in the URI or set separately after
        initialization.

        The OpenAI API key is expected to be set in the environment variables.
        Make sure to set the OPENAI_API_KEY environment variable before initializing
        Graphiti if you're using the default OpenAIClient.
        """

        if graph_driver:
            self.driver = graph_driver
        else:
            if uri is None:
                raise ValueError('uri must be provided when graph_driver is None')
            self.driver = Neo4jDriver(uri, user, password)

        # self.store_raw_episode_content = store_raw_episode_content
        self.max_coroutines = max_coroutines
        self.ensure_ascii = ensure_ascii
        if llm_client:
            self.llm_client = llm_client
        else:
            self.llm_client = OpenAIClient()
        if embedder:
            self.embedder = embedder
        else:
            self.embedder = OpenAIEmbedder()
        if cross_encoder:
            self.cross_encoder = cross_encoder
        else:
            self.cross_encoder = OpenAIRerankerClient()

        self.clients = GraphAgentClients(
            driver=self.driver,
            llm_client=self.llm_client,
            embedder=self.embedder,
            cross_encoder=self.cross_encoder,
            ensure_ascii=self.ensure_ascii,
        )

        # Capture telemetry event
        self._capture_initialization_telemetry()

    def _capture_initialization_telemetry(self):
        """Capture telemetry event for Graphiti initialization."""
        try:
            # Detect provider types from class names
            llm_provider = self._get_provider_type(self.llm_client)
            embedder_provider = self._get_provider_type(self.embedder)
            reranker_provider = self._get_provider_type(self.cross_encoder)

            properties = {
                'llm_provider': llm_provider,
                'embedder_provider': embedder_provider,
                'reranker_provider': reranker_provider,
            }

            capture_event('graph_agent_initialized', properties)
        except Exception:
            # Silently handle telemetry errors
            pass
    
    async def close(self):
        """
        Close the connection to the Neo4j database.

        This method safely closes the driver connection to the Neo4j database.
        It should be called when the Graphiti instance is no longer needed or
        when the application is shutting down.

        Parameters
        ----------
        self

        Returns
        -------
        None

        Notes
        -----
        It's important to close the driver connection to release system resources
        and ensure that all pending transactions are completed or rolled back.
        This method should be called as part of a cleanup process, potentially
        in a context manager or a shutdown hook.

        Example:
            graphiti = Graphiti(uri, user, password)
            try:
                # Use graphiti...
            finally:
                graphiti.close()
        """
        await self.driver.close()

    async def search(
        self,
        query: str,
        center_node_uuid: str | None = None,
        group_ids: list[str] | None = None,
        num_results=DEFAULT_SEARCH_LIMIT,
        search_filter: SearchFilters | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """
        Perform a hybrid search on the knowledge graph.

        This method executes a search query on the graph, combining vector and
        text-based search techniques to retrieve relevant facts, returning the edges as a string.

        This is our basic out-of-the-box search, for more robust results we recommend using our more advanced
        search method graphiti.search_().

        Parameters
        ----------
        query : str
            The search query string.
        center_node_uuid: str, optional
            Facts will be reranked based on proximity to this node
        # group_ids : list[str | None] | None, optional
        #     The graph partitions to return data from.
        num_results : int, optional
            The maximum number of results to return. Defaults to 10.

        Returns
        -------
        list
            A list of SemanticEdge objects that are relevant to the search query.

        Notes
        -----
        This method uses a SearchConfig with num_episodes set to 0 and
        num_results set to the provided num_results parameter.

        The search is performed using the current date and time as the reference
        point for temporal relevance.
        """
        search_config = (
            COMBINED_HYBRID_SEARCH_RRF if center_node_uuid is None else COMBINED_HYBRID_SEARCH_NODE_DISTANCE
        )
        search_config.limit = num_results

        group_ids = None

        result = await search(
                self.clients,
                query,
                group_ids,
                search_config,
                search_filter if search_filter is not None else SearchFilters(),
                center_node_uuid,
            )
        edge_dicts = []
        sentence_dicts = []
        article_dicts = []
        for edge, score in zip(result.edges, result.edge_reranker_scores):
            edge_dict = dict(edge)
            edge_dict['score'] = score
            edge_dicts.append(edge_dict)
        for sentence, score in zip(result.sentences, result.sentence_reranker_scores):
            sentence_dict = dict(sentence)
            sentence_dict['score'] = score
            sentence_dicts.append(sentence_dict)
        for article, score in zip(result.articles, result.article_reranker_scores):
            article_dict = dict(article)
            article_dict['score'] = score
            article_dicts.append(article_dict)
        
        return edge_dicts, article_dicts, sentence_dicts

    async def search_(
        self,
        query: str,
        center_node_uuid: str | None = None,
        group_ids: list[str] | None = None,
        num_results=DEFAULT_SEARCH_LIMIT,
        search_filter: SearchFilters | None = None,
    ) -> SearchResults:
        """
        Advanced search method that returns Graph objects (nodes and edges) rather
        than a list of facts. This endpoint allows the end user to utilize more advanced features such as filters and
        different search and reranker methodologies across different layers in the graph.

        For different config recipes refer to search/search_config_recipes.
        """
        search_config = (
            COMBINED_HYBRID_SEARCH_RRF if center_node_uuid is None else COMBINED_HYBRID_SEARCH_NODE_DISTANCE
        )
        search_config.limit = num_results

        group_ids = None

        result = await search(
                self.clients,
                query,
                group_ids,
                search_config,
                search_filter if search_filter is not None else SearchFilters(),
                center_node_uuid,
            )
        
        return result
    
    async def search_vocabulary(
        self,
        query: str,
        center_node_uuid: str | None = None,
        group_ids: list[str] | None = None,
        num_results=DEFAULT_SEARCH_LIMIT,
        search_filter: SearchFilters | None = None,
    ) -> list[dict]:
        search_config = (
            NODE_HYBRID_SEARCH_RRF if center_node_uuid is None else NODE_HYBRID_SEARCH_MMR
        )
        search_config.limit = num_results

        group_ids = None

        result = await vocabulary_search(
                self.clients,
                query,
                group_ids,
                search_config,
                search_filter if search_filter is not None else SearchFilters(),
                center_node_uuid,
            )
        vocabulary_dicts = []
        for node, score in zip(result.nodes, result.node_reranker_scores):
            vocabulary_dict = dict(node)
            if 'embedding' in vocabulary_dict:
                del vocabulary_dict['embedding']
            vocabulary_dict['score'] = score
            vocabulary_dicts.append(vocabulary_dict)
        
        return vocabulary_dicts
    
    async def get_article_by_id(self, id: str) -> ArticleNode:
        result = await ArticleNode.get_by_id(self.driver, id)
        if 'embedding' in result:
            del result['embedding']
        if 'openai_embedding' in result:
            del result['openai_embedding']
        return result
    
    async def get_article_by_pubmedid(self, pubmedid: str) -> ArticleNode:
        result = await ArticleNode.get_by_pubmedid(self.driver, pubmedid)
        result = dict(result)
        if 'embedding' in result:
            del result['embedding']
        if 'openai_embedding' in result:
            del result['openai_embedding']
        return result
    
    async def get_article_by_ids(self, ids: list[str]) -> list[ArticleNode]:
        results = await ArticleNode.get_by_ids(self.driver, ids)
        results = [dict(result) for result in results]
        for result in results:
            if 'embedding' in result:
                del result['embedding'] 
            if 'openai_embedding' in result:
                del result['openai_embedding']
        return results
    
    async def get_article_by_pubmedids(self, pubmedids: list[str]) -> list[ArticleNode]:
        results = await ArticleNode.get_by_pubmedids(self.driver, pubmedids)
        results = [dict(result) for result in results]
        for result in results:
            if 'embedding' in result:
                del result['embedding']
            if 'openai_embedding' in result:
                del result['openai_embedding']
        return results
    
    async def get_article_by_vocabulary_ids(self, vocabulary_ids: list[str]) -> list[ArticleNode]:
        results = await ArticleNode.get_by_vocabulary_ids(self.driver, vocabulary_ids)
        results = [dict(result) for result in results]
        for result in results:
            if 'embedding' in result:
                del result['embedding']
            if 'openai_embedding' in result:
                del result['openai_embedding']
        return results
    
    async def get_sentence_by_id(self, id: str) -> SentenceNode:
        result = await SentenceNode.get_by_id(self.driver, id)
        result = dict(result)
        if 'embedding' in result:
            del result['embedding']
        if 'openai_embedding' in result:
            del result['openai_embedding']
        return result
    
    async def get_sentence_by_ids(self, ids: list[str]) -> list[SentenceNode]:
        results = await SentenceNode.get_by_ids(self.driver, ids)
        results = [dict(result) for result in results]
        return results
    
    async def get_sentence_by_vocabulary_id(self, vocabulary_id: str) -> SentenceNode:
        results = await SentenceNode.get_by_vocabulary_id(self.driver, vocabulary_id)
        results = [dict(result) for result in results]
        for result in results:
            if 'embedding' in result:
                del result['embedding']
            if 'openai_embedding' in result:
                del result['openai_embedding']
        return results
    
    async def get_vocabulary_by_id(self, id: str) -> VocabularyNode:
        result = await VocabularyNode.get_by_id(self.driver, id)
        result = dict(result)
        if 'embedding' in result:
            del result['embedding']
        return result
    
    async def get_vocabulary_by_ids(self, ids: list[str]) -> list[VocabularyNode]:
        results = await VocabularyNode.get_by_ids(self.driver, ids)
        results = [dict(result) for result in results]
        for result in results:
            if 'embedding' in result:
                del result['embedding']
        return results