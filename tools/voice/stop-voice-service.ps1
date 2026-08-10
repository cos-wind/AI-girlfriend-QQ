$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PidFile = Join-Path $ProjectDir "data\runtime\voice-service.pid"

function Get-ListeningProcessId {
    param([int]$Port)
    $Connection = Get-NetTCPConnection `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($Connection) {
        return [int]$Connection.OwningProcess
    }
    return $null
}

$Processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
$TargetIds = New-Object System.Collections.Generic.HashSet[int]
if (Test-Path -LiteralPath $PidFile) {
    $RawPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($RawPid -match '^\d+$') {
        $TargetIds.Add([int]$RawPid) | Out-Null
    }
}
$ListeningProcessId = Get-ListeningProcessId -Port 8790
if ($ListeningProcessId) {
    $ListenerProcess = $Processes | Where-Object ProcessId -eq $ListeningProcessId | Select-Object -First 1
    if ($ListenerProcess -and $ListenerProcess.CommandLine -like "*atri_voice_service*") {
        $TargetIds.Add([int]$ListeningProcessId) | Out-Null
    }
}
do {
    $Added = $false
    foreach ($ProcessInfo in $Processes) {
        if ($TargetIds.Contains([int]$ProcessInfo.ParentProcessId) -and $ProcessInfo.CommandLine -like "*atri_voice_service*") {
            if ($TargetIds.Add([int]$ProcessInfo.ProcessId)) { $Added = $true }
        }
    }
} while ($Added)

$Targets = $Processes | Where-Object {
    $TargetIds.Contains([int]$_.ProcessId) -and $_.CommandLine -like "*atri_voice_service*"
} | Sort-Object ProcessId -Descending
foreach ($ProcessInfo in $Targets) {
    Stop-Process -Id $ProcessInfo.ProcessId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    if (-not (Get-ListeningProcessId -Port 8790)) {
        Write-Host "Voice service stopped."
        exit 0
    }
    Start-Sleep -Milliseconds 250
}
throw "Voice service still owns port 8790 after stop request."
