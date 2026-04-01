# Project Report: SRM KTR Admission Chatbot

## 1. Project Overview
* **Purpose:** The project is a full-stack AI chatbot designed to assist prospective students with admissions-related queries for the SRM Institute of Science and Technology (SRMIST).
* **Domain:** Education / EdTech / Conversational AI.
* **Main Features & Capabilities:**
  * **Custom Knowledge Base:** An asynchronous web scraper that crawls the SRM website to build a local dataset.
  * **Advanced RAG Pipeline:** A Retrieval-Augmented Generation system featuring query reformulation, abbreviation expansion, vector search, and cross-encoder reranking.
  * **Knowledge Graph Integration:** A lightweight, in-memory entity-relationship graph to accurately answer hierarchical questions (e.g., lists of departments, HOD names, and organizational structure).
  * **Interactive UI:** A modern, responsive React-based chat interface that renders markdown, handles source citations, and provides suggested prompts.
  * **Evaluation Suite:** A built-in evaluation script to measure intent accuracy, keyword recall, citation rates, and faithfulness against a test dataset.
  * **Local Execution:** Fully local execution using Ollama, ensuring privacy and zero API costs.

## 2. Tech Stack Identification
* **Backend:** Python 3.10+, FastAPI (Web framework), Uvicorn (ASGI server), `aiohttp` & `BeautifulSoup4` (Web scraping), `PyPDF` (PDF parsing).
* **Frontend:** React 18, TypeScript, Vite (Build tool), Tailwind CSS & Shadcn UI (Styling/Components), React Router, React Query, Lucide React (Icons).
* **AI / Machine Learning:** 
  * **LLM:** Local deployment via Ollama (default model: `gemma3`).
  * **Embeddings:** `sentence-transformers` (`all-MiniLM-L6-v2`).
  * **Reranking:** `sentence-transformers` Cross-Encoder (`ms-marco-MiniLM-L-6-v2`).
  * **Text Processing:** `langchain-text-splitters`.
* **Database:** Qdrant (Local Vector Database).
* **Package Managers:** `pip` (Python), `npm` (Node.js).

## 3. Architecture Analysis
* **Overall Architecture:** Client-Server architecture with a decoupled frontend and backend, powered by a local AI pipeline.
* **Major Modules:**
  * **Frontend Client (`frontend/`):** Manages user state, renders the chat UI, and communicates with the backend via REST.
  * **API Layer (`backend/main.py`):** Exposes endpoints (`/chat`, `/health`, `/admin/*`) and handles request validation, CORS, and caching.
  * **RAG Engine (`backend/rag_pipeline.py`):** The core intelligence module. It processes queries, retrieves context from Qdrant, reranks results, and constructs prompts for the LLM.
  * **Data Ingestion (`backend/scraper.py`):** An async crawler that populates the raw data folder (`data/srm_docs`).
* **Component Interaction:**
  ```text
  [ React UI ] --(POST /chat)--> [ FastAPI Server ]
                                        |
                                  (Cache Check)
                                        |
                               [ RAG Pipeline ] ---> (1. Preprocess & Embed)
                                        |
                                        v
                                  [ Qdrant ] ---> (2. Retrieve top N chunks)
                                        |
                                        v
                               [ Cross-Encoder ] ---> (3. Rerank & filter top K chunks)
                                        |
                                        v
                                [ Ollama LLM ] ---> (4. Generate Answer)
  ```

## 4. Code Structure Breakdown
* **`srm-ktr-admission-chatbot-main/`**
  * **`backend/`**: Contains all server-side logic.
    * `main.py`: The FastAPI application entry point and route definitions.
    * `rag_pipeline.py`: Core logic for document chunking, embedding, retrieval, and LLM communication.
    * `scraper.py`: Asynchronous web scraper for data collection.
    * `evaluate.py`: Script to test the RAG pipeline's accuracy and performance.
    * `models.py`: Pydantic schemas for API requests and responses.
    * `settings.py`: Environment variable management and configuration.
    * `cache.py`: In-memory caching mechanism for repeated queries.
  * **`frontend/`**: The Vite + React application.
    * `src/pages/Index.tsx`: The main chat interface and state management.
    * `src/components/`: Reusable UI components (buttons, inputs, select dropdowns).
    * `package.json`: Frontend dependencies and build scripts.
  * **`requirements.txt`**: Python dependencies.
  * **`run.bat`**: Windows batch script for automated setup and execution.

