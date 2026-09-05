@echo off
setlocal
cd /d "%~dp0"
title Dung Tinix-Facebook-Hunter

echo ========================================================
echo   TINIX - FACEBOOK HUNTER (Dung tien trinh ngam)
echo ========================================================
echo [Tinix] Dang tim va tat cac tien trinh Tinix-Facebook-Hunter...

REM Su dung utility don dep san co
python utils\process_cleanup.py --skip-windows >nul 2>nul

echo [Tinix] Da dung may chu ngam thanh cong.
ping 127.0.0.1 -n 3 >nul
exit /b 0
