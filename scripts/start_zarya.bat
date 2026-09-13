@echo off
title Zarya Launcher
echo ZARYA - Windows Start Script
echo ==========================================================
echo.

:: Ensure we are in the project root directory (parent of scripts/)
cd /d "%~dp0\.."

echo [1/2] Launching Python Desktop Agent...
if exist "venv\Scripts\python.exe" (
    start "Zarya Desktop Agent (Python)" cmd /k "venv\Scripts\python.exe scripts\run_agent.py"
) else if exist ".venv\Scripts\python.exe" (
    start "Zarya Desktop Agent (Python)" cmd /k ".venv\Scripts\python.exe scripts\run_agent.py"
) else (
    start "Zarya Desktop Agent (Python)" cmd /k "python scripts\run_agent.py"
)

:: Wait 2 seconds for Python to initialize
timeout /t 2 /nobreak >nul

echo [2/2] Launching Node.js Server ^& Vite Frontend...
start "Zarya Web Server (Node)" cmd /k "npm run dev"

echo.
echo ==========================================================
echo ZARYA IS RUNNING!
echo.
echo Open your browser to: http://localhost:3000
echo Automatically launching Microsoft Edge...
start msedge http://localhost:3000
echo.
echo Note: The Python agent and Node server are running in the
echo two newly opened command prompt windows.
echo To STOP Zarya, simply close those two windows.
echo ==========================================================
echo.
pause
