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
import sys
from collections.abc import Coroutine
from typing import Any

from neo4j import AsyncGraphDatabase, EagerResult
from typing_extensions import LiteralString

from .driver import GraphDriver, GraphDriverSession, GraphProvider

logger = logging.getLogger(__name__)


class Neo4jDriver(GraphDriver):
    provider = GraphProvider.NEO4J

    def __init__(self, uri: str, user: str | None, password: str | None, database: str = 'neo4j'):
        super().__init__()
        self.client = AsyncGraphDatabase.driver(
            uri=uri,
            auth=(user or '', password or ''),
            connection_timeout=60
        )
        self._database = database

    async def execute_query(self, cypher_query_: LiteralString, **kwargs: Any) -> EagerResult:
        # Check if database_ is provided in kwargs.
        # If not populated, set the value to retain backwards compatibility
        params = kwargs.pop('params', None)
        if params is None:
            params = {}
        params.setdefault('database_', self._database)

        print(f"[Neo4jDriver] Executing query: {cypher_query_}", file=sys.stderr)
        print(f"[Neo4jDriver] Parameters: {params}", file=sys.stderr)
        print(f"[Neo4jDriver] Database: {self._database}", file=sys.stderr)
        print(f"[Neo4jDriver] Additional kwargs: {kwargs}", file=sys.stderr)

        try:
            result = await self.client.execute_query(cypher_query_, parameters_=params, **kwargs)
            print(f"[Neo4jDriver] Query executed successfully", file=sys.stderr)
            print(f"[Neo4jDriver] Result type: {type(result)}", file=sys.stderr)
            if hasattr(result, '__len__'):
                print(f"[Neo4jDriver] Result length: {len(result)}", file=sys.stderr)
            return result
        except Exception as e:
            error_msg = f'Error executing Neo4j query: {e}\nQuery: {cypher_query_}\nParams: {params}'
            print(f"[Neo4jDriver] {error_msg}", file=sys.stderr)
            print(f"[Neo4jDriver] Exception type: {type(e).__name__}", file=sys.stderr)
            print(f"[Neo4jDriver] Exception details: {str(e)}", file=sys.stderr)
            import traceback
            print(f"[Neo4jDriver] Traceback: {traceback.format_exc()}", file=sys.stderr)
            logger.error(error_msg)
            raise

    def session(self, database: str | None = None) -> GraphDriverSession:
        _database = database or self._database
        return self.client.session(database=_database)  # type: ignore

    async def close(self) -> None:
        return await self.client.close()

    def delete_all_indexes(self) -> Coroutine[Any, Any, EagerResult]:
        return self.client.execute_query(
            'CALL db.indexes() YIELD name DROP INDEX name',
        )
