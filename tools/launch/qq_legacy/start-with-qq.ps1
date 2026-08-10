$ErrorActionPreference = "SilentlyContinue"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$NapCatSearchRoots = @(
    "D:\Tools\NapCat\OneKey",
    (Join-Path $env:LOCALAPPDATA "NapCat")
)
$NapCatDir = ""
$QQExe = "C:\Program Files\Tencent\QQNT\QQ.exe"
$QQUin = ""
$BotPort = 8765
$OllamaPort = 11434
$VoicePort = 8790
$DefaultOllamaModelsPath = Join-Path $env:USERPROFILE ".ollama\models"
$AsciiAtriModelsPath = "D:\AtriModels"
$LogDir = Join-Path $ProjectDir "logs"
$LogFile = Join-Path $LogDir "hidden-launcher.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-LauncherLog {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Test-ListeningPort {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}

function Test-BotConnected {
    $conn = Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $BotPort -or $_.RemotePort -eq $BotPort }
    return [bool]$conn
}

function Get-ProjectEnvValue {
    param([string]$Name)
    $envFile = Join-Path $ProjectDir ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return ""
    }
    $prefix = "$Name="
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.StartsWith($prefix)) {
            continue
        }
        return $trimmed.Substring($prefix.Length).Trim().Trim('"').Trim("'")
    }
    return ""
}

function Test-NapCatRuntimePath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    foreach ($name in @("NapCatWinBootMain.exe", "NapCatWinBootHook.dll", "napcat.mjs", "qqnt.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $name) -PathType Leaf)) {
            return $false
        }
    }
    return $true
}

function Resolve-NapCatDir {
    $configured = Get-ProjectEnvValue -Name "NAPCAT_DIR"
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = $env:NAPCAT_DIR
    }
    if (Test-NapCatRuntimePath -Path $configured) {
        return (Resolve-Path -LiteralPath $configured).Path
    }

    $candidates = @()
    foreach ($root in $NapCatSearchRoots) {
        if (Test-NapCatRuntimePath -Path $root) {
            $candidates += Get-Item -LiteralPath $root
        }
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        $patterns = @(
            (Join-Path $root "NapCat*.Shell\versions\*\resources\app\napcat"),
            (Join-Path $root "versions\*\resources\app\napcat")
        )
        foreach ($pattern in $patterns) {
            $candidates += Get-ChildItem -Path $pattern -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-NapCatRuntimePath -Path $_.FullName }
        }
    }
    $match = $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    return if ($match) { $match.FullName } else { "" }
}

$configuredQQ = Get-ProjectEnvValue -Name "QQ_EXE"
if ([string]::IsNullOrWhiteSpace($configuredQQ)) {
    $configuredQQ = $env:QQ_EXE
}
if (-not [string]::IsNullOrWhiteSpace($configuredQQ)) {
    $QQExe = $configuredQQ
}
$QQUin = Get-ProjectEnvValue -Name "BOT_QQ"
if ([string]::IsNullOrWhiteSpace($QQUin)) {
    $QQUin = $env:BOT_QQ
}
$NapCatDir = Resolve-NapCatDir

function Get-OllamaModelsPath {
    $configured = Get-ProjectEnvValue -Name "OLLAMA_MODELS"
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = $env:OLLAMA_MODELS
    }
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = $DefaultOllamaModelsPath
    }
    return $configured
}

function Test-NapCatBootRunning {
    $proc = Get-CimInstance Win32_Process -Filter "Name='NapCatWinBootMain.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -like "$NapCatDir*" } |
        Select-Object -First 1
    return [bool]$proc
}

