@echo off
setlocal
chcp 65001 >nul
title Stop Atri QQ Bot

echo Stopping Atri QQ Bot on port 8765...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$conns = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; if (-not $conns) { Write-Host 'No running bot was found.'; exit 0 }; foreach ($processId in ($conns.OwningProcess | Sort-Object -Unique)) { $p = Get-Process -Id $processId -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -like 'python*') { Stop-Process -Id $processId -Force; Write-Host ('Stopped python process: ' + $processId) } else { Write-Host ('Port 8765 is used by another process, skipped: ' + $processId) } }"

echo.
pause
