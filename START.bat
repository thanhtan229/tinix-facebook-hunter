@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
if /i "%~1"=="silent" set "TINIX_SILENT=1"
title Tinix-Facebook-Hunter App

echo ========================================================
echo   TINIX - FACEBOOK HUNTER (Desktop App Mode)
echo ========================================================

REM 1. Tim trinh thuc thi Python
set "PYTHON_CMD="
set "PYTHONW_CMD="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    set "PYTHONW_CMD=%~dp0.venv\Scripts\pythonw.exe"
    goto :found_python
)
if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
    set "PYTHONW_CMD=%~dp0venv\Scripts\pythonw.exe"
    goto :found_python
)

python -c "import uvicorn" >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        set "PYTHON_CMD=%%I"
        set "PYTHONW_CMD=%%~dpIpythonw.exe"
    )
    if defined PYTHON_CMD goto :found_python
)

py -3.11 -c "import uvicorn" >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
        set "PYTHON_CMD=%%I"
        set "PYTHONW_CMD=%%~dpIpythonw.exe"
    )
    if defined PYTHON_CMD goto :found_python
)

for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "C:\Python311"
    "C:\Python310"
) do (
    if exist "%%~D\python.exe" (
        set "PYTHON_CMD=%%~D\python.exe"
        set "PYTHONW_CMD=%%~D\pythonw.exe"
        goto :found_python
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        set "PYTHON_CMD=%%I"
        set "PYTHONW_CMD=%%~dpIpythonw.exe"
        goto :found_python
    )
)

:found_python
if not defined PYTHON_CMD (
    echo [LOI] Khong tim thay Python tren he thong!
    echo Vui long cai dat Python 3.10 hoac 3.11 tai https://www.python.org/
    if not "%TINIX_SILENT%"=="1" pause
    exit /b 1
)
if not exist "%PYTHONW_CMD%" (
    set "PYTHONW_CMD=%PYTHON_CMD%"
)

set "TINIX_PORT=7866"

REM 2. Kiem tra xem may chu ngam da chay chua
"%PYTHON_CMD%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%TINIX_PORT%/api/system/health', timeout=1)" >nul 2>nul && (
    echo [Tinix] May chu dang chay san tren port %TINIX_PORT%.
) || (
    call :start_background_server
    if errorlevel 1 exit /b 1
)

REM 3. Tim Google Chrome hoac Microsoft Edge de mo che do App Mode doc lap
set "BROWSER_APP_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER_APP_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_APP_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER_APP_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_APP_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER_APP_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_APP_EXE if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_APP_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER_APP_EXE if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_APP_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

echo [Tinix] Dang mo ung dung che do App Mode doc lap...
if defined BROWSER_APP_EXE (
    start "" "%BROWSER_APP_EXE%" --start-maximized --user-data-dir="%~dp0chrome_profile_ui" --no-first-run --no-default-browser-check --app="http://127.0.0.1:%TINIX_PORT%"
) else (
    start "" /max "http://127.0.0.1:%TINIX_PORT%"
)

REM 4. Tu dong tao Desktop shortcut neu chua ton tai
if not exist "%USERPROFILE%\Desktop\Tinix-Facebook-Hunter.lnk" (
    start "" /B "%PYTHONW_CMD%" "%~dp0utils\create_shortcut.py" >nul 2>nul
)

exit /b 0

:start_background_server
echo [Tinix] Dang kiem tra va don dep phien lam viec cu...
"%PYTHON_CMD%" utils\process_cleanup.py --skip-windows >nul 2>nul
if errorlevel 1 (
    echo [LOI] Cong %TINIX_PORT% van dang duoc su dung. Khong dung tien trinh ngoai project.
    exit /b 1
)

echo [Tinix] Dang khoi dong may chu ngam (port %TINIX_PORT%)...
set "TINIX_NO_BROWSER=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

start "" "%PYTHONW_CMD%" "%~dp0main.py"

REM Cho server san sang toi da 15 giay
for /l %%i in (1,1,15) do (
    "%PYTHON_CMD%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%TINIX_PORT%/api/system/health', timeout=1)" >nul 2>nul && (
        echo [Tinix] May chu ngam da san sang!
        exit /b 0
    )
    ping 127.0.0.1 -n 2 >nul
)

echo [LOI] May chu ngam khong phan hoi sau 15 giay!
echo Kiem tra log tai: %~dp0logs\server_startup.log
if not "%TINIX_SILENT%"=="1" pause
exit /b 1
