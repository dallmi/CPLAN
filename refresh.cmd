@echo off
REM Double-clickable launcher for the CPLAN daily refresh.
REM Runs refresh.ps1 with the execution policy bypassed, so it works on a
REM locked-down corp machine where double-clicking a .ps1 only opens the editor.
REM Pass-through args, e.g.:  refresh.cmd -SyncOnly   /   refresh.cmd -NoStudio
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh.ps1" %*
echo.
pause
