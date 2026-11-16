@echo off
rem One click: starts the server, your Horizon, Ollama and Keve. See README.md.
rem Voice packages (onnxruntime, PyAV...) only ship for Python 3.11-3.13 so far, so
rem those are preferred; the newest Python is the fallback.
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
%PY% -u "%~dp0companion\launch.py" %*
pause
