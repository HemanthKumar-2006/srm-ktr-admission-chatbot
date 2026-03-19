import asyncio
import logging
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.models import ChatRequest, ChatResponse, HealthResponse
from backend.rag_pipeline import query_rag, get_collection, build_db
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
    try:
        count = get_collection().count()
        logger.info(f"📊 Vector DB chunks loaded: {count}")
        if count == 0:
            logger.warning("⚠️ Vector DB is empty — run build_db first.")
    except Exception as e:
        logger.error(f"❌ Could not reach Vector DB: {e}")
    yield
    logger.info("👋 Shutting down...")

# ================= APP =================

app = FastAPI(
    title="SRM Admission Chatbot",
    version="2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= ROUTES =================

@app.get("/")
async def home():
    return {"message": "SRM Chatbot API 🚀"}


@app.get("/health", response_model=HealthResponse)
async def health():
    try:
        count = get_collection().count()
        db_status = f"ok ({count} chunks)"
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok",
        version="2.0",
        vector_db_status=db_status,
    )

# ================= CHAT =================

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):

    question = req.query.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # ================= CACHE =================
    cached = cache.get(question)
    if cached:
        logger.info(f"💾 Cache HIT: {question[:50]}")
        return ChatResponse(**cached)

    try:
        logger.info(f"💬 Query: {question}")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, partial(query_rag, question))

        # query_rag returns {"answer": str, "sources": list[str]}
        answer = result.get("answer", "")
        sources_raw = result.get("sources", [])

        if not answer:
            answer = "No relevant information found."

        # Build sources — Source model requires index + url + title (all 3)
        seen = set()
        sources = []
        for src in sources_raw:
            if src and src not in seen:
                seen.add(src)
                sources.append({
                    "index": len(sources) + 1,
                    "url": src,
                    "title": src,
                })

        response_data = {
            "response": answer,
            "intent": "general_query",
            "sources": sources,
            "campus": None,
            "program": None,
        }

        cache.set(question, response_data)
        logger.info(f"✅ Answered: {question[:50]}")

        return ChatResponse(**response_data)

    except Exception as e:
        logger.error(f"❌ Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ================= ADMIN =================

@app.post("/admin/build-db")
async def build_database():
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, partial(build_db, False))
        cache.clear()
        return {"message": "DB updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/rebuild-db")
async def rebuild_database():
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, partial(build_db, True))
        cache.clear()
        return {"message": "DB rebuilt"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ================= CACHE =================

@app.get("/cache/stats")
async def cache_stats():
    return cache.stats()


@app.post("/cache/clear")
async def clear_cache():
    cache.clear()
    return {"message": "Cache cleared"}
