# AI companion, first version: type in chat, it does the job (12 GB GPU)

**What this first version does:** you type in Minecraft chat, "kev get 10 wood", "kev mine for diamonds", "kev follow me", "kev defend me", and a second player in your world does it and answers in chat.
- No voice yet.
- No free will yet: it does what you tell it.
- Later phases add exploring with you on its own (see the end of this plan, and [VISION.md](VISION.md) for the long-term vision).

## 1. The setup: what runs where

```
 Your Horizon game (you play)  ── Open to LAN ──►  Companion: horizon-client --headless
   │ ctl socket (read only:                         │ (no window, no GPU, a real player "Kev")
   │  your position, what you look at)               │ ctl socket (actions)
   └──────────────┬──────────────────────────────────┘
                  ▼
        companion.exe  (new Rust program, the "brain")
          ├─ chat reader ─► command router (rules, instant)
          │                     └─► LLM (Ollama, only when the rules don't understand)
          ├─ task runner: one skill at a time, ticking ~10x a second
          └─ reflexes: eat, fight back, get out of lava (always on)
```

- **Your game stays as it is.** You open your world to LAN (`/` Pause > Open to LAN, or `horizon-ctl lan open`).
- **The companion is a second Horizon client with `--headless`.** That means no window, display or GPU, so it costs no VRAM, only some CPU and RAM. It joins your LAN world as an offline player named "Kev" (`connect 127.0.0.1:PORT Kev`). It's a real player: mobs target it, it picks things up, and it shows up in the player list.
- **`companion.exe`** talks to both games over Horizon's existing control socket (`horizon-ctl`'s JSON-line protocol):
  - **Kev's socket:** it moves, mines, attacks, reads inventory and sends chat.
  - **Your socket (read only):** your position, health and what your crosshair points at, so "come here" and "mine that" work.
- **Almost everything goes through commands that already exist:** `goto`, `break`, `place`, `hunt`, `collect`, `inventory`, `select`, `drop`, `use-item`, `click-slot`, `chat`, `messages`, `events`, `state`, `looking-at`, `look-at`. The one new Horizon command needed is `sight` (section 1d), so Kev can look around without X-ray.

## 1b. Fair play: no X-ray, no cheating, everything a real player could do

Kev may only know and do what a real survival player standing in its body could. This is enforced in code, not left to the prompt:

**What it may know (perception):**
1. **Sight: only blocks and entities with a clear line of sight from Kev's eyes, within its view cone.** That means about 110° horizontally by 70° vertically (a normal FOV and window shape) and up to the render distance. Blocks behind walls, ores inside stone, and mobs in caves below are **unknown** until it digs or walks to where it can see them.
2. **Hearing:** sounds with a direction and distance, as subtitles give them ("Zombie groans, left, ~12 blocks"). A player can hear a mob behind them; they can't see it.
3. **Chat, its own inventory, health, food and position** (what the HUD and F3 show a player).
4. **Memory:** things it *has seen before*. Remembering where the iron was or where the chest is is fair. Memories of blocks it saw are updated when it sees the spot again.
5. **What it doesn't need to see:** it may still read *your* position from your socket for follow and come. Another way to get it is "only when you're in sight or in chat range". Make that a setting (`fair_follow = sight|always`), default `sight` with a fallback to your last seen position plus the "come here" chat.

**What it must do to act:**
1. **Face it first.** Before breaking, placing, opening, attacking or using anything, it turns its head there smoothly, at a capped turn speed (e.g. ≤ 360°/s, eased: `look-at-block X Y Z --over 0.2` / `look-at-entity ID --over 0.15`). No instant snaps.
2. **Only in reach, only a visible face.** Horizon's `break` and `place` already do this:
   - `aim_block` in `crates/horizon-client/src/game/agent.rs` (around line 931) casts a real ray from the eye with `clip_ray`.
   - It refuses blocks more than reach + 0.9 away ("out of reach; goto it first").
   - It refuses blocks whose every face is hidden ("no face of block … is visible from here: stone at … is in the way").
   - Attacking an entity also refuses one that is out of reach or hidden ("that entity is out of reach or hidden", around line 1413).
   - **But** `aim_block` *snaps* the view (`self.yaw = yaw`). So `companion.exe` always calls the eased `look-at` first, and a Horizon change adds a `--turn-rate` cap to the agent (section 7).
3. **Mining and attacking take real time:** hold the attack button with the real dig speed (as `break` already does), and observe the attack cooldown before swinging.
4. **Survival mode, no cheats.** The only control commands allowed are listed in section 1c.

### 1c. The only commands Kev's brain is allowed to send

