@echo off
echo ==================================================
echo Starting SRM Admission Chatbot...
echo ==================================================

echo.
echo [1/4] Starting Ollama (Running gemma3)...
start cmd /k "ollama run gemma3"

echo.
echo [2/4] Setting up Python Environment...
if not exist .venv\Scripts\activate.bat (
    echo Creating Python virtual environment (.venv)...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing/Verifying Python requirements...
pip install -r requirements.txt

echo.
echo Verifying Vector Database...
if not exist vector_db\ (
    echo Vector DB not found. Building Vector Database...
    python backend/rag_pipeline.py --build
)

echo.
echo [3/4] Starting Backend Server (FastAPI on Port 8000)...
start cmd /k ".venv\Scripts\activate.bat && uvicorn backend.main:app --reload --port 8000"

echo.
echo [4/4] Starting Frontend Server (Vite)...
start cmd /k "cd frontend && npm install && npm run dev"

echo.
echo ==================================================
echo Services are starting in new terminal windows!
echo Backend URL:  http://localhost:8000
echo Frontend URL: http://localhost:5173
echo ==================================================
pause
