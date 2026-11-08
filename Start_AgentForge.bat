@echo off
title AgentForge AI - One-Click Launcher
cd /d "%~dp0"

echo =====================================================
echo      AgentForge AI  -  Clean One-Click Launch
echo =====================================================
echo.

echo [1/6] Stopping any running AgentForge servers...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,5180 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
echo    Ports 8000 and 5180 are now free.
echo.

echo [2/6] Checking prerequisites...
where python >nul 2>&1
if errorlevel 1 goto no_python
where node >nul 2>&1
if errorlevel 1 goto no_node
echo    Python and Node.js detected.
echo.

echo [3/6] Preparing backend environment...
cd backend
if exist "venv\Scripts\activate.bat" goto venv_ready
echo    Creating Python virtual environment...
python -m venv venv
if errorlevel 1 goto venv_fail
:venv_ready
call venv\Scripts\activate.bat
echo.

echo [4/6] Installing backend dependencies...
python -m pip install --upgrade pip >nul 2>&1
pip install --no-cache-dir -r requirements.txt
if errorlevel 1 goto backend_deps_fail
if not exist "requirements-optional.txt" goto backend_deps_done
echo    Installing optional RAG dependencies - failures here are OK...
pip install --no-cache-dir -r requirements-optional.txt
if errorlevel 1 echo    Warning: optional RAG deps skipped - app runs fine without them.
:backend_deps_done
echo.

echo [5/6] Installing frontend dependencies...
cd ..\frontend
call npm install
if errorlevel 1 goto frontend_deps_fail
echo.

echo [6/6] Starting servers...
cd ..
echo    Backend   - http://localhost:8000
start "AgentForge Backend" cmd /k "cd /d "%~dp0backend" && call venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"
echo    Frontend  - http://localhost:5180
start "AgentForge Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo Waiting for the app to come online...
powershell -NoProfile -Command "$u='http://localhost:5180'; for($i=0;$i -lt 90;$i++){ try{ if((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $u).StatusCode -eq 200){ break } }catch{}; Start-Sleep -Seconds 1 }; Start-Process $u"

echo.
echo =====================================================
echo   AgentForge is running!
echo   - Frontend : http://localhost:5180   opening now
echo   - Backend  : http://localhost:8000
echo   - API Docs : http://localhost:8000/docs
echo.
echo   Two server windows are open. Close them to stop.
echo   Re-run this launcher any time for a clean restart.
echo =====================================================
echo.
pause
exit /b 0

:no_python
echo    Error: Python not found on PATH. Install Python 3.11+ from https://python.org
pause
exit /b 1

:no_node
echo    Error: Node.js not found on PATH. Install Node.js 20+ from https://nodejs.org
pause
exit /b 1

:venv_fail
echo    Error: Failed to create virtual environment.
pause
exit /b 1

:backend_deps_fail
echo    Error: Failed to install backend dependencies.
pause
exit /b 1

:frontend_deps_fail
echo    Error: Failed to install frontend dependencies.
pause
exit /b 1
