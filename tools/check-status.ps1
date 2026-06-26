$listen = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
$established = Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -eq 8765 -or $_.RemotePort -eq 8765 }

if ($listen) {
    Write-Host "Atri service: running"
} else {
    Write-Host "Atri service: not running"
}

if ($established) {
    Write-Host "NapCat connection: connected"
} else {
    Write-Host "NapCat connection: not connected"
}

Write-Host ""

if ($listen -and $established) {
    Write-Host "Status OK. Use another QQ account to message 3380609082."
} else {
    Write-Host "If not connected, double-click start-all.bat or 启动亚托莉.bat."
}
