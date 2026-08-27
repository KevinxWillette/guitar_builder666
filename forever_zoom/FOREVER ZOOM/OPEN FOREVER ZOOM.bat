@echo off
title Forever Zoom
cd /d "%~dp0"

REM free port if stuck
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

start "ForeverZoomServer" /MIN cmd /c "cd /d "%~dp0" && python -m http.server 8765"
timeout /t 2 /nobreak >nul

set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%EDGE%" (
  start "" "%EDGE%" --new-window "http://127.0.0.1:8765/index.html"
) else (
  start "" "http://127.0.0.1:8765/index.html"
)
echo Forever Zoom should open in Edge.
echo Keep the minimized server window running while you use it.
timeout /t 5
