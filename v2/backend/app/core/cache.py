"""
FIREX v2 High-Performance In-Memory Cache (Stage 10 Performance)
Provides fast TTL-based caching for expensive geospatial queries,
facility registries, and historical climatology lookups.
"""
import time
from typing import Any, Optional, Dict, Tuple
from app.core.config import settings

class InMemoryCache:
    def __init__(self, default_ttl_seconds: int = 60):
        self.default_ttl = default_ttl_seconds
        # key -> (value, expiry_epoch)
        self._store: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        if not settings.CACHE_ENABLED:
            return None
        item = self._store.get(key)
        if not item:
            return None
        val, expiry = item
        if time.time() > expiry:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if not settings.CACHE_ENABLED:
            return
        ttl_val = ttl if ttl is not None else self.default_ttl
        expiry = time.time() + ttl_val
        self._store[key] = (value, expiry)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def size(self) -> int:
        now = time.time()
        # count non-expired
        return sum(1 for _, (_, exp) in self._store.items() if exp > now)

cache = InMemoryCache(default_ttl_seconds=settings.CACHE_DEFAULT_TTL_SECONDS)
