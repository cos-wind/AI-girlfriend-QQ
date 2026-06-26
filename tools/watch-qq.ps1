$ErrorActionPreference = "SilentlyContinue"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectDir "logs"
$LogFile = Join-Path $LogDir "qq-watcher.log"
$PidFile = Join-Path $LogDir "qq-watcher.pid"
$QQExe = "C:\Program Files\Tencent\QQNT\QQ.exe"
$NapCatDir = "D:\Tools\NapCat\OneKey\NapCat.44498.Shell\versions\9.9.26-44498\resources\app\napcat"
$BotPort = 8765

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-WatcherLog {
    param([string]$Message)
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message" -Encoding UTF8
}

function Test-ExistingWatcher {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $false
    }

    $oldPidText = Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue
    $oldPid = 0
    if (-not [int]::TryParse(($oldPidText -as [string]).Trim(), [ref]$oldPid)) {
        return $false
    }

    if ($oldPid -eq $PID) {
        return $false
    }

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue
    return [bool]($proc -and $proc.CommandLine -like "*watch-qq.ps1*")
}

function Test-BotConnected {
    $conn = Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $BotPort -or $_.RemotePort -eq $BotPort }
    return [bool]$conn
}

function Test-NapCatBootRunning {
    $proc = Get-CimInstance Win32_Process -Filter "Name='NapCatWinBootMain.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -like "$NapCatDir*" } |
        Select-Object -First 1
    return [bool]$proc
}

function Test-QQMainProcess {
    $qq = Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -eq $QQExe -and
            ($_.CommandLine -notlike "*--type=*")
        } |
        Select-Object -First 1
    return [bool]$qq
}

function Invoke-AtriLauncher {
    $launcher = Join-Path $PSScriptRoot "start-with-qq.vbs"
    Write-WatcherLog "QQ detected. Starting Atri stack."
    Start-Process -FilePath "wscript.exe" `
        -ArgumentList "`"$launcher`"" `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden | Out-Null
}

if (Test-ExistingWatcher) {
    exit 0
}

Set-Content -LiteralPath $PidFile -Value $PID -Encoding ASCII
Write-WatcherLog "QQ watcher started."

$armed = $true

while ($true) {
    Start-Sleep -Seconds 1

    $qqRunning = Test-QQMainProcess
    if (-not $qqRunning) {
        $armed = $true
        continue
    }

    if ($armed -and -not (Test-BotConnected) -and -not (Test-NapCatBootRunning)) {
        Invoke-AtriLauncher
        $armed = $false
        Start-Sleep -Seconds 20
        continue
    }

    if (Test-BotConnected) {
        $armed = $false
    }
}
