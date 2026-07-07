@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\desktop_pet\install-desktop-pet.ps1" -Launch

echo.
echo 亚托莉桌宠已安装到开始菜单，可手动固定到任务栏。
pause
