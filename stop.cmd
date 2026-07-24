@echo off
REM Double-clickable clean shutdown of the embedded CPLAN database (pg_ctl -m fast).
REM Run after closing the studio/portal windows so the next start needs no recovery.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
echo.
pause
