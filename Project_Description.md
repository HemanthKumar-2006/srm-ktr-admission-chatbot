# Project Report: SRM KTR Admission Chatbot

## 1. Project Overview
* **Purpose:** This project is a full-stack SRMIST assistant that answers student questions about admissions, fees, programs, departments, campus life, placements, research, and institutional structure.
* **Current Scope:** The chatbot is no longer just a basic admissions FAQ bot. The current version supports broader SRMIST knowledge retrieval, role lookups such as HOD and dean queries, department and school listing queries, and follow-up questions within the same session.
* **Version Context:** The backend is currently on **v4.1**, with major upgrades around hybrid retrieval, knowledge graph grounding, robust nested settings configuration, query intent role extraction loops, and strong answer guardrails.
* **Main Features & Capabilities:**
  * **Async SRM website scraper:** Builds and refreshes a local SRM corpus from sitemap-driven crawling.
  * **Hybrid RAG retrieval:** Combines dense embeddings and sparse BM25-style search in Qdrant using Reciprocal Rank Fusion (RRF).
  * **Knowledge Graph grounding:** Uses a structured SRMIST entity graph to answer listing and role-based questions more reliably.
  * **Hierarchical chunking:** Stores both page-level parent chunks and detailed child chunks, then prepends parent context during retrieval.
  * **Intent-aware answer generation:** Detects query types such as listing, procedural, comparison, person lookup, admission-date, and how-to-apply.
  * **Campus-aware querying:** The frontend campus selector is passed to the backend, and retrieval applies campus filtering for non-KTR campuses.
  * **Conversation memory:** Supports follow-up questions using lightweight per-session context memory.
  * **Source-backed UI:** The frontend displays answers with clickable source links and collapsible citation lists.
  * **Evaluation pipeline:** Includes an offline evaluation script for intent accuracy, keyword recall, citation rate, faithfulness, hallucination checks, and latency.
  * **Local-first deployment:** Runs against a local Ollama-compatible LLM endpoint with no external paid API dependency.

## 2. Tech Stack Identification
* **Backend:** Python 3.10+, FastAPI, Uvicorn, `aiohttp`, `BeautifulSoup4`, `requests`, `pydantic`.
* **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Radix UI / Shadcn-style components, Lucide React.
* **AI / Retrieval Stack:**
  * **LLM:** Ollama-compatible local model endpoint (`gemma3` by default).
  * **Embeddings:** `sentence-transformers` using `all-MiniLM-L6-v2`.
  * **Reranking:** `CrossEncoder` with `cross-encoder/ms-marco-MiniLM-L-6-v2`.
  * **Sparse Retrieval:** Local BM25-style sparse vectorizer built from project data.
  * **Text Splitting:** `langchain-text-splitters`.
* **Database / Storage:**
  * **Vector Store:** Local Qdrant collection in `vector_db_qdrant/`.
  * **Knowledge Graph Artifacts:** Serialized to `vector_db_qdrant/knowledge_graph.json`.
  * **Sparse Model Artifact:** Stored as `vector_db_qdrant/sparse_vectorizer.pkl`.
* **Package Managers:** `pip` for Python dependencies and `npm` for frontend dependencies.

## 3. Architecture Analysis
* **Architecture Style:** Client-server application with a React frontend, a FastAPI backend, a local vector database, and a local LLM inference endpoint.
* **Major Backend Layers:**
  * **API Layer (`backend/main.py`):** Handles `/chat`, `/health`, cache endpoints, and admin DB rebuild routes.
  * **RAG Engine (`backend/rag_pipeline.py`):** Preprocesses queries, detects intent, performs hybrid retrieval, reranks results, compresses context, and calls the LLM.
  * **Knowledge Graph (`backend/knowledge_graph.py`):** Builds and loads a structured SRMIST graph from seed data plus scraped content.
  * **Caching & Memory (`backend/cache.py`):** Stores repeated-query responses and short conversation history.
  * **Scraper (`backend/scraper.py`):** Collects SRM site data into local page folders.
