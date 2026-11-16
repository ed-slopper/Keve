@echo off
setlocal
rem Kev-4B (Q4_K_M) through Ollama: download, then a few Minecraft-style decision tests.
set MODEL=hf.co/turintech/Kev-4B-Artemis-GGUF:Q4_K_M

where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama was not found on PATH. Install it from https://ollama.com first.
  pause
  exit /b 1
)

echo === Downloading %MODEL% [about 2.5 GB, skipped if already there] ===
ollama pull %MODEL%
if errorlevel 1 (
  echo Download failed.
  pause
  exit /b 1
)

echo.
echo === Test 1: yes/no - is the player talking to Kev? ===
echo Steve says: kev come over here and help me fight| ollama run %MODEL% --verbose --ask "Is the player talking to Kev?"

echo.
echo === Test 2: choice - what should Kev do right now? ===
echo Kev health 14/20. Zombie 4 blocks away, approaching. Player 6 blocks away. Kev holding iron_sword.| ollama run %MODEL% --verbose --ask "What should Kev do right now?" --choice fight="Attack the nearest hostile mob" --choice flee="Run away from danger" --choice follow="Keep following the player" --choice eat="Eat food"

echo.
echo === Test 3: choice - a chat command ===
echo Steve says: kev go get me 10 wood| ollama run %MODEL% --verbose --ask "Which task is the player asking Kev to do?" --choice gather="Collect blocks or items" --choice follow="Follow the player" --choice defend="Fight mobs near the player" --choice mine="Mine underground for ores" --choice stop="Stop what Kev is doing" --choice none="Not a task, just talking"

echo.
echo === Test 4: level - how dangerous is this? ===
echo Creeper 2 blocks behind Kev, hissing. Kev health 6/20.| ollama run %MODEL% --verbose --ask "How dangerous is this for Kev?" --level Safe --level Risky --level Deadly

echo.
echo === Test 5: the HTTP endpoint the companion program would call [port 11434 is a guess] ===
set JSON=%TEMP%\kev_request.json
> "%JSON%" echo {"model":"%MODEL%","state":"Zombie 4 blocks away. Kev health 14/20.","questions":{"talking":{"type":"noul","instructions":"Is a hostile mob close to Kev?"}}}
curl -s http://127.0.0.1:11434/v1/systemone -H "Content-Type: application/json" -d @"%JSON%"
echo.
del "%JSON%" >nul 2>nul

echo.
echo === Loaded models and how much of each is on the GPU ===
ollama ps

echo.
echo Done. Check the "eval duration" / "total duration" lines from --verbose: Kev should answer in well under a second.
pause
