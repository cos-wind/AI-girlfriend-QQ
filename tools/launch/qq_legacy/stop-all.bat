@echo off
setlocal
chcp 65001 >nul
title Stop Atri + NapCat

echo Stopping Atri service, NapCat, and QQ...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$patterns = @('atri_qq_bot','start-atri.bat','start-napcat.bat','NapCatWinBootMain.exe'); $procs = Get-CimInstance Win32_Process | Where-Object { $cmd = $_.CommandLine; $name = $_.Name; ($cmd -and ($patterns | Where-Object { $cmd -like ('*' + $_ + '*') })) -or $name -eq 'QQ.exe' }; foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Host ('Stopped ' + $p.Name + ' PID ' + $p.ProcessId) } catch { Write-Host ('Could not stop PID ' + $p.ProcessId + ': ' + $_.Exception.Message) } }"

echo.
echo Done.
pause
