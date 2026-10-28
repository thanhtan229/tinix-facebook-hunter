@echo off
REM ========================================================
REM   TINIX - FACEBOOK HUNTER: one-time setup for a new PC
REM   Creates .venv, installs requirements.txt and Chromium
REM   for Playwright, then verifies the install.
REM   Safe to re-run. Does NOT create data, accounts or .env.
REM   Usage: install.bat        (pauses at the end)
REM          install.bat silent (no pause, for automation)
REM ========================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Tinix-Facebook-Hunter - Setup

echo ========================================================
echo   TINIX - FACEBOOK HUNTER - SETUP
echo ========================================================

REM --- 0. Locate Python 3.10 or 3.11 (project target: 3.11) ---
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.11 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3.11"
)
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 10), (3, 11)) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=python"
    )
)
if not defined PY goto :no_python
echo [0] Python found: %PY%

REM --- 1. Virtual environment (.venv is what START.bat uses) ---
if exist ".venv\Scripts\python.exe" (
    echo [1/4] Virtual environment .venv already exists - reusing it.
) else (
    echo [1/4] Creating virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

REM --- 2. Python packages ---
echo [2/4] Installing Python packages from requirements.txt ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

REM --- 3. Browser engine for Playwright (one-time download) ---
echo [3/4] Installing Chromium for Playwright (one-time download) ...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :fail

REM --- 4. Verify ---
echo [4/4] Verifying installation ...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, websockets, pydantic, playwright, yt_dlp, PIL, openpyxl, pyotp, pandas, piexif, psutil, httpx, bs4, lxml"
if errorlevel 1 goto :fail

REM --- Browser needed for App Mode (warning only) ---
set "BROWSER_FOUND="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER_FOUND=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER_FOUND=1"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER_FOUND=1"
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_FOUND=1"
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_FOUND=1"
if not defined BROWSER_FOUND echo [WARN] Google Chrome or Microsoft Edge was not found. Install Chrome before starting the app.

echo.
echo ========================================================
echo   SETUP COMPLETE
echo   Start the app: double-click START.vbs (or START.bat)
echo   Optional: copy .env.template to .env and fill in
echo   FB_APP_ID / FB_APP_SECRET if you use Facebook token features.
echo   Accounts, data and saved secrets are NOT included; add them
echo   inside the app. Secrets are tied to this Windows user and PC.
echo ========================================================
if /i not "%~1"=="silent" pause
exit /b 0

:no_python
echo [ERROR] Python 3.10 or 3.11 was not found.
echo         Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo         then run install.bat again.
goto :fail

:fail
echo.
echo [FAILED] Setup stopped. Fix the error shown above and run install.bat again.
if /i not "%~1"=="silent" pause
exit /b 1
