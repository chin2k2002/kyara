@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not exist ".git" (
  echo This folder was not downloaded with git.
  echo Download the latest ZIP, extract it over this folder, then run install.cmd.
  echo Your runtime\, models\ and MimicMotion\ folders are kept.
  pause
  exit /b 1
)
git pull --ff-only || (
  echo Update failed.
  pause
  exit /b 1
)
call "%~dp0install.cmd" -NoMimic
pause
