@echo off
setlocal
cd /d "%~dp0"
title Tinix-Facebook-Hunter - Khoi dong

set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

REM ========================================================
REM 1. Tim trinh thuc thi Python phu hop
REM ========================================================
set "PYTHON_CMD="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    goto :found_python
)
if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
    goto :found_python
)

python -c "import uvicorn" >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_CMD=%%I"
    if defined PYTHON_CMD goto :found_python
)

py -3.11 -c "import uvicorn" >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_CMD=%%I"
    if defined PYTHON_CMD goto :found_python
)

py -3.10 -c "import uvicorn" >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3.10 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_CMD=%%I"
    if defined PYTHON_CMD goto :found_python
)

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :found_python
)
if exist "C:\Python311\python.exe" (
    set "PYTHON_CMD=C:\Python311\python.exe"
    goto :found_python
)
if exist "C:\Python310\python.exe" (
    set "PYTHON_CMD=C:\Python310\python.exe"
    goto :found_python
)

where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_CMD=%%I"
    if not defined PYTHON_CMD set "PYTHON_CMD=python"
    if defined PYTHON_CMD goto :found_python
)

where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_CMD=%%I"
    if defined PYTHON_CMD goto :found_python
)

:found_python
if not defined PYTHON_CMD (
    echo ========================================================
    echo [LOI] Khong tim thay Python tren he thong!
    echo Vui long cai dat Python 3.10 hoac 3.11 tai https://www.python.org/
    echo va nho tick chon "Add Python to PATH".
    echo ========================================================
    pause
    exit /b 1
)

echo ========================================================
echo   TINIX-FACEBOOK-HUNTER
echo ========================================================
echo   Python: "%PYTHON_CMD%"

REM Kiem tra module bat buoc, tu dong cai dat neu thieu
"%PYTHON_CMD%" -c "import uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
    echo [!] Phat hien thieu thu vien, dang tu dong cai dat tu requirements.txt...
    "%PYTHON_CMD%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [LOI] Cai dat thu vien that bai. Vui long kiem tra ket noi mang.
        pause
        exit /b 1
    )
)

echo [1/2] Dang kiem tra va don dep phien lam viec cu...
"%PYTHON_CMD%" utils\process_cleanup.py --skip-windows
if errorlevel 1 (
    echo   [!] Co canh bao trong qua trinh don dep, tiep tuc khoi dong...
)

echo.
echo [2/2] Dang khoi dong Tinix-Facebook-Hunter (FastAPI + Modern WebUI)...
echo       URL: http://127.0.0.1:7866
echo       Giu cua so nay de duy tri ket noi.
echo       Nhan Ctrl+C hoac dong cua so de dung chuong trinh.
echo ========================================================
echo.

title Tinix-Facebook-Hunter
"%PYTHON_CMD%" main.py

echo.
echo ========================================================
echo [THONG BAO] Tinix-Facebook-Hunter da dung lai.
echo ========================================================
pause
