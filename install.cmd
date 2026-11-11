@echo off
rem Double-click to check this PC has what HotStreak needs, then (optionally) install it as a Windows service.
rem The work is done by windows\precheck.ps1; it asks before changing anything.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\precheck.ps1" %*
echo.
pause
