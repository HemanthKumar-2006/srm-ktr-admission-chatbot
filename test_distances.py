from backend.rag_pipeline import model, collection, detect_intent_and_entities
import json

def test_query(question):
    print(f"\n--- Testing Query: '{question}' ---")
    analysis = detect_intent_and_entities(question)
    print(f"Analysis: {analysis}")
    emb = model.encode(question).tolist()
    
    where_filter = None # Ignore filters for a moment to just see distances
    
    results = collection.query(
        query_embeddings=[emb],
        n_results=5,
        include=["documents", "metadatas", "distances"]
    )
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    
    for i in range(len(docs)):
        print(f"[{i}] Dist: {distances[i]:.4f} | Meta: {metas[i]}")
        print(f"    Doc: {docs[i][:150]}...\n")

test_query("What is the fees for BTech Degree in SRM KTR")
test_query("What are the courses available in SRM")
