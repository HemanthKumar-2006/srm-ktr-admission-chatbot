"""
SRM RAG Pipeline v2
- Aligned with scraper v2 output structure (content.txt / metadata.json / infobox.json / tables/*.csv)
- Reranker actually used (was loaded but never called in v1)
- Fixed collection scope bug
- MAX_DISTANCE filtering applied
- Incremental indexing (skip already-embedded pages)
- Infobox data ingested as dedicated chunks
- CSV tables read from tables/ subfolder (not missing tables.json)
- Source citations in every answer
- Streaming LLM support
- Structured logging + Config dataclass
- v2.1: Abbreviation expansion, query reformulation, granular fallbacks
"""

# ================= IMPORTS =================

import csv
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import chromadb
import requests
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import CrossEncoder, SentenceTransformer
from backend.settings import SETTINGS

# ================= CONFIG =================

@dataclass
class Config:
    data_path: Path = Path(SETTINGS.rag_data_path)
    vector_db_path: str = SETTINGS.rag_vector_db_path
    collection_name: str = SETTINGS.rag_collection_name

    # Chunking
    chunk_size: int = SETTINGS.rag_chunk_size
    chunk_overlap: int = SETTINGS.rag_chunk_overlap
    min_chunk_length: int = SETTINGS.rag_min_chunk_length

    # Retrieval
    retrieval_limit: int = SETTINGS.rag_retrieval_limit  # Candidates from vector DB
    max_distance: float = SETTINGS.rag_max_distance       # Filter out low-quality matches
    final_chunk_count: int = SETTINGS.rag_final_chunk_count  # Chunks sent to LLM after reranking

    # Embedding batch size
    embed_batch: int = SETTINGS.rag_embed_batch

    # Models
    embed_model: str = SETTINGS.rag_embed_model
    rerank_model: str = SETTINGS.rag_rerank_model

    # LLM
    llm_url: str = SETTINGS.rag_llm_url
    llm_model: str = SETTINGS.rag_llm_model
    llm_stream: bool = SETTINGS.rag_llm_stream

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


# ================= ABBREVIATION EXPANSION =================

ABBREVIATIONS: dict[str, str] = {
    # Academic departments / programs
    "cintel":      "computational intelligence",
    "nwc":         "networking and communications",
    "ctech":       "computing technologies",
    "dsbs":        "data science and business systems",
    "cse":         "computer science engineering",
    "ece":         "electronics and communication engineering",
    "eee":         "electrical and electronics engineering",
    "mech":        "mechanical engineering",
    "civil":       "civil engineering",
    "it":          "information technology",
    "biotech":     "biotechnology",
    "biomed":      "biomedical engineering",
    "aiml":        "artificial intelligence machine learning",
    "aids":        "artificial intelligence data science",
    "cyber":       "cyber security",
    "vlsi":        "vlsi design",
    "auto":        "automobile engineering",
    "aero":        "aerospace engineering",
    "chem":        "chemical engineering",
    "robotics":    "robotics and automation",
    "iot":         "internet of things",
    # Roles
    "hod":         "head of department",
    "vc":          "vice chancellor",
    "dc":          "dean campus",
    # Exams / processes
    "srmjeee":     "srm joint engineering entrance examination",
    "jee":         "joint entrance examination",
    "neet":        "national eligibility cum entrance test",
    "gate":        "graduate aptitude test in engineering",
    "cat":         "common admission test",
    "gmat":        "graduate management admission test",

    # Campus short-forms
    "ktr":         "kattankulathur campus",
    "vdp":         "vadapalani campus",
    "rmp":         "ramapuram campus",
    "ncr":         "delhi ncr campus",
    # Miscellaneous
    "pg":          "postgraduate",
    "ug":          "undergraduate",
    "btech":       "bachelor of technology",
    "mtech":       "master of technology",
    "phd":         "doctor of philosophy",
    "mba":         "master of business administration",
    "mca":         "master of computer applications",
    "nri":         "non resident indian",
    "dept":        "department",
    "sem":         "semester",
}

