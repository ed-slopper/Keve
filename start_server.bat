@echo off
setlocal EnableDelayedExpansion
rem Host an offline-mode Horizon server for you and Keve.
rem A world opened to LAN by a signed-in account runs in online mode and refuses Keve,
rem because Keve has no Microsoft account. On this server, you both join 127.0.0.1:25565.
rem Usage: start_server.bat [path\to\an\existing\world\folder]

set "SERVER_DIR=%LOCALAPPDATA%\Keve\server"
set "SRV="
for /f "delims=" %%d in ('dir /b /ad /o-d "%APPDATA%\horizon-launcher\versions" 2^>nul') do (
  if not defined SRV if exist "%APPDATA%\horizon-launcher\versions\%%d\horizon-server.exe" set "SRV=%APPDATA%\horizon-launcher\versions\%%d\horizon-server.exe"
)
if not defined SRV (
  echo Could not find horizon-server.exe. Install Horizon with its launcher first.
  pause
  exit /b 1
)

if not exist "%SERVER_DIR%\server.toml" (
  echo Setting up an offline-mode server in %SERVER_DIR%
  echo You will be asked to accept Minecraft's EULA: https://aka.ms/MinecraftEULA
  echo.
  if not exist "%SERVER_DIR%" mkdir "%SERVER_DIR%"
  "!SRV!" --dir "%SERVER_DIR%" init --world world --port 25565 --no-whitelist --offline
  if errorlevel 1 (
    echo Server setup did not finish.
    pause
    exit /b 1
  )
  if not "%~1"=="" (
    echo Copying your world from %~1 ...
    if exist "%SERVER_DIR%\world" rmdir /s /q "%SERVER_DIR%\world"
    xcopy /e /i /q "%~1" "%SERVER_DIR%\world" >nul
    del /q "%SERVER_DIR%\world\session.lock" >nul 2>nul
  )
)

echo.
echo Starting the server. In Horizon: Multiplayer, Direct Connection, 127.0.0.1
echo Then run: start_keve.bat 127.0.0.1:25565 YourName
echo Type "stop" here to shut the server down.
echo.
"!SRV!" --dir "%SERVER_DIR%" run
pause
