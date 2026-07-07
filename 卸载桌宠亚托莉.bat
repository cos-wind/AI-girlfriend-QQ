@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\desktop_pet\uninstall-desktop-pet.ps1"

echo.
echo 亚托莉桌宠快捷方式和开机启动项已移除。
pause
