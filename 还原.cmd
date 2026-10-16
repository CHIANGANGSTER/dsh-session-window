@echo off
rem ===========================================================================
rem  ONE-CLICK REVERT: put DSH back the way it was before the patch.
rem
rem  Closes DSH, restores resources\app.asar from the installation transaction's
rem  own backup, restores the two profile config files, removes the plugin
rem  directory, then restarts DSH.
rem ===========================================================================
setlocal
title DSH session-window - one-click revert
cd /d "%~dp0"

set "PS1=%~dp0work\r2\build\r2-oneclick-revert.ps1"
if not exist "%PS1%" (
  echo [FAIL] missing %PS1%
  pause
  exit /b 3
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo Reverted. DSH is back to its previous state.
) else (
  echo Exit code %RC%. See the message above; nothing else was changed.
)
echo.
pause
exit /b %RC%

