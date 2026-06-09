$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$WatcherVbs = Join-Path $PSScriptRoot "watch-qq.vbs"
$StartWithQQVbs = Join-Path $PSScriptRoot "start-with-qq.vbs"
$QQExe = "C:\Program Files\Tencent\QQNT\QQ.exe"
$Desktop = [Environment]::GetFolderPath("Desktop")
$CommonDesktop = [Environment]::GetFolderPath("CommonDesktopDirectory")
$UserStartQQ = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\QQ\QQ.lnk"
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupShortcut = Join-Path $StartupDir "Atri QQ Auto Launcher.lnk"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RunName = "Atri QQ Watcher"
$WindowsDir = $env:WINDIR
if (-not $WindowsDir) {
    $WindowsDir = $env:SystemRoot
}
if (-not $WindowsDir) {
    $WindowsDir = "C:\Windows"
}

$Shell = New-Object -ComObject WScript.Shell
$ConfiguredShortcuts = 0
$SkippedShortcuts = 0

foreach ($shortcutPath in @(
    (Join-Path $Desktop "QQ.lnk"),
    (Join-Path $CommonDesktop "QQ.lnk"),
    $UserStartQQ
)) {
    if (-not (Test-Path -LiteralPath $shortcutPath)) {
        continue
    }

    $shortcut = $Shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Join-Path $WindowsDir "System32\wscript.exe")
    $shortcut.Arguments = "`"$StartWithQQVbs`""
    $shortcut.WorkingDirectory = $ProjectDir
    $shortcut.WindowStyle = 1
    $shortcut.IconLocation = "$QQExe,0"
    $shortcut.Description = "启动 QQ，同时在后台启动亚托莉聊天机器人"
    try {
        $shortcut.Save()
        $ConfiguredShortcuts += 1
    } catch {
        $SkippedShortcuts += 1
        Write-Host "Skipped protected QQ shortcut: $shortcutPath"
    }
}

$existingAtri = Get-ChildItem -LiteralPath $Desktop -Filter "*.lnk" -ErrorAction SilentlyContinue | Where-Object {
    $lnk = $Shell.CreateShortcut($_.FullName)
    $_.Name -like "*亚托莉*" -or $lnk.TargetPath -like "$ProjectDir\*.bat"
}
foreach ($shortcut in $existingAtri) {
    Remove-Item -LiteralPath $shortcut.FullName -Force
}

if (Test-Path -LiteralPath $StartupShortcut) {
    Remove-Item -LiteralPath $StartupShortcut -Force
}

New-Item -Path $RunKey -Force | Out-Null
Set-ItemProperty -Path $RunKey -Name $RunName -Value "wscript.exe `"$WatcherVbs`""

Start-Process -FilePath "wscript.exe" -ArgumentList "`"$WatcherVbs`"" -WindowStyle Hidden | Out-Null

Write-Host "Installed QQ process watcher."
Write-Host "Configured QQ shortcuts: $ConfiguredShortcuts. Protected shortcuts skipped: $SkippedShortcuts."
Write-Host "No extra desktop shortcut was created."
