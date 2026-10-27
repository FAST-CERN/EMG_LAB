@echo off
setlocal
cd /d "%~dp0"
rem Interpreter priority: bundled local runtime, then system Python, then pinned fetch.
if not exist ".runtime\python313\tools\python.exe" (
  py -3.13 -c "" >nul 2>&1 || call scripts\fetch_runtime.cmd
)
chcp 65001 >nul
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
