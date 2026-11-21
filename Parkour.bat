@echo off
rem One click for parkour: stops the bots (one at a time: less lag), starts the server and
rem your Horizon, builds the course and records your runs. Close the window to stop.
set "PY="
for %%v in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%v -c "import sys" >nul 2>nul && set "PY=py -%%v"
  )
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.11 or newer is needed: https://www.python.org/downloads/
  pause
  exit /b 1
)
cd /d "%~dp0training\parkour"
%PY% -u play.py
pause
