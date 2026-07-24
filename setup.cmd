@echo off
REM Double-clickable one-time CPLAN setup: backend, auth secret, roles + admin,
REM portal schema. Idempotent - safe to re-run. Bypasses the execution policy so
REM it double-clicks on a locked-down corp machine.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
