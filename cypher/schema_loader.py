#!/usr/bin/env python3
"""
schema_loader.py
Fast, memoised accessor for the Neo4j schema JSON and optional hints.

Usage
-----
from schema_loader import get_schema, get_schema_hints
schema = get_schema()       # dict, loaded once per process
hints = get_schema_hints()  # dict or None, loaded once per process
"""

from __future__ import annotations
import json, os
from pathlib import Path
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv

load_dotenv()
_SCHEMA_PATH = Path(os.environ["NEO4J_SCHEMA_PATH"]).expanduser().resolve()
_HINTS_PATH = Path(os.environ.get("SCHEMA_HINTS_PATH")).expanduser().resolve()
_EXAMPLE_QUERIES_PATH = Path(os.environ.get("EXAMPLES")).expanduser().resolve()

# ── internal cache --------------------------------------------------------
_cached_schema: Dict[str, Any] | None = None
_cached_hints: Dict[str, Any] | None = None
_hints_loaded: bool = False
_cached_example_queries: List[Dict[str, str]] | None = None

def get_schema() -> Dict[str, Any]:
    """Return the Neo4j schema as a JSON dict (cached)."""
    global _cached_schema
    if _cached_schema is None:
        with _SCHEMA_PATH.open() as f:
            _cached_schema = json.load(f)
    return _cached_schema

def get_schema_hints() -> Optional[Dict[str, Any]]:
    """Return schema hints/clarifications if available (cached)."""
    global _cached_hints, _hints_loaded
    if not _hints_loaded:
        _hints_loaded = True
        if _HINTS_PATH and _HINTS_PATH.exists():
            with _HINTS_PATH.open() as f:
                _cached_hints = json.load(f)
    return _cached_hints

def get_example_queries() -> List[Dict[str, str]]:
    """Return example queries if available (cached)."""
    global _cached_example_queries
    if _cached_example_queries is None:
        if _EXAMPLE_QUERIES_PATH.exists():
            with _EXAMPLE_QUERIES_PATH.open() as f:
                _cached_example_queries = json.load(f)
        else:
            _cached_example_queries = []
    return _cached_example_queries