function Show-QQWindow {
    param([int]$TimeoutSeconds = 30)

    if (-not ([System.Management.Automation.PSTypeName]"AtriQQWindow").Type) {
        Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class AtriQQWindow {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $qq = Get-Process QQ -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 } |
            Sort-Object StartTime -Descending |
            Select-Object -First 1

        if ($qq) {
            [AtriQQWindow]::ShowWindowAsync($qq.MainWindowHandle, 5) | Out-Null
            Start-Sleep -Milliseconds 150
            [AtriQQWindow]::ShowWindowAsync($qq.MainWindowHandle, 9) | Out-Null
            [AtriQQWindow]::SetForegroundWindow($qq.MainWindowHandle) | Out-Null
            Write-LauncherLog "QQ window restored: pid=$($qq.Id)."
            return
        }

        $qqPids = @(Get-Process QQ -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.Id })
        $handles = New-Object System.Collections.Generic.List[IntPtr]
        [AtriQQWindow]::EnumWindows({
            param([IntPtr]$hWnd, [IntPtr]$lParam)

            [uint32]$windowPid = 0
            [AtriQQWindow]::GetWindowThreadProcessId($hWnd, [ref]$windowPid) | Out-Null
            if ($qqPids -contains [int]$windowPid) {
                $className = New-Object System.Text.StringBuilder 256
                [AtriQQWindow]::GetClassName($hWnd, $className, $className.Capacity) | Out-Null
                if ($className.ToString() -eq "Chrome_WidgetWin_0") {
                    $handles.Add($hWnd) | Out-Null
                }
            }

            return $true
        }, [IntPtr]::Zero) | Out-Null

        if ($handles.Count -gt 0) {
            $handle = $handles[0]
            [AtriQQWindow]::ShowWindowAsync($handle, 5) | Out-Null
            Start-Sleep -Milliseconds 150
            [AtriQQWindow]::ShowWindowAsync($handle, 9) | Out-Null
            [AtriQQWindow]::SetForegroundWindow($handle) | Out-Null
            Write-LauncherLog "QQ hidden Chrome window restored: handle=$handle."
            return
        }

        Start-Sleep -Milliseconds 500
    }

    Write-LauncherLog "QQ window was not found within $TimeoutSeconds seconds."
}

function Start-OllamaIfNeeded {
    if (Test-ListeningPort -Port $OllamaPort) {
        Write-LauncherLog "Ollama already listening on $OllamaPort."
        return
    }

    $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (-not (Test-Path -LiteralPath $ollama)) {
        $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
        if ($cmd) {
            $ollama = $cmd.Source
        }
    }

    if (Test-Path -LiteralPath $ollama) {
        $modelsPath = Get-OllamaModelsPath
        New-Item -ItemType Directory -Force -Path $modelsPath | Out-Null
        $env:OLLAMA_MODELS = $modelsPath
        Write-LauncherLog "Starting Ollama in background. models=$modelsPath"
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden | Out-Null
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 500
            if (Test-ListeningPort -Port $OllamaPort) {
                Write-LauncherLog "Ollama is ready."
                return
            }
        }
        Write-LauncherLog "Ollama did not report ready within timeout."
    } else {
        Write-LauncherLog "Ollama executable not found; bot will use fallback if model is unavailable."
    }
}

function Start-AtriIfNeeded {
    if (Test-ListeningPort -Port $BotPort) {
        Write-LauncherLog "Atri service already listening on $BotPort."
        return
    }

    $pythonw = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
    $python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $pythonw) {
        $pythonExe = $pythonw
    } elseif (Test-Path -LiteralPath $python) {
        $pythonExe = $python
    } else {
        Write-LauncherLog "Python venv not found. Run tools\launch\atri\start-atri.bat once to repair dependencies."
        return
    }

    Write-LauncherLog "Starting Atri service in background."
    Start-Process -FilePath $pythonExe -ArgumentList "-m", "atri_qq_bot" -WorkingDirectory $ProjectDir -WindowStyle Hidden | Out-Null

    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-ListeningPort -Port $BotPort) {
            Write-LauncherLog "Atri service is ready."
            return
        }
    }

    Write-LauncherLog "Atri service did not report ready within timeout."
}

function Start-VoiceIfNeeded {
    $asrEnabled = (Get-ProjectEnvValue -Name "VOICE_ASR_ENABLED").ToLower() -in @("1", "true", "yes", "on")
    $ttsEnabled = (Get-ProjectEnvValue -Name "VOICE_TTS_ENABLED").ToLower() -in @("1", "true", "yes", "on")
    if (-not ($asrEnabled -or $ttsEnabled)) { return }
    if (Test-ListeningPort -Port $VoicePort) {
        Write-LauncherLog "Voice service already listening on $VoicePort."
        return
    }
    $ollamaModelsPath = Get-OllamaModelsPath
    $runtimeCandidates = @(
        (Join-Path $ProjectDir "data\runtime\voice-runtime"),
        (Join-Path $ollamaModelsPath "manifests\atri-runtime"),
        (Join-Path (Split-Path $ollamaModelsPath -Parent) "Speech\atri-runtime")
    )
    $runtimeRoot = $runtimeCandidates |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ ".venv\Scripts\python.exe") } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($runtimeRoot)) {
        $runtimeRoot = $runtimeCandidates[0]
    }
    $pythonw = Join-Path $runtimeRoot ".venv\Scripts\pythonw.exe"
    $python = Join-Path $runtimeRoot ".venv\Scripts\python.exe"
    $pythonExe = if (Test-Path -LiteralPath $pythonw) { $pythonw } else { $python }
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Write-LauncherLog "Voice feature is enabled but its isolated runtime is not installed."
        return
    }
    $modelRoot = if (Test-Path -LiteralPath $AsciiAtriModelsPath) {
        $AsciiAtriModelsPath
    } else {
        Join-Path $ollamaModelsPath "AI_ATRI"
    }
    $env:MODELSCOPE_CACHE = Join-Path $modelRoot "voice\modelscope"
    $env:HF_HOME = Join-Path $modelRoot "voice\huggingface"
    $env:ATRI_ASR_PROVIDER = "sensevoice"
    $localSenseVoice = Join-Path $env:MODELSCOPE_CACHE "models\iic--SenseVoiceSmall\snapshots\master"
    $env:ATRI_ASR_MODEL = if (Test-Path -LiteralPath (Join-Path $localSenseVoice "model.pt")) { $localSenseVoice } else { "iic/SenseVoiceSmall" }
    $env:ATRI_ASR_DEVICE = "cpu"
    $compatPath = Join-Path $ProjectDir "tools\voice\compat"
    $existingPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($existingPythonPath)) {
        $compatPath
    } else {
        $compatPath + [IO.Path]::PathSeparator + $existingPythonPath
    }
    Write-LauncherLog "Starting isolated voice service in background."
    Start-Process -FilePath $pythonExe -ArgumentList "-m", "atri_voice_service" -WorkingDirectory $ProjectDir -WindowStyle Hidden | Out-Null
}

