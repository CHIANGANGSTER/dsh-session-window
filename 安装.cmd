@echo off
rem ===========================================================================
rem  ONE-CLICK INSTALL of the "Open in new window" feature.
rem
rem  Does everything: closes DSH, swaps the shell archive, installs the client
rem  plugin, restarts DSH. No other manual step is needed.
rem
rem  Undo with REVERT-ONECLICK.cmd.
rem ===========================================================================
setlocal
title DSH session-window - one-click install
cd /d "%~dp0"

set "PS1=%~dp0work\r2\build\r2-oneclick-install.ps1"
if not exist "%PS1%" (
  echo [FAIL] missing %PS1%
  pause
  exit /b 3
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo Done. Right-click a Session to see the new entry.
) else (
  echo Exit code %RC%. Nothing was left half-done; run REVERT-ONECLICK.cmd to undo.
)
echo.
pause
exit /b %RC%

