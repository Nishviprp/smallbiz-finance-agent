@echo off
setlocal
title SmallBiz Finance Agent
cd /d "%~dp0"

rem --- 1. Find Python 3.10+ -------------------------------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo   Python 3.10 or newer is needed and was not found.
  echo   1. Install it from https://www.python.org/downloads/
  echo   2. On the first install screen, tick "Add python.exe to PATH".
  echo   3. Double-click start.bat again.
  echo.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)

rem --- 2. First run: create a private Python environment ---------------------
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   First-time setup: creating a private Python environment...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)

rem --- 3. Install/update packages, start the app, open the browser -----------
".venv\Scripts\python.exe" launch.py %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo   Something went wrong - see the messages above.
echo   Help: https://github.com/Nishviprp/smallbiz-finance-agent/issues
pause
exit /b 1
