@echo off
rem One click: starts the server, your Horizon, Ollama and Keve. See README.md.
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is needed: https://www.python.org/downloads/
  pause
  exit /b 1
)
python -u "%~dp0companion\launch.py" %*
pause
