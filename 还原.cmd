@echo off
rem One-click wrapper around uninstall.ps1.
setlocal
title DSH session-window - uninstall
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
echo.
pause
