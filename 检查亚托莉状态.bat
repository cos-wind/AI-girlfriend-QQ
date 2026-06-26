@echo off
setlocal
chcp 65001 >nul
title Check Atri Status

echo ========================================
echo   Atri QQ Bot Status
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\check-status.ps1"

echo.
pause