function Start-NapCatIfNeeded {
    if (Test-BotConnected) {
        Write-LauncherLog "NapCat is already connected to Atri."
        Show-QQWindow -TimeoutSeconds 5
        return
    }

    if (Test-NapCatBootRunning) {
        Write-LauncherLog "NapCat boot process is already running."
        Show-QQWindow -TimeoutSeconds 15
        return
    }

    if ([string]::IsNullOrWhiteSpace($NapCatDir)) {
        Write-LauncherLog "NapCat runtime was not found. Set NAPCAT_DIR in .env or install NapCat under a supported location."
        return
    }
    if ([string]::IsNullOrWhiteSpace($QQUin) -or $QQUin -notmatch '^\d+$') {
        Write-LauncherLog "BOT_QQ is missing or invalid in .env."
        return
    }

    $launcher = Join-Path $NapCatDir "NapCatWinBootMain.exe"
    $hook = Join-Path $NapCatDir "NapCatWinBootHook.dll"
    $napcatMain = Join-Path $NapCatDir "napcat.mjs"
    $loadPath = Join-Path $NapCatDir "loadNapCat.js"
    $patchPackage = Join-Path $NapCatDir "qqnt.json"

    foreach ($required in @($launcher, $hook, $napcatMain, $patchPackage, $QQExe)) {
        if (-not (Test-Path -LiteralPath $required)) {
            Write-LauncherLog "Required launcher file not found: $required"
            return
        }
    }

    Write-LauncherLog "Closing stale QQ/NapCat processes before direct NapCat launch."
    Get-Process QQ -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process NapCatWinBootMain -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    $napcatUri = "file:///" + (($napcatMain -replace "\\", "/") -replace " ", "%20")
    "(async () => {await import(`"$napcatUri`")})()" |
        Set-Content -LiteralPath $loadPath -Encoding UTF8

    $env:NAPCAT_PATCH_PACKAGE = $patchPackage
    $env:NAPCAT_LOAD_PATH = $loadPath
    $env:NAPCAT_INJECT_PATH = $hook
    $env:NAPCAT_LAUNCHER_PATH = $launcher
    $env:NAPCAT_MAIN_PATH = $napcatMain
    $env:NAPCAT_QUICK_ACCOUNT = $QQUin

    Write-LauncherLog "Starting NapCat QQ directly for $QQUin."
    $arguments = "`"$QQExe`" `"$hook`" -q $QQUin"
    Start-Process -FilePath $launcher `
        -ArgumentList $arguments `
        -WorkingDirectory $NapCatDir `
        -WindowStyle Hidden | Out-Null

    Show-QQWindow -TimeoutSeconds 35

    for ($i = 0; $i -lt 75; $i++) {
        Start-Sleep -Seconds 1
        if (Test-BotConnected) {
            Write-LauncherLog "NapCat connected to Atri."
            return
        }
    }

    if (Test-NapCatBootRunning) {
        Write-LauncherLog "NapCat started, waiting for OneBot connection."
        return
    }

    Write-LauncherLog "NapCat failed to stay running."
}

Write-LauncherLog "Hidden QQ launcher invoked."
Start-OllamaIfNeeded
Start-VoiceIfNeeded
Start-AtriIfNeeded
Start-NapCatIfNeeded
