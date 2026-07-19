@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: ── Check Python is available ───────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+ from https://www.python.org
    pause
    exit /b 1
)

:: ── Verify Python 3.10+ ──────────────────────────────────────────────────────
for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set PY_VER=%%V
for /f "tokens=1,2 delims=." %%A in ("!PY_VER!") do (
    set PY_MAJOR=%%A
    set PY_MINOR=%%B
)
if !PY_MAJOR! LSS 3 (
    echo ERROR: Python !PY_VER! found, but 3.10+ is required.
    echo Please upgrade from: https://www.python.org/downloads/
    pause
    exit /b 1
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo ERROR: Python !PY_VER! found, but 3.10+ is required.
    echo Please upgrade from: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ── Create venv on first run ────────────────────────────────────────────────
if not exist "venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists, skipping creation.
)

:: ── Install / update requirements ───────────────────────────────────────────
echo [2/3] Installing / updating requirements...
venv\Scripts\python.exe -m pip --version >nul 2>&1
if errorlevel 1 (
    echo       pip not found in the virtual environment, bootstrapping it...
    venv\Scripts\python.exe -m ensurepip --upgrade
    if errorlevel 1 (
        echo ERROR: Failed to install pip in the virtual environment.
        pause
        exit /b 1
    )
)

venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Check requirements.txt and your internet connection.
    pause
    exit /b 1
)

:: ── Launch app ───────────────────────────────────────────────────────────────
echo [3/3] Starting Sprite Sheet Cutter...
echo        Open http://127.0.0.1:7860 in your browser if it doesn't open automatically.
echo.
venv\Scripts\python.exe app.py
pause
