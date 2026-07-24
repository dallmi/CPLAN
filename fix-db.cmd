@echo off
REM Double-clickable recovery for a wedged embedded database: clean stop, then a
REM patient start that lets crash recovery finish. Run this when a start hangs or
REM fails with "Timeout starting server" after an unclean shutdown.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix-db.ps1" %*
echo.
pause
