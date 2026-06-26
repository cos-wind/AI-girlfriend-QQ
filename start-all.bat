@echo off
setlocal
chcp 65001 >nul
title Start Atri + NapCat

cd /d "%~dp0"

echo ========================================
echo   Start Atri QQ Bot
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { exit 10 } else { exit 0 }"
if %ERRORLEVEL%==10 (
    echo Atri service is already running on port 8765.
) else (
    echo Opening Atri service window...
    start "Atri Service" cmd /k ""%~dp0start-atri.bat""
    timeout /t 4 /nobreak >nul
)

echo Opening NapCat QQ window...
start "NapCat QQ" cmd /k ""%~dp0start-napcat.bat""

echo.
echo Started.
echo You can close this small launcher window.
timeout /t 3 /nobreak >nul
