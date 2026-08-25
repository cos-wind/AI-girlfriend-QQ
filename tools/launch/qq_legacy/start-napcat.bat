@echo off
setlocal
chcp 65001 >nul
title Atri + NapCat core launcher

cd /d "%~dp0..\..\.."

echo ========================================
echo   Start Atri + NapCat core
echo ========================================
echo.
echo This compatibility entry delegates to the single hidden launcher.
echo If QQ login is required, open NapCat WebUI and scan there.
echo.

powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start-with-qq.ps1" -Mode core
if errorlevel 1 (
    echo Failed to request the ATRI core launcher.
    echo Run tools\launch\atri\start-atri.bat once if the project .venv is missing.
    pause
    exit /b 1
)

echo Core launcher requested. This window can be closed.
exit /b 0
