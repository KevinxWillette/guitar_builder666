@echo off
title Infinite Canvas
cd /d "%~dp0INFINITE"
python "%~dp0INFINITE\SERVE.py"
if errorlevel 1 py -3 "%~dp0INFINITE\SERVE.py"
if errorlevel 1 (
  echo Python needed to open the canvas.
  pause
)
