import json
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
import requests
import re

# ================= CONFIG =================
# 2A: Changed to processed (cleaned + re-categorized) data
DATA_PATH = Path("data/processed/srm_data_cleaned.json")

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

    # 2B: Per-record adaptive splitter based on category
    # (splitter is instantiated inside the loop below)

    all_chunks = []
    all_metadata = []

    for d in docs:
        content = clean_text(d["content"])
        source_url = d.get("url", "")
        page_title = d.get("title", "Untitled Page")
        category = d.get("category", "general_query")
        campus = d.get("campus", "ktr")

        # skip junk pages
        if len(content) < 200:
            continue

        # 2B: Adaptive chunk size per category
        splitter = get_splitter(category)
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

# ================= 2B: ADAPTIVE CHUNK SPLITTER =================
def get_splitter(category: str):
    """Returns a RecursiveCharacterTextSplitter tuned per content category."""
    SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", " ", ""]
    if category == "fee_structure":
        return RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150, separators=SEPARATORS)
    elif category in ("hostel_info", "admission_process"):
        return RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100, separators=SEPARATORS)
    else:
        return RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50, separators=SEPARATORS)


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
    # 3A: Improved intent detection prompt with examples and strict rules
    system_prompt = """You are a query parser for the SRM University chatbot.
Analyze the user query and return ONLY a valid JSON object. No explanation. No markdown.

INTENT OPTIONS:
- fee_structure        → tuition, fees, charges, payment, scholarships, cost, how much, price
- admission_process    → how to apply, deadlines, FRRO, visa, documents, registration, eligibility criteria
- hostel_info          → accommodation, room, mess, hostel fees, boarding, dining
- course_details       → programs, syllabus, departments, infrastructure, faculty, labs, curriculum
- eligibility          → cutoffs, JEE scores, marks required, qualifications
- campus_life          → clubs, events, sports, facilities, student life, activities
- general_query        → anything else, greetings, off-topic

CAMPUS OPTIONS: ktr, rmp, vdp, ncr, trp, ap, null

RULES:
- fee / cost / price / charges / how much / payment / scholarship → intent MUST be fee_structure
- hostel / accommodation / room / mess / dining → intent MUST be hostel_info
- If no campus is mentioned → campus must be null. Do NOT default to ktr.
- is_small_talk is true ONLY for greetings, jokes, or clearly off-topic questions.

EXAMPLES:
Query: "what is the tuition fee for b.tech cs"
{"intent":"fee_structure","entities":{"campus":null,"program":"B.Tech Computer Science"},"is_small_talk":false}

Query: "how do i apply for mba at ramapuram"
{"intent":"admission_process","entities":{"campus":"rmp","program":"MBA"},"is_small_talk":false}

Query: "is there a hostel at vdp campus"
{"intent":"hostel_info","entities":{"campus":"vdp","program":null},"is_small_talk":false}

Query: "what are the eligibility criteria for b.arch"
{"intent":"eligibility","entities":{"campus":null,"program":"B.Arch"},"is_small_talk":false}

Query: "hi there"
{"intent":"general_query","entities":{"campus":null,"program":null},"is_small_talk":true}

Now parse this query:
"""
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma3",
                "prompt": f"{system_prompt}\"{query}\"",
                "stream": False,
                "options": {"num_predict": 120, "temperature": 0.0}
            },
            timeout=10
        )
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

        # 2D: Always query globally — no hard metadata filter
        # Intent boosting is applied during reranking instead
        detected_intent = analysis.get("intent", "general_query")

        # ================= EMBEDDING =================
        emb = model.encode(question).tolist()

        # 2D: Global search — no where filter
        results = collection.query(
            query_embeddings=[emb],
            n_results=25,
            where=None,
            include=["documents", "metadatas", "distances"]
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        # ================= DEMANDING FILTER =================
        # Keep only reasonably close results (distance < 1.5)
        filtered = [
            {"doc": d, "meta": m, "distance": dist}
            for d, m, dist in zip(docs, metas, distances)
            if dist < 1.5
        ]

        if not filtered:
            return (
                "I couldn't find reliable information for that.\n"
                "Try asking about SRM KTR admissions, fees, or courses."
            )

        # ================= 2C + 2D: HYBRID RERANK WITH INTENT BOOST =================
        q_words = set(question.lower().split())

        # Precompute keyword overlaps
        for c in filtered:
            doc_words = set(c["doc"].lower().split())
            c["keyword_overlap"] = len(q_words & doc_words)

        # 2C: Normalize scores to 0-1 range
        max_overlap = max((c["keyword_overlap"] for c in filtered), default=1) or 1

        KEYWORD_WEIGHT = 0.4
        SEMANTIC_WEIGHT = 0.6
        INTENT_BOOST = 1.25  # 2D: boost for category match

        for c in filtered:
            keyword_score = c["keyword_overlap"] / max_overlap
            distance_score = 1.0 - (c["distance"] / 2.0)
            distance_score = max(0.0, min(1.0, distance_score))  # clamp

            final_score = (KEYWORD_WEIGHT * keyword_score) + (SEMANTIC_WEIGHT * distance_score)

            # 2D: Apply intent boost when metadata category matches detected intent
            if c.get("meta", {}).get("category") == detected_intent:
                final_score *= INTENT_BOOST

            c["keyword_score"] = keyword_score
            c["distance_score"] = distance_score
            c["final_score"] = final_score

        sorted_candidates = sorted(filtered, key=lambda x: x["final_score"], reverse=True)

        # ================= 4A: DEBUG LOGGING =================
        DEBUG = False  # Set to True to inspect retrieval quality
        if DEBUG:
            print("\n=== TOP 3 RERANKED CANDIDATES ===")
            for i, c in enumerate(sorted_candidates[:3]):
                print(
                    f"  [{i+1}] score={c['final_score']:.4f} | "
                    f"category={c.get('meta', {}).get('category', '?')} | "
                    f"keyword_score={c.get('keyword_score', 0):.3f} | "
                    f"distance_score={c.get('distance_score', 0):.3f} | "
                    f"intent_boosted={c.get('meta', {}).get('category') == detected_intent}"
                )
            print("=================================\n")

        top_docs = [c["doc"] for c in sorted_candidates[:5]]
        top_metas = [c["meta"] for c in sorted_candidates[:5]]

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

        # ================= 3B: FINAL ANSWER PROMPT =================
        detected_campus = analysis['entities'].get('campus')
        campus_context = detected_campus.upper() if detected_campus else "Not specified"
        program_context = analysis['entities'].get('program') or "Not specified"

        prompt = f"""You are the official SRM University Information Assistant.
You help prospective students with accurate information about admissions, fees, programs, and campus life.

SESSION CONTEXT:
- Detected Campus: {campus_context}
- Detected Program: {program_context}
- Query Intent: {detected_intent}

ANSWERING RULES:
1. Answer ONLY using the context sources provided below.
2. If a specific figure (fee amount, date, score) is found in context, state it directly. Do NOT use inline citations like [1] or [2] inside your answer.
3. PARTIAL INFORMATION RULE: If context contains some relevant facts but not all (e.g., international fees found but not domestic, or one campus but not another), share what IS available and clearly state what is missing. Never silently discard partial information.
4. TABLE ROW RULE: Context may include lines formatted as "Key: Value, Key: Value, ..." — these are rows from fee or eligibility tables. Treat each such line as a single fact and extract the row(s) relevant to the query. Do not ignore them because they look unusual.
5. CAMPUS RULE: If campus is not specified and fees/details differ by campus, list information for all campuses found in context rather than guessing.
6. DOMESTIC FEE GAP: If the query asks for domestic (Indian student) B.Tech fees in INR and context only shows international (USD) fees, explicitly say: "I have fee data for international students in USD, but I don't have the current domestic tuition fee in INR. Please check srmist.edu.in/admission-india or contact admissions."
7. ZERO CONTEXT FALLBACK — use ONLY if context has no relevant information at all: "I don't have that specific detail. Please contact admissions at admissions.ir@srmist.edu.in or WhatsApp 9003177786."
8. Never hallucinate figures, dates, or program names not present in context.
9. Do NOT add a reference list at the bottom. Do NOT use any inline citations or academic-style numbering in your response.

STYLE:
- Bullet points for fee breakdowns, lists of documents, or multi-item answers
- Bold all amounts, deadlines, and key terms
- Under 200 words unless the query needs a full breakdown (e.g., complete fee table)

USER QUESTION: {question}

CONTEXT SOURCES:
{context}

SOURCE INDEX:
{citation_block}

ANSWER:"""

        with open("debug_prompt.txt", "w", encoding="utf-8") as f:
            f.write(prompt)
        answer = call_llm(prompt)

        # ================= APPEND SOURCES =================
        # Since inline citations are removed, we'll list all sources provided in context
        if citation_list:
            answer += "\n\n📚 **Sources:**\n"
            for c in citation_list:
                answer += f"- [{c['title']}]({c['url']})\n"

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

# ================= RUN =================
if __name__ == "__main__":
    build_db()