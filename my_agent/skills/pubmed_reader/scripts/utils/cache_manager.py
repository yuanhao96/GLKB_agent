#!/usr/bin/env python3
"""
Cache manager for PubMed Reader skill.
Provides intelligent caching of API responses to reduce requests and improve performance.
"""

import os
import json
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any, Dict
import threading

logger = logging.getLogger(__name__)


class CacheManager:
    """
    File-based cache manager for API responses.

    Features:
    - TTL-based expiration
    - Automatic cleanup of expired entries
    - Thread-safe operations
    - Configurable cache directory
    """

    # Default TTL values (in seconds)
    DEFAULT_TTL = 86400  # 24 hours
    TTL_METADATA = 2592000  # 30 days (article metadata rarely changes)
    TTL_SEARCH = 3600  # 1 hour (new articles published frequently)
    TTL_CITATIONS = 604800  # 7 days (citation counts update periodically)
    TTL_FULLTEXT = 2592000  # 30 days (static once published)

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize cache manager.

        Args:
            cache_dir: Cache directory path (defaults to data/cache)
        """
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            # Default to data/cache relative to skill root
            skill_root = Path(__file__).parent.parent.parent
            self.cache_dir = skill_root / "data" / "cache"

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        # Cache statistics
        self._stats = {
            'hits': 0,
            'misses': 0,
            'writes': 0,
            'expired': 0
        }

    def _get_cache_key(self, key: str) -> str:
        """
        Generate cache filename from key.

        Args:
            key: Original cache key

        Returns:
            MD5 hash suitable for filename
        """
        return hashlib.md5(key.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        """Get full path for cache file."""
        cache_key = self._get_cache_key(key)
        return self.cache_dir / f"{cache_key}.json"

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        cache_path = self._get_cache_path(key)

        with self._lock:
            if not cache_path.exists():
                self._stats['misses'] += 1
                return None

            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)

                # Check expiration
                expires_at = datetime.fromisoformat(cached.get('expires_at', '1970-01-01'))
                if datetime.now() > expires_at:
                    self._stats['expired'] += 1
                    cache_path.unlink()  # Delete expired entry
                    return None

                self._stats['hits'] += 1
                return cached.get('data')

            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Cache read error for {key}: {e}")
                self._stats['misses'] += 1
                return None

    def set(self, key: str, data: Any, ttl: Optional[int] = None) -> bool:
        """
        Store value in cache.

        Args:
            key: Cache key
            data: Data to cache (must be JSON-serializable)
            ttl: Time-to-live in seconds (defaults to DEFAULT_TTL)

        Returns:
            True if successful, False otherwise
        """
        if ttl is None:
            ttl = self.DEFAULT_TTL

        cache_path = self._get_cache_path(key)
        expires_at = datetime.now() + timedelta(seconds=ttl)

        cached = {
            'key': key,
            'data': data,
            'created_at': datetime.now().isoformat(),
            'expires_at': expires_at.isoformat(),
            'ttl': ttl
        }

        with self._lock:
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cached, f, indent=2, default=str)
                self._stats['writes'] += 1
                return True

            except (IOError, TypeError) as e:
                logger.error(f"Cache write error for {key}: {e}")
                return False

    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False if not found
        """
        cache_path = self._get_cache_path(key)

        with self._lock:
            if cache_path.exists():
                cache_path.unlink()
                return True
            return False

    def clear(self, older_than: Optional[int] = None) -> int:
        """
        Clear cache entries.

        Args:
            older_than: If specified, only clear entries older than this many seconds

        Returns:
            Number of entries cleared
        """
        cleared = 0
        cutoff = None
        if older_than:
            cutoff = datetime.now() - timedelta(seconds=older_than)

        with self._lock:
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    if cutoff:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            cached = json.load(f)
                        created = datetime.fromisoformat(cached.get('created_at', '2099-01-01'))
                        if created >= cutoff:
                            continue

                    cache_file.unlink()
                    cleared += 1

                except (json.JSONDecodeError, IOError):
                    # Delete corrupted cache files
                    cache_file.unlink()
                    cleared += 1

        return cleared

    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.

        Returns:
            Number of entries removed
        """
        removed = 0
        now = datetime.now()

        with self._lock:
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached = json.load(f)

                    expires_at = datetime.fromisoformat(cached.get('expires_at', '1970-01-01'))
                    if now > expires_at:
                        cache_file.unlink()
                        removed += 1

                except (json.JSONDecodeError, IOError):
                    # Delete corrupted files
                    cache_file.unlink()
                    removed += 1

        return removed

    def get_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dict with hits, misses, writes, expired counts
        """
        return self._stats.copy()

    def get_size(self) -> Dict[str, Any]:
        """
        Get cache size information.

        Returns:
            Dict with entry count and total size in bytes
        """
        entries = list(self.cache_dir.glob("*.json"))
        total_bytes = sum(f.stat().st_size for f in entries)

        return {
            'entries': len(entries),
            'bytes': total_bytes,
            'mb': round(total_bytes / (1024 * 1024), 2)
        }


