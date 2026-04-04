"""
SRM RAG Pipeline v4.1
- All v3.1 features retained (Qdrant, hybrid search, metadata enrichment)
- v4.0: Lightweight Knowledge Graph for entity-relationship queries
- v4.0: Hierarchical parent-child chunking with parent fetching
- v4.0: Page authority scoring and recency-aware reranking
- v4.0: Contextual compression before LLM calls
- v4.0: Few-shot prompt templates with faithfulness guardrails
- v4.1: Nested settings configuration; role-query detection; structured prompt guardrails
"""

# ================= IMPORTS =================

import csv
import hashlib
import json
import logging
import math
import pickle
import re
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer
import numpy as np

from backend.admission_profiles import (
    answer_admission_question,
    load_admission_profiles,
    save_admission_profiles,
)
from backend.knowledge_graph import KnowledgeGraph, build_knowledge_graph
from backend.settings import SETTINGS  # new nested Settings object

# ================= CONFIG =================
# Thin bridge: pull values from the new nested SETTINGS so the rest of the
# pipeline continues to use the short CFG.* names without change.

@dataclass
class Config:
    data_path: Path = field(default_factory=lambda: Path(SETTINGS.rag.data_path))
    vector_db_path: str = field(default_factory=lambda: SETTINGS.rag.vector_db_path)
    collection_name: str = field(default_factory=lambda: SETTINGS.rag.collection_name)

    # Chunking
    chunk_size: int = field(default_factory=lambda: SETTINGS.rag.chunking.size)
    chunk_overlap: int = field(default_factory=lambda: SETTINGS.rag.chunking.overlap)
    min_chunk_length: int = field(default_factory=lambda: SETTINGS.rag.chunking.min_length)

    # Retrieval
    retrieval_limit: int = field(default_factory=lambda: SETTINGS.rag.retrieval.limit)
    max_distance: float = field(default_factory=lambda: SETTINGS.rag.retrieval.max_distance)
    final_chunk_count: int = field(default_factory=lambda: SETTINGS.rag.retrieval.final_chunk_count)

    # Embedding
    embed_batch: int = field(default_factory=lambda: SETTINGS.rag.embed.batch_size)
    embed_model: str = field(default_factory=lambda: SETTINGS.rag.embed.model)

    # Reranker
    rerank_model: str = field(default_factory=lambda: SETTINGS.rag.rerank_model)

    # LLM
    llm_url: str = field(default_factory=lambda: SETTINGS.rag.llm.url)
    llm_model: str = field(default_factory=lambda: SETTINGS.rag.llm.model)
    llm_stream: bool = field(default_factory=lambda: SETTINGS.rag.llm.stream)
    llm_num_predict: int = field(default_factory=lambda: SETTINGS.rag.llm.num_predict)


CFG = Config()

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("rag.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("srm_rag")


# ================= PAGE CLASSIFICATION & METADATA EXTRACTION =================

_TIER_RULES: list[tuple[str, list[str]]] = [
    ("tier1_admission", [
        "/admission-india/", "/admission-international/", "/program/",
        "/fee-structure", "/srmjeee", "/eligibility",
    ]),
    ("tier2_academic", [
        "/department/", "/college/", "/school-of-", "/about-us/",
        "/life-at-srm/", "/hostel", "/placement", "/faculty/", "/lab/",
        "/career-centre", "/directorate",
    ]),
    ("tier3_content", [
        "/events/", "/blog/", "/sports/",
    ]),
]

_NOISE_PATTERNS = [
    re.compile(r"/category/", re.I),
    re.compile(r"/tag/", re.I),
    re.compile(r"/page/\d", re.I),
    re.compile(r"/author/", re.I),
]

_ENTITY_TYPE_RULES: list[tuple[str, str]] = [
    ("/admission-india/", "admission"),
    ("/admission-international/", "admission"),
    ("/program/", "program"),
    ("/department/", "department"),
    ("/college/", "college"),
    ("/faculty/", "faculty"),
    ("/lab/", "lab"),
    ("/events/", "event"),
    ("/blog/", "article"),
    ("/sports/", "sports"),
    ("/life-at-srm/", "campus_life"),
    ("/career-centre", "placement"),
    ("/hostel", "facility"),
]

_CAMPUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bkattankulathur\b|\bktr\b", re.I), "KTR"),
    (re.compile(r"\bramapuram\b|\brmp\b", re.I), "Ramapuram"),
    (re.compile(r"\bvadapalani\b|\bvdp\b", re.I), "Vadapalani"),
    (re.compile(r"\bghaziabad\b|\bdelhi[\s-]?ncr\b|\bncr\b", re.I), "Delhi-NCR"),
    (re.compile(r"\btiruchirappalli\b|\btrichy\b", re.I), "Tiruchirappalli"),
]

_LEVEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bb\.?\s*tech\b|\bbtech\b", re.I), "UG"),
    (re.compile(r"\bb\.?\s*arch\b|\bb\.?\s*des\b|\bb\.?\s*sc\b|\bbba\b|\bb\.?\s*com\b", re.I), "UG"),
    (re.compile(r"\bm\.?\s*tech\b|\bmtech\b|\bm\.?\s*sc\b|\bmba\b|\bmca\b|\bm\.?\s*arch\b", re.I), "PG"),
    (re.compile(r"\bph\.?\s*d\b|\bdoctoral\b", re.I), "PhD"),
]


def classify_page_tier(url: str) -> str:
    url_lower = url.lower()
    if "applications.srmist.edu.in" in url_lower or "intlapplications.srmist.edu.in" in url_lower:
        return "tier1_admission"
    for tier, patterns in _TIER_RULES:
        if any(p in url_lower for p in patterns):
            return tier
    return "tier2_academic"


def is_noise_page(url: str) -> bool:
    return any(p.search(url) for p in _NOISE_PATTERNS)


def extract_entity_type(url: str) -> str:
    url_lower = url.lower()
    if "applications.srmist.edu.in" in url_lower or "intlapplications.srmist.edu.in" in url_lower:
        return "admission"
    for pattern, entity_type in _ENTITY_TYPE_RULES:
        if pattern in url_lower:
            return entity_type
    return "general"


def extract_campus(url: str, content: str) -> str:
    text = f"{url} {content[:500]}"
    for pattern, campus in _CAMPUS_PATTERNS:
        if pattern.search(text):
            return campus
    return "KTR"


def extract_program_level(url: str, content: str) -> str:
    text = f"{url} {content[:300]}"
    for pattern, level in _LEVEL_PATTERNS:
        if pattern.search(text):
            return level
    return ""


def extract_parent_entity(url: str) -> str:
    """Infer organizational parent from URL path hierarchy."""
    parts = [p for p in url.lower().split("/") if p]
    if "department" in parts:
        idx = parts.index("department")
        if idx + 1 < len(parts):
            dept_slug = parts[idx + 1]
            return dept_slug.replace("department-of-", "").replace("-", " ").strip().title()
    if "college" in parts:
        idx = parts.index("college")
        if idx + 1 < len(parts):
            return parts[idx + 1].replace("-", " ").strip().title()
    if "admission-india" in parts:
        idx = parts.index("admission-india")
        if idx + 1 < len(parts):
            return parts[idx + 1].replace("-", " ").strip().title()
    return ""


