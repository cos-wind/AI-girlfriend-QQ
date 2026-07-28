param(
    [string]$RuntimeRoot = "",
    [string]$ModelRoot = "",
    [string]$PythonExe = "python",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu124"
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DefaultLocalModelsRoot = $env:LOCAL_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($DefaultLocalModelsRoot)) {
    $DefaultLocalModelsRoot = Join-Path ("D:\" + [char]0x672C + [char]0x5730 + [char]0x5927 + [char]0x6A21 + [char]0x578B) "models"
}
$DefaultProjectModelRoot = Join-Path $DefaultLocalModelsRoot "AI_ATRI"
$AsciiModelRoot = $env:ASCII_ATRI_MODELS_ROOT
if ([string]::IsNullOrWhiteSpace($AsciiModelRoot)) {
    $AsciiModelRoot = "D:\AtriModels"
}
if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = $DefaultProjectModelRoot
}
New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
if (-not (Test-Path -LiteralPath $AsciiModelRoot)) {
    New-Item -ItemType Junction -Path $AsciiModelRoot -Target $ModelRoot | Out-Null
}
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $ProjectDir "data\runtime\voice-runtime"
}
$ModelAccessRoot = if (Test-Path -LiteralPath $AsciiModelRoot) { $AsciiModelRoot } else { $ModelRoot }
$env:PYTHONUTF8 = "1"
$env:PIP_PROGRESS_BAR = "off"
$env:PIP_CACHE_DIR = Join-Path $RuntimeRoot "pip-cache"
$env:MODELSCOPE_CACHE = Join-Path $ModelAccessRoot "voice\modelscope"
$env:HF_HOME = Join-Path $ModelAccessRoot "voice\huggingface"
$VenvDir = Join-Path $RuntimeRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $env:MODELSCOPE_CACHE, $env:HF_HOME | Out-Null

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create voice virtual environment." }
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }
& $VenvPython -m pip install torch torchaudio --index-url $TorchIndexUrl
if ($LASTEXITCODE -ne 0) { throw "Failed to install CUDA PyTorch." }
& $VenvPython -m pip install funasr modelscope huggingface_hub
if ($LASTEXITCODE -ne 0) { throw "Failed to install FunASR dependencies." }
& $VenvPython -m pip install --editable $ProjectDir
if ($LASTEXITCODE -ne 0) { throw "Failed to install the ATRI voice service." }
& $VenvPython -c "import torch, funasr, atri_voice_service; assert torch.cuda.is_available(), 'CUDA is not available to PyTorch'"
if ($LASTEXITCODE -ne 0) { throw "Voice runtime validation failed." }

Write-Host "Voice runtime is ready: $VenvPython"
Write-Host "Voice code: $(Join-Path $ProjectDir 'src\atri_voice_service')"
Write-Host "Voice models: $(Join-Path $ModelRoot 'voice')"
