@echo off
REM Double-clickable launcher for the CPLAN portal (port 8781).
REM Bypasses the execution policy so it double-clicks on a locked-down corp machine.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0portal.ps1" %*
echo.
pause
