@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Tinix-Facebook-Hunter App

REM 1. Dat cac bien moi truong
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
set "TINIX_NO_BROWSER=1"

REM 2. Tim trinh thuc thi Python phu hop (uu tien pythonw.exe de chay ngam khong hien console)
set "PYTHONW_CMD="
set "PYTHON_CMD="

if exist ".venv\Scripts\pythonw.exe" (
    set "PYTHONW_CMD=%~dp0.venv\Scripts\pythonw.exe"
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    goto :found_python
)
if exist "venv\Scripts\pythonw.exe" (
    set "PYTHONW_CMD=%~dp0venv\Scripts\pythonw.exe"
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
    goto :found_python
)

for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "C:\Python311"
    "C:\Python310"
) do (
    if exist "%%~D\pythonw.exe" (
        set "PYTHONW_CMD=%%~D\pythonw.exe"
        set "PYTHON_CMD=%%~D\python.exe"
        goto :found_python
    )
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where pythonw 2^>nul') do (
        set "PYTHONW_CMD=%%I"
        goto :found_pythonw
    )
)
:found_pythonw

where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        set "PYTHON_CMD=%%I"
        if not defined PYTHONW_CMD set "PYTHONW_CMD=%%I"
        goto :found_python
    )
)

:found_python
if not defined PYTHON_CMD (
    echo [ERROR] Khong tim thay Python tren he thong!
    echo Vui long cai dat Python 3.10 hoac 3.11 tai https://www.python.org/
    pause
    exit /b 1
)
if not defined PYTHONW_CMD (
    set "PYTHONW_CMD=%PYTHON_CMD%"
)

REM 3. Kiem tra xem Server co dang chay tren port 7866 khong
"%PYTHON_CMD%" -c "import socket, sys; s = socket.socket(); s.settimeout(0.5); (s.connect(('127.0.0.1', 7866)), s.close(), sys.exit(0))" >nul 2>nul
if not errorlevel 1 goto :server_ready

REM Server chua chay, tien hanh don dep phien cu va khoi dong ngam
"%PYTHON_CMD%" utils\process_cleanup.py --skip-windows >nul 2>nul
start "" "%PYTHONW_CMD%" "%~dp0main.py"

REM Cho server san sang phan hoi tren port 7866 (cho toi da 15 giay)
for /L %%i in (1,1,30) do (
    "%PYTHON_CMD%" -c "import socket, sys; s = socket.socket(); s.settimeout(0.5); (s.connect(('127.0.0.1', 7866)), s.close(), sys.exit(0))" >nul 2>nul
    if not errorlevel 1 goto :server_ready
    powershell -NoProfile -Command "Start-Sleep -Milliseconds 500" >nul 2>nul
)

:server_ready
REM 4. Tim Chrome hoac Microsoft Edge de khoi chay o che do App Mode (--app=...)
set "APP_URL=http://127.0.0.1:7866"
set "BROWSER_BIN="

if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_BIN=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
    goto :launch_app
)
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_BIN=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
    goto :launch_app
)
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
    goto :launch_app
)
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
    set "BROWSER_BIN=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
    goto :launch_app
)
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
    set "BROWSER_BIN=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
    goto :launch_app
)

:launch_app
if defined BROWSER_BIN (
    start "" "%BROWSER_BIN%" --app="%APP_URL%"
) else (
    start "" "%APP_URL%"
)

REM 5. Kiem tra va tu dong tao Desktop shortcut neu chua co
if not exist "%USERPROFILE%\Desktop\Tinix-Facebook-Hunter.lnk" (
    start "" /B "%PYTHONW_CMD%" "%~dp0utils\create_shortcut.py" >nul 2>nul
)

exit /b 0
