@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set DO_PAUSE=1
if /i "%~1"=="--nopause" set DO_PAUSE=0

set OLLAMA_HEALTH_URL=http://127.0.0.1:11434/api/tags
set BACKEND_HEALTH_URL=http://127.0.0.1:8000/health
set FRONTEND_URL=http://localhost:8080/

goto :main

rem Polling helper: waits until URL returns HTTP 200 (or times out).
:wait_for_http
set "url=%~1"
set /a "timeout_sec=%~2"
set /a elapsed=0
:wait_http_loop
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri '%url%' -UseBasicParsing -Method GET -TimeoutSec 2).StatusCode | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 exit /b 0
set /a elapsed+=2
if !elapsed! GEQ %timeout_sec% exit /b 1
powershell -NoProfile -Command "Start-Sleep -Seconds 2"
goto :wait_http_loop

rem Polling helper: waits until Ollama has at least one gemma3 model loaded.
:wait_for_ollama_gemma3
set /a "timeout_sec=%~1"
set /a elapsed=0
:wait_ollama_loop
powershell -NoProfile -Command "$u='http://127.0.0.1:11434/api/tags'; try { $r=Invoke-RestMethod -Uri $u -UseBasicParsing -Method GET -TimeoutSec 2; if (($r.models | Where-Object { $_.name -like 'gemma3*' } | Select-Object -First 1)) { exit 0 } } catch {} ; exit 1"
if %errorlevel%==0 exit /b 0
set /a elapsed+=2
if !elapsed! GEQ %timeout_sec% exit /b 1
powershell -NoProfile -Command "Start-Sleep -Seconds 2"
goto :wait_ollama_loop

:main
echo ==================================================
echo Starting SRM Admission Chatbot...
echo ==================================================

echo.
echo [1/4] Starting Ollama ^(server + gemma3^)...

rem Start Ollama only if not already reachable.
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri '%OLLAMA_HEALTH_URL%' -UseBasicParsing -Method GET -TimeoutSec 2).StatusCode | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
    echo Ollama is already running.
) else (
    start cmd /k "ollama serve"
    echo Waiting for Ollama server...
    call :wait_for_http "%OLLAMA_HEALTH_URL%" 60
    if errorlevel 1 (
        echo Timed out waiting for Ollama to start.
        exit /b 1
    )
)

rem Ensure gemma3 is available to reduce first-request latency.
powershell -NoProfile -Command "$u='http://127.0.0.1:11434/api/tags'; try { $r=Invoke-RestMethod -Uri $u -UseBasicParsing -Method GET -TimeoutSec 2; if (($r.models | Where-Object { $_.name -like 'gemma3*' } | Select-Object -First 1)) { exit 0 } } catch {} ; exit 1"
if %errorlevel%==0 (
    echo gemma3 is already available in Ollama.
) else (
    start cmd /k "ollama pull gemma3"
    echo Waiting for gemma3 model in Ollama...
    call :wait_for_ollama_gemma3 300
    if errorlevel 1 (
        echo Timed out waiting for gemma3. First chat may be slow.
    )
)

echo.
echo [2/4] Setting up Python Environment...
if not exist .venv\Scripts\activate.bat (
    echo Creating Python virtual environment ^(.venv^)...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing/Verifying Python requirements...
python -m pip install -r requirements.txt

echo.
echo Verifying Vector Database...
if not exist vector_db_qdrant\ (
    echo Vector DB not found. Building Vector Database...
    python backend/rag_pipeline.py --build
)

echo.
echo [3/4] Starting Backend Server ^(FastAPI on Port 8000^)...
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri '%BACKEND_HEALTH_URL%' -UseBasicParsing -Method GET -TimeoutSec 2).StatusCode | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
    echo Backend is already running.
) else (
    start cmd /k "call .venv\Scripts\activate.bat && uvicorn backend.main:app --host 127.0.0.1 --port 8000"
    echo Waiting for backend health...
    call :wait_for_http "%BACKEND_HEALTH_URL%" 90
    if errorlevel 1 (
        echo Timed out waiting for backend. Check backend terminal output.
        exit /b 1
    )
)

echo.
echo [4/4] Starting Frontend Server ^(Vite^)...
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri '%FRONTEND_URL%' -UseBasicParsing -Method GET -TimeoutSec 2).StatusCode | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
    echo Frontend is already running.
) else (
    start cmd /k "cd frontend && if not exist node_modules (npm install) && npm run dev"
    echo Waiting for frontend...
    call :wait_for_http "%FRONTEND_URL%" 90
    if errorlevel 1 (
        echo Timed out waiting for frontend. Check frontend terminal output.
        exit /b 1
    )
)

echo.
echo ==================================================
echo Services are ready.
echo Backend URL:  http://localhost:8000
echo Frontend URL: http://localhost:8080
echo ==================================================

if "%DO_PAUSE%"=="1" pause
exit /b 0

