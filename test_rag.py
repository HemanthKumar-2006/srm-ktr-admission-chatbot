from backend.rag_pipeline import query_rag
import sys

def test_query():
    try:
        print("🔍 Testing RAG query...")
        question = "What is the fee structure for Btech"
        answer = query_rag(question)
        print(f"\nAnswer:\n{answer}")
    except Exception as e:
        print(f"❌ Error during test: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_query()