_ABBREV_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(ABBREVIATIONS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def expand_abbreviations(text: str) -> str:
    """Replace known abbreviations with their full forms while keeping the original term."""
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
    """Append synonym hints when key topic phrases are detected."""
    extra: list[str] = []
    for pattern, synonyms in _QUERY_SYNONYMS:
        if pattern.search(query):
            extra.append(synonyms)
    if extra:
        return f"{query} {' '.join(extra)}"
    return query


# ================= QUERY PREPROCESSING =================

def preprocess_query(question: str) -> str:
    """
    Full preprocessing pipeline applied to the user's question before
    intent detection and retrieval. Steps:
    1. Expand known abbreviations (CINTEL → Computational Intelligence, etc.)
    2. Append synonym-based hints for common query patterns
    """
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


def detect_intent(question: str) -> dict[str, bool]:
    q = question.strip()
    is_btech = bool(_BTECH_TERMS.search(q))
    has_admission = bool(_ADMISSION_TERMS.search(q))
    has_date = bool(_DATE_TERMS.search(q))

    # "BTech admission dates" or "when is BTech admission" both qualify
    is_admission_date = has_admission and has_date
    # Also detect implicit admission-date queries like "BTech dates" or "BTech deadline"
    if not is_admission_date and is_btech and has_date:
        is_admission_date = True

    return {
        "is_admission_date_query": is_admission_date,
        "is_how_to_apply_query": bool(_HOW_TO_APPLY_TERMS.search(q) and has_admission),
        "is_btech_query": is_btech,
    }


def build_retrieval_query(question: str, intent: dict[str, bool]) -> str:
    expanded = question.strip()
    hints: list[str] = []

    if intent["is_admission_date_query"]:
        hints.append("official admission schedule important dates application opening date")

    if intent["is_how_to_apply_query"]:
        hints.append("official admission process steps online application registration")
        if intent["is_btech_query"]:
            hints.append("SRMJEEE UG entrance exam for B.Tech")

    if hints:
        expanded = f"{expanded} {' '.join(hints)}"

    return expanded


def filter_chunks_for_intent(
    chunks: list[tuple[str, dict, float]],
    intent: dict[str, bool],
) -> list[tuple[str, dict, float]]:
    filtered = chunks

    if intent["is_admission_date_query"]:
        filtered = []
        for item in chunks:
            doc = item[0]
            has_eligibility_only_signal = bool(_ELIGIBILITY_SIGNAL.search(doc)) and not bool(
                _ADMISSION_DATE_SIGNAL.search(doc)
            )
            if has_eligibility_only_signal:
                continue
            filtered.append(item)

    if intent["is_how_to_apply_query"] and intent["is_btech_query"]:
        srmjeee_chunks = [item for item in filtered if _SRMJEEE_SIGNAL.search(item[0])]
        non_cet_chunks = [item for item in filtered if not _CET_SIGNAL.search(item[0])]

        # Prefer explicit SRMJEEE chunks first; otherwise avoid CET-only instructions.
        if srmjeee_chunks:
            filtered = srmjeee_chunks + [item for item in non_cet_chunks if item not in srmjeee_chunks]
        elif non_cet_chunks:
            filtered = non_cet_chunks

        # Small ranking boost toward admission-focused sources.
        def apply_priority(item: tuple[str, dict, float]) -> tuple[int, int, int]:
            doc, meta, _ = item
            source = str(meta.get("source", "")).lower()
            return (
                1 if _SRMJEEE_SIGNAL.search(doc) else 0,
                1 if "admission" in source else 0,
                0 if _CET_SIGNAL.search(doc) else 1,
            )

        filtered = sorted(filtered, key=apply_priority, reverse=True)

    # Keep original chunks if filtering removed everything.
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

# ================= VECTOR DB =================

def get_collection() -> chromadb.Collection:
    """Always return a fresh handle — avoids the scope bug from v1."""
    client = chromadb.PersistentClient(path=CFG.vector_db_path)
    return client.get_or_create_collection(CFG.collection_name)

def get_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=CFG.vector_db_path)

# ================= TEXT UTILS =================

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()

# ================= DATA LOADERS =================
# All aligned with scraper v2 output structure

