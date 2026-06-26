$ErrorActionPreference = 'Stop'

$ProjectDir = Split-Path -Parent $PSScriptRoot
$HiddenWatcher = Join-Path $PSScriptRoot 'hidden_watcher.py'
$TaskName = 'AtriQQWatcher'

# 查找 pythonw.exe
$PythonwCandidates = @(
    "$env:LocalAppData\Programs\Python\Python311\pythonw.exe",
    (Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'),
    "C:\Windows\pyw.exe"
)
$PythonwExe = $PythonwCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $PythonwExe) {
    throw 'pythonw.exe not found. Install Python or create the project venv first.'
}

$Quote = [char]34

# 创建任务动作
$action = New-ScheduledTaskAction -Execute $PythonwExe -Argument "$Quote$HiddenWatcher$Quote"

# 创建触发器：登录时触发，延迟 30 秒
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT30S'

# 设置
$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 0)

# 注册任务
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force

# 删除旧的注册表启动项
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Atri QQ Watcher' -ErrorAction SilentlyContinue
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Atri QQ Launcher' -ErrorAction SilentlyContinue

Write-Host "Scheduled task '$TaskName' created."
Write-Host "  - Action: $PythonwExe $HiddenWatcher"
Write-Host "  - Trigger: At logon, 30s delay"
Write-Host "  - Run level: Highest"
Write-Host "Old registry Run key removed."