def compute_page_authority(url: str, entity_type: str) -> float:
    """Score how authoritative a page is within SRM's hierarchy."""
    stripped = re.sub(r"^https?://(?:www\.)?srmist\.edu\.in", "", url.rstrip("/"))
    depth = len([p for p in stripped.split("/") if p])

    if entity_type in ("department", "college", "admission"):
        if depth <= 2:
            return 1.0
        if depth == 3:
            return 0.7
        return 0.5
    if entity_type == "program":
        return 0.9 if depth <= 2 else 0.6
    if entity_type == "faculty":
        return 0.6
    if entity_type == "event":
        return 0.4
    if entity_type == "article":
        return 0.3
    return 0.5


# ================= ABBREVIATION EXPANSION =================

ABBREVIATIONS: dict[str, str] = {
    "cintel":   "computational intelligence",
    "nwc":      "networking and communications",
    "ctech":    "computing technologies",
    "dsbs":     "data science and business systems",
    "cse":      "computer science engineering",
    "ece":      "electronics and communication engineering",
    "eee":      "electrical and electronics engineering",
    "mech":     "mechanical engineering",
    "civil":    "civil engineering",
    "it":       "information technology",
    "biotech":  "biotechnology",
    "biomed":   "biomedical engineering",
    "aiml":     "artificial intelligence machine learning",
    "aids":     "artificial intelligence data science",
    "cyber":    "cyber security",
    "vlsi":     "vlsi design",
    "auto":     "automobile engineering",
    "aero":     "aerospace engineering",
    "chem":     "chemical engineering",
    "robotics": "robotics and automation",
    "iot":      "internet of things",
    "hod":      "head of department",
    "vc":       "vice chancellor",
    "dc":       "dean campus",
    "srmjeee":  "srm joint engineering entrance examination",
    "jee":      "joint entrance examination",
    "neet":     "national eligibility cum entrance test",
    "gate":     "graduate aptitude test in engineering",
    "cat":      "common admission test",
    "gmat":     "graduate management admission test",
    "ktr":      "kattankulathur campus",
    "vdp":      "vadapalani campus",
    "rmp":      "ramapuram campus",
    "ncr":      "delhi ncr campus",
    "pg":       "postgraduate",
    "ug":       "undergraduate",
    "btech":    "bachelor of technology",
    "mtech":    "master of technology",
    "phd":      "doctor of philosophy",
    "mba":      "master of business administration",
    "mca":      "master of computer applications",
    "nri":      "non resident indian",
    "dept":     "department",
    "sem":      "semester",
}

_ABBREV_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(ABBREVIATIONS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def expand_abbreviations(text: str) -> str:
    def _replace(match: re.Match) -> str:
        abbr = match.group(0)
        full = ABBREVIATIONS.get(abbr.lower(), abbr)
        if abbr.lower() == full.lower():
            return abbr
        return f"{abbr} ({full})"
    return _ABBREV_PATTERN.sub(_replace, text)


# ================= QUERY REFORMULATION =================

_QUERY_SYNONYMS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\badmission\s+dates?\b", re.I),
     "admission dates when to apply last date application deadline schedule timeline"),
    (re.compile(r"\bfee(?:s)?\s+structure\b", re.I),
     "fee structure tuition fees semester fees cost of studying"),
    (re.compile(r"\bplacements?\b", re.I),
     "placements campus recruitment placement statistics companies hiring"),
    (re.compile(r"\bhostel\b", re.I),
     "hostel accommodation rooms facilities mess"),
    (re.compile(r"\bscholarship(?:s)?\b", re.I),
     "scholarship financial aid merit scholarship fee waiver"),
    (re.compile(r"\beligibility\b", re.I),
     "eligibility criteria requirements qualifications minimum marks"),
    (re.compile(r"\bcutoff|cut[\s-]off\b", re.I),
     "cutoff cut-off minimum score rank required marks"),
    (re.compile(r"\bcampus\s+life\b", re.I),
     "campus life student activities clubs events cultural fests"),
]


def reformulate_query(query: str) -> str:
    extra: list[str] = []
    for pattern, synonyms in _QUERY_SYNONYMS:
        if pattern.search(query):
            extra.append(synonyms)
    if extra:
        return f"{query} {' '.join(extra)}"
    return query


# ================= QUERY PREPROCESSING =================

def preprocess_query(question: str) -> str:
    processed = expand_abbreviations(question)
    processed = reformulate_query(processed)
    log.debug(f"Preprocessed query: {question!r} → {processed!r}")
    return processed


# ================= QUERY INTENT =================

_ADMISSION_TERMS = re.compile(r"\b(admission|admissions|apply|application|enrol(?:l|)ment)\b", re.I)
_DATE_TERMS = re.compile(r"\b(when|date|opening|open|start|starts|starting|timeline|schedule|deadline|last\s+date)\b", re.I)
_HOW_TO_APPLY_TERMS = re.compile(r"\b(how\s+to\s+apply|application\s+process|apply\s+for)\b", re.I)
_BTECH_TERMS = re.compile(r"\b(b\.?\s*tech|btech|b\.?\s*e\.?|be)\b", re.I)

_ELIGIBILITY_SIGNAL = re.compile(
    r"(should\s+have\s+attained\s+the\s+age|31st\s+of?\s+july|12th\s+board\s+examination|nationality\s+and\s+age)",
    re.I,
)
_ADMISSION_DATE_SIGNAL = re.compile(
    r"(admissions?\s+(?:open|opening|start|starts)|application\s+(?:open|opens|start|starts)|important\s+dates?|last\s+date|registration\s+(?:open|starts?))",
    re.I,
)
_SRMJEEE_SIGNAL = re.compile(r"\bsrmje{2,3}\b|\bsrm\s*j[e]{2,3}\b", re.I)
_CET_SIGNAL = re.compile(r"\bcet\b", re.I)

_LISTING_SIGNAL = re.compile(
    r"\b(list|what are|which|how many|all|available|departments?\s+under|programs?\s+offered)\b",
    re.I,
)
_COMPARISON_SIGNAL = re.compile(
    r"\b(compare|comparison|vs\.?|versus|better|difference between|which is)\b",
    re.I,
)
_PROCEDURAL_SIGNAL = re.compile(
    r"\b(how to|how do i|steps|process|procedure|what are the steps)\b",
    re.I,
)
_PERSON_SIGNAL = re.compile(
    r"\b(who is|tell me about dr|prof\.|professor|faculty|hod|head of|dean)\b",
    re.I,
)
_ROLE_QUERY_SIGNAL = re.compile(
    r"\b(hod|head\s+of\s+(?:the\s+)?department|head\s+of|chairperson|chair\s+person|department\s+head)\b",
    re.I,
)
_ROLE_QUERY_HINTS = (
    "head of department HOD chairperson faculty profile contact email phone department office"
)


def classify_query_type(question: str) -> str:
    q = question.strip()
    if _PERSON_SIGNAL.search(q):
        return "person_lookup"
    if _COMPARISON_SIGNAL.search(q):
        return "comparison"
    if _LISTING_SIGNAL.search(q):
        return "listing"
    if _PROCEDURAL_SIGNAL.search(q):
        return "procedural"
    return "factual"


