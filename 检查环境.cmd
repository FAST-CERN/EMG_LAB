@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run install.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\check_classroom.py --render
pause
