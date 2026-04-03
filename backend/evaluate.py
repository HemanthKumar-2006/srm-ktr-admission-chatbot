"""
SRM Chatbot Evaluation Pipeline v2
===================================
Measures chatbot quality using RAGAS-inspired metrics.

Metrics:
  1. Intent Accuracy   -- Did the system detect the correct intent?
  2. Keyword Recall    -- Did the answer contain expected keywords?
  3. Item Completeness -- Did the answer contain all expected items? (listing queries)
  4. Source Citation    -- Did the answer include source references?
  5. Faithfulness      -- Did the answer avoid "I don't know" when it shouldn't?
  6. Hallucination     -- Did the answer contain things it should NOT contain?
  7. Response Time     -- Latency per query

Usage:
  python backend/evaluate.py
"""

import json
import re
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

_INTENT_EQUIVALENCES = {
    "factual": {"factual", "general_query", "admission_query"},
    "general_query": {"factual", "general_query", "listing", "comparison"},
    "procedural": {"procedural", "how_to_apply"},
    "listing": {"listing"},
    "comparison": {"comparison"},
    "person_lookup": {"person_lookup"},
}


def score_intent_accuracy(expected: str, actual: str) -> float:
    if expected == "general_query":
        return 1.0
    equivalents = _INTENT_EQUIVALENCES.get(expected, {expected})
    return 1.0 if actual in equivalents else 0.0


def score_keyword_recall(expected_keywords: list[str], answer: str) -> float:
    if not expected_keywords:
        return 1.0

    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return round(found / len(expected_keywords), 2)


def score_item_completeness(expected_items: list[str], answer: str) -> float:
    """For listing queries: what fraction of expected items appeared in the answer?"""
    if not expected_items:
        return 1.0

    answer_lower = answer.lower()
    found = sum(1 for item in expected_items if item.lower() in answer_lower)
    return round(found / len(expected_items), 2)


def score_citation(answer: str, sources: list) -> float:
    """1.0 if answer includes citations or API returned source URLs."""
    if sources:
        return 1.0
    citation_signals = ["[1]", "[2]", "Sources:", "http"]
    return 1.0 if any(sig in answer for sig in citation_signals) else 0.0


def score_faithfulness(answer: str) -> float:
    refusal_phrases = [
        "i don't have",
        "i couldn't find",
        "no relevant information",
        "api error",
        "llm not running",
        "rag error",
        "technical issue",
    ]
    answer_lower = answer.lower()
    for phrase in refusal_phrases:
        if phrase in answer_lower:
            return 0.0
    return 1.0


def score_hallucination(should_not_contain: list[str], answer: str) -> float:
    """1.0 if answer does NOT contain any forbidden terms. 0.0 if it does."""
    if not should_not_contain:
        return 1.0

    answer_lower = answer.lower()
    for term in should_not_contain:
        if term.lower() in answer_lower:
            return 0.0
    return 1.0


def score_answer_quality(answer: str) -> float:
    """Heuristic quality score based on answer structure and length."""
    score = 0.5
    if len(answer) > 100:
        score += 0.2
    if re.search(r"[-*]\s+\w", answer):
        score += 0.15
    if re.search(r"\d+[.)\s]", answer):
        score += 0.15
    return min(score, 1.0)


# ================= MAIN EVALUATION =================

