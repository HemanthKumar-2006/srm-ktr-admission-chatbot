import unittest

from backend.cache import QueryCache


class QueryCacheTests(unittest.TestCase):
    def test_cache_scope_includes_campus_session_and_model(self):
        cache = QueryCache(max_size=10, ttl_seconds=60, config_version="test")
        scope = {
            "query": "What are the fees?",
            "campus": "KTR",
            "session_scope": "session-a",
            "model": "gemma3",
            "config_version": "test:v1",
            "pinned_context": {},
        }
        cache.set(scope, {"response": "fees-a"})

        self.assertEqual(cache.get(scope)["response"], "fees-a")
        self.assertIsNone(cache.get({**scope, "campus": "Ramapuram"}))
        self.assertIsNone(cache.get({**scope, "session_scope": "session-b"}))
        self.assertIsNone(cache.get({**scope, "model": "gemma4"}))

    def test_cache_scope_includes_pinned_context(self):
        cache = QueryCache(max_size=10, ttl_seconds=60, config_version="test")
        base_scope = {
            "query": "Tell me more",
            "campus": "KTR",
            "session_scope": "session-a",
            "model": "gemma3",
            "config_version": "test:v1",
        }
        cache.set(
            {
                **base_scope,
                "pinned_context": {"type": "program", "value": "B.Tech CSE"},
            },
            {"response": "program-scoped"},
        )

        self.assertEqual(
            cache.get(
                {
                    **base_scope,
                    "pinned_context": {"type": "program", "value": "B.Tech CSE"},
                }
            )["response"],
            "program-scoped",
        )
        self.assertIsNone(
            cache.get(
                {
                    **base_scope,
                    "pinned_context": {"type": "department", "value": "CSE"},
                }
            )
        )

    def test_stats_report_scoped_key_fields(self):
        cache = QueryCache(max_size=5, ttl_seconds=60, config_version="test")
        stats = cache.stats()
        self.assertIn("campus", stats["key_fields"])
        self.assertIn("session_scope", stats["key_fields"])
        self.assertIn("pinned_context", stats["key_fields"])


if __name__ == "__main__":
    unittest.main()
