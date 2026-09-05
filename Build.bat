@echo off
setlocal
cd /d "%~dp0"
title Build Tinix-Facebook-Hunter App

set "PYTHON_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    goto :run_build
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :run_build
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :run_build
)

:run_build
if not defined PYTHON_CMD (
    echo [ERROR] Khong tim thay Python!
    pause
    exit /b 1
)

"%PYTHON_CMD%" scripts\build_app.py %*
if errorlevel 1 (
    echo [ERROR] Build that bai!
    pause
    exit /b 1
)

echo.
ping 127.0.0.1 -n 3 >nul