* **High-Level Query Flow:**
  ```text
  [ React Chat UI ]
          |
          v
  POST /chat (query, campus, session_id)
          |
          v
  [ FastAPI ]
          |
          +--> LRU Cache lookup
          |
          +--> Conversation context fetch
          |
          v
  [ RAG Pipeline ]
    1. Query preprocessing
    2. Intent detection
    3. Knowledge Graph grounding
    4. Hybrid dense+sparse retrieval from Qdrant
    5. Cross-encoder reranking + authority boosts
    6. Parent-context fetch + compression
    7. Prompt construction with guardrails
    8. Ollama LLM response generation
          |
          v
  [ FastAPI Response ]
          |
          v
  [ React UI with answer + sources ]
  ```

## 4. Code Structure Breakdown
* **`backend/`**
  * `main.py`: FastAPI entry point, chat route, health route, admin rebuild routes, and cache endpoints.
  * `rag_pipeline.py`: Core RAG implementation, vector DB build logic, hybrid retrieval, reranking, prompt building, and LLM integration.
  * `knowledge_graph.py`: SRMIST entity/relationship graph builder, loaders, role-query helpers, and listing-query helpers.
  * `cache.py`: LRU response cache plus lightweight session-based conversation memory.
  * `models.py`: Request and response schemas for the API.
  * `settings.py`: Environment-based runtime configuration.
  * `scraper.py`: Async sitemap scraper that saves cleaned content, metadata, tables, and infobox data.
  * `evaluate.py`: Offline evaluation runner against test queries.
* **`frontend/`**
  * `src/pages/Index.tsx`: Main standalone chat experience. Contains campus selector, prompt suggestions, markdown rendering, and local session handling.
  * `src/components/ui/`: Contains only essential core UI primitives (like `select.tsx`), with all unused Shadcn code pruned.
  * `package.json`: Frontend scripts and dependencies.
* **Project-Level Assets**
  * `backend/data/srm_docs/`: Scraped SRM page data.
  * `data/eval/`: Evaluation inputs and outputs.
  * `vector_db_qdrant/`: Qdrant data plus derived retrieval artifacts.
  * `KG_GUIDELINE.md`: Rules and structure for the knowledge graph.
  * `run.bat`: Windows startup script for local development.

## 5. Data Flow & Logic
1. **Scraping and extraction:** `backend/scraper.py` reads the SRM sitemap, respects `robots.txt`, fetches pages concurrently, and stores page content plus metadata locally.
2. **Index building:** `backend/rag_pipeline.py` loads scraped pages, extracts metadata such as campus, entity type, program level, parent entity, and page authority, then builds parent and child chunks.
3. **Knowledge graph generation:** During DB build, the system constructs a structured SRMIST graph from seeded institutional data and scraped content, then saves it as JSON.
4. **Vector indexing:** Dense embeddings and sparse vectors are generated and stored in a local Qdrant collection with payload indexes for fields like `campus`, `entity_type`, `page_authority`, `chunk_level`, and `parent_point_id`.
5. **Chat request handling:** The frontend sends `query`, `campus`, and `session_id` to `/chat`.
6. **Context resolution:** The backend checks the LRU cache, retrieves recent conversation context if available, and resolves pronoun-heavy follow-up questions.
7. **Intent and KG grounding:** The pipeline expands abbreviations, reformulates certain queries, detects intent, and attempts structured KG answers for role and listing questions before relying only on unstructured retrieval.
8. **Hybrid retrieval:** Qdrant retrieves dense and sparse matches, fuses them with RRF, applies campus filters when needed, reranks with a cross-encoder, and boosts stronger admission or high-authority pages.
9. **Answer assembly:** Parent overview chunks are prepended, child chunks may be compressed to relevant sentences, and a guarded prompt is sent to the local LLM.
10. **Frontend rendering:** The answer is cleaned, citations are normalized, markdown-like formatting is rendered, and sources are shown in a collapsible list.

