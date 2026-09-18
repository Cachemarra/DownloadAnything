@echo off
setlocal enabledelayedexpansion

REM Determine project root
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Find Python executable
where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PY=python"
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY=py -3"
    ) else (
        echo [ERROR] Python 3 was not found on your PATH.
        echo Please install Python 3.9+ from https://www.python.org/ and check "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

REM Setup virtual environment if missing
if not exist ".venv" (
    echo [*] Creating virtual environment (.venv)...
    %PY% -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Check and install dependencies if uvicorn is missing
python -c "import uvicorn, fastapi, yt_dlp" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing required dependencies...
    python -m pip install --upgrade pip
    if exist requirements.txt (
        pip install -r requirements.txt
    ) else (
        pip install "fastapi>=0.115.0" "uvicorn[standard]>=0.30.6" "yt-dlp>=2024.7.4" "sse-starlette>=2.1.3" "pydantic>=2.8.2"
    )
)

REM Launch Download Anything standalone web application
echo.
echo [*] Starting Download Anything...
python main.py

pause
