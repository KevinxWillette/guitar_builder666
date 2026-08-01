@echo off
title Killette Guitar Builder
where python >nul 2>nul || (echo Install Python from python.org first, then re-run this. & pause & exit /b)
python -m pip install --quiet pillow numpy opencv-python-headless
start "" http://localhost:8666
python -m guitar_mechanic app
pause