## 6. Current Retrieval and Answering Behavior
* **Query preprocessing:** Expands abbreviations like `CSE`, `KTR`, `SRMJEEE`, `HOD`, and similar terms before retrieval.
* **Intent-aware routing:** Supports factual, listing, procedural, comparison, person lookup, admission-date, how-to-apply, and general admission queries.
* **Knowledge Graph strengths:** Especially useful for:
  * department and school listings,
  * HOD / dean / chairperson lookups,
  * institutional hierarchy questions.
* **Hybrid retrieval details:**
  * dense semantic retrieval from embeddings,
  * sparse lexical retrieval from a BM25-style vectorizer,
  * RRF fusion inside Qdrant,
  * cross-encoder reranking,
  * page-authority-based score shaping,
  * diversity filtering to avoid overusing one source page.
* **Guardrails and fallbacks:**
  * blocks empty queries,
  * retries some failed role and admission-date queries with stronger hints,
  * prevents some common admission-date hallucinations,
  * returns a safe fallback when context is missing or the LLM is unavailable.

## 7. Frontend Behavior
* **Main UX:** A single-page SRM chat interface with a welcome screen, rotating suggestion prompts, and a persistent campus selector.
* **Session behavior:** Generates a session ID in the browser and reuses it for follow-up questions in the same chat.
* **Answer presentation:**
  * renders lightweight markdown-style headings, bullets, links, and citation references,
  * strips noisy inline source blocks from raw model output,
  * shows citations in a dedicated expandable sources section.
* **Controls:** Supports new chat reset, prompt refresh, Enter-to-send, and Shift+Enter for multi-line input.
* **Current Implementation Note:** The main chat experience is concentrated entirely in `frontend/src/pages/Index.tsx`. All older legacy chat components and unused Shadcn UI libraries were aggressively pruned to maintain a minimalistic footprint.

## 8. API, Data Models, and Storage
* **Primary Endpoint:** `POST /chat`
  * Request fields: `query`, `campus`, `session_id`
  * Response fields: `response`, `intent`, `sources`, `campus`, `program`
* **Operational Endpoints:**
  * `GET /health`
  * `POST /admin/build-db`
  * `POST /admin/rebuild-db`
  * `GET /cache/stats`
  * `POST /cache/clear`
* **Scraped Page Storage Format:** Each page folder can contain:
  * `content.txt`
  * `raw.html`
  * `metadata.json`
  * `infobox.json`
  * `tables/table_*.csv`

## 9. Strengths, Weaknesses & Risks
* **Strengths:**
  * **Much stronger retrieval quality than a basic RAG bot:** Hybrid search, reranking, parent-child chunking, and KG grounding significantly improve coverage and precision.
  * **Better handling of structured university questions:** Role lookups and department listings are explicitly supported.
  * **Campus-aware flow:** The frontend selector now reaches the backend retrieval layer.
  * **Local-first operation:** No paid inference dependency is required for normal use.
  * **Practical operational tooling:** Includes scraper, DB build routes, cache introspection, and evaluation scripts.
* **Weaknesses & Risks:**
  * **High local resource usage:** Embeddings, reranking, Qdrant, and a local LLM still require a capable machine.
  * **In-memory cache and session memory:** These do not persist across restarts and are not suitable for multi-instance scaling.
  * **Monolithic frontend page:** The main UI logic is concentrated in one large file, which may become harder to maintain.
  * **KTR-first behavior:** KTR is treated as the default corpus, so explicit campus filtering is mainly applied to non-KTR campuses.
  * **No auth / rate limiting / CI pipeline yet:** The project is still oriented toward local or controlled deployment.

## 10. Recommended Next Improvements
* **Streaming UX:** Stream tokens from FastAPI to the frontend instead of waiting for a full answer payload.
* **Persistent memory and cache:** Move cache and conversation state to Redis or another persistent store if multi-user deployment is needed.
* **Frontend refactor:** Break `Index.tsx` into smaller components for message rendering, composer logic, source display, and session controls.
* **Evaluation expansion:** Add more benchmark cases for non-KTR campuses, role questions, and follow-up queries.
* **Deployment hardening:** Add Docker support, environment templates, CI checks, and optional rate limiting.
* **Administrative observability:** Add logging dashboards or structured metrics for retrieval quality, cache hit rates, and query latency.
