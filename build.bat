@echo off
rem Build msg_checker.exe (GUI) and msg_checker_cli.exe (console) into dist\
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --noconfirm --clean --onefile --windowed --name msg_checker --collect-all extract_msg msg_checker.py || goto :error
python -m PyInstaller --noconfirm --clean --onefile --console --name msg_checker_cli --collect-all extract_msg msg_checker.py || goto :error
echo.
echo Done: dist\msg_checker.exe , dist\msg_checker_cli.exe
pause
exit /b 0
:error
echo.
echo Build failed.
pause
exit /b 1
