@echo off
REM Double-clickable clean shutdown of CPLAN: the studio/portal servers first,
REM then the embedded database (pg_ctl -m fast). Frees ports 8780/8781 and leaves
REM the database in a state the next start needs no crash recovery for.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
echo.
pause
