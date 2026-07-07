Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartupDir = [Environment]::GetFolderPath("Startup")
$ProgramsDir = [Environment]::GetFolderPath("Programs")
$StartMenuDir = Join-Path $ProgramsDir "Atri QQ Bot"
$ShortcutName = [string]::Concat([char]0x4E9A, [char]0x6258, [char]0x8389, [char]0x684C, [char]0x5BA0, ".lnk")
$DesktopShortcut = Join-Path $DesktopDir $ShortcutName
$StartupShortcut = Join-Path $StartupDir $ShortcutName
$StartMenuShortcut = Join-Path $StartMenuDir $ShortcutName

foreach ($shortcut in @($DesktopShortcut, $StartupShortcut, $StartMenuShortcut)) {
    if (Test-Path $shortcut) {
        Remove-Item -LiteralPath $shortcut -Force
        Write-Host ("Removed shortcut: " + $shortcut)
    }
}

if ((Test-Path $StartMenuDir) -and -not (Get-ChildItem -LiteralPath $StartMenuDir -Force -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $StartMenuDir -Force
}