def detect_intent(question: str) -> dict[str, bool]:
    q = question.strip()
    is_btech = bool(_BTECH_TERMS.search(q))
    has_admission = bool(_ADMISSION_TERMS.search(q))
    has_date = bool(_DATE_TERMS.search(q))

    is_admission_date = has_admission and has_date
    if not is_admission_date and is_btech and has_date:
        is_admission_date = True

    return {
        "is_admission_date_query": is_admission_date,
        "is_how_to_apply_query": bool(_HOW_TO_APPLY_TERMS.search(q) and has_admission),
        "is_btech_query": is_btech,
        "query_type": classify_query_type(q),
        "is_role_query": bool(_ROLE_QUERY_SIGNAL.search(q)),
    }


def build_retrieval_query(question: str, intent: dict[str, bool]) -> str:
    expanded = question.strip()
    hints: list[str] = []

    if intent.get("is_admission_date_query"):
        hints.append("official admission schedule important dates application opening date")

    if intent.get("is_how_to_apply_query"):
        hints.append("official admission process steps online application registration")
        if intent.get("is_btech_query"):
            hints.append("SRMJEEE UG entrance exam for B.Tech")

    if intent.get("is_role_query"):
        hints.append(_ROLE_QUERY_HINTS)

    if hints:
        expanded = f"{expanded} {' '.join(hints)}"

    return expanded


def filter_chunks_for_intent(
    chunks: list[tuple[str, dict, float]],
    intent: dict[str, bool],
    question: str = "",
) -> list[tuple[str, dict, float]]:
    filtered = chunks

    if intent.get("is_admission_date_query"):
        filtered = []
        for item in chunks:
            doc = item[0]
            has_eligibility_only_signal = bool(_ELIGIBILITY_SIGNAL.search(doc)) and not bool(
                _ADMISSION_DATE_SIGNAL.search(doc)
            )
            if has_eligibility_only_signal:
                continue
            filtered.append(item)

    if intent.get("is_how_to_apply_query") and intent.get("is_btech_query"):
        srmjeee_chunks = [item for item in filtered if _SRMJEEE_SIGNAL.search(item[0])]
        non_cet_chunks = [item for item in filtered if not _CET_SIGNAL.search(item[0])]

        if srmjeee_chunks:
            filtered = srmjeee_chunks + [item for item in non_cet_chunks if item not in srmjeee_chunks]
        elif non_cet_chunks:
            filtered = non_cet_chunks

        def apply_priority(item: tuple[str, dict, float]) -> tuple[int, int, int]:
            doc, meta, _ = item
            source = str(meta.get("source", "")).lower()
            return (
                1 if _SRMJEEE_SIGNAL.search(doc) else 0,
                1 if "admission" in source else 0,
                0 if _CET_SIGNAL.search(doc) else 1,
            )

        filtered = sorted(filtered, key=apply_priority, reverse=True)

    if intent.get("is_role_query"):
        def apply_role_priority(item: tuple[str, dict, float]) -> tuple[int, int, float]:
            doc, meta, score = item
            entity_type = meta.get("entity_type", "")
            parent_entity = meta.get("parent_entity", "").lower()
            parent_match = 1 if parent_entity and parent_entity in question.lower() else 0
            type_match = 1 if entity_type in {"department", "faculty"} else 0
            return (parent_match, type_match, score)

        filtered = sorted(filtered, key=apply_role_priority, reverse=True)

    return filtered or chunks


# ================= MODELS =================

@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    log.info(f"Loading embedding model: {CFG.embed_model}")
    return SentenceTransformer(CFG.embed_model)


@lru_cache(maxsize=1)
def get_reranker() -> Optional[CrossEncoder]:
    try:
        log.info(f"Loading reranker: {CFG.rerank_model}")
        return CrossEncoder(CFG.rerank_model)
    except Exception as e:
        log.warning(f"Reranker unavailable: {e}")
        return None


# ================= KNOWLEDGE GRAPH =================

_knowledge_graph: KnowledgeGraph | None = None
_KG_PATH = Path(SETTINGS.rag.vector_db_path) / "knowledge_graph.json"
_admission_profiles: dict[str, dict] | None = None
_ADMISSION_PROFILE_PATH = Path(SETTINGS.rag.vector_db_path) / "admission_profiles.json"


def get_knowledge_graph() -> KnowledgeGraph | None:
    global _knowledge_graph
    if _knowledge_graph is None and _KG_PATH.exists():
        try:
            _knowledge_graph = KnowledgeGraph.load(str(_KG_PATH))
        except Exception as e:
            log.warning(f"Could not load KG: {e}")
    return _knowledge_graph


def get_admission_profiles() -> dict[str, dict]:
    global _admission_profiles
    if _admission_profiles is None and _ADMISSION_PROFILE_PATH.exists():
        try:
            _admission_profiles = load_admission_profiles(str(_ADMISSION_PROFILE_PATH))
        except Exception as e:
            log.warning(f"Could not load admission profiles: {e}")
            _admission_profiles = {}
    return _admission_profiles or {}


# ================= VECTOR DB (Qdrant) =================

_qdrant_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(path=CFG.vector_db_path)
    return _qdrant_client


def get_collection_count() -> int:
    client = get_qdrant_client()
    try:
        info = client.get_collection(CFG.collection_name)
        return info.points_count or 0
    except Exception:
        return 0


# ================= SPARSE VECTORIZER (BM25) =================

_TOKENIZE_RE = re.compile(r"[a-zA-Z0-9]+")


