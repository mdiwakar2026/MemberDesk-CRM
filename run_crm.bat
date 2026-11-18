@echo off
title MemberDesk CRM
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo  The CRM is not installed yet. Running install.bat first...
  call install.bat
  if not exist ".venv\Scripts\python.exe" exit /b 1
)
echo.
echo  Starting MemberDesk CRM at http://127.0.0.1:5000
echo  Keep this window open while using the CRM. Close it to stop.
echo.
start "" http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py
pause
