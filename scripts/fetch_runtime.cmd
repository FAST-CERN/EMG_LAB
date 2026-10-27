@echo off
rem Fetch the pinned local runtime (see scripts\runtime.lock) into .runtime\python313.
rem Called by install.cmd only when both the local runtime and py -3.13 are unavailable.
rem Chinese text below is GBK-encoded on purpose: cmd's UTF-8 parser desyncs on multibyte lines.
rem System tools are pinned to %SystemRoot%\System32: PATH may resolve tar/curl to Git's
rem GNU tar (cannot read zip) or other substitutes. All file paths stay relative because
rem Windows tar treats "C:\..." as a remote host and its bsdtar build lacks --force-local.
rem The URL slots below are unrolled on purpose: loops need delayed expansion, which is
rem what desyncs cmd on this script. The lock errors out above 3 sources instead.
setlocal EnableExtensions
chcp 936 >nul
cd /d "%~dp0.."

if not exist "%SystemRoot%\System32\curl.exe" goto :fail_tooling
if not exist "%SystemRoot%\System32\tar.exe" goto :fail_tooling
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" goto :fail_tooling

set "VERSION="
set "WANT_SHA="
set /a URL_COUNT=0
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("scripts\runtime.lock") do call :consume "%%a" "%%b"
if not defined VERSION goto :fail_lock
if not defined WANT_SHA goto :fail_lock
if %URL_COUNT% lss 1 goto :fail_lock
if %URL_COUNT% gtr 3 goto :fail_lock

if not exist ".runtime\" mkdir ".runtime"
set "PKG=.runtime\runtime_%VERSION%.nupkg"
set "TARGET=.runtime\python313"
del "%PKG%" 2>nul
if exist "%TARGET%.tmp" rmdir /s /q "%TARGET%.tmp"

set "FETCH_OK="
if %URL_COUNT% geq 1 if not defined FETCH_OK call :try_download "%URL_1%"
if %URL_COUNT% geq 2 if not defined FETCH_OK call :try_download "%URL_2%"
if %URL_COUNT% geq 3 if not defined FETCH_OK call :try_download "%URL_3%"
if not defined FETCH_OK goto :fail_net
del "%PKG%" 2>nul
echo 运行时就绪：%TARGET%\tools\python.exe
exit /b 0

:consume
if /i "%~1"=="version" set "VERSION=%~2"
if /i "%~1"=="sha256" set "WANT_SHA=%~2"
if /i "%~1"=="url" set /a URL_COUNT+=1
if /i "%~1"=="url" call :store_url %URL_COUNT% "%~2"
goto :eof

:store_url
set "URL_%~1=%~2"
goto :eof

:try_download
echo 正在取回 Python %VERSION% 运行时...
"%SystemRoot%\System32\curl.exe" -fL --retry 3 --connect-timeout 20 -o "%PKG%" "%~1"
if errorlevel 1 (
    echo Source unavailable, trying next...
    goto :eof
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "exit [int]-not ((Get-FileHash -Algorithm SHA256 '%PKG%').Hash -eq '%WANT_SHA%')"
if errorlevel 1 goto :fail_hash
if not exist "%TARGET%.tmp\" mkdir "%TARGET%.tmp"
"%SystemRoot%\System32\tar.exe" -xf "%PKG%" -C "%TARGET%.tmp"
if errorlevel 1 goto :fail_extract
if not exist "%TARGET%.tmp\tools\python.exe" goto :fail_extract
if exist "%TARGET%" rmdir /s /q "%TARGET%"
move "%TARGET%.tmp" "%TARGET%" >nul
set "FETCH_OK=1"
goto :eof

:fail_lock
echo 运行时锁 scripts\runtime.lock 缺失或损坏（版本、哈希或来源数不合法），无法取回。
exit /b 1

:fail_tooling
echo 本机缺少 curl/tar/powershell（需要 Windows 10 以上）。请改用学生离线包安装。
exit /b 1

:fail_hash
echo 下载内容与运行时锁中的 SHA256 不符，已拒绝安装。
del "%PKG%" 2>nul
if exist "%TARGET%.tmp" rmdir /s /q "%TARGET%.tmp"
echo 请检查网络后重跑 install.cmd；仍失败请向老师索取学生离线包。
exit /b 1

:fail_extract
echo 解压运行时失败。
del "%PKG%" 2>nul
if exist "%TARGET%.tmp" rmdir /s /q "%TARGET%.tmp"
echo 请重跑 install.cmd 重试；仍失败请向老师索取学生离线包。
exit /b 1

:fail_net
echo 所有来源均无法下载 Python 运行时。
del "%PKG%" 2>nul
if exist "%TARGET%.tmp" rmdir /s /q "%TARGET%.tmp"
echo 请确认网络可用后重跑 install.cmd；无网环境请向老师索取学生离线包。
exit /b 1
