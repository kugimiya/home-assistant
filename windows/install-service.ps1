#Requires -Version 5.1
param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "JarvisWin"
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task $TaskName"
    } else {
        Write-Host "Task $TaskName is not registered"
    }
    exit 0
}

if (-not (Test-Path $PythonExe)) {
    throw "Missing venv Python: $PythonExe. Run .\install.ps1 first."
}

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m jarvis_win" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Registered and started scheduled task $TaskName (boot + restart on failure, min 1 min between restarts)"
Write-Host "  status: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "  remove: .\install-service.ps1 -Uninstall"
