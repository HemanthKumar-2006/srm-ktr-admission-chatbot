# SRM KTR Admission Chatbot

> **v4.1** — Full-stack SRMIST assistant powered by a local Knowledge Graph RAG pipeline.

Answers student questions about admissions, fees, programs, departments, campus life, placements, research, and institutional structure. Uses hybrid dense+sparse retrieval, cross-encoder reranking, a structured Knowledge Graph, and a local Ollama-compatible LLM — no paid API required.

---

## Project Layout

```
srm-ktr-admission-chatbot-main/
├── backend/
│   ├── main.py              # FastAPI entry point (chat, health, admin routes)
│   ├── rag_pipeline.py      # Full RAG engine (retrieval, reranking, prompting)
│   ├── knowledge_graph.py   # SRMIST entity/relationship graph builder
│   ├── settings.py          # Nested, env-var-driven configuration
│   ├── cache.py             # LRU response cache + session memory
│   ├── models.py            # API request/response schemas
│   ├── scraper.py           # Async SRM sitemap scraper
│   ├── admission_profiles.py# Admission profiles builder and loader
│   └── evaluate.py          # Offline RAG evaluation pipeline
├── frontend/
│   ├── src/pages/Index.tsx  # Main chat UI (campus selector, session, sources)
│   └── src/components/ui/  # Essential UI primitives only (pruned)
├── Programs Helper/         # Utility scripts for program reconciliation
├── analyze_kg.py            # Knowledge graph analysis/debug script
├── KG_GUIDELINE.md          # Rules for KG construction and maintenance
├── run.bat                  # Windows one-click startup script
└── requirements.txt
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| Ollama | latest (or compatible OpenAI-style API) |

> Make sure Ollama is running and the model configured in `RAG_LLM_MODEL` (default: `gemma3`) is pulled.

---

## Quick Start (Windows)

Double-click **`run.bat`** or run from the terminal:

```cmd
run.bat
```

This opens two terminal windows, installs missing dependencies, and starts both the FastAPI backend and the Vite frontend dev server.

---

## Manual Setup

### 1. Backend

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend proxies API calls to `http://localhost:8000` by default (configure via `VITE_API_URL`).

### 3. Build or Refresh the Vector DB

After scraping or when first setting up:

```bash
# Incremental update (only new pages)
python backend/rag_pipeline.py --build

# Full rebuild (wipe and re-embed everything)
python backend/rag_pipeline.py --rebuild
```

Or via the admin API endpoints:

```
POST http://localhost:8000/admin/build-db
POST http://localhost:8000/admin/rebuild-db
```

### 4. Run the Scraper

Crawls the SRM sitemap to populate `backend/data/srm_docs/`:

```bash
python backend/scraper.py
```

### 5. Run Evaluation

Runs offline queries against the live API and scores intent, faithfulness, and citation rate:

```bash
python backend/evaluate.py
```

### 6. Analyze the Knowledge Graph

Inspect entities, relationships, and detect structural issues:

```bash
python analyze_kg.py
```

---

## Environment Variables

All settings are loaded via `backend/settings.py`. Defaults are shown; override by setting environment variables.

### API

| Variable | Default | Description |
|---|---|---|
| `API_ALLOWED_ORIGINS` | `http://localhost:8080,...` | Comma-separated CORS allowed origins |

### RAG Pipeline

| Variable | Default | Description |
|---|---|---|
| `RAG_DATA_PATH` | `backend/data/srm_docs` | Scraped pages directory |
| `RAG_VECTOR_DB_PATH` | `vector_db_qdrant` | Qdrant DB path |
| `RAG_COLLECTION_NAME` | `srm_data` | Collection name in Qdrant |
| `RAG_CHUNK_SIZE` | `600` | Text chunk size |
| `RAG_CHUNK_OVERLAP` | `120` | Chunk overlap |
| `RAG_MIN_CHUNK_LENGTH` | `80` | Min chunk size to index |
| `RAG_RETRIEVAL_LIMIT` | `30` | Candidates fetched from vector DB |
| `RAG_MAX_DISTANCE` | `1.5` | Max score threshold for candidates |
| `RAG_FINAL_CHUNK_COUNT` | `8` | Chunks sent to LLM after reranking |
| `RAG_EMBED_MODEL` | `all-MiniLM-L6-v2` | Sentence-Transformers embedding model |
| `RAG_EMBED_BATCH` | `256` | Embedding batch size |
| `RAG_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | CrossEncoder reranking model |

### LLM

| Variable | Default | Description |
|---|---|---|
| `RAG_LLM_URL` | `http://localhost:11434/api/generate` | Ollama (or compatible) generate endpoint |
| `RAG_LLM_MODEL` | `gemma3` | Model name |
| `RAG_LLM_STREAM` | `true` | Enable streaming |
| `RAG_LLM_NUM_PREDICT` | `4096` | Max tokens to generate |

### Evaluation

| Variable | Default | Description |
|---|---|---|
| `EVAL_API_URL` | `http://127.0.0.1:8000/chat` | Chatbot endpoint for evaluation |

### Frontend

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend base URL |

---

## How It Works

```
[ React Chat UI ]
      |
      v
POST /chat  { query, campus, session_id }
      |
      v
[ FastAPI ]  ──> LRU cache lookup
      |
      v
[ RAG Pipeline ]
  1. Abbreviation expansion + query reformulation
  2. Intent detection (role, listing, admission-date, procedural, etc.)
  3. Knowledge Graph grounding (HOD/dean lookups, department/program listings)
  4. Hybrid retrieval: dense embeddings + BM25 sparse via Qdrant RRF
  5. Cross-encoder reranking + page-authority score shaping
  6. Parent-context prefetching + sentence compression
  7. Structured system prompt with faithfulness guardrails
  8. Ollama LLM generation
      |
      v
[ Response: answer + sources ]
      |
      v
[ React UI renders answer + collapsible source links ]
```

---

## Key v4.1 Improvements (vs v4.0)

| Area | Change |
|---|---|
| **Configuration** | Nested `Settings` dataclasses (`ApiConfig`, `RagConfig`, `LLMConfig`, etc.) with `from_env()` factories and validation |
| **Role Queries** | `_ROLE_QUERY_SIGNAL` detector + `_ROLE_QUERY_HINTS` injected into retrieval query |
| **Prompt Quality** | Rewritten `SYSTEM_PROMPT` with structured response style rules and strict faithfulness guardrails |
| **Scraper** | Simplified to single `base_domain` model — no brittle hardcoded seed URLs |
| **Frontend** | Pruned all unused Shadcn UI components and legacy chat components |
| **Payload Indexing** | Consolidated Qdrant index creation loop for cleaner `_ensure_collection` |
| **Embedding** | `normalize_embeddings=True` + `convert_to_numpy=True` for consistent cosine similarity |

---

## Development Notes

- **Knowledge Graph:** See `KG_GUIDELINE.md` for construction rules and entity type hierarchy.
- **Programs Helper:** `Programs Helper/` contains utility scripts for reconciling program data — not part of the main pipeline.
- **Cache:** In-memory only — clears on restart. Not suitable for multi-instance deployments without a backing store.
- **KTR Default:** KTR (Kattankulathur) is the default corpus. Non-KTR campus filtering is applied when explicitly selected.
