import os
import sys

from backend.rag_pipeline import detect_intent_and_entities, model, collection, hybrid_score

def test_query():
    question = "What is the fee structure for Btech"
    print(f"🔍 Testing RAG query: {question}")
    analysis = detect_intent_and_entities(question)
    
    where_filter = {}
    if analysis["entities"].get("campus"):
        where_filter["campus"] = analysis["entities"]["campus"]
    
    intent_map = {
        "fee_structure": "fee_structure",
        "admission_process": "admission",
        "hostel_info": "hostel",
        "course_details": "course_info",
        "campus_life": "campus_life",
        "eligibility": "admission",
    }
    
    target_cat = intent_map.get(analysis["intent"])
    if target_cat:
        where_filter["category"] = target_cat

    emb = model.encode(question).tolist()

    results = collection.query(
        query_embeddings=[emb],
        n_results=25,
        where=where_filter if where_filter else None,
        include=["documents", "metadatas", "distances"]
    )

    if not results.get("documents", [[]])[0]:
        print("⚠️ [RAG] Metadata filter returned 0 results. Falling back to global search.")
        results = collection.query(
            query_embeddings=[emb],
            n_results=25,
            where=None,
            include=["documents", "metadatas", "distances"]
        )

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    filtered = [
        (d, m, dist)
        for d, m, dist in zip(docs, metas, distances)
        if dist < 1.5
    ]
    
    q_words = set(question.lower().split())

    def hybrid_score(doc, dist):
        doc_words = set(doc.lower().split())
        overlap = len(q_words & doc_words)
        return overlap - dist

    filtered.sort(
        key=lambda x: hybrid_score(x[0], x[2]),
        reverse=True
    )

    top_docs = [x[0] for x in filtered[:5]]
    top_metas = [x[1] for x in filtered[:5]]
    
    print("\n--- TOP DOCS ---")
    for i, doc in enumerate(top_docs):
        print(f"[{i}] Meta: {top_metas[i]}")
        print(f"Doc: {doc[:300]}...\n")

if __name__ == "__main__":
    test_query()
