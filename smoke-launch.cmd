@echo off
rem ===========================================================================
rem  Launch the UNPATCHED smoke copy in FULL ISOLATION.
rem
rem  Isolation (R2-RUNBOOK.md A-09, level I1):
rem    DSH_HOME        -> a private test home, so the Host uses its own profile,
rem                       its own session store and its own storages
rem    --user-data-dir -> a private Electron userData, so sessionData, cookies and
rem                       the single-instance lock are the copy's own
rem
rem  ELECTRON_RUN_AS_NODE must be cleared. The DSH Host itself runs "under the
rem  Electron executable in Node mode", so any shell spawned from inside DSH
rem  carries ELECTRON_RUN_AS_NODE=1. Passing that on makes the copy start as plain
rem  Node, which rejects --user-data-dir with "bad option" and exits 9 in about
rem  two seconds WITHOUT any crash log or diagnostic. From Explorer the variable is
rem  absent, but clearing it makes this launcher correct from any parent shell.
rem
rem  Nothing here touches the formal installation or the formal profile.
rem  Cancel any "restart to update" / "update now" prompt.
rem ===========================================================================
setlocal
title DSH smoke copy (UNPATCHED) - isolated

set "SMOKE=E:\dsh-smoke\DeepSeek Harness"
set "PRIV=%LOCALAPPDATA%\dsh-r2-private"
set "DSH_HOME=%PRIV%\test-profile"
set "USERDATA=%PRIV%\test-userdata"

rem Make the copy behave as a real GUI app even when launched from inside DSH.
set "ELECTRON_RUN_AS_NODE="
set "ELECTRON_NO_ATTACH_CONSOLE="

echo ============================================================
echo   DSH Desktop smoke copy - ISOLATED, UNPATCHED
echo ============================================================
echo   exe       : %SMOKE%\DeepSeek Harness.exe
echo   DSH_HOME  : %DSH_HOME%
echo   userData  : %USERDATA%
echo.
echo   Verify in Task Manager that the running image is the one above,
echo   NOT E:\Software\DeepSeek Harness\.
echo.

if not exist "%SMOKE%\DeepSeek Harness.exe" (
  echo [FAIL] smoke copy missing at %SMOKE%
  echo        Run D-01 first.
  echo.
  pause
  exit /b 3
)

if not exist "%USERDATA%" mkdir "%USERDATA%"

start "" "%SMOKE%\DeepSeek Harness.exe" --user-data-dir="%USERDATA%"

echo Launched. This window can be closed.
timeout /t 3 >nul
exit /b 0

