param(
    [string]$SingingRoot = $env:ATRI_SINGING_ROOT,
    [string]$AsciiModelRoot = $env:ASCII_ATRI_MODELS_ROOT,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($SingingRoot)) {
    $SingingRoot = $env:ATRI_MODEL_ROOT
    if ([string]::IsNullOrWhiteSpace($SingingRoot)) {
        $SingingRoot = "D:\AtriModels\voice\singing"
    }
}
$SeedRoot = Join-Path $SingingRoot "seed-vc"
$SeedVenv = Join-Path $SingingRoot "seed-vc-runtime"
$SeparatorVenv = Join-Path $SingingRoot "separator-runtime"
$ModelDir = Join-Path $SingingRoot "separator-models"
$WheelDir = Join-Path $SingingRoot "wheels"
$ManifestPath = Join-Path $ProjectDir "data\voice\singing-pipeline.json"
$SeparatorModelName = "UVR-MDX-NET-Inst_HQ_4.onnx"
$SeparatorModelPath = Join-Path $ModelDir $SeparatorModelName
$SeparatorModelBytes = 59074342

New-Item -ItemType Directory -Force -Path $SingingRoot, $ModelDir, $WheelDir | Out-Null

function Invoke-Checked {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')"
    }
}

function Download-Resumable {
    param(
        [string]$Url,
        [string]$Output
    )
    Invoke-Checked "curl.exe" @(
        "-L",
        "--fail",
        "--retry", "20",
        "--retry-all-errors",
        "--connect-timeout", "30",
        "--continue-at", "-",
        "-o", $Output,
        $Url
    )
}

function Ensure-Python310 {
    $PreviousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $Existing = & py -3.10 -c "import sys; print(sys.executable)" 2>$null
    $PythonExitCode = $LASTEXITCODE
    $ErrorActionPreference = $PreviousErrorAction
    if ($PythonExitCode -eq 0 -and $Existing) {
        return $Existing.Trim()
    }
    $Uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $Uv) {
        throw "Seed-VC requires Python 3.10; neither py -3.10 nor uv was found."
    }
    Invoke-Checked "uv" @("python", "install", "3.10")
    $Installed = & uv python find 3.10
    if ($LASTEXITCODE -ne 0 -or -not $Installed) {
        throw "Unable to locate the Python 3.10 installed by uv."
    }
    return $Installed.Trim()
}

