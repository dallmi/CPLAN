@echo off
REM Double-clickable tracking-ID check: reads a list of tracking IDs - an .xlsx
REM with a "Tracking ID" column, or one ID per line in a text file - and says
REM which of them the source activity CSVs actually contain, naming a near-miss
REM for each one it cannot find. Pass the list with -Ids. The result is written
REM as a workbook under pipeline\output\reports unless -Out says otherwise.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0trackids.ps1" %*
echo.
pause
