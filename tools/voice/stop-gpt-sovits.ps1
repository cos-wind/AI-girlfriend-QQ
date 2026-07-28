$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PidFile = Join-Path $ProjectDir "data\runtime\gpt-sovits.pid"

$TargetIds = New-Object System.Collections.Generic.HashSet[int]
if (Test-Path -LiteralPath $PidFile) {
    $TargetIds.Add([int](Get-Content -LiteralPath $PidFile -Raw)) | Out-Null
}
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*gpt-sovits*api_v2.py*" } |
    ForEach-Object { $TargetIds.Add([int]$_.ProcessId) | Out-Null }
foreach ($ProcessId in $TargetIds) {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "GPT-SoVITS stopped."
