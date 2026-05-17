# Remove the cc-assistant Scheduled Task registered by install-task-scheduler.ps1.
#
# Usage (from elevated PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall-task-scheduler.ps1

[CmdletBinding()]
param(
    [string]$TaskName = "cc-assistant"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No task named '$TaskName' is registered. Nothing to do." -ForegroundColor Yellow
    exit 0
}

# Stop the task if it's currently running, then unregister.
$info = $task | Get-ScheduledTaskInfo
if ($info.LastTaskResult -eq 267009) {  # 267009 == "Task is currently running"
    Stop-ScheduledTask -TaskName $TaskName
    Write-Host "Stopped running task '$TaskName'."
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false

Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "If a daemon process is still alive, kill it manually:  taskkill /F /IM pythonw.exe"