# =============================================================================
# Specialized Cache Functions
# =============================================================================

# Global cache instance
_cache: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """Get or create global cache instance."""
    global _cache
    if _cache is None:
        cache_dir = os.environ.get('PUBMED_CACHE_DIR')
        _cache = CacheManager(cache_dir)
    return _cache


def cache_search_results(query: str, results: Any) -> bool:
    """
    Cache search results.

    Args:
        query: Search query
        results: Search results

    Returns:
        True if cached successfully
    """
    key = f"search:{query}"
    return get_cache().set(key, results, ttl=CacheManager.TTL_SEARCH)


def get_cached_search(query: str) -> Optional[Any]:
    """
    Get cached search results.

    Args:
        query: Search query

    Returns:
        Cached results or None
    """
    key = f"search:{query}"
    return get_cache().get(key)


def cache_article_metadata(pmid: str, metadata: Any) -> bool:
    """
    Cache article metadata.

    Args:
        pmid: PubMed ID
        metadata: Article metadata

    Returns:
        True if cached successfully
    """
    key = f"metadata:{pmid}"
    return get_cache().set(key, metadata, ttl=CacheManager.TTL_METADATA)


def get_cached_metadata(pmid: str) -> Optional[Any]:
    """
    Get cached article metadata.

    Args:
        pmid: PubMed ID

    Returns:
        Cached metadata or None
    """
    key = f"metadata:{pmid}"
    return get_cache().get(key)


def cache_fulltext(pmid: str, fulltext: Any) -> bool:
    """
    Cache full text content.

    Args:
        pmid: PubMed ID or PMC ID
        fulltext: Full text data

    Returns:
        True if cached successfully
    """
    key = f"fulltext:{pmid}"
    return get_cache().set(key, fulltext, ttl=CacheManager.TTL_FULLTEXT)


def get_cached_fulltext(pmid: str) -> Optional[Any]:
    """
    Get cached full text.

    Args:
        pmid: PubMed ID or PMC ID

    Returns:
        Cached full text or None
    """
    key = f"fulltext:{pmid}"
    return get_cache().get(key)


def cache_citations(pmid: str, citations: Any) -> bool:
    """
    Cache citation data.

    Args:
        pmid: PubMed ID
        citations: Citation data

    Returns:
        True if cached successfully
    """
    key = f"citations:{pmid}"
    return get_cache().set(key, citations, ttl=CacheManager.TTL_CITATIONS)


def get_cached_citations(pmid: str) -> Optional[Any]:
    """
    Get cached citations.

    Args:
        pmid: PubMed ID

    Returns:
        Cached citations or None
    """
    key = f"citations:{pmid}"
    return get_cache().get(key)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test cache manager."""
    print("Testing Cache Manager...\n")

    # Create temporary cache for testing
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(tmpdir)

        # Test basic operations
        print("1. Testing basic set/get:")
        cache.set("test_key", {"value": 123}, ttl=3600)
        result = cache.get("test_key")
        assert result == {"value": 123}, "Basic get failed"
        print(f"   Set and retrieved: {result}")

        # Test cache miss
        print("\n2. Testing cache miss:")
        result = cache.get("nonexistent_key")
        assert result is None, "Should return None for missing key"
        print(f"   Missing key returned: {result}")

        # Test expiration
        print("\n3. Testing expiration:")
        cache.set("short_ttl", {"data": "expires"}, ttl=1)
        import time
        time.sleep(1.5)
        result = cache.get("short_ttl")
        assert result is None, "Expired entry should return None"
        print(f"   Expired entry returned: {result}")

        # Test statistics
        print("\n4. Testing statistics:")
        stats = cache.get_stats()
        print(f"   Stats: {stats}")

        # Test size info
        print("\n5. Testing size info:")
        size = cache.get_size()
        print(f"   Size: {size}")

        # Test cleanup
        print("\n6. Testing cleanup:")
        for i in range(5):
            cache.set(f"test_{i}", {"i": i}, ttl=3600)
        cleared = cache.clear()
        print(f"   Cleared {cleared} entries")

        print("\n All cache tests passed!")


if __name__ == "__main__":
    main()
