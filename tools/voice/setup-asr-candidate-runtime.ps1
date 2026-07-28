param(
    [string]$RuntimeRoot = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VoiceRuntime = Join-Path $ProjectDir "data\runtime\voice-runtime\.venv"
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $ProjectDir "data\runtime\asr-candidate-runtime"
}
$VenvDir = Join-Path $RuntimeRoot ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$BasePython = Join-Path $VoiceRuntime "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $BasePython)) {
    throw "Install the stable voice runtime first."
}
if (-not (Test-Path -LiteralPath $Python)) {
    & $BasePython -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create ASR candidate runtime." }
}

$BaseSite = & $BasePython -c "import site; print(site.getsitepackages()[-1])"
$CandidateSite = & $Python -c "import site; print(site.getsitepackages()[-1])"
Remove-Item -LiteralPath (Join-Path $VenvDir "atri-asr-base.pth") -Force -ErrorAction SilentlyContinue
@(
    $BaseSite
    (Join-Path $ProjectDir "src")
) | Set-Content -LiteralPath (Join-Path $CandidateSite "atri-asr-base.pth") -Encoding ASCII

$env:PYTHONUTF8 = "1"
$env:PIP_PROGRESS_BAR = "off"
$env:PIP_CACHE_DIR = Join-Path $RuntimeRoot "pip-cache"
& $Python -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Failed to update pip." }
& $Python -m pip install "funasr==1.3.24" "faster-whisper==1.2.1"
if ($LASTEXITCODE -ne 0) { throw "Failed to install ASR candidate dependencies." }
& $Python -c "import torch, funasr, faster_whisper; assert torch.cuda.is_available(); print('torch', torch.__version__); print('funasr', funasr.__version__); print('faster-whisper', faster_whisper.__version__)"
if ($LASTEXITCODE -ne 0) { throw "ASR candidate runtime validation failed." }

New-Item -ItemType File -Force -Path (Join-Path $RuntimeRoot ".dependencies-ready") | Out-Null
Write-Host "ASR candidate runtime is ready: $Python"
