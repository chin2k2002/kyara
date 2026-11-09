@echo off
setlocal
cd /d "%~dp0"
title Kyara installer

echo ============================================================
echo  Kyara installer  (voice clone + RGB mocap + avatar video)
echo ============================================================
echo.

rem ---- 1. Python 3.11 -------------------------------------------------------
py -3.11 --version >nul 2>&1
if not errorlevel 1 goto :have_python
echo [1/7] Python 3.11 not found. Installing with winget...
where winget >nul 2>&1
if errorlevel 1 goto :no_winget_python
winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
py -3.11 --version >nul 2>&1
if errorlevel 1 goto :python_restart
goto :have_python
:no_winget_python
echo.
echo Please install Python 3.11 from https://www.python.org/downloads/windows/
echo  (check "Add python.exe to PATH" / "py launcher"), then run install.bat again.
goto :fail
:python_restart
echo.
echo Python 3.11 was installed. Please close this window and run install.bat again.
goto :fail
:have_python
for /f "delims=" %%v in ('py -3.11 --version') do echo [1/7] %%v OK

rem ---- 2. Git (needed to download MimicMotion) -----------------------------
where git >nul 2>&1
if not errorlevel 1 goto :have_git
echo [2/7] Git not found. Installing with winget...
where winget >nul 2>&1
if errorlevel 1 goto :git_skip
winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
where git >nul 2>&1
if not errorlevel 1 goto :have_git
:git_skip
echo      Git could not be installed automatically. Avatar video setup will be skipped.
echo      Install Git from https://git-scm.com/download/win if you need it.
set NO_GIT=1
goto :venv
:have_git
echo [2/7] Git OK

rem ---- 3. venv ---------------------------------------------------------------
:venv
if exist ".venv\Scripts\python.exe" goto :venv_ok
echo [3/7] Creating virtual environment .venv ...
py -3.11 -m venv .venv || goto :fail
:venv_ok
set "PY=%~dp0.venv\Scripts\python.exe"
echo [3/7] .venv OK
"%PY%" -m pip install --upgrade pip setuptools wheel || goto :fail

rem ---- 4. PyTorch (GPU if NVIDIA is present) ---------------------------------
echo.
where nvidia-smi >nul 2>&1
if errorlevel 1 goto :torch_cpu
echo [4/7] NVIDIA GPU detected. Installing PyTorch with CUDA...
"%PY%" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
if not errorlevel 1 goto :torch_ok
"%PY%" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
if not errorlevel 1 goto :torch_ok
echo      CUDA build failed. Falling back to CPU build.
:torch_cpu
echo [4/7] Installing PyTorch (CPU)...
"%PY%" -m pip install torch torchvision torchaudio || goto :fail
:torch_ok
"%PY%" -c "import torch; print('      torch', torch.__version__, '/ CUDA:', torch.cuda.is_available())"

rem ---- 5. Python packages -----------------------------------------------------
echo.
echo [5/7] Installing packages (TTS, moviepy, mediapipe, opencv)...
"%PY%" -m pip install -r requirements.txt soundfile || goto :fail
"%PY%" patch_tts.py

rem ---- 6. Mocap model --------------------------------------------------------
echo.
echo [6/7] Downloading pose estimation model...
"%PY%" -c "import rgb_mocap; rgb_mocap.ensure_model('full'); rgb_mocap.ensure_model('lite'); print('      mediapipe OK')" || goto :fail

rem ---- 7. MimicMotion (optional, large) --------------------------------------
echo.
if defined NO_GIT goto :done
echo [7/7] Avatar video (MimicMotion) needs an NVIDIA GPU and ~15GB of downloads.
choice /C YN /M "      Set up MimicMotion now"
if errorlevel 2 goto :done
"%PY%" setup_mimicmotion.py || goto :fail
"%PY%" patch_mimicmotion.py || goto :fail

:done
echo.
echo ============================================================
echo  Install finished!
echo.
echo   mocap.bat          : record your motion with the webcam
echo   guide_mocap.bat    : drag ^& drop a video on it to record
echo                        while watching it as a guide
echo   avatar.bat         : generate avatar video (see README)
echo ============================================================
pause
exit /b 0

:fail
echo.
echo Install stopped. Scroll up to see the error message.
pause
exit /b 1