## 5. Data Flow & Logic
1. **Ingestion:** `scraper.py` fetches HTML/PDFs, cleans the text, and saves it to `backend/data/srm_docs`.
2. **Indexing:** `rag_pipeline.py` reads the scraped data, splits it into chunks (using Langchain), generates embeddings, and stores them in Qdrant.
3. **Query Processing:** 
   * A user submits a query via the React UI.
   * FastAPI receives the request. If the exact query exists in `cache.py`, it returns the cached response instantly.
   * If not cached, `rag_pipeline.py` expands abbreviations (e.g., "KTR" -> "Kattankulathur") and reformulates the query with synonyms.
4. **Retrieval & Generation:**
   * The pipeline queries Qdrant for the top 25 chunks.
   * A Cross-Encoder reranks these chunks to find the 5 most relevant ones.
   * The chunks are bundled into a prompt and sent to the local Ollama API.
5. **Response:** The LLM streams/returns the answer, which FastAPI packages with source URLs and sends back to the frontend for markdown rendering.

## 6. Dependencies & Integrations
* **External Services:** The system is designed to be fully self-contained. It relies on a local instance of **Ollama** running on port `11434` for LLM inference.
* **Third-Party Libraries:** 
  * `sentence-transformers` (HuggingFace models for embeddings).
  * `Radix UI` / `Shadcn` (Accessible frontend components).

## 7. Database & Models
* **Database Type:** Vector Database.
* **Implementation:** **Qdrant** (running in embedded/local mode, saving to `vector_db_path`).
* **Schema/Entities:** 
  * Documents are stored as text chunks with associated metadata (e.g., `source_url`, `title`).
  * Pydantic models (`ChatRequest`, `ChatResponse`, `Source`) strictly define the API data contracts.

## 8. DevOps & Environment
* **Deployment Setup:** Currently designed for local development. There are no Dockerfiles or CI/CD pipelines present. A `run.bat` script is provided for one-click Windows startup.
* **Configuration:** Managed via `backend/settings.py`, which reads environment variables with sensible defaults (e.g., `RAG_LLM_URL`, `RAG_CHUNK_SIZE`, `VITE_API_URL`).

## 9. Strengths, Weaknesses & Risks
* **Strengths:**
  * **Privacy & Cost:** Fully local execution means no data is sent to external APIs (like OpenAI), ensuring privacy and zero recurring costs.
  * **Advanced RAG:** The inclusion of a Cross-Encoder for reranking and query reformulation significantly improves answer accuracy over standard vector search.
  * **Resilient Scraper:** The scraper uses asynchronous requests with exponential backoff and respects `robots.txt`.
* **Weaknesses & Risks:**
  * **Hardware Dependency:** Running an LLM (Gemma 3) and Cross-Encoders locally requires significant RAM/VRAM. On lower-end machines, response times will be slow.
  * **State Management:** The backend uses a simple in-memory dictionary for caching (`cache.py`). This will not scale if the FastAPI app is run with multiple Uvicorn workers.
  * **UI/Backend Disconnect:** The frontend has a "Campus Selector" (KTR, Ramapuram, etc.), but the selected campus state is currently only used for UI display and is not explicitly passed to the backend to filter vector search results.

## 10. Improvement Suggestions
* **Architectural Improvements:**
  * **Containerization:** Add a `Dockerfile` and `docker-compose.yml` to orchestrate the FastAPI backend, React frontend, and Ollama container. This will standardize cross-platform deployment.
  * **Distributed Caching:** Replace the in-memory `cache.py` with Redis to support multi-worker scaling.
* **Refactoring Areas:**
  * **Dynamic Configuration:** Move the hardcoded `ABBREVIATIONS` and `_QUERY_SYNONYMS` in `rag_pipeline.py` to an external JSON/YAML configuration file for easier updates.
  * **Frontend Integration:** Update `ChatRequest` to accept the `campus` parameter, and modify the Qdrant query in `rag_pipeline.py` to filter metadata by the selected campus.
* **Scalability, Security, and Performance:**
  * **Security:** Implement rate limiting (e.g., using `slowapi`) to prevent API abuse, especially since LLM generation is computationally expensive.
  * **Performance:** Implement streaming responses via WebSockets or Server-Sent Events (SSE) from FastAPI to the React frontend to improve perceived latency while the LLM generates tokens.