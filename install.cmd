@echo off
rem ===========================================================================
rem  R2.5 placeholder entry - the formal installer is NOT enabled yet.
rem
rem  A-01b/B-00 replace the v1 entry with this file so that double-clicking
rem  install.cmd cannot install the defective v1 patch. The formal installer is
rem  only placed here at E-03, after G1 passes and the user authorizes U-3.
rem
rem  Exit code 9 means "placeholder entry", per the R2 exit-code table.
rem ===========================================================================
setlocal
title DSH session-window patch - placeholder
echo.
echo   R2 in progress. Formal entry not enabled yet.
echo   See R2-RUNBOOK.md in this folder.
echo.
echo   (exit code 9 = placeholder entry; this is the expected result)
echo.
pause
exit /b 9

