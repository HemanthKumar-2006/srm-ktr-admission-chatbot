import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.models import ChatRequest, ChatResponse, HealthResponse, Source
from backend.rag_pipeline import query_rag, detect_intent_and_entities, collection, build_db
from backend.cache import cache

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("srm_chatbot")


# ================= LIFESPAN =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 SRM Admission Chatbot starting up...")
    logger.info(f"📊 Vector DB collection count: {collection.count()}")
    yield
    logger.info("👋 Shutting down...")


# ================= APP =================
app = FastAPI(
    title="SRM Admission Chatbot",
    description="AI-powered admission assistant for SRM Institute of Science and Technology",
    version="2.0",
    lifespan=lifespan,
)

# ================= CORS =================
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "*",  # keep during development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================= ROUTES =================

@app.get("/")
async def home():
    return {"message": "SRM Admission Chatbot API v2.0 🚀"}


@app.get("/health", response_model=HealthResponse)
async def health():
    try:
        db_count = collection.count()
        db_status = f"ok ({db_count} chunks)"
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok",
        version="2.0",
        vector_db_status=db_status,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    question = req.query.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # ================= CACHE CHECK =================
    cached = cache.get(question)
    if cached:
        logger.info(f"💾 Cache HIT: {question[:50]}...")
        return ChatResponse(**cached)

    try:
        # ================= INTENT DETECTION =================
        analysis = detect_intent_and_entities(question)
        logger.info(f"🎯 Intent: {analysis.get('intent')} | Entities: {analysis.get('entities')}")

        # ================= RAG =================
        answer = query_rag(question)

        if not answer:
            answer = "Sorry, I couldn't find relevant information. Please check the SRM website."

        # Build structured response
        response_data = {
            "response": answer,
            "intent": analysis.get("intent", "general_query"),
            "sources": [],
            "campus": analysis.get("entities", {}).get("campus"),
            "program": analysis.get("entities", {}).get("program"),
        }

        # ================= CACHE STORE =================
        cache.set(question, response_data)
        logger.info(f"✅ Answered: {question[:50]}...")

        return ChatResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


@app.get("/cache/stats")
async def cache_stats():
    """Returns cache hit/miss statistics."""
    return cache.stats()


@app.post("/cache/clear")
async def clear_cache():
    """Flush the query cache (admin endpoint)."""
    cache.clear()
    return {"message": "Cache cleared"}


@app.post("/admin/rebuild-db")
async def rebuild_database():
    """Trigger a vector DB rebuild from scraped data (admin endpoint)."""
    try:
        build_db()
        cache.clear()
        return {"message": "Vector DB rebuilt and cache cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rebuild error: {str(e)}")