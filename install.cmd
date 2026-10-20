@echo off
rem One-command install: calls install.ps1.
setlocal
title DSH session-window - install
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
