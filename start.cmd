@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required. Download it from https://www.python.org/downloads/
  pause
  exit /b 1
)
python launch.py
if errorlevel 1 (
  echo Could not start. See data/server.log or run python launch.py --port 8766
  pause
)
