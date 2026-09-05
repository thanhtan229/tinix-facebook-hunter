@echo off
title Tao Shortcut Desktop Tinix-Facebook-Hunter
cd /d "%~dp0"
python utils\create_shortcut.py
if errorlevel 1 (
    pause
) else (
    ping 127.0.0.1 -n 3 >nul
)
