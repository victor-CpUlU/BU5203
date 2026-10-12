@echo off
setlocal
cd /d "%~dp0"
title AI-Assisted Credit Analysis

rem ---- 1. Python 3.11+ ------------------------------------------------------
where python >nul 2>nul
if errorlevel 1 goto :nopython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto :nopython

rem ---- 2. Virtual environment and pinned dependencies (reused once installed) --
set "NEEDS_INSTALL=0"
if not exist ".venv\Scripts\python.exe" set "NEEDS_INSTALL=1"
if not exist ".venv\installed-requirements.txt" set "NEEDS_INSTALL=1"
if exist ".venv\installed-requirements.txt" (
  fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul || set "NEEDS_INSTALL=1"
)
if "%NEEDS_INSTALL%"=="1" (
  echo Setting up the app for the first time. This can take a few minutes...
  if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :venvfail
  )
  if exist ".venv\installed-requirements.txt" del ".venv\installed-requirements.txt"
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :pipfail
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

rem ---- 3. .env (created on first run, then stop so the key can be added) -----
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo  A settings file .env has been created.
  echo  Add your AI provider, model and API key to .env, save it, then double-click start.bat again.
  echo.
  start "" notepad ".env"
  pause
  exit /b 0
)

rem ---- 4. Fresh start: stop any earlier copy of this app, then check the port ----
for /f %%p in ('".venv\Scripts\python.exe" tools\launcher.py port') do set "PORT=%%p"
".venv\Scripts\python.exe" tools\launcher.py check-port
if errorlevel 2 (
  echo  An earlier copy of the app is still running. Restarting it...
  ".venv\Scripts\python.exe" tools\launcher.py restart
)
".venv\Scripts\python.exe" tools\launcher.py check-port
if errorlevel 1 (
  echo.
  echo  Port %PORT% is already in use. Close the other program or the app's other window, or change PORT in .env.
  echo.
  pause
  exit /b 1
)

rem ---- 5. Start the backend (serves the frontend too) and open the browser -----
rem APP_AUTO_SHUTDOWN=1: the backend stops itself when the browser tab is closed or "Close app" is clicked.
set "APP_AUTO_SHUTDOWN=1"
start "" /b ".venv\Scripts\python.exe" tools\launcher.py open
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %PORT%
if errorlevel 1 (
  echo.
  echo  The app stopped with an error. See the messages above.
  echo.
  pause
  exit /b 1
)
rem Normal close: this window closes too, so nothing keeps running.
exit 0

:nopython
echo.
echo  Python 3.11 or later is required. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run start.bat again.
echo.
pause
exit /b 1

:venvfail
echo.
echo  Setup failed while creating the virtual environment (.venv). It will be retried on the next launch.
echo.
pause
exit /b 1

:pipfail
echo.
echo  Setup failed while installing dependencies (check your internet connection). It will be retried on the next launch.
echo.
pause
exit /b 1
