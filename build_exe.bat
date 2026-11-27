@echo off
rem Windows 上で kyara.exe(GUI・トレイ常駐・自動起動すべて込み、単一ファイル)を作る。
rem 要: Python 3.12 など(tkinter 付き)。PowerPoint は実行する PC にあればよい。
py -m pip install --upgrade pip pywin32 pystray pillow pyinstaller || exit /b 1
py -m PyInstaller --noconfirm --onefile --noconsole --name kyara ^
  --hidden-import win32timezone --hidden-import pythoncom ^
  --hidden-import win32api --hidden-import pystray._win32 ^
  --collect-submodules win32com ^
  run_kyara.py || exit /b 1
echo dist\kyara.exe を作成しました
