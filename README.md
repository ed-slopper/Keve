https://discord.gg/Ad4FXvBSWQ


# Keve

**Steve + Kev:** an AI companion that plays Minecraft *with* you, running entirely on your own PC.

You type in chat, "keve get 10 wood", "keve mine for diamonds", "keve follow me", "keve defend me", and a second player in your world does it and answers back. Later it will come exploring with you and decide for itself when to fight, mine or help, partly copying what you do.

> **Status: playable.** Keve joins your world and takes chat orders. It follows and defends you, gathers, hands things over, crafts tools, smelts, mines (all the way to diamonds), remembers places, has a companion mode where it acts on its own, and you can **talk to it out loud**. It picks its models to fit your graphics card. A better path planner is next (see [docs/PLAN.md](docs/PLAN.md)).

## Play with Keve (Windows)

**You need:**
- [Horizon](https://playhorizon.dev/download), installed with its launcher and played once.
- Python 3.11 or newer.
- [Ollama](https://ollama.com) (optional). With it, Keve understands orders however you word them, and chats back. Without it, Keve still follows the plain orders.

**Double-click `Keve.bat`.** It does the rest:
1. Finds your name from the Horizon launcher.
2. Measures your graphics card and picks a profile from [profiles.json](profiles.json) (see **Graphics cards** below).
3. Starts Ollama, and offers to download that profile's models if they're missing.
4. **The first time only**, sets up an offline-mode Horizon server in `%LOCALAPPDATA%\Keve\server`. You accept Minecraft's EULA there yourself, and you can pick one of your worlds to copy in (the original isn't touched).
5. Starts the server in its own window, then starts your Horizon, which joins it by itself.
6. Starts Keve's game (no window, about 300 MB of GPU memory) and brings it into the world.
7. Runs Keve's brain, and starts listening and talking. Press Ctrl+C in that window to stop Keve; it then asks whether to stop the server too.

Then type **`keve help`** in chat. All the orders are in [COMMANDS.md](COMMANDS.md).

Options: `Keve.bat --no-game` (your Horizon is already open), `--no-llm` (no Ollama), `--no-voice`, `--setup-voice`, `--profile NAME`, `--owner NAME`, `--port N`.

## Talking to Keve

Say it out loud: **"Keve, follow me"**, **"Keve, get me ten wood and bring it to me"**, **"Keve, mine for diamonds"**. Every order in [COMMANDS.md](COMMANDS.md) works by voice too, and Keve says out loud what it says in chat. Start with "Keve". For about 20 seconds after Keve speaks, you can answer without its name.

| | Built in (no download) | Better (`Keve.bat --setup-voice`) |
| --- | --- | --- |
| **Ears** | Windows speech recognition, with a grammar of Keve's orders: it hears orders well, free chat less so | [faster-whisper](https://github.com/SYSTRAN/faster-whisper), any sentence, on the CPU or GPU (the model size depends on your profile) |
| **Voice** | Windows' own voice (Microsoft David) | [Kokoro-82M](https://github.com/thewh1teagle/kokoro-onnx), a natural voice on the CPU (about 120 MB) |

- **Setup:** `--setup-voice` asks before each pip install and download. Anything that's missing falls back to the built-in option, so voice always works on Windows.
- **Your mic:** it uses Windows' default recording device; set that in Sound settings.
- **No echo:** Keve ignores the mic while it's talking, so it doesn't hear itself through your speakers.
- **Mishearings:** "Kevin", "Kev" and "Diva" all count as "Keve".
- **What it heard** shows in Keve's window as `[heard] ...`.

## Graphics cards

Keve picks a setup by your graphics card's memory (VRAM). About 3 GB is kept for your own Horizon and Keve's game. Force one with `Keve.bat --profile 8gb`, or edit [profiles.json](profiles.json).

| Profile | Kev (understands orders) | Brain (chats) | Ears | Voice |
| --- | --- | --- | --- | --- |
| cpu (none or under 4 GB) | Kev-0.8B Q6_K, on the CPU | Qwen3 1.7B, on the CPU | Windows | Windows |
| 4gb | Kev-0.8B Q6_K | Qwen3 1.7B | Windows | Windows |
| 6gb | Kev-4B IQ3_M | Qwen3 1.7B | Whisper base.en (CPU) | Windows |
| 8gb | Kev-4B Q4_K_M | Qwen3 4B | Whisper small.en (CPU) | Kokoro |
| 10gb | Kev-4B Q4_K_M | Qwen3 8B | Whisper small.en (CPU) | Kokoro |
| 12gb (RTX 3060) | Kev-4B Q4_K_M | Gemma 4 12B (abliterated) | Whisper small.en (CPU) | Kokoro |
| 16gb | Kev-4B Q4_K_M | Gemma 4 12B (abliterated), longer memory | Whisper small.en (GPU) | Kokoro |
| 20gb | Kev-9B IQ4_XS | Gemma 4 12B (abliterated) | Whisper medium.en (GPU) | Kokoro |
| 24gb (3090/4090) | Kev-9B IQ4_XS | Gemma 4 12B, 16k memory | Whisper large-v3-turbo (GPU) | Kokoro |
| 32gb (5090) | Kev-9B IQ4_XS | Gemma 4 26B (MoE) | Whisper large-v3-turbo (GPU) | Kokoro |
| 48gb | Kev-27B IQ4_XS | Gemma 4 31B | Whisper large-v3-turbo (GPU) | Kokoro |
| 64gb | Kev-27B Q4_K_S | Gemma 4 31B, 32k memory | Whisper large-v3 (GPU) | Kokoro |
| 96gb | Kev-27B Q4_K_S | Gemma 4 31B, 64k memory | Whisper large-v3 (GPU) | Kokoro |
| 128gb | Kev-27B Q4_K_S | Gemma 4 31B, 128k memory | Whisper large-v3 (GPU) | Kokoro |

- **Companion mode** also asks Kev what to do more often on bigger cards: every 10 s on the CPU, every second at 96 GB and up.
- **Above 64 GB** there's no bigger model in these families that fits, so 96 and 128 GB run the 64 GB models with longer memory. Qwen3 235B, for one, is 142 GB.
- **Model names** were checked on Ollama and Hugging Face in November 2026: TurinTech's Kev-0.8B/4B/9B/27B GGUFs, `gemma4` e2b/e4b/12b/26b/31b and `qwen3`.
- **Smaller Kev models are less accurate.** Kev-0.8B's model card says it routes tool calls below chance. On small cards, the keyword rules still catch the plain orders.
- **Whisper on the GPU** needs NVIDIA's CUDA libraries. Without them it quietly runs on the CPU.

**A new world:** `Keve.bat --new-world 2024` swaps the server's world for a new one from seed 2024, which starts in a forest (oak and birch). Without a seed it's random. The old world is kept as `world-backup-<date>` in `%LOCALAPPDATA%\Keve\server`. To bring a backup back, stop the server, then rename that folder to `world`.

**Why a server and not Open to LAN?** When you're signed in with a Microsoft account, a LAN world runs in online mode, and Horizon refuses Keve at login, because Keve has no account. The offline-mode server lets both of you in. Offline mode means anyone who can reach the port can join under any name, so keep it on your own PC or LAN; don't forward the port.

`start_server.bat` and `start_keve.bat` still exist, to run the pieces one at a time. If you play offline in the launcher, you can also use Open to LAN with `start_keve.bat 127.0.0.1:PORT`.

**GPU memory:** Keve's game runs `--offscreen` (no window, small and with a short render distance), using about 300 MB of GPU memory. It needs a renderer because crafting tables and furnaces are menus, and menu clicks only work with one.

**Known limits:**
- Walking uses Horizon's built-in `goto`, which climbs only 1 block and never digs or bridges. Cliffs and big holes stop it.
- Mining is slow: about 8 seconds a stair step, so reaching diamond level takes 10 to 15 minutes.
- Keve only finds ores it can see, so a trip can come back empty.

## How it works

- **Game:** [Horizon](https://github.com/horizon-rust/horizon), a from-scratch Rust rewrite of Minecraft Java Edition 26.3. Keve is a real second player in your world: a windowless (offscreen) Horizon client. It is driven through Horizon's built-in agent control socket (`horizon-ctl`). It uses the game's real physics, so there is none of the rubber-banding of protocol bots such as Mineflayer.
- **Three layers:**
  1. **Skills and reflexes** (Rust, deterministic): follow, gather, mine, hunt, defend, give, craft; eat, fight back, get out of lava.
  2. **Nervous system:** [Kev](https://github.com/jaredpalmer/kev), a fast decision model (Kev-4B, Q4_K_M GGUF, through Ollama or llama.cpp) that makes the instant, second-by-second choices.
  3. **Brain:** a local LLM (Gemma 4 through Ollama) for chat, personality and planning. It is never used for moving or clicking.
- **Fair play:** no X-ray, no cheats. Keve only knows what it can see by ray-casting from its own eyes in its own field of view, plus what it hears and remembers. It has to turn to face anything it mines, places or attacks, within normal reach, and mining takes real time. The commands it may send are on a hard whitelist.
- **Fits in 12 GB of VRAM** (e.g. an RTX 3060), with the game running.

Inspired by "Giving Video Game NPC's Consciousness" (a Halo CE companion made with Kev, Gemma 4 12B, Parakeet and Breeze-TTS-2).

## Docs

- [docs/PLAN.md](docs/PLAN.md): **the plan to build first.** Chat commands, the skill list, mining for diamonds without X-ray, fair-play rules, the new `sight` command for Horizon, and models and memory for 12 GB.
- [docs/VISION.md](docs/VISION.md): the long-term vision. A splitscreen-style bot seat inside the game, a Baritone-grade pathfinder, the Kev nervous system, voice (speech to text and text to speech), and vision.

## Try the decision model

[`tools/test_kev.bat`](tools/test_kev.bat) (Windows, needs [Ollama](https://ollama.com)) does three things:
1. Downloads `hf.co/turintech/Kev-4B-Artemis-GGUF:Q4_K_M` (about 2.5 GB).
2. Runs a few Minecraft-style decisions, timed: is the player talking to Keve? fight, flee or follow? which task is this?
3. Shows how much GPU memory it uses.

## Credits

- [Horizon](https://github.com/horizon-rust/horizon) (LGPL-3.0)
- [Kev](https://github.com/jaredpalmer/kev) by Jared Palmer (Apache-2.0)
- [TurinTech's Kev-4B GGUF](https://huggingface.co/turintech/Kev-4B-Artemis-GGUF)
- Gemma 4 by Google

Not an official Minecraft product. Not approved by or associated with Mojang or Microsoft.
