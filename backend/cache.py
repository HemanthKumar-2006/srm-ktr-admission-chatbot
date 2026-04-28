"""
Lightweight LRU cache for the SRM Chatbot.
Caches identical queries to avoid redundant LLM + VectorDB calls.

Cache keys include a config_version so that stale entries from old
prompt/pipeline versions are never served after a code change.
"""

import hashlib
import json
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Mapping


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

    def _normalize_scope(self, scope: str | Mapping[str, Any]) -> str:
        if isinstance(scope, str):
            return json.dumps(
                {
                    "query": scope.lower().strip(),
                    "config_version": self._config_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            )

        normalized_scope = {
            "config_version": scope.get("config_version", self._config_version),
            "query": str(scope.get("query", "")).lower().strip(),
            "campus": str(scope.get("campus", "") or "").lower().strip(),
            "session_scope": str(scope.get("session_scope", "") or "").lower().strip(),
            "model": str(scope.get("model", "") or "").lower().strip(),
            "pinned_context": scope.get("pinned_context") or {},
        }
        return json.dumps(normalized_scope, sort_keys=True, separators=(",", ":"))

    def _make_key(self, scope: str | Mapping[str, Any]) -> str:
        normalized = self._normalize_scope(scope)
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, scope: str | Mapping[str, Any]) -> dict | None:
        key = self._make_key(scope)

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

    def set(self, scope: str | Mapping[str, Any], data: dict):
        key = self._make_key(scope)

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
                "key_fields": ["query", "campus", "session_scope", "model", "pinned_context", "config_version"],
            }

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0


class ConversationMemory:
    """
    Lightweight session-based conversation memory.
    Stores the last N turns per session for pronoun/context resolution.
    """

    def __init__(self, max_turns: int = 5, max_sessions: int = 200, ttl_seconds: int = 1800):
        self.max_turns = max_turns
        self.max_sessions = max_sessions
        self.ttl = ttl_seconds
        self._sessions: OrderedDict[str, dict] = OrderedDict()
        self._lock = Lock()

    def add_turn(self, session_id: str, question: str, answer: str):
        with self._lock:
            if session_id not in self._sessions:
                if len(self._sessions) >= self.max_sessions:
                    self._sessions.popitem(last=False)
                self._sessions[session_id] = {"turns": [], "updated": time.time()}

            session = self._sessions[session_id]
            session["turns"].append({"q": question, "a": answer[:200]})
            if len(session["turns"]) > self.max_turns:
                session["turns"] = session["turns"][-self.max_turns:]
            session["updated"] = time.time()
            self._sessions.move_to_end(session_id)

    def get_context(self, session_id: str) -> str:
        with self._lock:
            if session_id not in self._sessions:
                return ""

            session = self._sessions[session_id]
            if time.time() - session["updated"] > self.ttl:
                del self._sessions[session_id]
                return ""

            parts = []
            for turn in session["turns"][-3:]:
                parts.append(f"User: {turn['q']}\nAssistant: {turn['a']}")
            return "\n\n".join(parts)

    def clear_session(self, session_id: str):
        with self._lock:
            self._sessions.pop(session_id, None)


_CACHE_VERSION = "v4.0-kg-hierarchical"

cache = QueryCache(max_size=500, ttl_seconds=3600, config_version=_CACHE_VERSION)
conversation_memory = ConversationMemory()
