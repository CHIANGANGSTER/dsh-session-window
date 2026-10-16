@echo off
rem ===========================================================================
rem  R2 plugin-layer rollback: restores the two profile config files the client
rem  plugin changed, from the exact backups an active binding names.
rem
rem  Takes no arguments on purpose: it reads only the default binding file at
rem  %LOCALAPPDATA%\dsh-r2-private\ACTIVE-PLUGIN-RECOVERY.json. Until C-05/E-02
rem  records that binding this always exits 8 ("not bound"), which is expected.
rem ===========================================================================
setlocal
title DSH session-window plugin - rollback
cd /d "%~dp0"

echo ============================================================
echo   DSH Desktop : roll back the client plugin files
echo ============================================================

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0work\r2\build\rollback-plugin.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="8" (
  echo Nothing is bound yet. This is expected until the plugin is installed and
  echo a recovery binding is recorded.
) else (
  echo Exit code %RC%. See the R2 exit-code table in R2-RUNBOOK.md.
)
echo.
pause
exit /b %RC%

