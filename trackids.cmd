@echo off
REM Double-clickable tracking-ID check: reads a text file of tracking IDs and
REM says which of them the source activity CSVs actually contain, naming a
REM near-miss for each one it cannot find. Pass the list with -Ids.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0trackids.ps1" %*
echo.
pause
