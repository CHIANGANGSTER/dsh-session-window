@echo off
rem ===========================================================================
rem  R2 smoke install: applies the patch to the smoke copy only.
rem
rem  The smoke copy is a throwaway clone of the app used for D-phase testing.
rem  It never touches the formal installation.
rem ===========================================================================
setlocal
title DSH session-window patch - smoke install
cd /d "%~dp0"

set "SMOKE=E:\dsh-smoke\DeepSeek Harness"

echo ============================================================
echo   DSH Desktop : patch the SMOKE copy
echo ============================================================
echo   target: %SMOKE%
echo.

if not exist "%SMOKE%\DeepSeek Harness.exe" (
  echo [FAIL] smoke copy not found at %SMOKE%
  echo        D-01 builds it; see R2-RUNBOOK.md.
  echo.
  pause
  exit /b 3
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -AppDir "%SMOKE%" -RequireAuthorization %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo Smoke patch installed. Start the smoke copy to test.
) else (
  echo Exit code %RC%. See the R2 exit-code table in R2-RUNBOOK.md.
)
echo.
pause
exit /b %RC%

