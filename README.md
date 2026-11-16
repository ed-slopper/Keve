https://discord.gg/Ad4FXvBSWQ


# Keve

**Steve + Kev:** an AI companion that plays Minecraft *with* you, running entirely on your own PC.

You type in chat, "keve get 10 wood", "keve mine for diamonds", "keve follow me", "keve defend me", and a second player in your world does it and answers back. Later it will come exploring with you and decide for itself when to fight, mine or help, partly copying what you do.

> **Status: v0, playable.** Keve joins your world and handles chat orders: come, follow, stay, stop, status, jump, "get N wood/dirt/sand/gravel/stone" and defend. Deep mining, crafting and its own free will are next (see [docs/PLAN.md](docs/PLAN.md)).

## Play with Keve (v0, Windows)

**You need:**
- [Horizon](https://playhorizon.dev/download), installed with its launcher.
- Python 3.11 or newer.
- [Ollama](https://ollama.com) with these models:

```bash
ollama pull hf.co/turintech/Kev-4B-Artemis-GGUF:Q4_K_M
```
```bash
ollama pull huihui_ai/gemma-4-abliterated:12b
```

Gemma is only used for chat replies. Kev understands orders worded in unusual ways. Without Ollama, Keve still follows the plain orders.

**Steps:**
1. Start Horizon and open a world. Then press Esc, choose **Open to LAN** and **Start LAN World**, and note the port that appears in chat.
2. Run `start_keve.bat`. Type the port when asked, or pass it directly with your name: `start_keve.bat 127.0.0.1:PORT YourName`. Keve's game runs headless (no window, no GPU) and joins your world as the player "Keve".
3. Type in chat:

| You type | Keve does |
| --- | --- |
| `keve follow me` / `keve come here` / `keve stay` / `keve stop` | Follows you / walks to you / waits / stops |
| `keve get 10 wood`, `keve grab 5 dirt`, `keve collect sand` | Looks around, walks to what it can *see*, mines it, picks it up |
| `keve defend me` | Kills hostile mobs it can see within 12 blocks of you |
| `keve what you got` | Says its health, food and items |
| anything else with "keve" in it | Answers in chat (Gemma) |

**Signed in with a Microsoft account? Use the server instead of LAN.**
- When you're signed in, Open to LAN runs your world in online mode, and Horizon refuses Keve at login ("not signed in"), because Keve has no account.
- Run `start_server.bat` instead. It sets up an offline-mode Horizon server in `%LOCALAPPDATA%\Keve\server`, and you accept Minecraft's EULA there yourself.
- Join it in Horizon with Multiplayer → Direct Connection → `127.0.0.1`.
- Then run `start_keve.bat 127.0.0.1:25565 YourName`.
- **To play an existing world:** pass its folder the first time, e.g. `start_server.bat "%APPDATA%\horizon\saves\New World"`. It's copied; the original isn't touched.
- Offline mode means anyone who can reach the port can join under any name. Keep it on your own PC or LAN.

**Fair play:** Keve only knows the blocks and mobs it can see (ray cast from its eyes, in its field of view), and only sends whitelisted commands (`companion/ctl.py`). One exception for now: it always knows where you are, as the locator bar shows teammates.

**Known limits in v0:**
- Walking uses Horizon's built-in `goto`, which climbs only 1 block and never digs or bridges. Cliffs and big holes stop it.
- Mining stone needs a pickaxe in its inventory.
- `defend` hasn't been tested against real mobs yet.

## How it works

- **Game:** [Horizon](https://github.com/horizon-rust/horizon), a from-scratch Rust rewrite of Minecraft Java Edition 26.3. Keve is a real second player in your world: a headless Horizon client, which uses no GPU. It is driven through Horizon's built-in agent control socket (`horizon-ctl`). It uses the game's real physics, so there is none of the rubber-banding of protocol bots such as Mineflayer.
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