def load_tables(folder: Path) -> str:
    """
    Scraper v2 saves tables as tables/table_0.csv, table_1.csv …
    Old code looked for tables.json which never existed → always empty.
    """
    table_dir = folder / "tables"
    if not table_dir.exists():
        return ""

    parts = []
    for csv_file in sorted(table_dir.glob("table_*.csv")):
        try:
            with open(csv_file, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            if rows:
                # Convert to readable text: "Col1 | Col2 | Col3"
                parts.append("\n".join(" | ".join(row) for row in rows))
        except Exception as e:
            log.debug(f"Table read error {csv_file}: {e}")

    return "\n\n".join(parts)


def load_infobox(folder: Path) -> str:
    """
    Scraper v2 saves structured key→value pairs as infobox.json.
    Was completely ignored in v1 — now becomes its own chunk type.
    """
    infobox_file = folder / "infobox.json"
    if not infobox_file.exists():
        return ""
    try:
        data: dict = json.loads(infobox_file.read_text(encoding="utf-8"))
        return "\n".join(f"{k}: {v}" for k, v in data.items())
    except Exception as e:
        log.debug(f"Infobox read error {folder}: {e}")
        return ""


def load_pages() -> list[dict]:
    if not CFG.data_path.exists():
        log.error(f"Data path not found: {CFG.data_path}")
        return []

    pages = []
    for folder in CFG.data_path.iterdir():
        if not folder.is_dir():
            continue

        content_file = folder / "content.txt"
        meta_file = folder / "metadata.json"

        if not content_file.exists() or not meta_file.exists():
            continue

        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Bad metadata in {folder}: {e}")
            continue

        pages.append({
            "folder": folder,
            "content": content_file.read_text(encoding="utf-8"),
            "meta": meta,
            "table_text": load_tables(folder),
            "infobox_text": load_infobox(folder),
        })

    log.info(f"Loaded {len(pages)} pages from {CFG.data_path}")
    return pages

# ================= BUILD VECTOR DB =================

def _already_indexed(collection: chromadb.Collection, url: str) -> bool:
    """Incremental indexing: skip pages whose URL is already in the DB."""
    try:
        result = collection.get(where={"source": url}, limit=1)
        return len(result["ids"]) > 0
    except Exception:
        return False


def _build_chunks(pages: list[dict]) -> tuple[list[str], list[dict]]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CFG.chunk_size,
        chunk_overlap=CFG.chunk_overlap,
    )

    docs: list[str] = []
    metas: list[dict] = []

    for page in pages:
        meta = page["meta"]
        url = meta.get("url", "")
        title = meta.get("title", "SRM Page")
        # og:description from scraper v2 meta field
        description = meta.get("meta", {}).get("og:description", "")
        header = f"Title: {title}\nURL: {url}"
        if description:
            header += f"\nDescription: {description}"

        base_meta = {
            "source": url,
            "title": title,
            "scraped_at": meta.get("scraped_at", ""),
        }

        def add_chunks(text: str, chunk_type: str):
            for chunk in splitter.split_text(text):
                if len(chunk) < CFG.min_chunk_length:
                    continue
                enriched = clean(f"{header}\n\n{chunk}")
                docs.append(enriched)
                metas.append({**base_meta, "chunk_type": chunk_type})

        # 1. Main content
        add_chunks(page["content"], "text")

        # 2. Tables (CSV rows — now actually loaded)
        if page["table_text"]:
            add_chunks(page["table_text"], "table")

        # 3. Infobox (key-value structured data — was ignored in v1)
        if page["infobox_text"]:
            add_chunks(page["infobox_text"], "infobox")

    return docs, metas


def build_db(force_rebuild: bool = False):
    """
    Build or incrementally update the vector DB.
    Pass force_rebuild=True to wipe and re-embed everything.
    """
    client = get_client()

    if force_rebuild:
        try:
            client.delete_collection(CFG.collection_name)
            log.info("Deleted existing collection for full rebuild.")
        except Exception:
            pass

    collection = client.get_or_create_collection(CFG.collection_name)
    embedder = get_embedder()

    pages = load_pages()
    if not pages:
        log.error("No pages found — run the scraper first.")
        return

    # Incremental: only process new pages
    new_pages = [p for p in pages if not _already_indexed(collection, p["meta"].get("url", ""))]
    log.info(f"New pages to index: {len(new_pages)} / {len(pages)} total")

    if not new_pages:
        log.info("Nothing new to index. DB is up to date.")
        return

    docs, metas = _build_chunks(new_pages)
    log.info(f"Chunks to embed: {len(docs)}")

    # Batch embedding with progress
    all_embeddings = []
    for i in range(0, len(docs), CFG.embed_batch):
        batch = docs[i : i + CFG.embed_batch]
        all_embeddings.extend(embedder.encode(batch, show_progress_bar=False).tolist())
        log.info(f"Embedded {min(i + CFG.embed_batch, len(docs))}/{len(docs)} chunks")

    # ChromaDB hard limit is 5461 items per add() call — batch accordingly
    CHROMA_BATCH = 5000
    existing_count = collection.count()

    for i in range(0, len(docs), CHROMA_BATCH):
        batch_slice = slice(i, i + CHROMA_BATCH)
        collection.add(
            ids=[str(existing_count + i + j) for j in range(len(docs[batch_slice]))],
            documents=docs[batch_slice],
            embeddings=all_embeddings[batch_slice],
            metadatas=metas[batch_slice],
        )
        log.info(f"DB insert: {min(i + CHROMA_BATCH, len(docs))}/{len(docs)} chunks")

    log.info(f"✅ Indexed {len(docs)} chunks into '{CFG.collection_name}'")

