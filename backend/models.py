"""
Pydantic models for SRM Admission Chatbot API.
Separates request/response schemas from the API logic.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


# ================= REQUEST MODELS =================

class PinnedContext(BaseModel):
    """Optional user-pinned conversational context."""
    type: Literal["campus", "program", "department"]
    value: str = Field(..., min_length=1, description="Pinned value sent with chat requests")
    entity_id: str | None = Field(default=None, description="Canonical entity id if resolved")
    display_name: str | None = Field(default=None, description="Human-readable label for UI display")


class ChatRequest(BaseModel):
    """Incoming chat request from the frontend."""
    query: str = Field(..., min_length=1, max_length=2000, description="The user's question")
    campus: str | None = Field(default=None, description="Selected campus filter (KTR, Ramapuram, etc.)")
    session_id: str | None = Field(default=None, description="Session ID for conversation memory")
    pinned_context: PinnedContext | None = Field(
        default=None,
        description="Optional pinned campus/program/department context",
    )


# ================= RESPONSE MODELS =================

class Source(BaseModel):
    """A single citation source."""
    index: int
    title: str
    url: str


class QueryMetadata(BaseModel):
    """Interpreted query metadata surfaced to the UI."""
    domain: str | None = Field(default=None, description="Detected query domain")
    task: str | None = Field(default=None, description="Detected query task")
    routing_target: str | None = Field(default=None, description="Chosen routing subsystem")
    confidence: float | None = Field(default=None, description="Router confidence score")
    entities: dict[str, Any] = Field(default_factory=dict, description="Resolved entities and matched items")
    freshness: str | None = Field(default=None, description="Freshness summary from evidence timestamps")
    used_pinned_context: bool = Field(default=False, description="Whether a pinned context shaped the routing")
    decomposed: bool = Field(default=False, description="Whether the query was decomposed into subtasks")


class ChatResponse(BaseModel):
    """Full chat response with answer, sources, and metadata."""
    response: str = Field(..., description="The generated answer text")
    intent: str = Field(default="general_query", description="Detected intent of the query")
    sources: list[Source] = Field(default_factory=list, description="Citation sources used")
    campus: str | None = Field(default=None, description="Detected campus entity")
    program: str | None = Field(default=None, description="Detected program entity")
    confidence: float | None = Field(default=None, description="Overall routing confidence")
    query_metadata: QueryMetadata | None = Field(
        default=None,
        description="Structured metadata about how the query was interpreted",
    )


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    vector_db_status: str