class SparseVectorizer:
    """BM25-based sparse vector generator for hybrid search."""

    def __init__(self):
        self._vocab: dict[str, int] = {}
        self._idf: dict[int, float] = {}
        self._avgdl: float = 0.0
        self._corpus_size: int = 0

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return _TOKENIZE_RE.findall(text.lower())

    def fit(self, corpus: list[str]) -> None:
        tokenized = [self._tokenize(doc) for doc in corpus]
        vocab: dict[str, int] = {}
        df: Counter = Counter()

        for tokens in tokenized:
            unique = set(tokens)
            for t in unique:
                if t not in vocab:
                    vocab[t] = len(vocab)
                df[t] += 1

        self._vocab = vocab
        self._corpus_size = len(tokenized)
        self._avgdl = sum(len(t) for t in tokenized) / max(len(tokenized), 1)

        self._idf = {}
        for term, term_id in vocab.items():
            n = df[term]
            self._idf[term_id] = math.log(
                (self._corpus_size - n + 0.5) / (n + 0.5) + 1.0
            )

    def encode_document(self, doc: str) -> models.SparseVector:
        tokens = self._tokenize(doc)
        tf: Counter = Counter(tokens)
        dl = len(tokens)
        k1, b = 1.5, 0.75

        indices, values = [], []
        for term, count in tf.items():
            tid = self._vocab.get(term)
            if tid is None:
                continue
            idf = self._idf.get(tid, 0.0)
            tf_norm = (count * (k1 + 1)) / (
                count + k1 * (1 - b + b * dl / max(self._avgdl, 1))
            )
            score = idf * tf_norm
            if score > 0:
                indices.append(tid)
                values.append(float(score))

        if not indices:
            indices, values = [0], [0.0]
        return models.SparseVector(indices=indices, values=values)

    def encode_query(self, query: str) -> models.SparseVector:
        tokens = self._tokenize(query)
        tf: Counter = Counter(tokens)

        indices, values = [], []
        for term, count in tf.items():
            tid = self._vocab.get(term)
            if tid is None:
                continue
            idf = self._idf.get(tid, 0.0)
            score = idf * count
            if score > 0:
                indices.append(tid)
                values.append(float(score))

        if not indices:
            indices, values = [0], [0.0]
        return models.SparseVector(indices=indices, values=values)

    def save(self, path: str) -> None:
        data = {
            "vocab": self._vocab,
            "idf": self._idf,
            "avgdl": self._avgdl,
            "corpus_size": self._corpus_size,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._vocab = data["vocab"]
        self._idf = data["idf"]
        self._avgdl = data["avgdl"]
        self._corpus_size = data["corpus_size"]


_sparse_vectorizer: SparseVectorizer | None = None
_SPARSE_MODEL_PATH = Path(SETTINGS.rag.vector_db_path) / "sparse_vectorizer.pkl"


def get_sparse_vectorizer() -> SparseVectorizer | None:
    global _sparse_vectorizer
    if _sparse_vectorizer is None and _SPARSE_MODEL_PATH.exists():
        _sparse_vectorizer = SparseVectorizer()
        _sparse_vectorizer.load(str(_SPARSE_MODEL_PATH))
        log.info("Loaded sparse vectorizer from disk.")
    return _sparse_vectorizer


# ================= TEXT UTILS =================

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


# ================= DATA LOADERS =================

def load_tables(folder: Path) -> str:
    table_dir = folder / "tables"
    if not table_dir.exists():
        return ""

    parts = []
    for csv_file in sorted(table_dir.glob("table_*.csv")):
        try:
            with open(csv_file, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            if rows:
                parts.append("\n".join(" | ".join(row) for row in rows))
        except Exception as e:
            log.debug(f"Table read error {csv_file}: {e}")

    return "\n\n".join(parts)


def load_infobox(folder: Path) -> str:
    infobox_file = folder / "infobox.json"
    if not infobox_file.exists():
        return ""
    try:
        data: dict = json.loads(infobox_file.read_text(encoding="utf-8"))
        return "\n".join(f"{k}: {v}" for k, v in data.items())
    except Exception as e:
        log.debug(f"Infobox read error {folder}: {e}")
        return ""


import concurrent.futures


def _load_single_page(folder: Path) -> dict | None:
    if not folder.is_dir():
        return None

    content_file = folder / "content.txt"
    meta_file = folder / "metadata.json"

    if not content_file.exists() or not meta_file.exists():
        return None

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Bad metadata in {folder}: {e}")
        return None

    url = meta.get("url", "")
    if is_noise_page(url):
        return {"noise": True}

    return {
        "folder": folder,
        "content": content_file.read_text(encoding="utf-8"),
        "meta": meta,
        "table_text": load_tables(folder),
        "infobox_text": load_infobox(folder),
    }


def load_pages() -> list[dict]:
    log.info(f"Starting to load pages from {CFG.data_path}...")
    if not CFG.data_path.exists():
        log.error(f"Data path not found: {CFG.data_path}")
        return []

    pages = []
    skipped_noise = 0
    folders = list(CFG.data_path.iterdir())

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
        results = list(executor.map(_load_single_page, folders))

    for res in results:
        if res is None:
            continue
        if "noise" in res:
            skipped_noise += 1
        else:
            pages.append(res)

    log.info(f"Loaded {len(pages)} pages from {CFG.data_path} (skipped {skipped_noise} noise pages)")
    return pages


# ================= BUILD VECTOR DB =================

def _already_indexed(client: QdrantClient, collection_name: str, url: str) -> bool:
    try:
        result = client.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(
                    key="source",
                    match=models.MatchValue(value=url),
                )]
            ),
            limit=1,
        )
        return len(result[0]) > 0
    except Exception:
        return False


def _semantic_split(text: str, max_size: int, min_size: int) -> list[str]:
    sections = re.split(r"\n(?=#{1,3}\s)|\n\s*\n|\n(?=[A-Z][A-Za-z\s]{5,100}:)", text)

    chunks: list[str] = []
    current = ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(current) + len(section) + 2 <= max_size:
            current = f"{current}\n\n{section}" if current else section
        else:
            if current and len(current) >= min_size:
                chunks.append(current.strip())
            current = section if len(section) <= max_size else section[:max_size]
    if current and len(current) >= min_size:
        chunks.append(current.strip())

    if not chunks and text.strip():
        fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_size,
            chunk_overlap=min(100, max_size // 5),
        )
        chunks = [c for c in fallback_splitter.split_text(text) if len(c) >= min_size]

    return chunks


_PARENT_CHUNK_MAX = 2000


def _deterministic_id(seed: str) -> str:
    return str(uuid.UUID(hashlib.md5(seed.encode("utf-8")).hexdigest()))


def _build_chunks(pages: list[dict]) -> tuple[list[str], list[dict], dict[str, str]]:
    docs: list[str] = []
    metas: list[dict] = []
    point_id_map: dict[str, str] = {}

    log.info(f"Starting to build chunks for {len(pages)} pages...")
    for i, page in enumerate(pages):
        if i > 0 and i % 500 == 0:
            log.info(f"Chunked {i}/{len(pages)} pages...")
        meta = page["meta"]
        url = meta.get("url", "")
        title = meta.get("title", "SRM Page")
        description = meta.get("meta", {}).get("og:description", "")
        content = page["content"]

        header = f"Title: {title}\nURL: {url}"
        if description:
            header += f"\nDescription: {description}"

        page_tier = classify_page_tier(url)
        entity_type = extract_entity_type(url)
        campus = extract_campus(url, content)
        program_level = extract_program_level(url, content)
        parent_entity = extract_parent_entity(url)
        authority = compute_page_authority(url, entity_type)

        base_meta = {
            "source": url,
            "title": title,
            "scraped_at": meta.get("scraped_at", ""),
            "page_tier": page_tier,
            "entity_type": entity_type,
            "campus": campus,
            "page_authority": authority,
            "program_level": program_level,
            "parent_entity": parent_entity,
        }

        parent_point_id = _deterministic_id(url + "::parent")

        full_text = content
        if page["table_text"]:
            full_text += "\n\n" + page["table_text"]
        if page["infobox_text"]:
            full_text += "\n\n" + page["infobox_text"]
        parent_text = clean(f"{header}\n\n{full_text[:_PARENT_CHUNK_MAX]}")
        docs.append(parent_text)
        metas.append({
            **base_meta,
            "chunk_type": "text",
            "chunk_level": "parent",
            "parent_point_id": "",
        })
        point_id_map[parent_point_id] = "parent"

        def add_child_chunks(text: str, chunk_type: str):
            for ci, chunk in enumerate(_semantic_split(text, CFG.chunk_size, CFG.min_chunk_length)):
                enriched = clean(f"{header}\n\n{chunk}")
                child_id = _deterministic_id(f"{url}::child::{chunk_type}::{ci}")
                docs.append(enriched)
                metas.append({
                    **base_meta,
                    "chunk_type": chunk_type,
                    "chunk_level": "child",
                    "parent_point_id": parent_point_id,
                })
                point_id_map[child_id] = "child"

        add_child_chunks(content, "text")
        if page["table_text"]:
            add_child_chunks(page["table_text"], "table")
        if page["infobox_text"]:
            add_child_chunks(page["infobox_text"], "infobox")

    log.info(f"Total chunks: {len(docs)} (parents + children)")
    return docs, metas, point_id_map


DB_SCHEMA_VERSION = "v4.0-kg-hierarchical"


