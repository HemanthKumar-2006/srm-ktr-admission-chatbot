import asyncio
import logging
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.models import ChatRequest, ChatResponse, HealthResponse
from backend.rag_pipeline import query_rag, get_collection_count, build_db, LLMError
from backend.cache import cache, conversation_memory
from backend.settings import SETTINGS

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("srm_chatbot")


def _model_dump(model_obj):
    if model_obj is None:
        return None
    if hasattr(model_obj, "model_dump"):
        return model_obj.model_dump(exclude_none=True)
    return model_obj.dict(exclude_none=True)

# ================= LIFESPAN =================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SRM Chatbot starting up...")
    cache.clear()
    logger.info("Cache cleared (new config version)")
    try:
        count = get_collection_count()
        logger.info(f"Vector DB chunks loaded: {count}")
        if count == 0:
            logger.warning("Vector DB is empty -- run build_db first.")
    except Exception as e:
        logger.error(f"Could not reach Vector DB: {e}")
    yield
    logger.info("Shutting down...")

# ================= APP =================

app = FastAPI(
    title="SRM Admission Chatbot",
    version="4.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.api.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= ROUTES =================

@app.get("/")
async def home():
    return {"message": "SRM Chatbot API"}


@app.get("/health", response_model=HealthResponse)
async def health():
    try:
        count = get_collection_count()
        db_status = f"ok ({count} chunks)"
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok",
        version="4.1",
        vector_db_status=db_status,
    )

# ================= CHAT =================

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):

    question = req.query.strip()
    pinned_context = _model_dump(req.pinned_context)

    if not question:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # ================= CACHE =================
    cache_scope = {
        "query": question,
        "campus": req.campus,
        "session_scope": req.session_id or "",
        "model": SETTINGS.rag.llm.model,
        "config_version": f"{app.version}:{SETTINGS.rag.collection_name}",
        "pinned_context": pinned_context or {},
    }
    cached = cache.get(cache_scope)
    if cached:
        logger.info(f"Cache HIT: {question[:50]}")
        return ChatResponse(**cached)

    try:
        logger.info(f"Query: {question} | Campus: {req.campus} | Session: {req.session_id}")

        conv_context = ""
        if req.session_id:
            conv_context = conversation_memory.get_context(req.session_id)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                query_rag,
                question,
                campus=req.campus,
                conversation_context=conv_context,
                pinned_context=pinned_context,
            ),
        )

        answer = result.get("answer", "")
        sources_raw = result.get("sources", [])
        detected_intent = result.get("intent", "general_query")
        resolved_campus = result.get("campus") or req.campus
        resolved_program = result.get("program")
        query_metadata = result.get("query_metadata")
        confidence = result.get("confidence")

        if not answer:
            answer = (
                "I couldn't find relevant information about that. "
                "Please visit https://www.srmist.edu.in or contact the SRM admissions office."
            )

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
            "intent": detected_intent,
            "sources": sources,
            "campus": resolved_campus,
            "program": resolved_program,
            "confidence": confidence,
            "query_metadata": query_metadata,
        }

        cache.set(cache_scope, response_data)

        if req.session_id:
            conversation_memory.add_turn(req.session_id, question, answer)

        logger.info(f"Answered: {question[:50]}")

        return ChatResponse(**response_data)

    except LLMError as e:
        logger.error(f"LLM error for query: {question[:50]} — {e}")
        return ChatResponse(
            response=str(e),
            intent="error",
            sources=[],
            campus=None,
            program=None,
            confidence=None,
            query_metadata=None,
        )

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
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
