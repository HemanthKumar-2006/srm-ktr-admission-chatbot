"""
Lightweight LRU cache for the SRM Chatbot.
Caches identical queries to avoid redundant LLM + VectorDB calls.

Cache keys include a config_version so that stale entries from old
prompt/pipeline versions are never served after a code change.
"""

import hashlib
import time
from collections import OrderedDict
from threading import Lock


class QueryCache:
    """
    Thread-safe LRU cache for chat responses.

    - max_size:  Maximum number of cached entries
    - ttl_seconds: Time-to-live per entry (default 1 hour)
    - config_version: Arbitrary string mixed into every key so a
      prompt/pipeline change automatically invalidates old entries.
    """

    def __init__(
        self,
        max_size: int = 500,
        ttl_seconds: int = 3600,
        config_version: str = "1",
    ):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._config_version = config_version
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, query: str) -> str:
        normalized = f"{self._config_version}:{query.lower().strip()}"
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, query: str) -> dict | None:
        key = self._make_key(query)

        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]

            if time.time() - entry["timestamp"] > self.ttl:
                del self._cache[key]
                self._misses += 1
                return None

            self._cache.move_to_end(key)
            self._hits += 1
            return entry["data"]

    def set(self, query: str, data: dict):
        key = self._make_key(query)

        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = {"data": data, "timestamp": time.time()}
            else:
                if len(self._cache) >= self.max_size:
                    self._cache.popitem(last=False)
                self._cache[key] = {"data": data, "timestamp": time.time()}

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{(self._hits / total * 100):.1f}%" if total > 0 else "0%",
            }

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0


_CACHE_VERSION = "v2.1-abbrev-reformulation-fallback"

cache = QueryCache(max_size=500, ttl_seconds=3600, config_version=_CACHE_VERSION)