def _check_db_version(client: QdrantClient, collection_name: str) -> bool:
    try:
        result = client.scroll(collection_name=collection_name, limit=1)
        points = result[0]
        if points:
            payload = points[0].payload or {}
            has_v31 = "page_tier" in payload and "entity_type" in payload
            has_v40 = "chunk_level" in payload and "page_authority" in payload
            if not has_v31 or not has_v40:
                missing = []
                if not has_v31:
                    missing.append("page_tier/entity_type")
                if not has_v40:
                    missing.append("chunk_level/page_authority")
                log.warning(
                    f"Existing DB missing {', '.join(missing)}. "
                    f"Run with --rebuild to re-index with {DB_SCHEMA_VERSION} features."
                )
                return False
    except Exception:
        pass
    return True


# BGE-M3 outputs 1024-dim embeddings (not 384 like MiniLM).
# If you ever swap the embed model, update this constant to match.
_EMBED_DIM = 384


def _ensure_collection(client: QdrantClient, force_rebuild: bool) -> None:
    exists = client.collection_exists(CFG.collection_name)

    if force_rebuild and exists:
        client.delete_collection(CFG.collection_name)
        log.info("Deleted existing collection for full rebuild.")
        exists = False

    if not exists:
        client.create_collection(
            collection_name=CFG.collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=_EMBED_DIM,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(),
            },
        )
        for field_name, schema in [
            ("source", models.PayloadSchemaType.KEYWORD),
            ("campus", models.PayloadSchemaType.KEYWORD),
            ("entity_type", models.PayloadSchemaType.KEYWORD),
            ("page_tier", models.PayloadSchemaType.KEYWORD),
            ("chunk_level", models.PayloadSchemaType.KEYWORD),
            ("parent_point_id", models.PayloadSchemaType.KEYWORD),
            ("page_authority", models.PayloadSchemaType.FLOAT),
        ]:
            client.create_payload_index(
                collection_name=CFG.collection_name,
                field_name=field_name,
                field_schema=schema,
            )
        log.info(
            f"Created Qdrant collection '{CFG.collection_name}' "
            f"with dense({_EMBED_DIM}d)+sparse vectors and v4.0 indexes."
        )


def build_db(force_rebuild: bool = False):
    global _sparse_vectorizer, _knowledge_graph, _admission_profiles

    client = get_qdrant_client()
    _ensure_collection(client, force_rebuild)

    if not force_rebuild:
        _check_db_version(client, CFG.collection_name)

    embedder = get_embedder()

    pages = load_pages()
    if not pages:
        log.error("No pages found — run the scraper first.")
        return

    log.info("Building Knowledge Graph...")
    _knowledge_graph = build_knowledge_graph(pages)
    _knowledge_graph.save(str(_KG_PATH))
    _admission_profiles = getattr(_knowledge_graph, "admission_profiles", {}) or {}
    save_admission_profiles(_admission_profiles, str(_ADMISSION_PROFILE_PATH))
    log.info(f"Knowledge Graph: {_knowledge_graph.stats()}")

    if force_rebuild:
        new_pages = pages
    else:
        new_pages = [
            p for p in pages
            if not _already_indexed(client, CFG.collection_name, p["meta"].get("url", ""))
        ]
    log.info(f"New pages to index: {len(new_pages)} / {len(pages)} total")

    if not new_pages:
        log.info("Nothing new to index. DB is up to date.")
        return

    docs, metas, point_id_map = _build_chunks(new_pages)
    log.info(f"Chunks to embed: {len(docs)}")

    log.info(f"Starting dense embeddings (batch={CFG.embed_batch})...")
    all_embeddings: list[list[float]] = []
    for i in range(0, len(docs), CFG.embed_batch):
        batch = docs[i: i + CFG.embed_batch]
        all_embeddings.extend(
            embedder.encode(
                batch,
                batch_size=CFG.embed_batch,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).tolist()
        )
        log.info(f"Dense embed: {min(i + CFG.embed_batch, len(docs))}/{len(docs)} chunks")

    log.info("Starting sparse embeddings...")
    sparse_vec = SparseVectorizer()
    sparse_vec.fit(docs)
    sparse_vectors = [sparse_vec.encode_document(doc) for doc in docs]

    sparse_path = Path(CFG.vector_db_path) / "sparse_vectorizer.pkl"
    sparse_path.parent.mkdir(parents=True, exist_ok=True)
    sparse_vec.save(str(sparse_path))
    _sparse_vectorizer = sparse_vec
    log.info(f"Sparse vectorizer fitted on {len(docs)} docs, vocab size: {len(sparse_vec._vocab)}")

    existing_count = get_collection_count()
    BATCH = 100

    for i in range(0, len(docs), BATCH):
        end = min(i + BATCH, len(docs))
        points = []
        for j in range(i, end):
            point_id = existing_count + j
            points.append(models.PointStruct(
                id=point_id,
                vector={
                    "dense": all_embeddings[j],
                    "sparse": sparse_vectors[j],
                },
                payload={
                    **metas[j],
                    "document": docs[j],
                },
            ))
        client.upsert(collection_name=CFG.collection_name, points=points)
        log.info(f"Upsert: {end}/{len(docs)} chunks")

    log.info(f"Indexed {len(docs)} chunks into Qdrant collection '{CFG.collection_name}'")


# ================= RETRIEVE =================

def _build_query_filter(campus: str | None) -> models.Filter | None:
    if not campus or campus == "KTR":
        return None
    return models.Filter(must=[
        models.FieldCondition(
            key="campus",
            match=models.MatchValue(value=campus),
        )
    ])


def _qdrant_results_to_candidates(
    results, score_threshold: float
) -> list[tuple[str, dict, float]]:
    candidates = []
    for point in results.points:
        score = point.score or 0.0
        if score < score_threshold:
            continue
        payload = dict(point.payload or {})
        doc = payload.pop("document", "")
        candidates.append((doc, payload, score))
    return candidates


def retrieve(
    query: str,
    *,
    campus: str | None = None,
    boost_admission: bool = False,
    intent: dict | None = None,
) -> list[tuple[str, dict, float]]:
    return retrieve_with_overrides(
        query=query, campus=campus, boost_admission=boost_admission, intent=intent
    )


