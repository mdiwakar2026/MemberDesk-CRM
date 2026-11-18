@echo off
title MemberDesk CRM - Reset admin password
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo Run install.bat first. & pause & exit /b 1 )
".venv\Scripts\python.exe" setup_admin.py
pause