# ================= RETRIEVE =================

def retrieve(query: str) -> list[tuple[str, dict, float]]:
    """
    Returns (doc, metadata, distance) triples.
    Applies MAX_DISTANCE filter (was defined but never used in v1).
    Then reranks with CrossEncoder if available.
    """
    return retrieve_with_overrides(query=query)


def retrieve_with_overrides(
    query: str,
    *,
    retrieval_limit: int | None = None,
    max_distance: float | None = None,
    final_chunk_count: int | None = None,
) -> list[tuple[str, dict, float]]:
    """
    Same as retrieve(), but allows per-call overrides.
    Useful for a second-pass retry when the LLM returns a fallback
    even though we may have partially relevant context.
    """
    collection = get_collection()
    embedder = get_embedder()

    query_embed = embedder.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embed,
        n_results=min((retrieval_limit or CFG.retrieval_limit), collection.count() or 1),
        include=["documents", "metadatas", "distances"],
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    # Filter by distance threshold
    dist_threshold = CFG.max_distance if max_distance is None else max_distance
    candidates = [
        (doc, meta, dist)
        for doc, meta, dist in zip(docs, metas, distances)
        if dist <= dist_threshold
    ]

    if not candidates:
        log.warning(f"No results within distance {CFG.max_distance} for: {query!r}")
        return []

    # Rerank — was loaded in v1 but never actually called
    reranker = get_reranker()
    if reranker and len(candidates) > 1:
        pairs = [(query, doc) for doc, _, _ in candidates]
        scores = reranker.predict(pairs).tolist()
        candidates = sorted(
            zip([c[0] for c in candidates], [c[1] for c in candidates], scores),
            key=lambda x: x[2],
            reverse=True,
        )

    k = CFG.final_chunk_count if final_chunk_count is None else final_chunk_count
    return _diverse_top_k(candidates, k, max_per_source=2)


def _diverse_top_k(
    candidates: list[tuple[str, dict, float]],
    k: int,
    max_per_source: int = 2,
) -> list[tuple[str, dict, float]]:
    """
    Pick top-k chunks while capping how many come from a single source URL.
    Prevents context from being dominated by one page's repeated chunks.
    """
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

SYSTEM_PROMPT = """You are the official SRM Institute of Science and Technology (SRMIST, KTR campus) assistant.
You help with ANY question about SRMIST — admissions, fees, courses, events, campus life, placements, hostels, cultural fests, research, and more.

Rules:
- Answer ONLY from the provided context. Use all relevant facts available.
- If the context genuinely contains no useful information for the question, say: "I don't have enough information about this. Please visit https://www.srmist.edu.in or contact admissions."
- Do NOT output fallback text when the context contains relevant information — answer the question instead.
- Do NOT include a "Sources:" section in your answer — sources are handled separately.
- Be concise and factual. Use bullet points for lists."""

_SOURCE_TAIL_RE = re.compile(
    r"(?:\n|^)\s*\*{0,2}sources?\*{0,2}\s*:.*", re.I | re.DOTALL
)

_FALLBACK_RE = re.compile(
    r"[\n\r]*\s*I don[''\u2019]?t have (?:enough |specific |)information"
    r".*?(?:contact\s+(?:the\s+)?(?:SRM\s+)?admissions|srmist\.edu\.in)[.!]?\s*",
    re.I | re.DOTALL,
)


def clean_answer_text(answer: str) -> str:
    """
    1) Strip trailing 'Sources:' sections (handled by UI).
    2) Remove fallback sentences when a substantive answer exists.
       Works even when the fallback spans multiple lines.
    """
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

    # Remove leftover tail fragments from partial fallback stripping.
    cleaned = re.sub(r"\s*(?:please\s+visit\s+)?or\s+contact\s+(?:the\s+)?(?:srm\s+)?admissions?\.?\s*$", "", cleaned, flags=re.I).strip()

    return cleaned


