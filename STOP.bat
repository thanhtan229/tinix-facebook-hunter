@echo off
setlocal
cd /d "%~dp0"
title Dung Tinix-Facebook-Hunter

if /i "%~1"=="silent" set "TINIX_SILENT=1"

echo ========================================================
echo   TINIX - FACEBOOK HUNTER (Dung tien trinh ngam)
echo ========================================================
echo [Tinix] Dang tim va tat cac tien trinh Tinix-Facebook-Hunter...

REM Su dung utility don dep san co
python utils\process_cleanup.py --skip-windows >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong the dung server hoac cong 7866 dang duoc ung dung khac su dung.
    exit /b 1
)

echo [Tinix] Da dung may chu ngam thanh cong.
if not "%TINIX_SILENT%"=="1" ping 127.0.0.1 -n 3 >nul
exit /b 0
