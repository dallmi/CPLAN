@echo off
REM Double-clickable launcher for the CPLAN calendar report.
REM Runs report.ps1 with the execution policy bypassed, so it works on a
REM locked-down corp machine where double-clicking a .ps1 only opens the editor.
REM Pass-through args, e.g.:  report.cmd -NoOpen   /   report.cmd -InputDir C:\tmp\csv
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0report.ps1" %*
echo.
pause
