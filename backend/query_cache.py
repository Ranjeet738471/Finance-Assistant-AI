"""Query result caching with TTL support for frequently executed queries.
Caches are tenant-scoped to prevent data leakage between tenants."""
import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any

from backend.config import DEFAULT_TENANT
from backend.logging_config import get_logger

log = get_logger(__name__)


class QueryCache:
    """LRU cache with TTL for query results."""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()

    def _make_key(self, sql: str, tenant_id: str) -> str:
        """Create a cache key from SQL and tenant."""
        key_data = f"{tenant_id}:{sql}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, sql: str, tenant_id: str = DEFAULT_TENANT) -> dict[str, Any] | None:
        """Get cached result if available and not expired."""
        key = self._make_key(sql, tenant_id)
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry["timestamp"] < self.ttl_seconds:
                    # Move to end (most recently used)
                    self._cache.move_to_end(key)
                    log.debug("query_cache_hit tenant_id=%s sql=%r", tenant_id, sql[:50])
                    return entry["data"]
                else:
                    # Expired
                    del self._cache[key]
                    log.debug("query_cache_expired tenant_id=%s", tenant_id)
            return None

    def set(self, sql: str, tenant_id: str, data: dict[str, Any]) -> None:
        """Cache query result."""
        key = self._make_key(sql, tenant_id)
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._cache.popitem(last=False)
            
            self._cache[key] = {
                "timestamp": time.time(),
                "data": data,
            }
            self._cache.move_to_end(key)
            log.debug("query_cache_set tenant_id=%s sql=%r", tenant_id, sql[:50])

    def invalidate_tenant(self, tenant_id: str) -> None:
        """Clear all cached entries for a tenant (e.g., after data reload)."""
        with self._lock:
            keys_to_remove = [
                k for k in self._cache.keys() 
                if self._cache[k]["data"].get("_tenant_id") == tenant_id
            ]
            for key in keys_to_remove:
                del self._cache[key]
            log.info("query_cache_invalidate tenant_id=%s removed=%d", tenant_id, len(keys_to_remove))

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            log.info("query_cache_cleared")

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
            }


# Global cache instance
_query_cache: QueryCache | None = None
_cache_lock = threading.Lock()


def get_query_cache() -> QueryCache:
    """Get or create the global query cache."""
    global _query_cache
    if _query_cache is None:
        with _cache_lock:
            if _query_cache is None:
                _query_cache = QueryCache(max_size=100, ttl_seconds=300)
    return _query_cache
