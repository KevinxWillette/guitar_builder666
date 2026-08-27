@echo off
title Universe Canvases
cd /d "%~dp0UNIVERSE"
python "%~dp0UNIVERSE\SERVE_KILLY_UNIVERSE.py"
if errorlevel 1 py "%~dp0UNIVERSE\SERVE_KILLY_UNIVERSE.py"
if errorlevel 1 (
  echo Python needed to open the canvases.
  pause
)
