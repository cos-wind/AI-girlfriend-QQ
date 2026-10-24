# Read the same saved endpoint as the desktop app; never start a speech runtime.
function Get-ConfiguredVoicePort {
    param([Parameter(Mandatory = $true)][string]$ProjectDir)

    $ConfigPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $ConfigPython)) {
        throw "Project Python is missing. Install the project environment first."
    }
    $PortOutput = & $ConfigPython -B -c "import sys; sys.path.insert(0, sys.argv[1]); from atri_shared.voice_endpoint import local_voice_port; print(local_voice_port())" (Join-Path $ProjectDir "src")
    if ($LASTEXITCODE -ne 0 -or "$PortOutput" -notmatch '^\d+$') {
        throw "Cannot read the saved voice service port."
    }
    $ConfiguredPort = [int]$PortOutput
    if ($ConfiguredPort -lt 1 -or $ConfiguredPort -gt 65535) {
        throw "Voice service port must be between 1 and 65535."
    }
    return $ConfiguredPort
}
