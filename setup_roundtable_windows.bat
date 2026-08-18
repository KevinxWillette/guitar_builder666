@echo off
title AI Roundtable setup
cd /d "%~dp0"
where python >nul 2>nul || (echo Install Python from python.org first, then re-run this. & pause & exit /b)
python -m roundtable setup
echo.
pause
