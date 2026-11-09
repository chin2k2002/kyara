@echo off
rem Avatar video generation. Example:
rem   avatar.bat --text "Hello" --photo me.jpg --voice_sample voice.m4a --mocap --guide guide.mov
cd /d "%~dp0"
if not exist "runtime\Scripts\python.exe" (
  echo Please run install.cmd first.
  pause
  exit /b 1
)
if "%~1"=="" (
  "runtime\Scripts\python.exe" generate_avatar_video.py --help
  pause
  exit /b 0
)
"runtime\Scripts\python.exe" generate_avatar_video.py %*
pause