if (-not $SkipInstall) {
    $Python310 = Ensure-Python310
    if (-not (Test-Path -LiteralPath (Join-Path $SeedRoot "inference.py"))) {
        $PreviousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        & git clone --depth 1 https://github.com/Plachtaa/seed-vc.git $SeedRoot
        $GitExitCode = $LASTEXITCODE
        $ErrorActionPreference = $PreviousErrorAction
        if ($GitExitCode -ne 0) {
            $ArchivePath = Join-Path $SingingRoot "seed-vc-main.zip"
            $ExtractRoot = Join-Path $SingingRoot "seed-vc-download"
            if (-not (Test-Path -LiteralPath $ArchivePath)) {
                & curl.exe `
                    -L `
                    --fail `
                    --retry 5 `
                    --retry-all-errors `
                    --connect-timeout 30 `
                    -o $ArchivePath `
                    "https://codeload.github.com/Plachtaa/seed-vc/zip/refs/heads/main"
                if ($LASTEXITCODE -ne 0) {
                    throw "Seed-VC source archive download failed."
                }
            }
            Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractRoot -Force
            $ExtractedSource = Join-Path $ExtractRoot "seed-vc-main"
            if (-not (Test-Path -LiteralPath (Join-Path $ExtractedSource "inference.py"))) {
                throw "Seed-VC source archive is invalid."
            }
            Move-Item -LiteralPath $ExtractedSource -Destination $SeedRoot
        }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $SeedVenv "Scripts\python.exe"))) {
        & $Python310 -m venv $SeedVenv
    }
    $SeedPython = Join-Path $SeedVenv "Scripts\python.exe"
    Invoke-Checked $SeedPython @("-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools")
    $TorchWheel = Join-Path $WheelDir "torch-2.4.1+cu121-cp310-cp310-win_amd64.whl"
    $TorchvisionWheel = Join-Path $WheelDir "torchvision-0.19.1+cu121-cp310-cp310-win_amd64.whl"
    $TorchaudioWheel = Join-Path $WheelDir "torchaudio-2.4.1+cu121-cp310-cp310-win_amd64.whl"
    if (-not (Test-Path -LiteralPath $TorchWheel)) {
        Download-Resumable `
            "https://download.pytorch.org/whl/cu121/torch-2.4.1%2Bcu121-cp310-cp310-win_amd64.whl" `
            $TorchWheel
    }
    if (-not (Test-Path -LiteralPath $TorchvisionWheel)) {
        Download-Resumable `
            "https://download.pytorch.org/whl/cu121/torchvision-0.19.1%2Bcu121-cp310-cp310-win_amd64.whl" `
            $TorchvisionWheel
    }
    if (-not (Test-Path -LiteralPath $TorchaudioWheel)) {
        Download-Resumable `
            "https://download.pytorch.org/whl/cu121/torchaudio-2.4.1%2Bcu121-cp310-cp310-win_amd64.whl" `
            $TorchaudioWheel
    }
    Invoke-Checked $SeedPython @(
        "-m", "pip", "install",
        $TorchWheel, $TorchvisionWheel, $TorchaudioWheel
    )
    Invoke-Checked $SeedPython @(
        "-m", "pip", "install",
        "accelerate",
        "scipy==1.13.1",
        "librosa==0.10.2",
        "huggingface-hub>=0.28.1,<1",
        "munch==4.0.0",
        "einops==0.8.0",
        "descript-audio-codec==1.0.0",
        "transformers==4.46.3",
        "soundfile==0.12.1",
        "numpy==1.26.4",
        "hydra-core==1.3.2",
        "pyyaml",
        "python-dotenv",
        "imageio-ffmpeg"
    )

    if (-not (Test-Path -LiteralPath (Join-Path $SeparatorVenv "Scripts\python.exe"))) {
        & $Python310 -m venv $SeparatorVenv
    }
    $SeparatorPython = Join-Path $SeparatorVenv "Scripts\python.exe"
    Invoke-Checked $SeparatorPython @("-m", "pip", "install", "--upgrade", "pip", "wheel")
    Invoke-Checked $SeparatorPython @(
        "-m", "pip", "install", "audio-separator[gpu]", "imageio-ffmpeg"
    )
    Invoke-Checked $SeparatorPython @(
        "-m", "pip", "install",
        $TorchWheel, $TorchvisionWheel, $TorchaudioWheel
    )
    if (
        -not (Test-Path -LiteralPath $SeparatorModelPath) -or
        (Get-Item -LiteralPath $SeparatorModelPath).Length -ne $SeparatorModelBytes
    ) {
        Download-Resumable `
            "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/$SeparatorModelName" `
            $SeparatorModelPath
    }
} else {
    $SeedPython = Join-Path $SeedVenv "Scripts\python.exe"
    $SeparatorPython = Join-Path $SeparatorVenv "Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $SeedPython)) {
    throw "Seed-VC runtime does not exist: $SeedPython"
}
if (-not (Test-Path -LiteralPath $SeparatorPython)) {
    throw "Stem-separation runtime does not exist: $SeparatorPython"
}
if (
    -not (Test-Path -LiteralPath $SeparatorModelPath) -or
    (Get-Item -LiteralPath $SeparatorModelPath).Length -ne $SeparatorModelBytes
) {
    throw "Stem-separation model is incomplete: $SeparatorModelPath"
}

Invoke-Checked $SeedPython @(
    "-c",
    "import torch, librosa, transformers, soundfile; assert torch.cuda.is_available(), 'Seed-VC CUDA is unavailable'"
)
Invoke-Checked $SeparatorPython @(
    "-c",
    "import torch, onnxruntime, audio_separator; assert torch.cuda.is_available(), 'separator CUDA is unavailable'; assert 'CUDAExecutionProvider' in onnxruntime.get_available_providers(), 'ONNX CUDA provider is unavailable'"
)

$Manifest = [ordered]@{
    id = "seed-vc-atri-44k"
    model_root = $SingingRoot
    working_directory = $SeedRoot
    timeout_seconds = 1200
    separator = @(
        $SeparatorPython,
        (Join-Path $ProjectDir "tools\voice\separate_singing_stems.py"),
        "--source", "{source}",
        "--vocal-output", "{vocal}",
        "--instrumental-output", "{instrumental}",
        "--model-dir", $ModelDir,
        "--model", $SeparatorModelName
    )
    converter = @(
        $SeedPython,
        (Join-Path $ProjectDir "tools\voice\seed_vc_singing_adapter.py"),
        "--seed-vc-root", $SeedRoot,
        "--source", "{vocal}",
        "--reference", "{reference}",
        "--output", "{converted}",
        "--pitch-shift", "{pitch_shift}",
        "--diffusion-steps", "35"
    )
    mixer = @(
        $SeedPython,
        (Join-Path $ProjectDir "tools\voice\mix_singing_audio.py"),
        "--vocal", "{converted}",
        "--instrumental", "{instrumental}",
        "--output", "{output}"
    )
}
$Manifest | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath $ManifestPath -Encoding UTF8

Write-Host "Seed-VC singing pipeline configured: $ManifestPath"
Write-Host "Models and isolated runtimes: $SingingRoot"
