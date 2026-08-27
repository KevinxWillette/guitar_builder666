@echo off
title Forever Zoom
cd /d "%~dp0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :17891 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
python "%~dp0SERVE.py"
if errorlevel 1 py -3 "%~dp0SERVE.py"
if errorlevel 1 (
  echo Python needed to serve the canvas.
  pause
)
