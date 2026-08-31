@echo off
title Tao Shortcut Desktop Tinix FB Down
cd /d "%~dp0"
python utils\create_shortcut.py
timeout /t 3
