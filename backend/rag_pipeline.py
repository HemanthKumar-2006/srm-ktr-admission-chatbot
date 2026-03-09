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
        chunk_size=400,
        chunk_overlap=50,
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""]
    )

    all_chunks = []
    all_metadata = []

    for d in docs:
        content = clean_text(d["content"])
        source_url = d.get("url", "")
        page_title = d.get("title", "Untitled Page")
        category = d.get("category", "general")
        campus = d.get("campus", "ktr")

        # skip junk pages
        if len(content) < 200:
            continue

        raw_chunks = splitter.split_text(content)

        for chunk in raw_chunks:
            chunk = chunk.strip()
            if len(chunk) < 60:
                continue

            # 🔥 CONTEXT PREPENDING: Add title to help retrieval & generation
            enriched_chunk = f"[Title: {page_title}] {chunk}"

            all_chunks.append(enriched_chunk)
            all_metadata.append({
                "source": source_url,
                "title": page_title,
                "category": category,
                "campus": campus,
            })

    print(f"[INFO] Clean chunks: {len(all_chunks)}")

    # Count category and campus distribution across chunks
    cat_counts = {}
    cam_counts = {}
    for m in all_metadata:
        cat = m["category"]
        cam = m["campus"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        cam_counts[cam] = cam_counts.get(cam, 0) + 1
    
    print(f"[INFO] Chunk categories: {json.dumps(cat_counts, indent=2)}")
    print(f"[INFO] Chunk campuses: {json.dumps(cam_counts, indent=2)}")

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

# ================= INTENT DETECTION =================

INTENTS = [
    "fee_structure",
    "admission_process",
    "hostel_info",
    "course_details",
    "campus_life",
    "eligibility",
    "general_query",
]

def detect_intent_and_entities(query: str) -> dict:
    """Use a fast LLM call to classify intent and extract entities (Campus, Program)."""
    system_prompt = f"""
Analyze the user query for a university admission chatbot.
Intents: {", ".join(INTENTS)}
Campuses: ktr, rmp, vdp, ncr, trp, ap

Return ONLY a JSON object:
{{
  "intent": "detected_intent",
  "entities": {{
    "campus": "detected_campus_or_null",
    "program": "detected_program_or_null"
  }},
  "is_small_talk": true/false
}}
"""
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma3", # Using same model but with lower token limit for speed
                "prompt": f"{system_prompt}\n\nQuery: {query}\n\nJSON:",
                "stream": False,
                "options": {"num_predict": 100, "temperature": 0.0}
            },
            timeout=10
        )
        # Crude JSON extraction
        res_text = response.json().get("response", "{}")
        json_match = re.search(r"\{.*\}", res_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    
    return {"intent": "general_query", "entities": {"campus": None, "program": None}, "is_small_talk": False}

# ================= RAG QUERY =================
def query_rag(question: str) -> str:
    try:
        # ================= UNDERSTANDING =================
        analysis = detect_intent_and_entities(question)
        
        if analysis.get("is_small_talk"):
            return (
                "Hello! 👋 I'm the SRM KTR Assistant.\n\n"
                "I can help you with:\n"
                "• B.Tech fees & scholarships\n"
                "• Admission eligibility & process\n"
                "• Hostel & Campus life\n"
                "• Courses & Curriculum"
            )

        # ================= METADATA FILTERING =================
        where_filter = {}
        if analysis["entities"].get("campus"):
            where_filter["campus"] = analysis["entities"]["campus"]
        
        # Mapping intent to category
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

        # ================= EMBEDDING =================
        emb = model.encode(question).tolist()

        # Query with metadata filter
        results = collection.query(
            query_embeddings=[emb],
            n_results=25,
            where=where_filter if where_filter else None,
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
        campus_context = f"Campus: {analysis['entities']['campus'].upper()}" if analysis['entities'].get('campus') else "Campus: SRM KTR (General)"
        program_context = f"Program: {analysis['entities']['program']}" if analysis['entities'].get('program') else ""
        
        prompt = f"""
You are the SRM University Official Admission Assistant.
{campus_context}
{program_context}

STYLE:
- Professional, factual, and helpful
- Use clear headings and bullet points
- Be concise but thorough

STRICT RULES:
1. ONLY use information from the provided context sources.
2. If context lacks the answer, say "I don't have that specific information. Please check our website or contact admissions."
3. Cite sources using [1], [2], etc. next to specific facts.
4. SRM KTR is the main campus in Chennai.

INTENT: {analysis['intent']}
USER QUESTION: {question}

CONTEXT SOURCES:
{context}

SOURCE DETAILS:
{citation_block}

FINAL ANSWER:
"""

        answer = call_llm(prompt)

        # ================= APPEND CITATIONS =================
        if citation_list:
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