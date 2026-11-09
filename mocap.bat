@echo off
rem Webcam motion capture. Extra options are passed through, e.g.
rem   mocap.bat --duration 10 --output my_motion.mp4
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" rgb_mocap.py %*
pause
