@echo off
title VoxEdge React Frontend
cd /d "%~dp0frontend"
echo ========================================================
echo   Starting VoxEdge React Frontend on port 5173
echo   URL: http://localhost:5173
echo ========================================================
npm run dev
pause