def retrieve_with_overrides(
    query: str,
    *,
    retrieval_limit: int | None = None,
    max_distance: float | None = None,
    final_chunk_count: int | None = None,
    campus: str | None = None,
    boost_admission: bool = False,
    intent: dict | None = None,
) -> list[tuple[str, dict, float]]:
    client = get_qdrant_client()
    embedder = get_embedder()
    sparse_vec = get_sparse_vectorizer()

    query_embed = embedder.encode(
        [query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).tolist()[0]

    n = retrieval_limit or CFG.retrieval_limit
    query_filter = _build_query_filter(campus)

    score_threshold = 0.0
    if max_distance is not None:
        score_threshold = 1.0 - max_distance

    prefetch_n = max(n * 2, 40)

    if sparse_vec:
        sparse_query = sparse_vec.encode_query(query)
        prefetch = [
            models.Prefetch(
                query=query_embed, using="dense", limit=prefetch_n, filter=query_filter,
            ),
            models.Prefetch(
                query=sparse_query, using="sparse", limit=prefetch_n, filter=query_filter,
            ),
        ]
        results = client.query_points(
            collection_name=CFG.collection_name,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=n,
            with_payload=True,
        )
    else:
        results = client.query_points(
            collection_name=CFG.collection_name,
            query=query_embed,
            using="dense",
            limit=n,
            query_filter=query_filter,
            with_payload=True,
        )

    candidates = _qdrant_results_to_candidates(results, score_threshold)

    if not candidates and query_filter:
        log.info(f"No results with campus filter {campus}; retrying without filter")
        if sparse_vec:
            sparse_query = sparse_vec.encode_query(query)
            prefetch = [
                models.Prefetch(query=query_embed, using="dense", limit=prefetch_n),
                models.Prefetch(query=sparse_query, using="sparse", limit=prefetch_n),
            ]
            results = client.query_points(
                collection_name=CFG.collection_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=n,
                with_payload=True,
            )
        else:
            results = client.query_points(
                collection_name=CFG.collection_name,
                query=query_embed,
                using="dense",
                limit=n,
                with_payload=True,
            )
        candidates = _qdrant_results_to_candidates(results, score_threshold)

    if not candidates:
        log.warning(f"No results for: {query!r}")
        return []

    reranker = get_reranker()
    if reranker and len(candidates) > 1:
        pairs = [(query, doc) for doc, _, _ in candidates]
        scores = reranker.predict(pairs).tolist()

        if boost_admission:
            _TIER_BOOST = {"tier1_admission": 1.5, "tier2_academic": 1.0, "tier3_content": 0.9}
            scores = [
                s * _TIER_BOOST.get(candidates[i][1].get("page_tier", ""), 1.0)
                for i, s in enumerate(scores)
            ]

        is_role_query = bool(intent and intent.get("is_role_query"))
        for i, s in enumerate(scores):
            authority = candidates[i][1].get("page_authority", 0.5)
            scores[i] = s * (0.5 + authority) if is_role_query else s * (0.8 + 0.2 * authority)

        candidates = sorted(
            zip([c[0] for c in candidates], [c[1] for c in candidates], scores),
            key=lambda x: x[2],
            reverse=True,
        )

    k = CFG.final_chunk_count if final_chunk_count is None else final_chunk_count
    final = _diverse_top_k(candidates, k, max_per_source=2)
    final = _fetch_parent_context(client, final)
    return final


def _fetch_parent_context(
    client: QdrantClient,
    chunks: list[tuple[str, dict, float]],
) -> list[tuple[str, dict, float]]:
    parent_ids_needed: set[str] = set()
    existing_sources: set[str] = set()

    for _, meta, _ in chunks:
        existing_sources.add(meta.get("source", ""))
        ppid = meta.get("parent_point_id", "")
        if ppid and meta.get("chunk_level") == "child":
            parent_ids_needed.add(ppid)

    if not parent_ids_needed:
        return chunks

    try:
        result = client.scroll(
            collection_name=CFG.collection_name,
            scroll_filter=models.Filter(must=[
                models.FieldCondition(
                    key="chunk_level",
                    match=models.MatchValue(value="parent"),
                ),
            ]),
            limit=100,
            with_payload=True,
        )
        parent_lookup: dict[str, tuple[str, dict]] = {}
        for point in result[0]:
            payload = dict(point.payload or {})
            source = payload.get("source", "")
            parent_lookup[source] = (payload.pop("document", ""), payload)
    except Exception as e:
        log.warning(f"Parent fetch failed: {e}")
        return chunks

    parent_chunks: list[tuple[str, dict, float]] = []
    seen_parent_sources: set[str] = set()
    for _, meta, _ in chunks:
        ppid = meta.get("parent_point_id", "")
        source = meta.get("source", "")
        if ppid and source and source not in seen_parent_sources:
            parent_data = parent_lookup.get(source)
            if parent_data:
                pdoc, pmeta = parent_data
                if pdoc and pdoc not in {c[0] for c in chunks}:
                    parent_chunks.append((pdoc, pmeta, 0.0))
                    seen_parent_sources.add(source)

    if parent_chunks:
        log.info(f"Prepended {len(parent_chunks)} parent chunks for context")

    return parent_chunks + chunks


def _diverse_top_k(
    candidates: list[tuple[str, dict, float]],
    k: int,
    max_per_source: int = 2,
) -> list[tuple[str, dict, float]]:
    selected: list[tuple[str, dict, float]] = []
    source_counts: dict[str, int] = {}

    for item in candidates:
        src = item[1].get("source", "")
        count = source_counts.get(src, 0)
        if count >= max_per_source:
            continue
        selected.append(item)
        source_counts[src] = count + 1
        if len(selected) >= k:
            break

    return selected


# ================= PROMPT =================

SYSTEM_PROMPT = """You are the official SRMIST (SRM Institute of Science and Technology) virtual assistant for the Kattankulathur campus.

YOUR TASK: Answer the student's question using ONLY the context provided below. Write a complete, helpful, well-structured answer.

RESPONSE STYLE:
- Write in a warm, professional tone — like a knowledgeable senior student helping a newcomer.
- Give COMPLETE answers. Do not cut short. If the context has details, include them ALL.
- Use **bold** for key terms, names, and important values (fees, dates, percentages).
- Use bullet points (- ) for lists of 3+ items.
- Use numbered steps (1. 2. 3.) for processes and procedures.
- Include specific numbers: fees in INR, percentages, dates, phone numbers — whatever the context provides.
- End with a helpful next-step when appropriate (e.g., "You can apply at..." or "For more details, visit...").

STRICT RULES:
- Answer ONLY from the provided context and Knowledge Graph data. Every claim must be grounded.
- If the context has NO relevant information, respond exactly: "I don't have enough information about this. Please visit https://www.srmist.edu.in or contact the SRM admissions office."
- Do NOT add a "Sources:" section — sources are handled by the system.
- NEVER invent names, fees, dates, or phone numbers not in the context.
- If Knowledge Graph data is present, treat it as the primary authority for names, roles, and org structure."""

_SOURCE_TAIL_RE = re.compile(
    r"(?:\n|^)\s*\*{0,2}sources?\*{0,2}\s*:.*", re.I | re.DOTALL
)

_FALLBACK_RE = re.compile(
    r"[\n\r]*\s*I don[''\u2019]?t have (?:enough |specific |)information"
    r".*?(?:contact\s+(?:the\s+)?(?:SRM\s+)?admissions|srmist\.edu\.in)[.!]?\s*",
    re.I | re.DOTALL,
)


def clean_answer_text(answer: str) -> str:
    cleaned = (answer or "").strip()
    if not cleaned:
        return cleaned

    cleaned = _SOURCE_TAIL_RE.sub("", cleaned).strip()
    cleaned = re.sub(
        r"\s+\*{0,2}sources?\*{0,2}\s*:\s*(?:\[[^\]]*\]\([^)]*\)|https?://\S+|\[\d+\]|,\s*)+\s*$",
        "",
        cleaned,
        flags=re.I,
    ).strip()

    candidate = _FALLBACK_RE.sub("", cleaned).strip()
    if len(candidate) >= 40:
        cleaned = candidate

    cleaned = re.sub(
        r"\s*(?:please\s+visit\s+)?or\s+contact\s+(?:the\s+)?(?:srm\s+)?admissions?\.?\s*$",
        "",
        cleaned,
        flags=re.I,
    ).strip()

    return cleaned


_QUERY_TYPE_INSTRUCTIONS = {
    "listing": (
        "FORMAT: The student wants a LIST. "
        "Write a brief intro sentence, then list EVERY item from the context as bullet points. "
        "Do NOT skip any items. Add a note if the list may not be exhaustive."
    ),
    "procedural": (
        "FORMAT: The student wants STEPS or a PROCESS. "
        "Write numbered steps in order (1. 2. 3. ...). "
        "Include specific requirements, documents, fees, exam names, and deadlines from the context."
    ),
    "comparison": (
        "FORMAT: The student wants a COMPARISON. "
        "Structure your answer with clear sections for each item being compared. "
        "Highlight key differences and similarities using bullet points."
    ),
    "person_lookup": (
        "FORMAT: The student is asking about a PERSON (faculty, HOD, dean). "
        "State their **full name**, **designation**, **department**, and any contact info found. "
        "If Knowledge Graph data is present, use it as the primary source for the person's name and role. "
        "If multiple sources conflict, prefer the department overview page over individual profile pages."
    ),
    "factual": (
        "FORMAT: Give a direct, specific answer. "
        "Lead with the key fact, then add supporting details. "
        "Include exact numbers (fees in INR, dates, percentages, contact numbers) from the context."
    ),
}


def compress_chunks(
    chunks: list[tuple[str, dict, float]],
    query: str,
    threshold: float = 0.25,
) -> list[tuple[str, dict, float]]:
    embedder = get_embedder()
    query_embed = embedder.encode(
        [query], normalize_embeddings=True, convert_to_numpy=True
    )[0]
    compressed = []

    for doc, meta, score in chunks:
        if meta.get("chunk_level") == "parent":
            compressed.append((doc, meta, score))
            continue

        sentences = re.split(r"(?<=[.!?])\s+", doc)
        if len(sentences) <= 3:
            compressed.append((doc, meta, score))
            continue

        sent_embeds = embedder.encode(
            sentences, normalize_embeddings=True, convert_to_numpy=True
        )
        similarities = np.dot(sent_embeds, query_embed) / (
            np.linalg.norm(sent_embeds, axis=1) * np.linalg.norm(query_embed) + 1e-8
        )

        relevant = [s for s, sim in zip(sentences, similarities) if sim >= threshold]
        if not relevant:
            compressed.append((doc, meta, score))
        else:
            compressed.append((" ".join(relevant), meta, score))

    return compressed


def build_prompt(
    question: str,
    chunks: list[tuple[str, dict, float]],
    query_type: str = "factual",
    kg_grounding: str = "",
) -> str:
    context_parts = []
    for i, (doc, meta, _) in enumerate(chunks, 1):
        context_parts.append(f"[{i}] (Source: {meta.get('source', 'N/A')})\n{doc}")

    context = "\n\n---\n\n".join(context_parts)
    type_instruction = _QUERY_TYPE_INSTRUCTIONS.get(query_type, "")

    kg_section = ""
    if kg_grounding:
        kg_section = (
            "\n=== KNOWLEDGE GRAPH (structured data — use as primary reference) ===\n"
            f"{kg_grounding}\n"
            "\nThe above is from the university's structured records. "
            "Use it as the primary answer and supplement with details from the context below. "
            "If context contradicts the KG data, prefer the KG data for role/listing information.\n"
        )

    parts = [SYSTEM_PROMPT, ""]
    if type_instruction:
        parts.append(type_instruction)
        parts.append("")
    if kg_section:
        parts.append(kg_section)
    parts.append("=== CONTEXT ===")
    parts.append(context)
    parts.append("")
    parts.append(f"=== STUDENT'S QUESTION ===\n{question}")
    parts.append("")
    parts.append("=== YOUR ANSWER (be thorough, use formatting, include all relevant details) ===")
    return "\n".join(parts)


# ================= LLM =================

class LLMError(Exception):
    """Raised when the LLM backend is unreachable or returns an error."""


def call_llm(prompt: str, stream: bool = CFG.llm_stream) -> str:
    try:
        r = requests.post(
            CFG.llm_url,
            json={
                "model": CFG.llm_model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "num_predict": CFG.llm_num_predict,
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "repeat_penalty": 1.15,
                },
            },
            stream=stream,
            timeout=120,
        )
        r.raise_for_status()

        if not stream:
            return r.json().get("response", "")

        full = []
        for line in r.iter_lines():
            if not line:
                continue
            try:
                token_data = json.loads(line)
                token = token_data.get("response", "")
                try:
                    print(token, end="", flush=True)
                except UnicodeEncodeError:
                    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
                    safe = token.encode(encoding, errors="replace").decode(encoding, errors="replace")
                    print(safe, end="", flush=True)
                full.append(token)
                if token_data.get("done"):
                    break
            except json.JSONDecodeError:
                continue

        print()
        return "".join(full)

    except requests.ConnectionError as e:
        log.error(f"LLM connection failed: {e}")
        raise LLMError("The language model is currently unavailable. Please try again in a moment.") from e
    except requests.Timeout as e:
        log.error(f"LLM request timed out: {e}")
        raise LLMError("The language model took too long to respond. Please try again.") from e
    except requests.RequestException as e:
        log.error(f"LLM request failed: {e}")
        raise LLMError("An error occurred while generating the answer. Please try again later.") from e


