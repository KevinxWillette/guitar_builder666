@echo off
setlocal enabledelayedexpansion
title AI Roundtable - Installer
cd /d "%~dp0"
color 0F

echo ==================================================================
echo   AI ROUNDTABLE - INSTALLER
echo ==================================================================
echo.
echo  This connects GPT and Grok to Claude so you only ever talk
echo  to Claude, and it asks them for you.
echo.
echo  It is FREE. It uses the ChatGPT and SuperGrok accounts you
echo  already pay for. It will never ask you for a card.
echo.
echo  You will be asked to sign in twice, in a browser window.
echo  That is the only part you have to do yourself.
echo.
echo  If anything goes wrong this window STAYS OPEN and tells you
echo  what happened. Nothing here can break your computer.
echo.
pause
echo.

REM ================================================================
REM  1. Python
REM ================================================================
echo [1/6] Looking for Python...
set PYEXE=
where python >nul 2>nul && set PYEXE=python
if "!PYEXE!"=="" (where py >nul 2>nul && set PYEXE=py)

if "!PYEXE!"=="" (
  echo       Not found. Installing it for you...
  echo.
  winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
  echo.
  echo  ------------------------------------------------------------
  echo   Python was just installed.
  echo.
  echo   Windows needs you to start fresh for it to be found.
  echo   Please CLOSE this window, then DOUBLE-CLICK this same file
  echo   again. It will pick up where it left off.
  echo  ------------------------------------------------------------
  echo.
  pause
  exit /b 0
)
echo       Found Python: !PYEXE!
echo.

REM ================================================================
REM  2. Node (needed to install the two AI tools)
REM ================================================================
echo [2/6] Looking for Node...
set NPMEXE=
where npm >nul 2>nul && set NPMEXE=npm
if "!NPMEXE!"=="" (
  if exist "%ProgramFiles%\nodejs\npm.cmd" set NPMEXE="%ProgramFiles%\nodejs\npm.cmd"
)

if "!NPMEXE!"=="" (
  echo       Not found. Installing it for you...
  echo.
  winget install --id OpenJS.NodeJS.LTS --exact --silent --accept-package-agreements --accept-source-agreements
  echo.
  if exist "%ProgramFiles%\nodejs\npm.cmd" (
    set NPMEXE="%ProgramFiles%\nodejs\npm.cmd"
    echo       Installed.
  ) else (
    echo  ------------------------------------------------------------
    echo   Node was just installed.
    echo.
    echo   Please CLOSE this window, then DOUBLE-CLICK this same file
    echo   again. It will pick up where it left off.
    echo  ------------------------------------------------------------
    echo.
    pause
    exit /b 0
  )
)
echo       Found Node.
echo.

REM ================================================================
REM  3. The two AI helper programs
REM ================================================================
echo [3/6] Installing the GPT helper (this takes a minute)...
where codex >nul 2>nul
if errorlevel 1 (
  call !NPMEXE! install -g @openai/codex
  if errorlevel 1 (
    echo.
    echo   THAT FAILED. Copy the red text above and send it to Claude.
    echo.
    pause
    exit /b 1
  )
) else (
  echo       Already installed.
)
echo.

echo [4/6] Installing the Grok helper (this takes a minute)...
where grok >nul 2>nul
if errorlevel 1 (
  call !NPMEXE! install -g @xai-official/grok
  if errorlevel 1 (
    echo.
    echo   That did not work. Grok may install a different way now.
    echo   Everything else will still work with GPT alone.
    echo   Send this window's text to Claude and it will fix it.
    echo.
    pause
  )
) else (
  echo       Already installed.
)
echo.

REM ================================================================
REM  4. Sign in
REM ================================================================
echo ==================================================================
echo   [5/6] SIGNING IN - your turn
echo ==================================================================
echo.
echo  A browser window is about to open for ChatGPT.
echo  Click "Sign in with ChatGPT" and use your normal ChatGPT login.
echo  Then come back to this window.
echo.
pause
call codex login
if errorlevel 1 (
  echo.
  echo   If no browser opened, type this word and press Enter:  codex
  echo   then follow the sign-in on screen, and close it when done.
  echo.
)
echo.
echo  Now the same for Grok. A browser will open.
echo  Sign in with the account your SuperGrok subscription is on.
echo.
pause
call grok login
if errorlevel 1 (
  echo.
  echo   If no browser opened, type this word and press Enter:  grok
  echo   then follow the sign-in on screen, and close it when done.
  echo.
)
echo.

REM ================================================================
REM  5. Connect it all to Claude
REM ================================================================
echo [6/6] Connecting everything to Claude Desktop...
echo.
call !PYEXE! -m roundtable setup
echo.
echo ==================================================================
echo   ALMOST DONE - two things left, both easy
echo ==================================================================
echo.
echo   1. QUIT Claude Desktop completely.
echo      Closing the window is NOT enough. Find the Claude icon
echo      near the clock (bottom-right), right-click it, choose Quit.
echo      Then open Claude again.
echo.
echo   2. Ask Claude this exact question:
echo.
echo         what does roundtable_status say?
echo.
echo   If it names GPT and Grok, you are finished. That is it.
echo.
echo   If anything above looked wrong, take a photo or copy the text
echo   of this window and send it to Claude.
echo.
pause
