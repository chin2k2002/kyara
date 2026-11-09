@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
echo ============================================================
echo  Kyara installer
echo  Everything is installed inside this folder (runtime\, .setup\).
echo  Python / Git do not need to be installed on this PC.
echo ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install.ps1" %*
set "result=%ERRORLEVEL%"
if not "%result%"=="0" (
  echo.
  echo Installation failed. See the message above; run install.cmd again to retry.
)
if "%~1"=="" pause
exit /b %result%