The `companion.exe` socket client has a **hard whitelist**. Anything else is refused, so a bug or the LLM can't cheat:

- **Allowed:**
  - Moving and looking: `goto`, `move`, `jump`, `look`, `turn`, `look-at` / `look-at-block` / `look-at-entity` (always with `--over`), `stop`.
  - Acting: `break`, `place`, `interact`, `use-item`, `attack`, `hunt`, `collect`, `interact-entity`.
  - Inventory and screens: `select`, `drop`, `open-inventory`, `click-slot`, `close`, `container` (only for a container in reach and in sight).
  - Talking and status: `chat` (plain text, no `/`), `respawn`, `inventory`, `state` (own player only), `events`, `messages`, `looking-at`, and the new `sight` (below).
- **Banned (they're X-ray or cheats):**
  - X-ray: `find-block`, `blocks`, `block`, and raw `entities` (it sees *every* mob through walls).
  - Cheats: `tp`, `give`, `setblock`, `fill`, `summon`, `effect`, `xp`, `enchant`, `potion`, `time`, `fly`, `creative`, `dimension`, and any chat starting with `/`.
- **`goto` and `hunt` with a target it hasn't seen are refused by the companion before they're sent.**

### 1d. New Horizon command needed: `sight` (what Kev can see right now)

This needs to be built first: it's how Kev looks around without X-ray.

```
sight [--fov 110x70] [--range 64] [--rays 96x56] [--types blocks,entities]
```

- Cast a grid of rays from the eye across the view cone, e.g. 96x56 ≈ 5,400 rays, using the existing `clip_ray` / `clip_ray_fluids` (`game/clip_ray.rs`, `game.rs:3553`). The headless client has no screen, so this stands in for one.
- **Return:**
  - Every block the rays *hit first*, deduplicated: its id, position, the face seen, the distance, and the screen direction.
  - Every entity whose box a ray reaches before a block does: type, id, position, health if shown, and whether it's hostile.
  - Fluids such as lava and water that were seen.
- **Cost:** a few milliseconds. Call it about 4 times a second, or right after the head turns.
- **Looking around:** to look behind itself, Kev **turns its head** (a 4-way look-around takes about 1 s), as a player does.
- **Building it:** about 150 lines next to `aim_block` in `agent.rs`, plus an entry in the ctl command table (`bin/horizon-ctl/commands.rs`), so it shows up as an MCP tool and in the docs.
- **Optional `hear` command:** recent sound events with a direction and rough distance, from the same data the subtitles draw.

All of Kev's "where is the nearest tree / cow / ore / zombie" questions go to a **world memory** in `companion.exe`, filled *only* from `sight` and `hear` results:
- Known blocks (sparse, per chunk) with the time they were last seen.
- Entities seen in the last 10 s, with their last positions.
- The places you've named ("home", "the mine").

## 2. Models on 12 GB

| Part | Choice | GPU memory | Why |
| --- | --- | --- | --- |
| Command understanding and chat replies | **Gemma 4 12B, Q4_K_M, in Ollama** (e.g. `huihui_ai/gemma-4-abliterated:12b`), with `num_ctx` 8192 and `keep_alive -1` | ~7.6 to 8.5 GB | Good at JSON and following instructions; fits with room for your game |
| Faster fallback, if the 12B is too slow while you play | Gemma 4 E4B or Qwen3 4B at Q4 | ~3 GB | About 3 times faster. It only has to turn a sentence into a JSON command |
| Fast "nervous system" | **Not needed for this version.** A rules router does that job instantly | 0 | Kev comes later (section 2b) |
| Your own Horizon game | — | ~1.5 to 3 GB | Lower the render distance if things get tight |

**Total:** about 10 to 11 GB with the 12B, or about 6 GB with a 4B. Check with `nvidia-smi`. If the game stutters while the model answers, switch to the 4B; command parsing doesn't need a big model.

### 2b. Which Kev to use on 12 GB (checked against the model cards)

| Option | File / memory (from the cards) | Accuracy | How it runs | Verdict |
| --- | --- | --- | --- | --- |
| [kev-4b](https://huggingface.co/jaredpalmer/kev-4b) bf16 (the video's) | 8.4 GB weights, **14.3 GB resident** | Best | `python -m kev.serve` (Python, from the repo) | Doesn't fit |
| **[Kev-4B-Artemis-GGUF](https://huggingface.co/turintech/Kev-4B-Artemis-GGUF) Q4_K_M** (TurinTech) | **2.54 GB file.** 7.6 GiB peak *at their test settings* (`-c 16384 -ub 4096`, very large batch buffers) | **93 % same answers as the full 4B.** Same accuracy on their test (66.8 %), no confident answer changed | **Stock llama.cpp `llama-server` (b11540+)**, which serves `/v1/systemone` directly. The card says Ollama and LM Studio run it too | **Use this one** |
| Kev-4B Artemis IQ3_M / Q3_K_M | 2.17 / 2.04 GB | 90 % / 89 % agreement | Same | A fallback if memory is tight |
| [kev-0.8b](https://huggingface.co/jaredpalmer/kev-0.8b) (official) | **3.8 GB resident** (bf16, Python server) | **Much worse:** 0.586 on the breadth test (Jev 0.757). Its card says "markedly less accurate than Kev-4B" outside its training domain, and that **tool-call routing is below chance** | `python -m kev.serve` | Skip it: it's bigger in memory than the 4B Q4 file, and weaker |
| kev-0.5b | — | Its card says it's a v0.1 prototype; use 0.8B or bigger | — | Skip |
| kev-0.6b | Not in the official Kev collection; I couldn't find it | — | — | Probably doesn't exist |

Caveats: the agreement numbers are TurinTech's own, measured on the same test set they used to choose the quantization, so they flatter it a little. The 0.8b's lower accuracy comes from its own card. I haven't run any of these yet.

**Run Kev-4B Q4 with a small context**, because Kev's inputs are short game snapshots:

```bash
llama-server -m Kev-4B-Artemis-Q4_K_M.gguf --port 8080 -c 4096 -ub 512 -b 2048 -ngl 99
```

Expect roughly **3.5 to 4.5 GB** this way. That's my estimate: 2.5 GB of weights plus a smaller KV cache and buffers. Measure it with `nvidia-smi`.

**Memory plans by phase** (12 GB, your Horizon game included; Kev's headless client uses no GPU):

| Phase | Brain | Nervous system | Game | About |
| --- | --- | --- | --- | --- |
| Chat commands (steps 1 to 6) | Gemma 4 12B Q4, ~8 GB | rules only | ~2 GB | ~10 GB |
| Companion mode (section 8) | **Gemma 4 E4B / Qwen3 4B Q4, ~3 to 4 GB** | **Kev-4B Q4, ~4 GB** | ~2 GB | ~10 GB |
| If you want to keep the 12B brain together with Kev | Gemma 12B Q4 with a 4k context, a few layers on the CPU (slower answers) | Kev-4B IQ3_M | ~2 GB | ~11.5 GB, tight |

The brain can afford to be smaller once Kev makes the second-by-second choices, because it's then only called for talking and planning.

**How the LLM is used (it only does two things):**
1. **Turn a message into a task**, when the rules can't. It returns strict JSON through Ollama's `format` JSON schema, so it can't produce invalid output. For example:
   `{"say":"on it, getting wood","task":{"skill":"gather","item":"log","count":10}}`.
   "Mine for diamonds and grab whatever iron you see" becomes
   `{"skill":"mine_ores","targets":["diamond_ore","iron_ore"],"until":{"diamond":5}}`.
2. **Write chat replies with personality** ("ugh fine, 10 logs coming up"), plus answers to questions ("how many diamonds do you have?").

It is **never** used to steer movement or decide clicks. That's what made the Mindcraft and Voyager-style bots slow and erratic.

## 3. The skills (what it can actually do)

Each skill is a small state machine in `companion.exe` that issues ctl commands. Every skill:
- can be stopped at any time (`kev stop`);
- reports progress ("7/10 logs");
- has a timeout and a clear failure reason ("no trees within 64 blocks").

| # | Skill | Chat examples | How it works with the commands that exist |
| --- | --- | --- | --- |
| 1 | **come** | "kev come here", "kev tp" | Your position from your socket, then `goto X Y Z --near 2 --sprint` |
| 2 | **follow** | "kev follow me" | Every 0.5 s: if you're more than 4 blocks away, `goto` near you. If you're more than 48 away, run `/tp` when cheats are on, otherwise sprint. Re-plan when stuck |
| 3 | **stay / stop** | "kev wait here", "kev stop" | `stop`, then stand there. "stay" also stops following |
| 4 | **gather (blocks)** | "get 10 wood", "collect 32 cobble", "get sand" | Map the word to block ids (wood is any `*_log`). Loop: look for it in **world memory**. If it's not there, *explore*: turn around with `sight`, then walk towards open ground or the treeline and look again. `goto` until it's in reach, `look-at-block --over 0.2`, pick the best tool (`select`), `break`, then `collect 4`, until `inventory` shows the count. For a tree, mine the visible logs from the bottom up, stepping back to see the higher ones |
| 5 | **mine_ores** | "go mine deep for diamonds", "find iron" | See section 4. The biggest skill |
| 6 | **hunt (items from mobs)** | "get me some leather / food", "kill 3 cows" | Seen animals from memory (or explore until `sight` finds one), then `look-at-entity --over 0.15` and `hunt ID`, and `collect` |
| 7 | **defend / guard** | "defend me", "guard this spot" | Every 0.25 s: `sight`, plus `hear` for mobs behind it: hostile mobs it *sees* within 12 blocks of you (or the spot). A heard but unseen hostile sound makes it **turn towards** the sound, and it attacks once it sees the mob. Equip the best weapon, face the mob, `hunt ID`, then go back next to you |
| 8 | **give** | "give me the diamonds", "give me everything" | `goto` you, `look-at` you, `select` the item, `drop all` |
| 9 | **craft basics** | Automatic, inside other skills; also "make a pickaxe" | A small hand-written recipe list: planks, sticks, crafting table, wooden/stone/iron pickaxes and swords, torches, furnace. Uses the 2x2 inventory grid or a placed table, through `open-inventory` / `container` plus `click-slot` |
| 10 | **status** | "kev what you got", "kev hp?" | `inventory` and `state`, summed up in chat, with no LLM needed |

**Reflexes** run every tick whatever the current skill is, and pause it while they work:
- Eat when food is 14 or less (`select` food, `use-item --hold 1.7`).
- Fight back when hurt by a mob (`events` hurt → `hunt` the attacker).
- Back away from lava or fire under its feet.
- Swim up when underwater for more than 5 s.
- Say "I died, at X Y Z" and come back to you after respawning (`respawn`).

## 4. Mining for diamonds (the hard part, done step by step)

Horizon's `goto` path planner (`agent_navigation.rs`) only *walks*: it never breaks or places blocks. So deep mining needs its own skill that digs on purpose instead of pathfinding through caves:

1. **Get gear first:** make sure there's a stone or iron pickaxe; if not, run gather wood → craft → gather cobble → craft. Bring torches if there's coal.
2. **Staircase down, without X-ray:** dig a 1x2 staircase, one step down per block forward, until Y = −58, the best diamond level in 26.3. Like a real player, it **can't know what's behind a block until it breaks it**. So after every break it runs `sight` on the newly opened hole and the floor of the next step:
   - **Lava or flowing water seen:** stop digging, `place` cobble or dirt into the gap (a visible face in reach), step back, and turn 90°.
   - **Air or a cave seen below the next step** (looking down shows the drop): don't step. Bridge it, or turn.
   - **Gravel or sand above** (seen as the ceiling block): stand back while it falls, or mine it from the side.
3. **Branch mine:** a 1x2 tunnel straight ahead, with side tunnels every 3 blocks, 16 blocks long. **Ore is only found when a face of it becomes visible:** as the tunnel opens, `sight` sees the walls, floor and ceiling of the tunnel and of any cave it breaks into. When it sees an ore it wants, it faces it and mines it, then follows the vein. Each newly exposed ore face is seen after a break, so the vein is followed only as far as it can actually see. Breaking into a cave counts too: it may mine the ore it can see on the cave walls, within reach and by walking there.
4. **Safety rules:** never dig straight up or straight down (the classic player rule). Retreat if health is 8 or less and there are hostiles in sight or heard. Place a torch every 8 blocks once it has some (so it can see; light doesn't change raycasts, but keep it fair: optionally treat very dark blocks beyond about 6 blocks as unseen).
5. **Finish:** when the target is reached, or the pickaxe is about to break, or the inventory is full, say so in chat ("got 6 diamonds, 20 iron, heading back"). Walk back up the staircase (the path is remembered), then come to you or wait.

## 5. How a chat message is handled

1. Kev's `events --since` / `messages` gives a new chat line from *your* name. Ignore its own lines and other players unless they're allowed.
2. **Wake word:** the line starts with "kev" (or whatever the companion is called), or it's a reply within 30 s of Kev speaking.
3. **Rules router** (regex and keywords, under 1 ms):
   - stop, come, follow, stay, defend, status, give, and "get/collect/mine N X".
   - If it matches, start that skill and reply with a short canned line.
4. **Otherwise, the LLM:**
   - It gets a short prompt (≤ 600 tokens): persona, skill list with arguments, inventory summary, current task, last 6 chat lines.
   - It returns JSON `{say, task|null}`.
   - Say the `say` text right away, then start the task.
   - If a task needs things it doesn't have (diamonds need an iron pickaxe), the skill itself plans the prerequisites; the LLM doesn't have to.
5. A **new order replaces the current task** ("kev stop, defend me"). "after that ..." puts it in a queue.

## 6. Build order (each step is usable on its own)

| Step | What | Done when | Rough time |
| --- | --- | --- | --- |
| 0 | Build Horizon. Open your world to LAN. Start `horizon-client --headless --control` and `connect` it as Kev. Drive it by hand with `horizon-ctl` | `horizon-ctl goto` and `break` work on Kev while you watch from your game | half a day |
| 0.5 | Add the **`sight`** command (and optionally **`hear`**) to Horizon's agent. Build the world memory and the command whitelist in `companion.exe` | `sight` lists the tree in front of Kev but not the one behind a hill, and not the ores inside the stone it's facing | 1 to 2 days |
| 1 | `companion.exe` skeleton: two socket connections, chat polling, the rules router, skills **come, follow, stay, stop, status** | Typing "kev follow me" works, and it keeps up over hills | 1 to 2 days |
| 2 | **gather** (wood, stone, dirt, sand...) + **give** + reflexes (eat, fight back) | "kev get 10 wood" brings back 10 logs | 2 to 3 days |
| 3 | **defend / guard** + **hunt** | Zombies near you at night get killed, and it comes back to you afterwards | 2 days |
| 4 | Ollama hookup for free-form messages + persona replies | "yo kev can you grab me some sand and then come back" works | 1 to 2 days |
| 5 | **craft basics** + **mine_ores** (staircase, branch mine, ore scan, safety) | "kev mine for diamonds" comes back with diamonds in a fresh survival world | 1 to 2 weeks |
| 6 | Polish: stuck detection (no movement for 3 s means jump, re-plan, or break the block in front), memory of home and chests, `kev come` across long distances | It survives an hour of play without needing to be rescued | ongoing |

Write it in **Rust** (tokio + serde_json + reqwest to Ollama) to match Horizon. It can go in your fork as `crates/horizon-companion`, or stay outside Horizon as its own project, since it only talks to the socket. Keep it outside at first, so Horizon updates never break your build.

## 7. Engine work in Horizon you'll want soon after (not needed on day 1)
- **A fair-play agent mode** (`--agent-fair`, or a socket flag): this enforces the rules of section 1b *in the game*, not just in `companion.exe`.
  - A turn-rate cap on every aim (`aim_block` and the entity aim, which snap the view today).
  - The X-ray and cheat commands refused.
  - `goto` planning only through cells the agent has seen (unknown cells assumed walkable, re-planned when they turn out solid), instead of reading the whole loaded world.
- **A better `goto`:** the current planner moves in 4 directions only, steps up 1 or down 3, stops at 30,000 nodes, and never digs, bridges or pillars. Breaking and placing while pathing is what makes follow and gather robust in hilly or cave terrain. That's the Baritone-style upgrade in [VISION.md](VISION.md), Phase 2.
- **A `craft ITEM N` ctl command** that uses the recipe book, instead of clicking slots by hand.
- **A headless splitscreen "bot seat"** inside your own game process, so you don't need a LAN or a second process (Phase 1 of the big plan).

## 8. Later: exploring with you on its own

Once the commands above are solid, the same skills become the companion's *own* choices:
- **Companion mode:** no task means it follows you and keeps an eye on the world every second (cheap rules, no LLM):
  - A hostile mob within 10 blocks of either of you: fight it.
  - You started mining: mine the blocks next to yours.
  - Low food: hunt.
  - It sees exposed ore within 8 blocks: grab it, then come back.
- **Mirroring:** read your recent actions (your socket's `events` and `input-log`: mining, fighting, building) and lean towards helping with the same thing.
- **Its own will:** every 30 to 60 s, or on interesting events, a short LLM call. It gets the situation and its personality, and returns `{say, intent: keep_following | suggest | go_do(task) | refuse}`. For example: "I'm grabbing that iron, back in a sec".
- **A fast decision model:** add **Kev-4B Q4_K_M** (`llama-server` on port 8080, `/v1/systemone`, about 4 GB) for the every-second choices. That is the nervous system from the video. Each tick, it gets one short snapshot of what Kev can see and hear, with questions such as:
  - `choice`: "what now?" [keep_following, fight_nearest, flee, mine_seen_ore, eat, help_player_mine, idle].
  - `noul`: "is the player talking to me?"
  - `noul`: "does this need the brain?"

  See section 2b for why it's not the 0.8b. Voice (Parakeet + a small TTS) can come after that.