# ================= RAG QUERY =================

_GREETINGS = {"hi", "hello", "hey", "hii", "helo", "yo", "sup", "greetings"}

_FALLBACK_NO_CONTEXT = (
    "I couldn't find relevant information about that in my knowledge base. "
    "This topic may not be covered in my current data. "
    "Please visit https://www.srmist.edu.in or contact the SRM admissions office for help."
)

_FALLBACK_LLM_ERROR = (
    "I found some relevant information but encountered a technical issue while generating the answer. "
    "Please try again in a moment. If the problem persists, visit https://www.srmist.edu.in for help."
)

_ADMISSION_DATE_RETRY_HINTS = (
    "SRMJEEE B.Tech UG admission important dates application opening date "
    "registration start last date to apply admission timeline schedule phase"
)

_ADMISSION_QUERY_SIGNAL = re.compile(
    r"\b(admission|admissions|fee|fees|eligibility|srmjeee|entrance|scholarship|apply|application|"
    r"cutoff|cut[\s-]off|intake|counselling|seat)\b",
    re.I,
)

_PRONOUN_PATTERN = re.compile(
    r"\b(he|she|they|it|this|that|his|her|their|its|them|those|the same|above|previous)\b",
    re.I,
)


def _resolve_with_context(question: str, conversation_context: str) -> str:
    if not conversation_context:
        return question
    if not _PRONOUN_PATTERN.search(question):
        return question
    return f"[Previous conversation for context:\n{conversation_context}]\n\nCurrent question: {question}"


