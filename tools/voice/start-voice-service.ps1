param(
    [string]$RuntimeRoot = "",
    [string]$ModelRoot = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DefaultLocalModelsRoot = $env:LOCAL_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($DefaultLocalModelsRoot)) {
    $DefaultLocalModelsRoot = Join-Path ("D:\" + [char]0x672C + [char]0x5730 + [char]0x5927 + [char]0x6A21 + [char]0x578B) "models"
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

function Test-VoiceReady {
    try {
        $Health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8790/health" `
            -Method Get `
            -TimeoutSec 3
        return [bool]$Health.ok -and [bool]$Health.ready
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Voice runtime is not installed. Run setup-voice-runtime.ps1 first."
}
$ExistingProcessId = Get-ListeningProcessId -Port 8790
if ($ExistingProcessId) {
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-VoiceReady) {
            Write-Host "Voice service is ready at http://127.0.0.1:8790"
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Voice service is listening but did not become ready within 30 seconds."
}

New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir, $ModelRoot | Out-Null
$AsciiModelRoot = $env:ASCII_ATRI_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($AsciiModelRoot)) {
    $AsciiModelRoot = "D:\AtriModels"
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
$env:ATRI_TTS_QUALITY_GATE_ENABLED = "true"
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
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    $ListeningProcessId = Get-ListeningProcessId -Port 8790
    if ($ListeningProcessId -and (Test-VoiceReady)) {
        $ListeningProcessId | Set-Content -LiteralPath $PidFile -Encoding ASCII
        Write-Host "Voice service is ready at http://127.0.0.1:8790"
        return
    }
    if ($Process.HasExited) {
        throw "Voice service exited during startup. Check logs\voice-service-error.log."
    }
}
throw "Voice service did not become ready within 30 seconds."
