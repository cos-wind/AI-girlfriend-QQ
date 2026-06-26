@echo off
setlocal
chcp 65001 >nul
title Atri QQ Bot

cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ========================================
echo   Atri QQ Bot
echo ========================================
echo.

set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Please install Python 3.11 or newer, then run this file again.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Creating .env from .env.example ...
    copy ".env.example" ".env" >nul
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { exit 10 } else { exit 0 }"
if %ERRORLEVEL%==10 (
    echo Port 8765 is already listening.
    echo The bot may already be running.
    echo.
    echo NapCat reverse WebSocket address:
    echo   ws://127.0.0.1:8765/onebot
    echo.
    pause
    exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating local Python environment. First run may take a minute...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo Failed to create Python environment.
        echo.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import atri_qq_bot, websockets, httpx, dotenv" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies. First run may take a minute...
    ".venv\Scripts\python.exe" -m pip install -e . --disable-pip-version-check
    if errorlevel 1 (
        echo Dependency installation failed.
        echo.
        pause
        exit /b 1
    )
)

echo.
echo Bot is starting...
echo NapCat reverse WebSocket address:
echo   ws://127.0.0.1:8765/onebot
echo.
echo Keep this window open while using the bot.
echo Press Ctrl+C or close this window to stop it.
echo.

".venv\Scripts\python.exe" -m atri_qq_bot

echo.
echo Bot stopped.
pause
