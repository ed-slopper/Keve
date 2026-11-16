@echo off
setlocal EnableDelayedExpansion
rem Start Keve: a headless Horizon player that joins your world, plus the companion brain.
rem Usage: start_keve.bat [HOST:PORT] [YourPlayerName]

set "HERE=%~dp0"
set "KEVE_HOME=%LOCALAPPDATA%\Keve"
if not exist "%KEVE_HOME%\player" mkdir "%KEVE_HOME%\player"

rem --- find horizon-ctl.exe from the Horizon launcher (newest version first) ---
set "CTL="
for /f "delims=" %%d in ('dir /b /ad /o-d "%APPDATA%\horizon-launcher\versions" 2^>nul') do (
  if not defined CTL if exist "%APPDATA%\horizon-launcher\versions\%%d\horizon-ctl.exe" set "CTL=%APPDATA%\horizon-launcher\versions\%%d\horizon-ctl.exe"
)
if not defined CTL (
  echo Could not find horizon-ctl.exe. Install Horizon with its launcher first: https://playhorizon.dev/download
  pause
  exit /b 1
)
echo Using !CTL!

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is needed: https://www.python.org/downloads/
  pause
  exit /b 1
)

rem --- where to join ---
set "ADDR=%~1"
if "!ADDR!"=="" (
  echo.
  echo In your Horizon game: Esc, Open to LAN, Start LAN World. Note the port it prints in chat.
  set /p "PORT=LAN port: "
  set "ADDR=127.0.0.1:!PORT!"
)
set "OWNER=%~2"
set "OWNER_ARG="
if not "!OWNER!"=="" set "OWNER_ARG=--owner !OWNER!"

set "SOCK=%KEVE_HOME%\keve-ctl.json"
set "HORIZON_HOME=%KEVE_HOME%\home"

echo.
echo Starting Keve's game (no window) and joining !ADDR! ...
"!CTL!" --socket "!SOCK!" launch --offscreen --server !ADDR! --name Keve --player-dir "%KEVE_HOME%\player" --width 640 --height 360 --render-distance 4
if errorlevel 1 (
  echo Keve's game did not start. Its log is in %KEVE_HOME%.
  pause
  exit /b 1
)
"!CTL!" --socket "!SOCK!" --timeout 90 wait-ready >nul
echo Keve's game is up. Once it says "connected", talk to it in chat, for example: keve follow me
echo Press Ctrl+C here to stop Keve.
echo.

python -u "%HERE%companion\keve.py" --socket "!SOCK!" !OWNER_ARG!

echo.
echo Keve stopped. Closing Keve's game...
"!CTL!" --socket "!SOCK!" quit >nul 2>nul
pause
