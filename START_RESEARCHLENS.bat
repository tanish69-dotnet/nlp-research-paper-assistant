@echo off
REM Start ResearchLens locally on Windows (no Docker required)
REM Requires: Python with deps installed, Ollama with qwen2.5:1.5b and qwen2.5vl:3b, and network access for arXiv search if used.

REM --- Environment ---
set MODEL_PROVIDER=ollama
set RETRIEVAL_MODE=http
set RETRIEVAL_BASE_URL=http://127.0.0.1:8000
set API_HOST=127.0.0.1
set API_PORT=8001
set ANALYZER_MODEL=qwen2.5:1.5b
set TEXT_MODEL=qwen2.5:1.5b
set TABLE_MODEL=qwen2.5:1.5b
set JUDGE_MODEL=qwen2.5:1.5b
set GENERATOR_MODEL=qwen2.5:1.5b
set VISION_MODEL=qwen2.5vl:3b
set LOG_FORMAT=console
set LOG_LEVEL=INFO

echo Checking Ollama...
curl -s http://127.0.0.1:11434/api/tags >NUL 2>&1
if errorlevel 1 (
  echo Resolved: starting Ollama server...
  start "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve
  timeout /t 6 >NUL
)

if not exist "multimodal_rag_retrieval_person2\venv\Scripts\python.exe" (
  echo ERROR: retrieval venv not found at multimodal_rag_retrieval_person2\venv\Scripts\python.exe
  pause
  exit /b 1
)

echo Checking retrieval service on :8000...
curl -s http://127.0.0.1:8000/health >NUL 2>&1
if errorlevel 1 (
  echo Starting retrieval service on :8000...
  start "ResearchLens retrieval :8000" cmd /k "multimodal_rag_retrieval_person2\venv\Scripts\python.exe -m uvicorn src.app:app --host 127.0.0.1 --port 8000"
  echo Waiting for retrieval /health — corpus indexes (~90s on first cold start with 50 papers)...
  :RETRY_RETRIEVAL
  timeout /t 6 >NUL
  curl -s http://127.0.0.1:8000/health >NUL 2>&1
  if errorlevel 1 goto RETRY_RETRIEVAL
) else (
  echo retrieval already reachable.
)

echo Checking reasoning service on :8001...
curl -s http://127.0.0.1:8001/api/v1/health >NUL 2>&1
if errorlevel 1 (
  echo Starting reasoning service on :8001...
  start "ResearchLens reasoning :8001" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port 8001"
  timeout /t 4 >NUL
  :RETRY_REASONING
  timeout /t 4 >NUL
  curl -s http://127.0.0.1:8001/api/v1/health >NUL 2>&1
  if errorlevel 1 goto RETRY_REASONING
) else (
  echo reasoning already reachable.
)

echo.
echo ResearchLens is running.
echo   UI:        http://127.0.0.1:8001/ui
echo   Reasoning: http://127.0.0.1:8001/api/v1/health
echo   Retrieval: http://127.0.0.1:8000/health
echo.
echo Press any key to open the UI.
pause >NUL
start "" http://127.0.0.1:8001/ui
