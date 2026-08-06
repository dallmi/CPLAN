@echo off
REM Double-clickable time-zone check: lists every time zone the export carries
REM and names any value too long for the database column. An over-long value
REM ends the daily refresh before it writes a single row, so run this after the
REM export changes and before refresh.cmd.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0timezones.ps1" %*
echo.
pause
