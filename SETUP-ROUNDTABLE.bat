@echo off
setlocal enabledelayedexpansion
title AI Roundtable - Setup
color 0F

echo ==================================================================
echo   AI ROUNDTABLE - SETUP
echo ==================================================================
echo.
echo   This gets GPT and Grok working inside Claude, so you only ever
echo   talk to Claude and it asks them for you.
echo.
echo   It is free. It uses your ChatGPT and SuperGrok accounts.
echo   You will never be asked for a card.
echo.
echo   Your job: sign in twice when a browser opens. That is all.
echo.
echo   This window will stay open no matter what happens.
echo.
echo ------------------------------------------------------------------
pause
echo.

set "DEST=%USERPROFILE%\AI-Roundtable"
set "ZIPFILE=%TEMP%\ai-roundtable.zip"
set "URL=https://github.com/KevinxWillette/guitar_builder666/archive/refs/heads/claude/killy-ai-roundtable-arch-q0ip34.zip"

echo Getting the files...  (about 10 seconds)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIPFILE%' -UseBasicParsing } catch { Write-Host ('  PROBLEM: ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 (
  echo.
  echo   Could not download the files.
  echo   Usually that means no internet, or a firewall blocked it.
  echo   Send a photo of this window to Claude.
  echo.
  pause
  exit /b 1
)

echo Unpacking...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -Path '%ZIPFILE%' -DestinationPath '%DEST%' -Force } catch { Write-Host ('  PROBLEM: ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 (
  echo.
  echo   Could not unpack the files. Send a photo of this window to Claude.
  echo.
  pause
  exit /b 1
)

set "APP="
for /d %%D in ("%DEST%\*") do (
  if exist "%%D\roundtable_server.py" set "APP=%%D"
)
if not defined APP (
  echo.
  echo   Unpacked, but the files are not where expected.
  echo   Send a photo of this window to Claude.
  echo.
  pause
  exit /b 1
)

echo Done. Files are in: !APP!
echo.
echo Starting the installer...
echo.
cd /d "!APP!"
call INSTALL_ROUNDTABLE_WINDOWS.bat
