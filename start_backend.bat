@echo off
title VoxEdge FastAPI Backend
cd /d "%~dp0backend"
set PYTHONPATH=%cd%
echo ========================================================
echo   Starting VoxEdge FastAPI Backend on port 8000
echo   API Docs: http://127.0.0.1:8000/docs
echo ========================================================
"..\.venv311\Scripts\python.exe" -m uvicorn app.main:app --app-dir "%~dp0backend" --host 0.0.0.0 --port 8000 --reload
pause
