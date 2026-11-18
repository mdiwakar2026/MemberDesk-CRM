@echo off
title MemberDesk CRM - Installer
cd /d "%~dp0"
echo.
echo  ==========================================================
echo    MemberDesk CRM
echo    One-time installation
echo  ==========================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo  [!] Python is not installed on this computer.
  echo      1. Download Python 3.10 or newer from https://www.python.org/downloads/
  echo      2. During setup TICK "Add python.exe to PATH"
  echo      3. Run install.bat again.
  echo.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo  [!] Python 3.10 or newer is required. Please update Python and run install.bat again.
  pause
  exit /b 1
)

echo  [1/3] Creating private Python environment (.venv) ...
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 ( echo  [!] Could not create the environment. & pause & exit /b 1 )

echo  [2/3] Installing required packages (needs internet) ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 ( echo  [!] Package installation failed - check your internet connection. & pause & exit /b 1 )

echo  [3/3] Set up the administrator login
".venv\Scripts\python.exe" setup_admin.py
if errorlevel 1 ( echo  [!] Admin setup was not completed. Run install.bat again. & pause & exit /b 1 )

echo.
echo  Installation complete!  Double-click  run_crm.bat  to start the CRM.
echo.
pause
