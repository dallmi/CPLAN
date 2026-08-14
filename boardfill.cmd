@echo off
REM Double-clickable board fill check: says which board panels have a figure to
REM draw against the pack that was last built, and which of the four causes is
REM behind each one that does not. Reads only; writes nothing but the optional -Csv.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0boardfill.ps1" %*
echo.
pause
