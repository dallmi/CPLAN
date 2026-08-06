@echo off
REM Double-clickable launcher for the CPLAN agent pack.
REM Runs agentpack.ps1 with the execution policy bypassed, so it works on a
REM locked-down corp machine where double-clicking a .ps1 only opens the editor.
REM Pass-through args, e.g.:  agentpack.cmd -NoOpen  /  agentpack.cmd -Year 2026
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agentpack.ps1" %*
echo.
pause
