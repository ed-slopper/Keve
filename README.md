https://discord.gg/Ad4FXvBSWQ


# Keve

**Steve + Kev:** an AI companion that plays Minecraft *with* you, running entirely on your own PC.

You type in chat, "keve get 10 wood", "keve mine for diamonds", "keve follow me", "keve defend me", and a second player in your world does it and answers back. Later it will come exploring with you and decide for itself when to fight, mine or help, partly copying what you do.

> **Status: v0, playable.** Keve joins your world and handles chat orders: follow, come, stay, stop, gather wood/dirt/sand/gravel/stone (and bring it to you), give, defend, status and help. Deep mining, crafting and its own free will are next (see [docs/PLAN.md](docs/PLAN.md)).

## Play with Keve (Windows)

**You need:**
- [Horizon](https://playhorizon.dev/download), installed with its launcher and played once.
- Python 3.11 or newer.
- [Ollama](https://ollama.com) (optional). With it, Keve understands orders however you word them, and chats back. Without it, Keve still follows the plain orders.

**Double-click `Keve.bat`.** It does the rest:
1. Finds your name from the Horizon launcher.
2. Starts Ollama, and offers to download the two models if they're missing: Kev-4B (2.5 GB) and Gemma 4 12B (7.6 GB).
3. **The first time only**, sets up an offline-mode Horizon server in `%LOCALAPPDATA%\Keve\server`. You accept Minecraft's EULA there yourself, and you can pick one of your worlds to copy in (the original isn't touched).
4. Starts the server in its own window, then starts your Horizon, which joins it by itself.
5. Starts Keve's game (headless: no window, no GPU) and brings it into the world.
6. Runs Keve's brain. Press Ctrl+C in that window to stop Keve; it then asks whether to stop the server too.

Then type **`keve help`** in chat. All the orders are in [COMMANDS.md](COMMANDS.md).

Options: `Keve.bat --no-game` (your Horizon is already open), `--no-llm` (no Ollama), `--owner NAME`, `--port N`.

**A new world:** `Keve.bat --new-world 2024` swaps the server's world for a new one from seed 2024, which starts in a forest (oak and birch). Without a seed it's random. The old world is kept as `world-backup-<date>` in `%LOCALAPPDATA%\Keve\server`. To bring a backup back, stop the server, then rename that folder to `world`.

**Why a server and not Open to LAN?** When you're signed in with a Microsoft account, a LAN world runs in online mode, and Horizon refuses Keve at login, because Keve has no account. The offline-mode server lets both of you in. Offline mode means anyone who can reach the port can join under any name, so keep it on your own PC or LAN; don't forward the port.

`start_server.bat` and `start_keve.bat` still exist, to run the pieces one at a time. If you play offline in the launcher, you can also use Open to LAN with `start_keve.bat 127.0.0.1:PORT`.

**Known limits:**
- Walking uses Horizon's built-in `goto`, which climbs only 1 block and never digs or bridges. Cliffs and big holes stop it.
- Mining stone needs a pickaxe in its inventory.
- Handing items over uses only stacks on Keve's hotbar.

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
