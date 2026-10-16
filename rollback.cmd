@echo off
rem ===========================================================================
rem  R2.5 placeholder entry - the formal rollback is NOT enabled yet.
rem
rem  The v1 rollback.cmd killed every process named "DeepSeek Harness.exe" and
rem  then picked the newest app.asar.original-* by filename alone; A-01b/B-00
rem  replace it with this file. The R2 rollback is only placed here at E-03.
rem
rem  Exit code 9 means "placeholder entry", per the R2 exit-code table.
rem ===========================================================================
setlocal
title DSH session-window rollback - placeholder
echo.
echo   R2 in progress. Formal entry not enabled yet.
echo   See R2-RUNBOOK.md in this folder.
echo.
echo   (exit code 9 = placeholder entry; this is the expected result)
echo.
pause
exit /b 9

