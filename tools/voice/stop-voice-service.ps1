$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PidFile = Join-Path $ProjectDir "data\runtime\voice-service.pid"

function Get-ListeningProcessId {
    param([int]$Port)
    foreach ($Line in (netstat.exe -ano -p TCP 2>$null)) {
        if ($Line -match ("^\s*TCP\s+\S+:" + $Port + "\s+\S+\s+LISTENING\s+(\d+)\s*$")) {
            return [int]$Matches[1]
        }
    }
    return $null
}

$TargetIds = New-Object System.Collections.Generic.HashSet[int]
$RecordedProcessId = $null
if (Test-Path -LiteralPath $PidFile) {
    $RawPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($RawPid -match '^\d+$') {
        $RecordedProcessId = [int]$RawPid
    }
}
$ListeningProcessId = Get-ListeningProcessId -Port 8790
if ($ListeningProcessId) {
    $IsAtriVoice = $false
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8790/health" -TimeoutSec 2
        $IsAtriVoice = [bool]$Health.ok -and $Health.service -eq "atri-voice"
    } catch {
        $IsAtriVoice = $false
    }
    if ($IsAtriVoice) {
        $TargetIds.Add([int]$ListeningProcessId) | Out-Null
        if ($RecordedProcessId -eq $ListeningProcessId) {
            $TargetIds.Add([int]$RecordedProcessId) | Out-Null
        }
    }
}
foreach ($ProcessId in $TargetIds) {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
    $RemainingProcessId = Get-ListeningProcessId -Port 8790
    if (-not $RemainingProcessId) {
        Write-Host "Voice service stopped."
        exit 0
    }
    # A Python process can take a moment to leave the listener table while an
    # inference future is unwinding. Retry only the already verified ATRI PID;
    # never touch a replacement process that later acquires the same port.
    if (($Attempt % 4) -eq 3 -and $TargetIds.Contains([int]$RemainingProcessId)) {
        Stop-Process -Id $RemainingProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 250
}
throw "Voice service still owns port 8790 after stop request."
