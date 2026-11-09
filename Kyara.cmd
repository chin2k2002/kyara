@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not exist "runtime\Scripts\python.exe" (
  echo Kyara is not installed. Run install.cmd first.
  pause
  exit /b 1
)
set PYTHONUTF8=1
"%~dp0runtime\Scripts\python.exe" -X utf8 -u "%~dp0app.py" %*
set "app_exit=%errorlevel%"
if not "%app_exit%"=="0" (
  echo.
  echo Kyara exited with code %app_exit%. See the messages above.
  pause
)
exit /b %app_exit%