def query_rag(
    question: str,
    *,
    campus: str | None = None,
    conversation_context: str = "",
) -> dict:
    log.info(f"Query: {question!r}")
    t0 = time.time()

    if question.lower().strip().rstrip("!?.") in _GREETINGS:
        return {
            "answer": (
                "Hello! I'm the SRMIST Assistant. "
                "Ask me anything about SRM — admissions, fees, courses, departments, events, campus life, placements, research, and more!"
            ),
            "sources": [],
            "intent": "greeting",
        }

    contextualized_q = _resolve_with_context(question, conversation_context)
    if contextualized_q != question:
        log.info("Resolved pronouns with conversation context")

    processed_question = preprocess_query(contextualized_q)
    log.info(f"Preprocessed: {processed_question!r}")

    intent = detect_intent(processed_question)
    retrieval_query = build_retrieval_query(processed_question, intent)

    is_admission_query = bool(_ADMISSION_QUERY_SIGNAL.search(processed_question))
    query_type = intent.get("query_type", "factual")

    kg_grounding: str = ""
    kg = get_knowledge_graph()

    if kg:
        if query_type == "listing":
            kg_answer = kg.answer_listing_query(processed_question)
            if kg_answer:
                kg_grounding = kg_answer
                log.info(f"KG listing answer found: {kg_grounding[:100]}")
        elif query_type == "person_lookup" or intent.get("is_role_query"):
            kg_answer = kg.answer_role_query(processed_question)
            if kg_answer:
                kg_grounding = kg_answer
                log.info(f"KG role answer found: {kg_grounding}")

    if not kg_grounding and (is_admission_query or intent.get("is_how_to_apply_query")):
        admission_profiles = get_admission_profiles()
        if kg and admission_profiles:
            structured_admission = answer_admission_question(
                processed_question,
                campus=campus,
                kg=kg,
                profiles=admission_profiles,
            )
            if structured_admission:
                log.info("Structured admission answer found.")
                return structured_admission

    chunks = retrieve(
        retrieval_query, campus=campus, boost_admission=is_admission_query, intent=intent,
    )
    chunks = filter_chunks_for_intent(chunks, intent, processed_question)

    if not chunks:
        if kg_grounding:
            log.info("No vector results but KG has an answer; using KG-only response.")
            return {"answer": kg_grounding, "sources": [], "intent": query_type}
        log.warning(f"No context retrieved for: {question!r}")
        return {"answer": _FALLBACK_NO_CONTEXT, "sources": [], "intent": "no_context"}

    log.info(f"Retrieved {len(chunks)} chunks in {time.time() - t0:.2f}s")

    seen: set[str] = set()
    sources: list[str] = []
    for _, meta, _ in chunks:
        url = meta.get("source", "")
        if url and url not in seen:
            seen.add(url)
            sources.append(url)

    if intent.get("is_role_query") and not kg_grounding:
        context_text = " ".join(doc for doc, _, _ in chunks)
        if not _ROLE_QUERY_SIGNAL.search(context_text):
            log.warning(f"Role query grounding failed for {question!r}")
            return {"answer": _FALLBACK_NO_CONTEXT, "sources": [], "intent": "no_context"}

    chunks = compress_chunks(chunks, processed_question)

    prompt = build_prompt(question, chunks, query_type=query_type, kg_grounding=kg_grounding)
    try:
        answer = clean_answer_text(call_llm(prompt))
    except LLMError as e:
        log.error(f"LLM failed for query: {question!r} — {e}")
        return {"answer": _FALLBACK_LLM_ERROR, "sources": sources, "intent": "error"}

    if not answer or not answer.strip():
        log.warning(f"LLM returned empty answer for: {question!r}")
        return {"answer": _FALLBACK_LLM_ERROR, "sources": sources, "intent": "error"}

    # Retry 1: role query fallback
    if _FALLBACK_RE.search(answer) and _ROLE_QUERY_SIGNAL.search(processed_question):
        log.info("LLM fallback detected; retrying with role-expanded retrieval query.")
        retry_query = f"{processed_question} {_ROLE_QUERY_HINTS}"
        retry_chunks = retrieve_with_overrides(
            query=retry_query,
            retrieval_limit=max(CFG.retrieval_limit * 2, 25),
            max_distance=max(CFG.max_distance, 2.2),
            final_chunk_count=max(CFG.final_chunk_count + 3, 8),
        )
        retry_chunks = filter_chunks_for_intent(retry_chunks, intent, processed_question)

        if retry_chunks:
            retry_sources = list(dict.fromkeys(
                m.get("source", "") for _, m, _ in retry_chunks if m.get("source")
            ))
            retry_prompt = build_prompt(question, retry_chunks, query_type=query_type)
            try:
                retry_answer = clean_answer_text(call_llm(retry_prompt))
            except LLMError:
                retry_answer = ""

            if retry_answer and not _FALLBACK_RE.search(retry_answer):
                log.info("Retry succeeded; returning retry answer.")
                answer = retry_answer
                sources = retry_sources

    # Retry 2: admission date fallback
    if _FALLBACK_RE.search(answer) and intent["is_admission_date_query"]:
        log.info("LLM fallback detected; retrying with admission-date-expanded retrieval query.")
        retry_query = f"{processed_question} {_ADMISSION_DATE_RETRY_HINTS}"
        retry_chunks = retrieve_with_overrides(
            query=retry_query,
            retrieval_limit=max(CFG.retrieval_limit * 2, 30),
            max_distance=max(CFG.max_distance, 2.2),
            final_chunk_count=max(CFG.final_chunk_count + 3, 8),
        )
        retry_chunks = filter_chunks_for_intent(retry_chunks, intent, processed_question)

        if retry_chunks:
            retry_sources = list(dict.fromkeys(
                m.get("source", "") for _, m, _ in retry_chunks if m.get("source")
            ))
            retry_prompt = build_prompt(question, retry_chunks, query_type=query_type)
            try:
                retry_answer = clean_answer_text(call_llm(retry_prompt))
            except LLMError:
                retry_answer = ""

            if retry_answer and not _FALLBACK_RE.search(retry_answer):
                log.info("Admission-date retry succeeded; returning retry answer.")
                answer = retry_answer
                sources = retry_sources

    # Guardrail: age cut-off date vs admission opening date
    if intent["is_admission_date_query"] and re.search(r"\b31st\b.*\bjuly\b", answer, re.I):
        context_text = " ".join(doc for doc, _, _ in chunks)
        if bool(_ELIGIBILITY_SIGNAL.search(context_text)) and not bool(_ADMISSION_DATE_SIGNAL.search(context_text)):
            answer += (
                "\n\n**Note:** The 31st July reference above is an age-eligibility criterion, "
                "not an admission opening date. For the latest admissions timeline, "
                "please visit https://www.srmist.edu.in/admission-india/."
            )

    if intent["is_how_to_apply_query"] and intent["is_btech_query"]:
        if _CET_SIGNAL.search(answer) and not _SRMJEEE_SIGNAL.search(answer):
            answer += (
                "\n\n**Note:** For B.Tech admissions at SRMIST, the primary route is through "
                "**SRMJEEE (UG)**. Please verify the latest B.Tech application steps at "
                "https://www.srmist.edu.in/admission-india/."
            )

    if intent["is_admission_date_query"]:
        detected_intent = "admission_date"
    elif intent["is_how_to_apply_query"]:
        detected_intent = "how_to_apply"
    elif is_admission_query:
        detected_intent = "admission_query"
    else:
        detected_intent = query_type

    log.info(f"Total query time: {time.time() - t0:.2f}s | Intent: {detected_intent}")
    return {"answer": answer, "sources": sources, "intent": detected_intent}


# ================= MAIN =================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SRM RAG Pipeline")
    parser.add_argument("--build", action="store_true", help="Build / update the vector DB")
    parser.add_argument("--rebuild", action="store_true", help="Force full rebuild of vector DB")
    parser.add_argument("--query", type=str, help="Ask a question")
    args = parser.parse_args()

    if args.build or args.rebuild:
        build_db(force_rebuild=args.rebuild)

    if args.query:
        result = query_rag(args.query)
        if not CFG.llm_stream:
            print(result)
