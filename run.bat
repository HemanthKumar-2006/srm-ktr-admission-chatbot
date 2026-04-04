@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set DO_PAUSE=1
if /i "%~1"=="--nopause" set DO_PAUSE=0

REM 🔥 CHANGE MODEL HERE (ONLY THIS LINE IN FUTURE)
set MODEL_NAME=gemma3

set OLLAMA_HEALTH_URL=http://127.0.0.1:11434/api/tags
set BACKEND_HEALTH_URL=http://127.0.0.1:8000/health
set FRONTEND_URL=http://127.0.0.1:8080/

goto :main


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


REM 🔥 GENERIC MODEL CHECK
:wait_for_ollama_model
set /a "timeout_sec=%~1"
set /a elapsed=0
:wait_model_loop
powershell -NoProfile -Command "$u='http://127.0.0.1:11434/api/tags'; try { $r=Invoke-RestMethod -Uri $u -UseBasicParsing -Method GET -TimeoutSec 2; if (($r.models | Where-Object { $_.name -like '%MODEL_NAME%*' } | Select-Object -First 1)) { exit 0 } } catch {} ; exit 1"
if %errorlevel%==0 exit /b 0
set /a elapsed+=2
if !elapsed! GEQ %timeout_sec% exit /b 1
powershell -NoProfile -Command "Start-Sleep -Seconds 2"
goto :wait_model_loop


:main
echo ==================================================
echo Starting SRM Admission Chatbot...
echo ==================================================

echo.
echo [1/4] Starting Ollama (server + %MODEL_NAME%)...

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

REM 🔥 CHECK IF MODEL EXISTS
powershell -NoProfile -Command "$u='http://127.0.0.1:11434/api/tags'; try { $r=Invoke-RestMethod -Uri $u -UseBasicParsing -Method GET -TimeoutSec 2; if (($r.models | Where-Object { $_.name -like '%MODEL_NAME%*' } | Select-Object -First 1)) { exit 0 } } catch {} ; exit 1"
if %errorlevel%==0 (
    echo %MODEL_NAME% is already available in Ollama.
) else (
    start cmd /k "ollama pull %MODEL_NAME%"
    echo Waiting for %MODEL_NAME% model in Ollama...
    call :wait_for_ollama_model 300
    if errorlevel 1 (
        echo Timed out waiting for %MODEL_NAME%. First chat may be slow.
    )
)

echo.
echo [2/4] Setting up Python Environment...
if not exist .venv\Scripts\activate.bat (
    echo Creating Python virtual environment (.venv)...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Installing/Verifying Python requirements...
python -m pip install -q -r requirements.txt

echo.
echo Verifying Vector Database...
if not exist vector_db_qdrant\ (
    echo Vector DB not found. Building Vector Database...
    python backend/rag_pipeline.py --build
)

echo.
echo [3/4] Starting Backend Server (FastAPI on Port 8000)...
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
echo [4/4] Starting Frontend Server (Vite)...
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