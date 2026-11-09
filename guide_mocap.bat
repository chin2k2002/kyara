@echo off
rem Drag and drop a video file onto this .bat:
rem the video is shown next to the webcam preview and you copy its motion.
rem Output: <video name>_motion.mp4 next to the dropped video.
cd /d "%~dp0"
if not exist "runtime\Scripts\python.exe" (
  echo Please run install.cmd first.
  pause
  exit /b 1
)
if "%~1"=="" (
  echo Drag and drop a guide video file onto guide_mocap.bat
  pause
  exit /b 1
)
"runtime\Scripts\python.exe" rgb_mocap.py --camera 0 --guide "%~1" --mirror_guide --output "%~dpn1_motion.mp4" %2 %3 %4 %5 %6 %7 %8 %9
pause
