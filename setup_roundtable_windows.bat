@echo off
title AI Roundtable setup
cd /d "%~dp0"

rem Windows installs Python as `python` or the `py` launcher - rarely `python3`.
set PYEXE=
where python >nul 2>nul && set PYEXE=python
if "%PYEXE%"=="" (where py >nul 2>nul && set PYEXE=py)
if "%PYEXE%"=="" (
  echo Python was not found.
  echo Install it from https://python.org and tick "Add Python to PATH",
  echo then run this file again.
  pause
  exit /b 1
)

%PYEXE% -m roundtable setup
echo.
pause