def build_prompt(question: str, chunks: list[tuple[str, dict, float]]) -> str:
    context_parts = []
    for i, (doc, meta, _) in enumerate(chunks, 1):
        context_parts.append(f"[{i}] (Source: {meta.get('source', 'N/A')})\n{doc}")

    context = "\n\n---\n\n".join(context_parts)

    return f"""{SYSTEM_PROMPT}

=== CONTEXT ===
{context}

=== QUESTION ===
{question}

=== ANSWER ==="""

# ================= LLM =================

class LLMError(Exception):
    """Raised when the LLM backend is unreachable or returns an error."""


def call_llm(prompt: str, stream: bool = CFG.llm_stream) -> str:
    """
    Call the LLM and return the text response.
    Raises LLMError on connection/HTTP failures so callers can
    distinguish "LLM broke" from "no relevant context."
    """
    try:
        r = requests.post(
            CFG.llm_url,
            json={"model": CFG.llm_model, "prompt": prompt, "stream": stream},
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
                # Streaming is only for console visibility (the API response is returned at the end).
                # On Windows, the default console encoding may be cp1252 and can crash on '₹'.
                # We therefore print defensively with replacement on encoding errors.
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
        raise LLMError(
            "The language model is currently unavailable. Please try again in a moment."
        ) from e
    except requests.Timeout as e:
        log.error(f"LLM request timed out: {e}")
        raise LLMError(
            "The language model took too long to respond. Please try again."
        ) from e
    except requests.RequestException as e:
        log.error(f"LLM request failed: {e}")
        raise LLMError(
            "An error occurred while generating the answer. Please try again later."
        ) from e

# ================= RAG QUERY =================

# Common greetings to intercept before hitting the vector DB
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

_ROLE_QUERY_SIGNAL = re.compile(
    r"\b(hod|head\s+of\s+(?:the\s+)?department|head\s+of|chairperson|chair\s+person|department\s+head)\b",
    re.I,
)

_ROLE_QUERY_HINTS = (
    "head of department HOD chairperson faculty profile contact email phone department office"
)

_ADMISSION_DATE_RETRY_HINTS = (
    "SRMJEEE B.Tech UG admission important dates application opening date "
    "registration start last date to apply admission timeline schedule phase"
)


def query_rag(question: str) -> dict:
    """
    Returns {"answer": str, "sources": list[str]}
    so main.py can unpack answer and sources independently.
    """
    log.info(f"Query: {question!r}")
    t0 = time.time()

    # Intercept greetings — no point hitting the vector DB for these
    if question.lower().strip().rstrip("!?.") in _GREETINGS:
        return {
            "answer": (
                "Hello! 👋 I'm the SRM KTR Assistant. "
                "Ask me anything about SRMIST — admissions, courses, events, campus life, placements, and more!"
            ),
            "sources": [],
        }

    # ---- Preprocessing: expand abbreviations + synonym hints ----
    processed_question = preprocess_query(question)
    log.info(f"Preprocessed: {processed_question!r}")

    # Intent detection on the *expanded* query so abbreviations are resolved
    intent = detect_intent(processed_question)
    retrieval_query = build_retrieval_query(processed_question, intent)

    chunks = retrieve(retrieval_query)
    chunks = filter_chunks_for_intent(chunks, intent)

    # ---- Fallback: no relevant context found ----
    if not chunks:
        log.warning(f"No context retrieved for: {question!r}")
        return {
            "answer": _FALLBACK_NO_CONTEXT,
            "sources": [],
        }

    log.info(f"Retrieved {len(chunks)} chunks in {time.time() - t0:.2f}s")

    seen = set()
    sources = []
    for _, meta, _ in chunks:
        url = meta.get("source", "")
        if url and url not in seen:
            seen.add(url)
            sources.append(url)

    # ---- LLM call with error handling ----
    prompt = build_prompt(question, chunks)
    try:
        answer = clean_answer_text(call_llm(prompt))
    except LLMError as e:
        log.error(f"LLM failed for query: {question!r} — {e}")
        return {
            "answer": _FALLBACK_LLM_ERROR,
            "sources": sources,
        }

    if not answer or not answer.strip():
        log.warning(f"LLM returned empty answer for: {question!r}")
        return {
            "answer": _FALLBACK_LLM_ERROR,
            "sources": sources,
        }

    # If the LLM responded with the built-in "no info" fallback despite having context,
    # do one targeted retry with role-specific query expansion and a slightly broader
    # retrieval window. This helps questions like "who is the head of cintel".
    if _FALLBACK_RE.search(answer) and _ROLE_QUERY_SIGNAL.search(processed_question):
        log.info("LLM fallback detected; retrying with role-expanded retrieval query.")
        retry_query = f"{processed_question} {_ROLE_QUERY_HINTS}"
        retry_chunks = retrieve_with_overrides(
            query=retry_query,
            retrieval_limit=max(CFG.retrieval_limit * 2, 25),
            max_distance=max(CFG.max_distance, 2.2),
            final_chunk_count=max(CFG.final_chunk_count + 3, 8),
        )
        retry_chunks = filter_chunks_for_intent(retry_chunks, intent)

        if retry_chunks:
            retry_sources_seen = set()
            retry_sources: list[str] = []
            for _, meta, _ in retry_chunks:
                url = meta.get("source", "")
                if url and url not in retry_sources_seen:
                    retry_sources_seen.add(url)
                    retry_sources.append(url)

            retry_prompt = build_prompt(question, retry_chunks)
            try:
                retry_answer = clean_answer_text(call_llm(retry_prompt))
            except LLMError:
                retry_answer = ""

            if retry_answer and not _FALLBACK_RE.search(retry_answer):
                log.info("Retry succeeded; returning retry answer.")
                answer = retry_answer
                sources = retry_sources

    # Admission-date queries can also receive generic fallback if first-pass chunks
    # are weakly related (eligibility/process pages). Retry with date-centric hints.
    if _FALLBACK_RE.search(answer) and intent["is_admission_date_query"]:
        log.info("LLM fallback detected; retrying with admission-date-expanded retrieval query.")
        retry_query = f"{processed_question} {_ADMISSION_DATE_RETRY_HINTS}"
        retry_chunks = retrieve_with_overrides(
            query=retry_query,
            retrieval_limit=max(CFG.retrieval_limit * 2, 30),
            max_distance=max(CFG.max_distance, 2.2),
            final_chunk_count=max(CFG.final_chunk_count + 3, 8),
        )
        retry_chunks = filter_chunks_for_intent(retry_chunks, intent)

        if retry_chunks:
            retry_sources_seen = set()
            retry_sources: list[str] = []
            for _, meta, _ in retry_chunks:
                url = meta.get("source", "")
                if url and url not in retry_sources_seen:
                    retry_sources_seen.add(url)
                    retry_sources.append(url)

            retry_prompt = build_prompt(question, retry_chunks)
            try:
                retry_answer = clean_answer_text(call_llm(retry_prompt))
            except LLMError:
                retry_answer = ""

            if retry_answer and not _FALLBACK_RE.search(retry_answer):
                log.info("Admission-date retry succeeded; returning retry answer.")
                answer = retry_answer
                sources = retry_sources

    # Guardrail: prevent age cut-off dates from being misreported as admissions opening dates.
    if intent["is_admission_date_query"] and re.search(r"\b31st\b.*\bjuly\b", answer, re.I):
        context_text = " ".join(doc for doc, _, _ in chunks)
        has_only_eligibility_signals = bool(_ELIGIBILITY_SIGNAL.search(context_text)) and not bool(
            _ADMISSION_DATE_SIGNAL.search(context_text)
        )
        if has_only_eligibility_signals:
            answer = (
                "I could not find an explicit admissions opening date in the available SRMIST context. "
                "The 31st July mention is an age-eligibility criterion, not an admission opening date. "
                "Please check the latest admissions timeline on https://www.srmist.edu.in/admission-india/."
            )

    if intent["is_how_to_apply_query"] and intent["is_btech_query"]:
        answer_has_cet_only = _CET_SIGNAL.search(answer) and not _SRMJEEE_SIGNAL.search(answer)
        if answer_has_cet_only:
            answer = (
                "For B.Tech admissions at SRMIST, please follow the SRMJEEE (UG) route on the official admissions portal. "
                "The CET instructions in retrieved context appear to be from a different admission flow. "
                "Please verify the latest B.Tech application steps at https://www.srmist.edu.in/admission-india/."
            )

    log.info(f"Total query time: {time.time() - t0:.2f}s")
    return {"answer": answer, "sources": sources}

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
        answer = query_rag(args.query)
        if not CFG.llm_stream:   # streaming already printed above
            print(answer)
