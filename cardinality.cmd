@echo off
REM Double-clickable cardinality check: says what each breakdown dimension
REM would cost in the pack's three aggregate files, and what it is worth --
REM distinct values, coverage, and how concentrated the top value is.
REM Reads only; writes nothing but the optional -Csv.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cardinality.ps1" %*
echo.
pause
