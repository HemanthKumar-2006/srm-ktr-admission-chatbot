"""
SRM Chatbot Evaluation Pipeline
================================
Measures chatbot quality using RAGAS-inspired metrics without external dependencies.

Metrics:
  1. Intent Accuracy   — Did the system detect the correct intent?
  2. Keyword Recall    — Did the answer contain expected keywords?
  3. Source Citation    — Did the answer include source references?
  4. Faithfulness      — Did the answer avoid "I don't know" when it shouldn't?
  5. Response Time     — Latency per query

Usage:
  python backend/evaluate.py
"""

import json
import time
import requests
from pathlib import Path
from backend.settings import SETTINGS

# ================= CONFIG =================

API_URL = SETTINGS.eval_api_url
TEST_DATA_PATH = Path("data/eval/test_queries.json")
RESULTS_PATH = Path("data/eval/eval_results.json")


def load_test_data() -> list[dict]:
    with open(TEST_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def query_api(question: str) -> dict:
    """Send a query to the chatbot API and return the full response."""
    try:
        start = time.time()
        res = requests.post(
            API_URL,
            json={"query": question},
            timeout=60,
        )
        latency = time.time() - start

        data = res.json()
        data["latency_seconds"] = round(latency, 2)
        return data

    except Exception as e:
        return {
            "response": f"API Error: {e}",
            "intent": "error",
            "latency_seconds": -1,
        }


# ================= METRICS =================

def score_intent_accuracy(expected: str, actual: str) -> float:
    """1.0 if intents match, 0.0 otherwise."""
    if expected == "general_query":
        return 1.0  # Don't penalize general queries
    return 1.0 if expected == actual else 0.0


def score_keyword_recall(expected_keywords: list[str], answer: str) -> float:
    """Fraction of expected keywords found in the answer (case-insensitive)."""
    if not expected_keywords:
        return 1.0  # No keywords to check (e.g., small talk)

    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return round(found / len(expected_keywords), 2)


def score_citation(answer: str) -> float:
    """1.0 if answer contains source citations, 0.0 otherwise."""
    citation_signals = ["[1]", "[2]", "Sources:", "http"]
    return 1.0 if any(sig in answer for sig in citation_signals) else 0.0


def score_faithfulness(answer: str) -> float:
    """
    Penalize if the answer refuses to answer when it shouldn't.
    Returns 0.0 if it's an unhelpful refusal, 1.0 otherwise.
    """
    refusal_phrases = [
        "i don't have",
        "i couldn't find",
        "no relevant information",
        "api error",
        "llm not running",
        "rag error",
    ]
    answer_lower = answer.lower()
    for phrase in refusal_phrases:
        if phrase in answer_lower:
            return 0.0
    return 1.0


# ================= MAIN EVALUATION =================

def run_evaluation():
    test_data = load_test_data()
    results = []

    print("=" * 60)
    print("  SRM CHATBOT EVALUATION PIPELINE")
    print("=" * 60)
    print(f"  Test queries: {len(test_data)}")
    print(f"  API endpoint: {API_URL}")
    print("=" * 60)

    totals = {
        "intent_accuracy": 0,
        "keyword_recall": 0,
        "citation_score": 0,
        "faithfulness": 0,
        "latency": 0,
    }

    for i, test in enumerate(test_data):
        q = test["question"]
        print(f"\n[{i+1}/{len(test_data)}] {q}")

        api_res = query_api(q)

        answer = api_res.get("response", "")
        detected_intent = api_res.get("intent", "unknown")
        latency = api_res.get("latency_seconds", -1)

        # Score each metric
        intent_acc = score_intent_accuracy(test["expected_intent"], detected_intent)
        kw_recall = score_keyword_recall(test["expected_keywords"], answer)
        citation = score_citation(answer)
        faithful = score_faithfulness(answer)

        totals["intent_accuracy"] += intent_acc
        totals["keyword_recall"] += kw_recall
        totals["citation_score"] += citation
        totals["faithfulness"] += faithful
        totals["latency"] += max(latency, 0)

        result = {
            "id": test["id"],
            "question": q,
            "expected_intent": test["expected_intent"],
            "detected_intent": detected_intent,
            "intent_correct": intent_acc == 1.0,
            "keyword_recall": kw_recall,
            "has_citations": citation == 1.0,
            "is_faithful": faithful == 1.0,
            "latency_seconds": latency,
            "answer_preview": answer[:200],
        }

        results.append(result)

        status = "✅" if intent_acc == 1.0 and kw_recall >= 0.5 else "⚠️"
        print(f"  {status} Intent: {detected_intent} (expected: {test['expected_intent']}) | "
              f"KW: {kw_recall:.0%} | Citation: {'✓' if citation else '✗'} | "
              f"Latency: {latency}s")

    # ================= SUMMARY =================
    n = len(test_data)

    summary = {
        "total_queries": n,
        "intent_accuracy": round(totals["intent_accuracy"] / n * 100, 1),
        "avg_keyword_recall": round(totals["keyword_recall"] / n * 100, 1),
        "citation_rate": round(totals["citation_score"] / n * 100, 1),
        "faithfulness_rate": round(totals["faithfulness"] / n * 100, 1),
        "avg_latency_seconds": round(totals["latency"] / n, 2),
    }

    print("\n" + "=" * 60)
    print("  EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Intent Accuracy:    {summary['intent_accuracy']}%")
    print(f"  Keyword Recall:     {summary['avg_keyword_recall']}%")
    print(f"  Citation Rate:      {summary['citation_rate']}%")
    print(f"  Faithfulness Rate:  {summary['faithfulness_rate']}%")
    print(f"  Avg Latency:        {summary['avg_latency_seconds']}s")
    print("=" * 60)

    # Save detailed results
    output = {
        "summary": summary,
        "results": results,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n📊 Detailed results saved to: {RESULTS_PATH}")

    return summary


if __name__ == "__main__":
    run_evaluation()
