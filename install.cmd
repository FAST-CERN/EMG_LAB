@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if exist ".runtime\python313\tools\python.exe" (
  ".runtime\python313\tools\python.exe" scripts\bootstrap.py
) else (
  py -3.13 scripts\bootstrap.py
)
if errorlevel 1 (
  echo Installation did not finish. Read the message above.
  pause
  exit /b 1
)
pause
exit /b 0
