@echo off
REM Double-clickable pack-link check: says which columns of the pack export the
REM pipeline cannot see, and which activity column actually links to the pack
REM list. Reads only; writes nothing but the optional -Csv.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packlink.ps1" %*
echo.
pause
