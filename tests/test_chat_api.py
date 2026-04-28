from __future__ import annotations

import importlib
import sys
import types
import unittest

from fastapi.testclient import TestClient

from backend.cache import ConversationMemory, QueryCache


def _load_main_with_stub(query_handler):
    fake_rag_pipeline = types.ModuleType("backend.rag_pipeline")

    class StubLLMError(Exception):
        pass

    fake_rag_pipeline.query_rag = query_handler
    fake_rag_pipeline.get_collection_count = lambda: 1
    fake_rag_pipeline.build_db = lambda force_rebuild=False: None
    fake_rag_pipeline.LLMError = StubLLMError

    sys.modules["backend.rag_pipeline"] = fake_rag_pipeline
    sys.modules.pop("backend.main", None)

    import backend.main as main

    main = importlib.reload(main)
    main.cache = QueryCache(max_size=20, ttl_seconds=60, config_version="test")
    main.conversation_memory = ConversationMemory(max_turns=5, max_sessions=10, ttl_seconds=60)
    return main


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def stub_query_rag(question, campus=None, conversation_context="", pinned_context=None):
            call_index = len(self.calls) + 1
            self.calls.append(
                {
                    "question": question,
                    "campus": campus,
                    "conversation_context": conversation_context,
                    "pinned_context": pinned_context,
                }
            )
            return {
                "answer": f"stub-answer-{call_index}",
                "intent": "test_intent",
                "sources": ["https://example.com/source"],
                "campus": campus,
                "program": pinned_context.get("value") if pinned_context else None,
                "confidence": 0.91,
                "query_metadata": {
                    "domain": "admissions",
                    "task": "procedure",
                    "routing_target": "admissions",
                    "confidence": 0.91,
                    "entities": {"campus": campus},
                    "freshness": None,
                    "used_pinned_context": bool(pinned_context),
                    "decomposed": False,
                },
            }

        self.main = _load_main_with_stub(stub_query_rag)
        self.client = TestClient(self.main.app)
        self.addCleanup(self.client.close)

    def test_identical_request_hits_scoped_cache(self):
        payload = {
            "query": "How do I apply?",
            "campus": "KTR",
            "session_id": "session-a",
            "pinned_context": {"type": "program", "value": "B.Tech CSE"},
        }

        first = self.client.post("/chat", json=payload)
        second = self.client.post("/chat", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first.json()["response"], "stub-answer-1")
        self.assertEqual(second.json()["response"], "stub-answer-1")
        self.assertTrue(first.json()["query_metadata"]["used_pinned_context"])

    def test_different_session_does_not_reuse_cache(self):
        base_payload = {
            "query": "How do I apply?",
            "campus": "KTR",
        }

        first = self.client.post("/chat", json={**base_payload, "session_id": "session-a"})
        second = self.client.post("/chat", json={**base_payload, "session_id": "session-b"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.calls), 2)

    def test_different_campus_does_not_reuse_cache(self):
        base_payload = {
            "query": "What are the fees?",
            "session_id": "session-a",
        }

        first = self.client.post("/chat", json={**base_payload, "campus": "KTR"})
        second = self.client.post("/chat", json={**base_payload, "campus": "Ramapuram"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0]["campus"], "KTR")
        self.assertEqual(self.calls[1]["campus"], "Ramapuram")

    def test_follow_up_in_same_session_receives_conversation_context(self):
        first = self.client.post(
            "/chat",
            json={"query": "Tell me about hostel facilities", "campus": "KTR", "session_id": "session-a"},
        )
        second = self.client.post(
            "/chat",
            json={"query": "What about fees?", "campus": "KTR", "session_id": "session-a"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0]["conversation_context"], "")
        self.assertIn("Tell me about hostel facilities", self.calls[1]["conversation_context"])
        self.assertIn("stub-answer-1", self.calls[1]["conversation_context"])


if __name__ == "__main__":
    unittest.main()
