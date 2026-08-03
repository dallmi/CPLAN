@echo off
REM Double-clickable launcher for the CPLAN standalone studio export.
REM Runs snapshot.ps1 with the execution policy bypassed, so it works on a
REM locked-down corp machine where double-clicking a .ps1 only opens the editor.
REM Pass-through args, e.g.:  snapshot.cmd -NoOpen   /   snapshot.cmd -Out C:\tmp\plan.html
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0snapshot.ps1" %*
echo.
pause
