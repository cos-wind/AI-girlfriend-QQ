$ErrorActionPreference = 'Stop'

$ProjectDir = Split-Path -Parent $PSScriptRoot
$WatcherVbs = Join-Path $PSScriptRoot 'watch-qq.vbs'
$StartWithQQVbs = Join-Path $PSScriptRoot 'start-with-qq.vbs'
$HiddenLauncher = Join-Path $PSScriptRoot 'hidden_launcher.py'
$HiddenWatcher = Join-Path $PSScriptRoot 'hidden_watcher.py'
$QQExe = 'C:\Program Files\Tencent\QQNT\QQ.exe'
$StartupDir = [Environment]::GetFolderPath('Startup')
$StartupShortcut = Join-Path $StartupDir 'Atri QQ Auto Launcher.lnk'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$RunName = 'Atri QQ Watcher'
$PythonwCandidates = @(
    "$env:LocalAppData\Programs\Python\Python311\pythonw.exe",
    (Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'),
    "C:\Windows\pyw.exe"
)
$PythonwExe = $PythonwCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $PythonwExe) {
    throw 'pythonw.exe not found. Install Python or create the project venv first.'
}

$Shell = New-Object -ComObject WScript.Shell
$Quote = [char]34
$WatcherVbs = Join-Path $PSScriptRoot 'launcher-delayed.vbs'
$WatcherRunValue = "wscript.exe " + $Quote + $WatcherVbs + $Quote

New-Item -Path $RunKey -Force | Out-Null
Set-ItemProperty -Path $RunKey -Name $RunName -Value $WatcherRunValue
if (Test-Path -LiteralPath $StartupShortcut) {
    Remove-Item -LiteralPath $StartupShortcut -Force
}

Start-Process -FilePath "wscript.exe" -ArgumentList "$Quote$WatcherVbs$Quote" -WindowStyle Hidden | Out-Null

Write-Host 'Installed QQ process watcher.'
Write-Host 'QQ shortcuts are left untouched; the watcher follows normal QQ startup.'
Write-Host 'Startup folder shortcut removed; HKCU Run is used instead.'
