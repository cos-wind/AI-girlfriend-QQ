@echo off
setlocal
chcp 65001 >nul
title Atri QQ Bot

cd /d "%~dp0..\..\.."
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

if not exist ".venv\Scripts\python.exe" (
    echo Creating local Python environment. First run may take a minute...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo Failed to create Python environment.
        echo.
        pause
        exit /b 1
    )
    echo Installing dependencies. First run may take a minute...
    ".venv\Scripts\python.exe" -m pip install -e . --disable-pip-version-check
    if errorlevel 1 (
        echo Dependency installation failed.
        echo.
        pause
        exit /b 1
    )
)

echo Starting Atri in the background...
start "" /b ".venv\Scripts\pythonw.exe" "tools\launch\qq_legacy\hidden_launcher.py" core
exit /b 0
