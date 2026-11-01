@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ForgeFSD needs its project environment. Please follow the README setup once.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m forge.dashboard
if errorlevel 1 pause
