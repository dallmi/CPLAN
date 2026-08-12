@echo off
REM Double-clickable launcher for the CPLAN campaign activity dashboard.
REM Runs dashboard.ps1 with the execution policy bypassed, so it works on a
REM locked-down corp machine where double-clicking a .ps1 only opens the editor.
REM Pass-through args, e.g.:  dashboard.cmd -NoOpen   /   dashboard.cmd -Check
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard.ps1" %*
echo.
pause
