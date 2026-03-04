from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from backend.rag_pipeline import query_rag

# ================= APP =================
app = FastAPI(
    title="SRM Admission Chatbot",
    version="1.1",
)

# ================= CORS =================
# 🔥 allow both localhost styles (IMPORTANT)
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

# ================= MODELS =================
class Query(BaseModel):
    query: str


class ChatResponse(BaseModel):
    response: str


# ================= ROUTES =================
@app.get("/")
async def home():
    return {"message": "SRM Admission Chatbot API is running 🚀"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(q: Query):
    try:
        question = q.query.strip()

        if not question:
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        answer = query_rag(question)

        if not answer:
            answer = "Sorry, I couldn't find relevant information."

        return ChatResponse(response=answer)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")