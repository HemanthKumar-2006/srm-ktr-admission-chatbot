import os
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Primitive env helpers
# ---------------------------------------------------------------------------

def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise EnvironmentError(f"Env var '{name}' must be an integer, got: {value!r}")


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise EnvironmentError(f"Env var '{name}' must be a float, got: {value!r}")


def _str_env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed if parsed else default


# ---------------------------------------------------------------------------
# Grouped sub-configs (all frozen for immutability)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ApiConfig:
    allowed_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ])

    @classmethod
    def from_env(cls) -> "ApiConfig":
        return cls(
            allowed_origins=_csv_env(
                "API_ALLOWED_ORIGINS",
                cls.__dataclass_fields__["allowed_origins"].default_factory(),
            ),
        )


@dataclass(frozen=True)
class DeviceConfig:
    """Device configuration locked to CPU as requested."""
    use_gpu: bool = False

    @classmethod
    def from_env(cls) -> "DeviceConfig":
        return cls()

    @property
    def torch_device(self) -> str:
        """Ready-to-use string for torch.device() / HuggingFace device= arg."""
        return "cpu"

    @property
    def use_fp16(self) -> bool:
        """Disabled for CPU."""
        return False


@dataclass(frozen=True)
class ChunkingConfig:
    size: int = 600
    overlap: int = 120
    min_length: int = 80

    def __post_init__(self) -> None:
        if self.overlap >= self.size:
            raise ValueError(
                f"chunk_overlap ({self.overlap}) must be less than chunk_size ({self.size})"
            )
        if self.min_length < 0:
            raise ValueError(f"min_chunk_length must be non-negative, got {self.min_length}")

    @classmethod
    def from_env(cls) -> "ChunkingConfig":
        return cls(
            size=_int_env("RAG_CHUNK_SIZE", cls.size),
            overlap=_int_env("RAG_CHUNK_OVERLAP", cls.overlap),
            min_length=_int_env("RAG_MIN_CHUNK_LENGTH", cls.min_length),
        )


@dataclass(frozen=True)
class RetrievalConfig:
    limit: int = 30
    max_distance: float = 1.5
    final_chunk_count: int = 8

    def __post_init__(self) -> None:
        if self.final_chunk_count > self.limit:
            raise ValueError(
                f"final_chunk_count ({self.final_chunk_count}) cannot exceed "
                f"retrieval_limit ({self.limit})"
            )
        if self.max_distance <= 0:
            raise ValueError(f"max_distance must be positive, got {self.max_distance}")

    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        return cls(
            limit=_int_env("RAG_RETRIEVAL_LIMIT", cls.limit),
            max_distance=_float_env("RAG_MAX_DISTANCE", cls.max_distance),
            final_chunk_count=_int_env("RAG_FINAL_CHUNK_COUNT", cls.final_chunk_count),
        )


@dataclass(frozen=True)
class EmbedConfig:
    model: str = "all-MiniLM-L6-v2"
    batch_size: int = 256               # MiniLM is small — 256 fits easily in 16GB VRAM

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("embed model name must not be empty")
        if self.batch_size < 1:
            raise ValueError(f"embed batch_size must be >= 1, got {self.batch_size}")

    @classmethod
    def from_env(cls) -> "EmbedConfig":
        return cls(
            model=_str_env("RAG_EMBED_MODEL", cls.model),
            batch_size=_int_env("RAG_EMBED_BATCH", cls.batch_size),
        )


@dataclass(frozen=True)
class LLMConfig:
    url: str = "http://localhost:11434/api/generate"
    model: str = "gemma3"
    stream: bool = True
    num_predict: int = 4096

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(
                f"LLM url must start with http:// or https://, got: {self.url!r}"
            )
        if self.num_predict < 1:
            raise ValueError(f"num_predict must be >= 1, got {self.num_predict}")

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            url=_str_env("RAG_LLM_URL", cls.url),
            model=_str_env("RAG_LLM_MODEL", cls.model),
            stream=_bool_env("RAG_LLM_STREAM", cls.stream),
            num_predict=_int_env("RAG_LLM_NUM_PREDICT", cls.num_predict),
        )


@dataclass(frozen=True)
class RagConfig:
    data_path: str = "backend/data/srm_docs"
    vector_db_path: str = "vector_db_qdrant"
    collection_name: str = "srm_data"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    device: DeviceConfig = field(default_factory=DeviceConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_env(cls) -> "RagConfig":
        return cls(
            data_path=_str_env("RAG_DATA_PATH", cls.data_path),
            vector_db_path=_str_env("RAG_VECTOR_DB_PATH", cls.vector_db_path),
            collection_name=_str_env("RAG_COLLECTION_NAME", cls.collection_name),
            rerank_model=_str_env("RAG_RERANK_MODEL", cls.rerank_model),
            device=DeviceConfig.from_env(),
            chunking=ChunkingConfig.from_env(),
            retrieval=RetrievalConfig.from_env(),
            embed=EmbedConfig.from_env(),
            llm=LLMConfig.from_env(),
        )


# ---------------------------------------------------------------------------
# Top-level Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """Application-wide configuration loaded once from environment variables."""

    api: ApiConfig = field(default_factory=ApiConfig)
    rag: RagConfig = field(default_factory=RagConfig)
    eval_api_url: str = "http://127.0.0.1:8000/chat"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api=ApiConfig.from_env(),
            rag=RagConfig.from_env(),
            eval_api_url=_str_env("EVAL_API_URL", cls.eval_api_url),
        )

    def summary(self) -> dict[str, Any]:
        """Return a loggable snapshot of key settings (safe to print)."""
        return {
            "api.allowed_origins":              self.api.allowed_origins,
            "rag.data_path":                    self.rag.data_path,
            "rag.vector_db_path":               self.rag.vector_db_path,
            "rag.embed.model":                  self.rag.embed.model,
            "rag.embed.batch_size":             self.rag.embed.batch_size,
            "rag.device.torch_device":          self.rag.device.torch_device,
            "rag.device.use_fp16":              self.rag.device.use_fp16,
            "rag.llm.model":                    self.rag.llm.model,
            "rag.llm.url":                      self.rag.llm.url,
            "rag.llm.stream":                   self.rag.llm.stream,
            "rag.retrieval.limit":              self.rag.retrieval.limit,
            "rag.retrieval.final_chunk_count":  self.rag.retrieval.final_chunk_count,
            "eval_api_url":                     self.eval_api_url,
        }


# ---------------------------------------------------------------------------
# Module-level singleton — loaded once at import time
# ---------------------------------------------------------------------------

SETTINGS: Settings = Settings.from_env()