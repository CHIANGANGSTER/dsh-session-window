@echo off
rem ===========================================================================
rem  R2 smoke rollback: restores the smoke copy from its own transaction.
rem ===========================================================================
setlocal
title DSH session-window patch - smoke rollback
cd /d "%~dp0"

set "SMOKE=E:\dsh-smoke\DeepSeek Harness"

echo ============================================================
echo   DSH Desktop : roll back the SMOKE copy
echo ============================================================
echo   target: %SMOKE%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0rollback.ps1" -AppDir "%SMOKE%" %*
set "RC=%ERRORLEVEL%"

echo.
echo Exit code %RC%. See the R2 exit-code table in R2-RUNBOOK.md.
echo.
pause
exit /b %RC%

