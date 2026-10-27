@echo off
setlocal
cd /d "%~dp0"
if exist ".runtime\dotnet\dotnet.exe" (
  set "DOTNET_ROOT=%~dp0.runtime\dotnet"
  set "PATH=%~dp0.runtime\dotnet;%PATH%"
)
if not exist ".venv\Scripts\python.exe" (
  echo Please run install.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  pause
  exit /b 1
)
exit /b 0
