Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -e .

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
}

.\.venv\Scripts\python.exe -m atri_qq_bot