def run_evaluation():
    test_data = load_test_data()
    results = []

    print("=" * 60)
    print("  SRM CHATBOT EVALUATION PIPELINE v2")
    print("=" * 60)
    print(f"  Test queries: {len(test_data)}")
    print(f"  API endpoint: {API_URL}")
    print("=" * 60)

    totals = {
        "intent_accuracy": 0,
        "keyword_recall": 0,
        "item_completeness": 0,
        "citation_score": 0,
        "faithfulness": 0,
        "hallucination_free": 0,
        "answer_quality": 0,
        "latency": 0,
    }

    item_completeness_count = 0

    for i, test in enumerate(test_data):
        q = test["question"]
        print(f"\n[{i+1}/{len(test_data)}] {q}")

        api_res = query_api(q)

        answer = api_res.get("response", "")
        detected_intent = api_res.get("intent", "unknown")
        latency = api_res.get("latency_seconds", -1)
        sources = api_res.get("sources", [])

        intent_acc = score_intent_accuracy(test["expected_intent"], detected_intent)
        kw_recall = score_keyword_recall(test.get("expected_keywords", []), answer)
        citation = score_citation(answer, sources)
        faithful = score_faithfulness(answer)
        hallucination = score_hallucination(test.get("should_not_contain", []), answer)
        quality = score_answer_quality(answer)

        expected_items = test.get("expected_items", [])
        item_complete = score_item_completeness(expected_items, answer)
        if expected_items:
            totals["item_completeness"] += item_complete
            item_completeness_count += 1

        totals["intent_accuracy"] += intent_acc
        totals["keyword_recall"] += kw_recall
        totals["citation_score"] += citation
        totals["faithfulness"] += faithful
        totals["hallucination_free"] += hallucination
        totals["answer_quality"] += quality
        totals["latency"] += max(latency, 0)

        result = {
            "id": test["id"],
            "question": q,
            "expected_intent": test["expected_intent"],
            "detected_intent": detected_intent,
            "intent_correct": intent_acc == 1.0,
            "keyword_recall": kw_recall,
            "item_completeness": item_complete if expected_items else None,
            "has_citations": citation == 1.0,
            "is_faithful": faithful == 1.0,
            "hallucination_free": hallucination == 1.0,
            "answer_quality": quality,
            "latency_seconds": latency,
            "answer_preview": answer[:300],
        }

        results.append(result)

        status = "PASS" if intent_acc == 1.0 and kw_recall >= 0.5 and faithful == 1.0 else "FAIL"
        print(f"  [{status}] Intent: {detected_intent} (expected: {test['expected_intent']}) | "
              f"KW: {kw_recall:.0%} | Citation: {'Y' if citation else 'N'} | "
              f"Halluc-free: {'Y' if hallucination else 'N'} | Latency: {latency}s")

    # ================= SUMMARY =================
    n = len(test_data)

    summary = {
        "total_queries": n,
        "intent_accuracy": round(totals["intent_accuracy"] / n * 100, 1),
        "avg_keyword_recall": round(totals["keyword_recall"] / n * 100, 1),
        "item_completeness": round(
            totals["item_completeness"] / item_completeness_count * 100, 1
        ) if item_completeness_count > 0 else None,
        "citation_rate": round(totals["citation_score"] / n * 100, 1),
        "faithfulness_rate": round(totals["faithfulness"] / n * 100, 1),
        "hallucination_free_rate": round(totals["hallucination_free"] / n * 100, 1),
        "avg_answer_quality": round(totals["answer_quality"] / n * 100, 1),
        "avg_latency_seconds": round(totals["latency"] / n, 2),
    }

    print("\n" + "=" * 60)
    print("  EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Intent Accuracy:        {summary['intent_accuracy']}%")
    print(f"  Keyword Recall:         {summary['avg_keyword_recall']}%")
    if summary["item_completeness"] is not None:
        print(f"  Item Completeness:      {summary['item_completeness']}%")
    print(f"  Citation Rate:          {summary['citation_rate']}%")
    print(f"  Faithfulness Rate:      {summary['faithfulness_rate']}%")
    print(f"  Hallucination-Free:     {summary['hallucination_free_rate']}%")
    print(f"  Avg Answer Quality:     {summary['avg_answer_quality']}%")
    print(f"  Avg Latency:            {summary['avg_latency_seconds']}s")
    print("=" * 60)

    output = {
        "summary": summary,
        "results": results,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDetailed results saved to: {RESULTS_PATH}")

    return summary


if __name__ == "__main__":
    run_evaluation()
