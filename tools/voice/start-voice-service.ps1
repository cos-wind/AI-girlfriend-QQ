param(
    [string]$RuntimeRoot = "",
    [string]$ModelRoot = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
. (Join-Path $PSScriptRoot "voice-endpoint.ps1")
$VoiceServicePort = Get-ConfiguredVoicePort -ProjectDir $ProjectDir
$DefaultLocalModelsRoot = $env:LOCAL_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($DefaultLocalModelsRoot)) {
    $DefaultLocalModelsRoot = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".ollama\models"
}
$DefaultProjectModelRoot = Join-Path $DefaultLocalModelsRoot "AI_ATRI"
if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = $DefaultProjectModelRoot
}
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeCandidates = @(
        (Join-Path $ProjectDir "data\runtime\voice-runtime"),
        (Join-Path $DefaultLocalModelsRoot "manifests\atri-runtime"),
        (Join-Path (Split-Path $DefaultLocalModelsRoot -Parent) "Speech\atri-runtime")
    )
    $RuntimeRoot = $RuntimeCandidates |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ ".venv\Scripts\python.exe") } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $RuntimeRoot = $RuntimeCandidates[0]
    }
}
$Python = Join-Path $RuntimeRoot ".venv\Scripts\python.exe"
$Pythonw = Join-Path $RuntimeRoot ".venv\Scripts\pythonw.exe"
$RuntimeDir = Join-Path $ProjectDir "data\runtime"
$LogDir = Join-Path $ProjectDir "logs"
$PidFile = Join-Path $RuntimeDir "voice-service.pid"

function Get-ListeningProcessId {
    param([int]$Port)
    foreach ($Line in (netstat.exe -ano -p TCP 2>$null)) {
        if ($Line -match ("^\s*TCP\s+\S+:" + $Port + "\s+\S+\s+LISTENING\s+(\d+)\s*$")) {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Test-VoiceReady {
    try {
        $Health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$VoiceServicePort/health" `
            -Method Get `
            -TimeoutSec 3
        return [bool]$Health.ok -and $Health.service -eq "atri-voice" -and [bool]$Health.ready
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Voice runtime is not installed. Run setup-voice-runtime.ps1 first."
}
$ExistingProcessId = Get-ListeningProcessId -Port $VoiceServicePort
if ($ExistingProcessId) {
    try {
        $ExistingHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$VoiceServicePort/health" -TimeoutSec 3
    } catch {
        throw "Port $VoiceServicePort is occupied; cannot confirm an ATRI voice service."
    }
    if ($ExistingHealth.service -ne "atri-voice" -or -not $ExistingHealth.ok) {
        throw "Port $VoiceServicePort belongs to another service. Choose a different port in the desktop app."
    }
    for ($i = 0; $i -lt 180; $i++) {
        if (Test-VoiceReady) {
            Write-Host "Voice service is ready at http://127.0.0.1:$VoiceServicePort"
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Voice service is listening but did not become ready within 90 seconds."
}

New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir, $ModelRoot | Out-Null
$AsciiModelRoot = $env:ASCII_ATRI_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($AsciiModelRoot)) {
    $AsciiModelRoot = Join-Path $ProjectDir "models"
}
$ModelAccessRoot = if (Test-Path -LiteralPath $AsciiModelRoot) {
    $AsciiModelRoot
} else {
    $ModelRoot
}
$env:MODELSCOPE_CACHE = Join-Path $ModelAccessRoot "voice\modelscope"
$env:HF_HOME = Join-Path $ModelAccessRoot "voice\huggingface"
$env:ATRI_ASR_PROVIDER = "sensevoice"
$LocalSenseVoice = Join-Path $env:MODELSCOPE_CACHE "models\iic--SenseVoiceSmall\snapshots\master"
$env:ATRI_ASR_MODEL = if (Test-Path -LiteralPath (Join-Path $LocalSenseVoice "model.pt")) {
    $LocalSenseVoice
} else {
    "iic/SenseVoiceSmall"
}
$env:ATRI_ASR_DEVICE = "cpu"
if ([string]::IsNullOrWhiteSpace($env:ATRI_ASR_WORKER_IDLE_SECONDS)) {
    $env:ATRI_ASR_WORKER_IDLE_SECONDS = "60"
}
$env:ATRI_VOICE_HOST = "127.0.0.1"
$env:ATRI_VOICE_PORT = "$VoiceServicePort"
$LocalVad = Join-Path $env:MODELSCOPE_CACHE "models\iic--speech_fsmn_vad_zh-cn-16k-common-pytorch\snapshots\master"
$env:ATRI_ASR_VAD_MODEL = if (Test-Path -LiteralPath (Join-Path $LocalVad "model.pt")) {
    $LocalVad
} else {
    "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
}
$env:ATRI_ASR_PREPROCESS_ENABLED = "true"
$env:ATRI_ASR_LEXICON_PATH = Join-Path $ProjectDir "data\voice\asr-hotwords.json"
$OriginalVoiceFolder = "ATRI" + [char]0x8BAD + [char]0x7EC3 + [char]0x97F3 +
    [char]0x9891 + [char]0x7D20 + [char]0x6750
$env:ATRI_ORIGINAL_VOICE_LIBRARY = Join-Path $env:USERPROFILE (Join-Path "Music" $OriginalVoiceFolder)
$env:ATRI_ORIGINAL_CLIP_ENABLED = "true"
$env:ATRI_TTS_QUALITY_GATE_ENABLED = "false"
$env:ATRI_TTS_PREWARM_ENABLED = "true"
$env:ATRI_TTS_IDLE_SHUTDOWN_SECONDS = "0"
$env:ATRI_TTS_TOTAL_TIMEOUT_SECONDS = "75"
$env:ATRI_TTS_STARTUP_TIMEOUT_SECONDS = "45"
$env:ATRI_TTS_QUALITY_MAX_ERROR_RATE = "0.22"
$env:ATRI_TTS_QUALITY_RETRIES = "1"
$env:ATRI_SINGING_ENABLED = "true"
$env:ATRI_SINGING_PIPELINE_MANIFEST = Join-Path $ProjectDir "data\voice\singing-pipeline.json"
$env:ATRI_SINGING_MAXIMUM_JOBS = "50"
$CompatPath = Join-Path $ProjectDir "tools\voice\compat"
$ExistingPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($ExistingPythonPath)) {
    $CompatPath
} else {
    $CompatPath + [IO.Path]::PathSeparator + $ExistingPythonPath
}

$Executable = if (Test-Path -LiteralPath $Pythonw) { $Pythonw } else { $Python }
$Process = Start-Process `
    -FilePath $Executable `
    -ArgumentList "-m", "atri_voice_service" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "voice-service.log") `
    -RedirectStandardError (Join-Path $LogDir "voice-service-error.log") `
    -PassThru
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Milliseconds 500
    $ListeningProcessId = Get-ListeningProcessId -Port $VoiceServicePort
    if ($ListeningProcessId -and (Test-VoiceReady)) {
        $ListeningProcessId | Set-Content -LiteralPath $PidFile -Encoding ASCII
        Write-Host "Voice service is ready at http://127.0.0.1:$VoiceServicePort"
        return
    }
    if ($Process.HasExited) {
        throw "Voice service exited during startup. Check logs\voice-service-error.log."
    }
}
throw "Voice service did not become ready within 90 seconds."
