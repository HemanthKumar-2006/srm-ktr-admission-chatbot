import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or default


@dataclass(frozen=True)
class Settings:
    api_allowed_origins: list[str]
    rag_data_path: str
    rag_vector_db_path: str
    rag_collection_name: str
    rag_chunk_size: int
    rag_chunk_overlap: int
    rag_min_chunk_length: int
    rag_retrieval_limit: int
    rag_max_distance: float
    rag_final_chunk_count: int
    rag_embed_batch: int
    rag_embed_model: str
    rag_rerank_model: str
    rag_llm_url: str
    rag_llm_model: str
    rag_llm_stream: bool
    eval_api_url: str


def load_settings() -> Settings:
    return Settings(
        api_allowed_origins=_csv_env(
            "API_ALLOWED_ORIGINS",
            [
                "http://localhost:8080",
                "http://127.0.0.1:8080",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ],
        ),
        rag_data_path=os.getenv("RAG_DATA_PATH", "data/srm_docs"),
        rag_vector_db_path=os.getenv("RAG_VECTOR_DB_PATH", "vector_db"),
        rag_collection_name=os.getenv("RAG_COLLECTION_NAME", "srm_data"),
        rag_chunk_size=_int_env("RAG_CHUNK_SIZE", 450),
        rag_chunk_overlap=_int_env("RAG_CHUNK_OVERLAP", 80),
        rag_min_chunk_length=_int_env("RAG_MIN_CHUNK_LENGTH", 80),
        rag_retrieval_limit=_int_env("RAG_RETRIEVAL_LIMIT", 25),
        rag_max_distance=_float_env("RAG_MAX_DISTANCE", 1.8),
        rag_final_chunk_count=_int_env("RAG_FINAL_CHUNK_COUNT", 5),
        rag_embed_batch=_int_env("RAG_EMBED_BATCH", 256),
        rag_embed_model=os.getenv("RAG_EMBED_MODEL", "all-MiniLM-L6-v2"),
        rag_rerank_model=os.getenv("RAG_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
        rag_llm_url=os.getenv("RAG_LLM_URL", "http://localhost:11434/api/generate"),
        rag_llm_model=os.getenv("RAG_LLM_MODEL", "gemma3"),
        rag_llm_stream=_bool_env("RAG_LLM_STREAM", True),
        eval_api_url=os.getenv("EVAL_API_URL", "http://127.0.0.1:8000/chat"),
    )


SETTINGS = load_settings()
