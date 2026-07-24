@echo off
REM Double-clickable preflight check: proves every critical CPLAN file is the
REM current version (prints download URLs for anything stale), purges stale
REM Python bytecode caches, and verifies the interpreter loads the new code.
REM Run this FIRST after hand-copying files, before fix-db/setup/start.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check.ps1" %*
echo.
pause
