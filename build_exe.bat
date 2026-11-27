@echo off
rem Windows 上で kyara.exe を作る (要: Python, PowerPoint 不要)
py -m pip install --upgrade pip pywin32 pyinstaller || exit /b 1
py -m PyInstaller --noconfirm --onefile --name kyara ^
  --hidden-import win32timezone --hidden-import pythoncom ^
  --hidden-import win32api --collect-submodules win32com ^
  run_kyara.py || exit /b 1
echo dist\kyara.exe を作成しました
