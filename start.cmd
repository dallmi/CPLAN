@echo off
REM Double-clickable launcher: starts the CPLAN studio (8780) and, if
REM CPLAN_AUTH_SECRET is set, the portal (8781), each in its own window.
REM Pass-through args, e.g.:  start.cmd -StudioOnly
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
echo.
pause
