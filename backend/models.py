"""
Pydantic models for SRM Admission Chatbot API.
Separates request/response schemas from the API logic.
"""

from pydantic import BaseModel, Field


# ================= REQUEST MODELS =================

class ChatRequest(BaseModel):
    """Incoming chat request from the frontend."""
    query: str = Field(..., min_length=1, max_length=2000, description="The user's question")
    campus: str | None = Field(default=None, description="Selected campus filter (KTR, Ramapuram, etc.)")
    session_id: str | None = Field(default=None, description="Session ID for conversation memory")


# ================= RESPONSE MODELS =================

class Source(BaseModel):
    """A single citation source."""
    index: int
    title: str
    url: str


class ChatResponse(BaseModel):
    """Full chat response with answer, sources, and metadata."""
    response: str = Field(..., description="The generated answer text")
    intent: str = Field(default="general_query", description="Detected intent of the query")
    sources: list[Source] = Field(default_factory=list, description="Citation sources used")
    campus: str | None = Field(default=None, description="Detected campus entity")
    program: str | None = Field(default=None, description="Detected program entity")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    vector_db_status: str