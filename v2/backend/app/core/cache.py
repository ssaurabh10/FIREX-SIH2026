"""
FIREX v2 High-Performance In-Memory Cache (Stage 10 Performance)
Provides fast TTL-based caching for expensive geospatial queries,
facility registries, and historical climatology lookups.
Bounded LRU store with proactive TTL eviction prevents memory exhaustion (M-3).
"""
import time
from collections import OrderedDict
from typing import Any, Optional, Tuple
from app.core.config import settings

class InMemoryCache:
    def __init__(self, default_ttl_seconds: int = 60, max_size: int = 2000):
        self.default_ttl = default_ttl_seconds
        self.max_size = max_size
        # key -> (value, expiry_epoch) in insertion/access order
        self._store: OrderedDict[str, Tuple[Any, float]] = OrderedDict()

    def _evict_expired(self) -> None:
        now = time.time()
        expired_keys = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired_keys:
            self._store.pop(k, None)

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
        self._store.move_to_end(key)
        return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if not settings.CACHE_ENABLED:
            return
        ttl_val = ttl if ttl is not None else self.default_ttl
        expiry = time.time() + ttl_val

        if key in self._store:
            self._store[key] = (value, expiry)
            self._store.move_to_end(key)
            return

        # Bound check: prune expired if approaching capacity
        if len(self._store) >= self.max_size:
            self._evict_expired()

        # If still at or over capacity, evict oldest entry (LRU)
        while len(self._store) >= self.max_size:
            self._store.popitem(last=False)

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
