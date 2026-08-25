$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PidFile = Join-Path $ProjectDir "data\runtime\gpt-sovits.pid"

$TargetIds = New-Object System.Collections.Generic.HashSet[int]
if (Test-Path -LiteralPath $PidFile) {
    try {
        $TargetIds.Add([int](Get-Content -LiteralPath $PidFile -Raw)) | Out-Null
    } catch {
        # Ignore a truncated/stale pid file and fall back to the listener probe.
    }
}
# Do not scan Win32_Process here. On some Windows installations that WMI query
# can block indefinitely while the inference lock is held. The launcher writes
# the listener PID, and netstat provides a bounded, dependency-free fallback.
netstat.exe -ano -p TCP 2>$null |
    Select-String -Pattern ':9880\s+.*LISTENING\s+(\d+)\s*$' |
    ForEach-Object {
        $match = [regex]::Match($_.ToString(), ':9880\s+.*LISTENING\s+(\d+)\s*$')
        if ($match.Success) {
            $TargetIds.Add([int]$match.Groups[1].Value) | Out-Null
        }
    }
foreach ($ProcessId in $TargetIds) {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "GPT-SoVITS stopped."
