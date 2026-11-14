@echo off
setlocal
cd /d "%~dp0"
set "DOTNET_ROOT=%CD%\.runtime\dotnet"
set "PATH=%DOTNET_ROOT%;%PATH%"
".runtime\python313\tools\python.exe" scripts\windows_acceptance.py %*
if errorlevel 1 (
  echo Windows acceptance failed. See local\windows-acceptance.json.
  pause
  exit /b 1
)
pause
