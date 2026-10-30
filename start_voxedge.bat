@echo off
title VoxEdge Launcher
echo ========================================================
echo   Launching VoxEdge Backend and Frontend
echo ========================================================
start "VoxEdge Backend" cmd /k "cd /d "%~dp0backend" && "..\.venv311\Scripts\python.exe" -m uvicorn app.main:app --app-dir "%~dp0backend" --host 0.0.0.0 --port 8000 --reload"
timeout /t 3 /nobreak >nul
start "VoxEdge Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"
echo.
echo Both servers have been launched in separate console windows!
echo - Frontend: http://localhost:5173
echo - Backend:  http://127.0.0.1:8000/docs
echo.
pause
