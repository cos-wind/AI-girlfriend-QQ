[CmdletBinding()]
param(
    [ValidateSet("core")]
    [string]$Mode = "core"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Launcher = Join-Path $ProjectRoot "tools\launch\qq_legacy\hidden_launcher.py"
$PythonCandidates = @(
    (Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"),
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe")
)

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
    throw "ATRI launcher was not found: $Launcher"
}

$Python = $PythonCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1

if ([string]::IsNullOrWhiteSpace($Python)) {
    throw "Project Python runtime was not found. Run tools\launch\atri\start-atri.bat once to create .venv and install dependencies."
}

Start-Process `
    -FilePath $Python `
    -ArgumentList @($Launcher, $Mode) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden | Out-Null

Write-Output "ATRI core launcher requested: $Mode"
