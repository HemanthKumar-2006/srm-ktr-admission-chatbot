# SRM KTR Admission Chatbot

Full-stack chatbot for SRM admissions using a local RAG pipeline.

## Project Layout

- `frontend/` - React + Vite chat UI
- `backend/` - FastAPI API, RAG pipeline, scraper, evaluation scripts
- `backend/data/srm_docs/` - scraped corpus (kept as-is)

## Prerequisites

- Python 3.10+
- Node.js 18+
- Ollama (or compatible API) running at your configured `RAG_LLM_URL`

## 1) Backend Setup

From repository root:

```bash
pip install -r requirements.txt
```

Start API:

```bash
uvicorn backend.main:app --reload --port 8000
```

## 2) Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend reads `VITE_API_URL` (defaults to `http://localhost:8000`).

## 3) Build / Refresh Vector DB

From repository root:

```bash
python backend/rag_pipeline.py --build
```

Force rebuild:

```bash
python backend/rag_pipeline.py --rebuild
```

## 4) Run Scraper

From repository root:

```bash
python backend/scraper.py
```

## 5) Run Evaluation

From repository root:

```bash
python backend/evaluate.py
```

## Environment Variables

Backend (`backend/settings.py`):

- `API_ALLOWED_ORIGINS` (comma-separated, default `http://localhost:8080`)
- `RAG_DATA_PATH`
- `RAG_VECTOR_DB_PATH`
- `RAG_COLLECTION_NAME`
- `RAG_CHUNK_SIZE`
- `RAG_CHUNK_OVERLAP`
- `RAG_MIN_CHUNK_LENGTH`
- `RAG_RETRIEVAL_LIMIT`
- `RAG_MAX_DISTANCE`
- `RAG_FINAL_CHUNK_COUNT`
- `RAG_EMBED_BATCH`
- `RAG_EMBED_MODEL`
- `RAG_RERANK_MODEL`
- `RAG_LLM_URL`
- `RAG_LLM_MODEL`
- `RAG_LLM_STREAM`
- `EVAL_API_URL`

Frontend:

- `VITE_API_URL`
