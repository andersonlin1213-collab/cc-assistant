@echo off
REM Wrapper invoked by the cc-assistant Scheduled Task.
REM Captures stdout + stderr to logs\daemon.out for diagnosis when python
REM exits unexpectedly under Task Scheduler.

set REPO_ROOT=%~dp0..
cd /d "%REPO_ROOT%"

echo [%DATE% %TIME%] starting daemon >> logs\daemon.out
echo [diag] where claude: >> logs\daemon.out
where claude >> logs\daemon.out 2>&1
python -m src.cli run >> logs\daemon.out 2>&1
echo [%DATE% %TIME%] daemon exited with code %ERRORLEVEL% >> logs\daemon.out
