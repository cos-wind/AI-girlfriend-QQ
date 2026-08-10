param(
    [string]$ModelRoot = "",
    [int]$Port = 9880
)

$ErrorActionPreference = "Stop"
$StartupMutex = New-Object System.Threading.Mutex($false, "Global\AtriGptSovitsService")
if (-not $StartupMutex.WaitOne(0)) {
    Write-Host "GPT-SoVITS startup is already in progress."
    return
}
try {
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeRoot = Join-Path $ProjectDir "data\runtime\gpt-sovits"
$SourceRoot = Join-Path $RuntimeRoot "source"
$Python = Join-Path $RuntimeRoot ".venv\Scripts\python.exe"
$Pythonw = Join-Path $RuntimeRoot ".venv\Scripts\pythonw.exe"
$DefaultLocalModelsRoot = $env:LOCAL_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($DefaultLocalModelsRoot)) {
    $DefaultLocalModelsRoot = Join-Path ("D:\" + [char]0x672C + [char]0x5730 + [char]0x5927 + [char]0x6A21 + [char]0x578B) "models"
}
$DefaultProjectModelRoot = Join-Path $DefaultLocalModelsRoot "AI_ATRI"
$AsciiModelRoot = $env:ASCII_ATRI_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($AsciiModelRoot)) {
    $AsciiModelRoot = "D:\AtriModels"
}

if ([string]::IsNullOrWhiteSpace($ModelRoot)) { $ModelRoot = $DefaultProjectModelRoot }
if (-not (Test-Path -LiteralPath $AsciiModelRoot)) {
    New-Item -ItemType Junction -Path $AsciiModelRoot -Target $ModelRoot | Out-Null
}
$ModelAccessRoot = if (Test-Path -LiteralPath $AsciiModelRoot) { $AsciiModelRoot } else { $ModelRoot }
$VoiceModels = Join-Path $ModelAccessRoot "voice"
$BaseModels = Join-Path $VoiceModels "base\gpt-sovits\pretrained_models"
$Candidate = Join-Path $VoiceModels "candidates\2dipw-atri-gpt-sovits"
$ConfigPath = Join-Path $RuntimeRoot "atri-tts-infer.yaml"
$PidFile = Join-Path $ProjectDir "data\runtime\gpt-sovits.pid"
$LogDir = Join-Path $ProjectDir "logs"

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "GPT-SoVITS is already listening on port $Port."
    return
}
foreach ($Required in @(
    $Python,
    (Join-Path $SourceRoot "api_v2.py"),
    (Join-Path $RuntimeRoot ".dependencies-ready"),
    (Join-Path $BaseModels "chinese-roberta-wwm-ext-large\pytorch_model.bin"),
    (Join-Path $BaseModels "chinese-hubert-base\pytorch_model.bin"),
    (Join-Path $Candidate "atri-e10.ckpt"),
    (Join-Path $Candidate "atri_e25_s5250.pth")
)) {
    if (-not (Test-Path -LiteralPath $Required)) {
        throw "GPT-SoVITS runtime is incomplete: $Required"
    }
}

$SourcePretrained = Join-Path $SourceRoot "GPT_SoVITS\pretrained_models"
New-Item -ItemType Directory -Force -Path $SourcePretrained, $LogDir | Out-Null
foreach ($Directory in @("chinese-roberta-wwm-ext-large", "chinese-hubert-base", "fast_langdetect", "sv")) {
    $Link = Join-Path $SourcePretrained $Directory
    $Target = Join-Path $BaseModels $Directory
    if (-not (Test-Path -LiteralPath $Link)) {
        New-Item -ItemType Junction -Path $Link -Target $Target | Out-Null
    }
}
$G2PWLink = Join-Path $SourceRoot "GPT_SoVITS\text\G2PWModel"
if (-not (Test-Path -LiteralPath $G2PWLink)) {
    New-Item -ItemType Junction -Path $G2PWLink -Target (Join-Path $VoiceModels "base\gpt-sovits\G2PWModel") | Out-Null
}

$Config = @"
custom:
  bert_base_path: D:/AtriModels/voice/base/gpt-sovits/pretrained_models/chinese-roberta-wwm-ext-large
  cnhuhbert_base_path: D:/AtriModels/voice/base/gpt-sovits/pretrained_models/chinese-hubert-base
  device: cuda
  is_half: true
  t2s_weights_path: D:/AtriModels/voice/candidates/2dipw-atri-gpt-sovits/atri-e10.ckpt
  version: v1
  vits_weights_path: D:/AtriModels/voice/candidates/2dipw-atri-gpt-sovits/atri_e25_s5250.pth
"@
Set-Content -LiteralPath $ConfigPath -Value $Config -Encoding UTF8

$env:PYTHONUTF8 = "1"
$env:NLTK_DATA = Join-Path $RuntimeRoot ".venv\nltk_data"
$env:HF_HOME = Join-Path $VoiceModels "huggingface"
$env:PYTHONPATH = (Join-Path $ProjectDir "tools\voice\compat")
$env:PATH = $SourceRoot + ";" + $env:PATH
$Executable = if (Test-Path -LiteralPath $Pythonw) { $Pythonw } else { $Python }
$Process = Start-Process `
    -FilePath $Executable `
    -ArgumentList "api_v2.py", "-a", "127.0.0.1", "-p", "$Port", "-c", ('"' + $ConfigPath + '"') `
    -WorkingDirectory $SourceRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "gpt-sovits.log") `
    -RedirectStandardError (Join-Path $LogDir "gpt-sovits-error.log") `
    -PassThru

for ($i = 0; $i -lt 240; $i++) {
    Start-Sleep -Milliseconds 500
    $Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Listener) {
        $Listener.OwningProcess | Set-Content -LiteralPath $PidFile -Encoding ASCII
        Write-Host "GPT-SoVITS is ready at http://127.0.0.1:$Port"
        return
    }
    if ($Process.HasExited) {
        throw "GPT-SoVITS exited during startup. Check logs\gpt-sovits-error.log."
    }
}
throw "GPT-SoVITS did not become ready within 120 seconds."
} finally {
    $StartupMutex.ReleaseMutex()
    $StartupMutex.Dispose()
}
