@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required. Download it from https://www.python.org/downloads/
  pause
  exit /b 1
)
python app.py serve
if errorlevel 1 (
  echo Could not start. If port 8765 is occupied, open http://127.0.0.1:8765 or run python app.py --port 8766
  pause
)
