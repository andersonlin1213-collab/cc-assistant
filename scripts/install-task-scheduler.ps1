# Register cc-assistant as a Windows Scheduled Task that starts at user logon.
#
# Usage:
#   cd <repo-root>
#   powershell -ExecutionPolicy Bypass -File scripts\install-task-scheduler.ps1
#
# Effect: a task named "cc-assistant" runs `python -m src.cli run` at logon,
# detached and hidden via Start-Process. The daemon writes its log to
# logs\agent.jsonl; no console window appears.
#
# To remove later: scripts\uninstall-task-scheduler.ps1

[CmdletBinding()]
param(
    [string]$TaskName = "cc-assistant",
    [string]$RepoRoot = "",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

# $PSScriptRoot is unreliable inside `param()` defaults on PowerShell 5.1, so
# resolve the repo root here in the body instead.
if (-not $RepoRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
}

if (-not $Python) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "python.exe not on PATH. Pass -Python <full path>, or install Python with launcher."
    }
    $Python = $cmd.Source
}

if (-not (Test-Path $RepoRoot)) {
    throw "Repo root not found: $RepoRoot"
}

# Sanity check: the repo must contain src/cli.py (the daemon entry point).
$cliEntry = Join-Path $RepoRoot "src\cli.py"
if (-not (Test-Path $cliEntry)) {
    throw "Could not find src\cli.py under '$RepoRoot'. Run from the cc-assistant repo, or pass -RepoRoot."
}

$logsDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }

# Strategy: invoke scripts\run-daemon.bat as the task body. The .bat handles
# `cd` + `python -m src.cli run` and captures stdout+stderr to
# logs\daemon.out, so any startup error (import failure, missing dep,
# permission issue) is visible there. The python process IS the task body,
# so Task Scheduler tracks its lifetime and RestartCount kicks in on crash.
$batPath = Join-Path $RepoRoot "scripts\run-daemon.bat"
if (-not (Test-Path $batPath)) {
    throw "Missing wrapper: $batPath"
}
# Task Scheduler's Execute expects an .exe. Invoke the .bat via cmd.exe.
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Task '$TaskName' already exists. Replacing." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "cc-assistant local AI task automation daemon" | Out-Null

# PS 5.1's New-ScheduledTaskSettingsSet doesn't expose battery toggles. Mutate
# the registered task's Settings COM object directly so the daemon runs even
# on battery (laptop scenarios).
$registered = Get-ScheduledTask -TaskName $TaskName
$registered.Settings.DisallowStartIfOnBatteries = $false
$registered.Settings.StopIfGoingOnBatteries     = $false
$registered | Set-ScheduledTask | Out-Null

Write-Host ""
Write-Host "Registered task '$TaskName'." -ForegroundColor Green
Write-Host "  Working dir : $RepoRoot"
Write-Host "  Python      : $Python"
Write-Host "  Daemon log  : $logsDir\agent.jsonl"
Write-Host ""
Write-Host "To start now without rebooting: Start-ScheduledTask -TaskName $TaskName"
Write-Host "To check status:                Get-ScheduledTask  -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "To remove:                      scripts\uninstall-task-scheduler.ps1"
