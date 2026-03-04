import json
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
import requests
import re

# ================= CONFIG =================
DATA_PATH = Path("data/raw/srm_data.json")

# ================= MODELS =================
model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path="vector_db")
collection = client.get_or_create_collection("srm_data")

# ================= SMALL TALK =================
SMALL_TALK = {"hi", "hello", "hey", "good morning", "good evening"}

def is_small_talk(q: str) -> bool:
    q = q.lower().strip()
    return any(greet in q for greet in SMALL_TALK)

# ================= HELPER CLEAN =================
def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# ================= BUILD VECTOR DB =================
def build_db():
    global collection

    if not DATA_PATH.exists():
        print("❌ Run scraper first")
        return

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        docs = json.load(f)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80
    )

    all_chunks = []
    all_metadata = []

    for d in docs:
        content = clean_text(d["content"])

        # skip junk pages
        if len(content) < 300:
            continue

        chunks = splitter.split_text(content)

        # Extract enriched metadata fields (with fallbacks for old format)
        source_url = d.get("url", "")
        page_title = d.get("title", "Untitled Page")
        category = d.get("category", "general")

        for chunk in chunks:
            if len(chunk) < 80:
                continue

            all_chunks.append(chunk)
            all_metadata.append({
                "source": source_url,
                "title": page_title,
                "category": category,
            })

    print(f"[INFO] Clean chunks: {len(all_chunks)}")

    # Count category distribution across chunks
    cat_counts = {}
    for m in all_metadata:
        cat = m["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    print(f"[INFO] Chunk categories: {json.dumps(cat_counts, indent=2)}")

    # reset collection
    try:
        client.delete_collection("srm_data")
    except Exception:
        pass

    collection = client.get_or_create_collection("srm_data")

    print("[INFO] Creating embeddings...")

    embeddings = model.encode(
        all_chunks,
        batch_size=64,
        show_progress_bar=True
    ).tolist()

    # SAFE BATCH INSERT
    BATCH_SIZE = 4000
    total = len(all_chunks)

    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)

        print(f"[INFO] Inserting batch {start} → {end}")

        collection.add(
            ids=[str(i) for i in range(start, end)],
            documents=all_chunks[start:end],
            embeddings=embeddings[start:end],
            metadatas=all_metadata[start:end],
        )

    print("[SUCCESS] Vector DB built")

# ================= RAG QUERY =================
def query_rag(question: str) -> str:
    try:
        # ================= SMALL TALK =================
        if is_small_talk(question):
            return (
                "Hello! 👋 I'm the SRM KTR Assistant.\n\n"
                "Ask me about:\n"
                "• B.Tech fees\n"
                "• Courses\n"
                "• Hostel\n"
                "• Campus life\n"
                "• Admissions"
            )

        # ================= EMBEDDING =================
        emb = model.encode(question).tolist()

        results = collection.query(
            query_embeddings=[emb],
            n_results=25,
            include=["documents", "metadatas", "distances"]
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        # ================= STRONG FILTER =================
        filtered = [
            (d, m, dist)
            for d, m, dist in zip(docs, metas, distances)
            if dist < 1.0
        ]

        if not filtered:
            return (
                "I couldn't find reliable information for that.\n"
                "Try asking about SRM KTR admissions, fees, or courses."
            )

        # ================= HYBRID RERANK =================
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

        # ================= BUILD CITATION MAP =================
        # Deduplicate sources and build numbered citation list
        seen_sources = {}
        citation_list = []
        for m in top_metas:
            url = m.get("source", "")
            if url and url not in seen_sources:
                idx = len(citation_list) + 1
                seen_sources[url] = idx
                citation_list.append({
                    "index": idx,
                    "title": m.get("title", "SRM Page"),
                    "url": url,
                })

        # Build context with source labels
        context_parts = []
        for doc, meta in zip(top_docs, top_metas):
            url = meta.get("source", "")
            ref_idx = seen_sources.get(url, "?")
            context_parts.append(f"[Source {ref_idx}]: {doc}")

        context = "\n\n".join(context_parts)

        # Format citation block for the prompt
        citation_block = "\n".join(
            f"[{c['index']}] {c['title']} — {c['url']}"
            for c in citation_list
        )

        # ================= PROMPT =================
        prompt = f"""
You are SRM KTR official admission assistant.

STYLE:
- Professional but friendly
- Clear structured answer
- Use bullet points when helpful
- If greeting → greet briefly
- If unsure → say information may vary

STRICT RULES:
- Never mention the word "context"
- Never hallucinate locations
- SRM KTR is in Chennai, Tamil Nadu
- Prefer concise readable answers
- When stating facts, add the source number in brackets like [1] or [2]
- Only use information from the sources provided below

QUESTION:
{question}

INFORMATION (with source labels):
{context}

AVAILABLE SOURCES:
{citation_block}

FINAL ANSWER:
"""

        answer = call_llm(prompt)

        # ================= APPEND CITATIONS =================
        if citation_list and len(filtered) >= 3:
            answer += "\n\n📚 **Sources:**\n"
            for c in citation_list:
                answer += f"[{c['index']}] [{c['title']}]({c['url']})\n"

        return answer.strip()

    except Exception as e:
        return f"RAG Error: {e}"

# ================= LLM CALL =================
def call_llm(prompt: str) -> str:
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma3",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 512
                }
            },
            timeout=120
        )

        return response.json().get("response", "LLM error")

    except Exception as e:
        return f"LLM not running: {e}"