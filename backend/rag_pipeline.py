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

# ================= CONFIG =================

@dataclass
class Config:
    data_path: Path = Path("data/srm_docs")
    vector_db_path: str = "vector_db"
    collection_name: str = "srm_data"

    # Chunking
    chunk_size: int = 450
    chunk_overlap: int = 80
    min_chunk_length: int = 80

    # Retrieval
    retrieval_limit: int = 25       # Candidates from vector DB
    max_distance: float = 1.8       # Filter out low-quality matches
    final_chunk_count: int = 5      # Chunks sent to LLM after reranking

    # Embedding batch size
    embed_batch: int = 256

    # Models
    embed_model: str = "all-MiniLM-L6-v2"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # LLM
    llm_url: str = "http://localhost:11434/api/generate"
    llm_model: str = "gemma3"
    llm_stream: bool = True

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
    collection = get_collection()
    embedder = get_embedder()

    query_embed = embedder.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embed,
        n_results=min(CFG.retrieval_limit, collection.count() or 1),
        include=["documents", "metadatas", "distances"],
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    # Filter by distance threshold
    candidates = [
        (doc, meta, dist)
        for doc, meta, dist in zip(docs, metas, distances)
        if dist <= CFG.max_distance
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

    return candidates[: CFG.final_chunk_count]

# ================= PROMPT =================

SYSTEM_PROMPT = """You are the official SRM Institute of Science and Technology (KTR campus) admissions assistant.

Rules:
- Answer ONLY from the provided context and tell relevant facts.
- If the context does not contain enough information, say: "I don't have enough information about this. Please visit https://www.srmist.edu.in or contact admissions."
- Always cite the source URL at the end of your answer under "Sources:".
- Be concise and factual. Use bullet points for lists."""


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

def call_llm(prompt: str, stream: bool = CFG.llm_stream) -> str:
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

        # Stream tokens and collect full response
        full = []
        for line in r.iter_lines():
            if not line:
                continue
            try:
                token_data = json.loads(line)
                token = token_data.get("response", "")
                full.append(token)
                if token_data.get("done"):
                    break
            except json.JSONDecodeError:
                continue

        return "".join(full)

    except requests.RequestException as e:
        log.error(f"LLM request failed: {e}")
        return f"LLM error: {e}"

# ================= RAG QUERY =================

# Common greetings to intercept before hitting the vector DB
_GREETINGS = {"hi", "hello", "hey", "hii", "helo", "yo", "sup", "greetings"}

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
                "Hello! 👋 I'm the SRM KTR Admission Assistant. "
                "Ask me anything about admissions, fees, courses, or campus life!"
            ),
            "sources": [],
        }

    chunks = retrieve(question)

    if not chunks:
        return {
            "answer": (
                "I don't have specific information about that. "
                "Please visit https://www.srmist.edu.in or contact the SRM admissions office directly."
            ),
            "sources": [],
        }

    log.info(f"Retrieved {len(chunks)} chunks in {time.time() - t0:.2f}s")

    # Deduplicated source URLs from the retrieved chunks
    seen = set()
    sources = []
    for _, meta, _ in chunks:
        url = meta.get("source", "")
        if url and url not in seen:
            seen.add(url)
            sources.append(url)

    prompt = build_prompt(question, chunks)
    answer = call_llm(prompt)

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
