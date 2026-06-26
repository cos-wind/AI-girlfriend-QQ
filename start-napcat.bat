@echo off
setlocal
chcp 65001 >nul
title NapCat QQ 3380609082

set "QQ_UIN=3380609082"
set "NAPCAT_DIR=D:\Tools\NapCat\OneKey\NapCat.44498.Shell\versions\9.9.26-44498\resources\app\napcat"
set "BOT_WS=ws://127.0.0.1:8765/onebot"

echo ========================================
echo   NapCat QQ
echo ========================================
echo.

if not exist "%NAPCAT_DIR%\launcher-user.bat" (
    echo NapCat was not found:
    echo   %NAPCAT_DIR%
    echo.
    pause
    exit /b 1
)

echo Closing normal QQ first, so NapCat can take over...
taskkill /F /IM QQ.exe >nul 2>nul
timeout /t 2 /nobreak >nul

set "NAPCAT_QUICK_ACCOUNT=%QQ_UIN%"

echo Starting NapCat QQ: %QQ_UIN%
echo OneBot reverse WebSocket:
echo   %BOT_WS%
echo.
echo If QQ asks you to scan/login, finish that once.
echo After login, send a private message to %QQ_UIN% from another QQ to test.
echo.

cd /d "%NAPCAT_DIR%"
call launcher-user.bat -q %QQ_UIN%
