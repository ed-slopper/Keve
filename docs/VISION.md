# AI companion for Horizon: plan

**Goal:** an AI friend who is a real second player in your world. They talk with you in chat (and later by voice), decide what to do on their own, and can mine, build, fight and follow you. They run on local models through Ollama on a 12 GB GPU (e.g. an RTX 3060).

## 1. What went wrong with Mineflayer and Baritone

| Tool | What it is | Why it felt glitchy |
| --- | --- | --- |
| **Mineflayer** | A JavaScript client at the protocol level, with its own physics port (`prismarine-physics`) and a pathfinder plugin | Its physics is a re-port that drifts from the real game, so the server pulls the bot back (rubber-banding) and it gets stuck on stairs, slabs, water and ladders. Version support lags behind new releases. Pathing, digging and combat are separate plugins that fight over the controls. |
| **Baritone** | An A* pathfinder in a client mod, with "processes" (mine, follow, farm, build, explore) | The pathing is good, but it is a mod for the Java client: it needs Forge or Fabric, a version-matched build and a second Java client running. It has no brain, and stopping, starting and chaining processes from outside (chat or the API) is fragile. |
| **LLM agents** (Voyager, Mindcraft) | An LLM writes or calls Mineflayer actions | They inherit all of Mineflayer's problems. They also make the LLM decide every small step, which is slow (seconds per step) and goes off track. |

**The lesson:** the body has to use the game's real physics, the reflexes have to be fast deterministic code, and the LLM should only decide *what* to do, never *how* to move.

## 1b. How "Kevin" in the video works (from the transcript)

The video is a Halo 1 PC port, not Minecraft. The design carries over directly:

| Kevin's part | What it is | What it does in the video | Minecraft / Horizon version |
| --- | --- | --- | --- |
| **"Nervous system"** | **Kev**, a small, fast *classifier* model the creator calls "a spin-off of the Jev model". I couldn't find Jev or Kev publicly; it's probably his own. | Runs first on *every* event (speech or something in the game). Fires an instant reaction (jump, crouch, stand up, hold fire, fire) with no LLM call, then decides whether the brain needs to think. | **Phase 2.5** below: an intent and reflex classifier in Rust, under 50 ms |
| **"Brain"** | **Gemma 4 12B**, uncensored, run locally | Talks, keeps the mission and recent events in mind, holds a persona, chooses tactics, can refuse ("he can also just not jump"), fights back if betrayed | Same model, e.g. `huihui_ai/gemma-4-abliterated:12b` in Ollama |
| **Ears** | **Parakeet** for speech to text, *plus game audio* fed in as well | Hears you and the game's own NPC voice lines and radio | Parakeet (NVIDIA, runs locally). Minecraft's sounds go in as **subtitle events** ("Zombie groans, left"), which Horizon already has |
| **Voice** | **"Breeze TTS 2"** (as he said it; I couldn't find it either). Local, expressive, can shout and whisper | Shouts in combat, whispers when told, has a radio when far away | A local expressive TTS (e.g. Kokoro, Chatterbox, Orpheus) with volume and style tags, positioned at the companion's head; a radio filter past ~32 blocks |
| **Eyes** | A vision model turning what it sees into coordinates | "Stand by that rock", "go near those bodies" | Gemma 4 is multimodal, so send it the bot seat's screenshot. In Minecraft it's often simpler to resolve "that" from **your crosshair** (`looking-at` on your seat) or from entity and block lookups |
| **"Console / MK Ultra"** | Typed text injected into his context | Changing the persona live ("you're a cat now") | A `/kevin <text>` client command that adds a system note to the brain's context |
| **Orders** | Standing orders kept in his state | "Hold fire until I say", "wait here" | Rules of engagement (`hold_fire`, `stay`, `follow`, `guard`) stored by the reflex layer, so they take effect without the LLM |

## 1c. The video's exact stack, and what fits a 12 GB RTX 3060

These are from the video description. "Resident GPU" is the memory each part keeps on the GPU while running, from each model card.

| Part | Video uses | Resident GPU (from the card) | Notes |
| --- | --- | --- | --- |
| Game | [OpenCE](https://github.com/OpenCommunityEdition/OpenCE), a Halo CE decompilation port (AGPL) | — | Not related to Minecraft. Its README mentions a telnet console, but no bot API, so the creator probably drove the game through it. Horizon's ctl socket plays that role. |
| Nervous system | [Kev-4B](https://huggingface.co/jaredpalmer/kev-4b) (Qwen3.5-4B + LoRA + pointer head, Apache-2.0) | **~14.3 GB** in bf16, "about 16 GB free" | English only. Served at `POST /v1/systemone` |
| Brain | [Gemma 4 12B](https://huggingface.co/google/gemma-4-12B) (Apache-2.0, 256K context, text, image, video and audio in) | ~24 GB in bf16, **~7.6 GB at Q4** (your Ollama copy) | Its image input works as the companion's eyes |
| Ears | [Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0, English) | ~2 GB | NeMo. Very fast; also runs well on the CPU |
| Voice | [Breeze-TTS-2](https://huggingface.co/BreezeBlue/Breeze-TTS-2) (3B, voice cloning, "voice direction", `(laugh)`-style tags, streaming) | **~7.7 GB** (14.4 GB in fast mode) | **The weights are for research and non-commercial use only.** Linux only (use WSL2 on Windows). |

**Total for the video's stack: about 32 GB of GPU memory.** The creator must have a 24 to 32 GB card or more than one GPU. On a 3060 it won't all fit at once, so pick one of these setups:

- **A. Everything on the 3060 (recommended to start).** About 11 GB in total.
  - **Kev-0.8B** instead of the 4B, ~2 to 3 GB.
  - **Gemma 4 12B at Q4** in Ollama, ~7.6 GB.
  - **Parakeet on the CPU**, through sherpa-onnx or NeMo.
  - **A light TTS on the CPU,** e.g. Kokoro-82M. Use Breeze only if you accept its non-commercial licence and have room for it.
- **B. Video quality, with two machines.** The 3060 runs Horizon, Kev-0.8B and Gemma. A second PC (or a rented GPU) runs Breeze-TTS-2 and Parakeet over the LAN. All the brain's model calls are HTTP anyway.
- **C. Fewer models:** Gemma 4 takes audio input itself (up to 30 s clips), so it could replace Parakeet. That is slower, though, because every utterance becomes a full LLM call. Keep Parakeet for speed.

Check the real numbers on your machine with `nvidia-smi` once everything is loaded. Also leave headroom for Horizon itself (1 to 2 GB).

The plan below is that design, mapped onto Horizon.

## 2. Why Horizon already has most of it

What is already in `horizon-src`:

- **A real second player in your world: splitscreen seats** (`crates/horizon-client/src/game/split.rs`).
  - Each extra seat is a full `Game` in the same process that joins *your* integrated server through memory. There is no network or physics re-port, so nothing to rubber-band.
  - It is a real player that the game, mobs and other players all treat as one.
  - Each seat answers `horizon-ctl` on your control socket's path with the seat number added ("2").
- **The agent control API** (`game/agent.rs`, `game/control.rs`, `docs/horizon-ctl-commands.md`), about 150 commands over a socket or MCP:
  - Observe: `state`, `inventory`, `entities`, `events --since`, `find-block`, `blocks`, `looking-at`.
  - Move: `goto` (with pathfinding), `look-at`, `jump`, `stop`.
  - Act: `break`, `place`, `use-item`, `attack`, `hunt` (chase, kill, collect drops), `collect`, `interact-entity`, `click-slot`, `container`, `chat`.
  - `wait-for event KIND`, so the brain can sleep until something happens.
- **The game's real physics for bots** (`game/native_bots.rs`): `native_simulate_player_move` and `native_collision_boxes`.
- **A port of vanilla's mob A\*** (`mobs/path.rs`, `mobs/nav.rs`) to use as a reference.
- **The narrator** (text to speech) and **chat hooks** (`native_client_chat_received`, `native_send_chat`).

**What is weak today:** `goto` uses `agent_navigation.rs`, a simple A\*. It only moves in 4 directions, steps up 1 block or drops up to 3, caps the search at 30,000 nodes, and never breaks or places blocks. This is the piece that needs Baritone-level work.

## 3. Architecture

```
 ┌──────────────── horizon-client process ─────────────────┐
 │  You (seat 1)        Companion (seat 2, "bot seat")      │
 │      │                    │  real Game, no window          │
 │      └── integrated server (same world, same physics) ──┘ │
 │                           ▲                               │
 │        Skills / reflexes (Rust, 20 Hz, in agent.rs)       │
 │        follow · mine · gather · craft · smelt · fight ·   │
 │        guard · eat · flee · build · deposit · goto+       │
 └───────────────────────────┬───────────────────────────────┘
                             │ horizon-ctl socket ("…2"), JSON lines
 ┌───────────────────────────▼───────────────────────────────┐
 │  horizon-companion (new Rust binary, the "brain")         │
 │   event loop ─ observation builder ─ LLM (Ollama, local)  │
 │   memory (places, chests, goals, facts about you)         │
 │   personality profile · optional STT/TTS                  │
 └───────────────────────────────────────────────────────────┘
```

There are three layers, each with its own speed:

1. **Body:** a real player, simulated by the game itself.
2. **Reflexes and skills (milliseconds):** deterministic Rust running inside the game tick. It does the pathing, digging, combat targeting, eating when hungry and escaping lava. It never waits on the LLM.
3. **Brain (about 0.5 to 3 s):** a local LLM, called only on *events*: you said something, a skill finished or failed, the companion took damage, or it has been idle for a while. It answers with a short reply to say and one skill call, as JSON.

## 4. Phases

### Phase 0: prototype with no engine changes (1 to 2 days)
- Run the brain against a second **`horizon-client --headless`** that joins your world over LAN. On your side: `lan open`. The second client logs in with an offline-mode account name such as "Kev".
- Write `horizon-companion` as a loop:
  1. Poll `events --since` and `messages`.
  2. On a chat that mentions the companion's name (or any chat), build an observation and call Ollama `/api/chat` with `format: json` and the skill list as tools.
  3. Run the returned ctl command, then send the `chat` reply.
- Skills at this point are the existing commands only: `goto`, `hunt`, `collect`, `break`, `find-block`, `give` and `chat`.
- **Done when:** you type "come here", "kill that cow" or "get me some wood" and the companion does it in a couple of seconds.

### Phase 1: bot seat in the same process (about 1 week)
- Add a **headless seat type** to `split.rs`: a seat with no view, no compositor slot and no input routing, that only answers the ctl socket. Keep a tiny offscreen render for screenshots and vision as an option.
- Add a way to start it: Horizon Settings > AI Companion > "Invite companion", plus `HORIZON_COMPANION=1` and a ctl command `companion spawn NAME [SKIN]`.
- The companion's skin, name tag and player list entry use the existing hooks: `native_set_name_tag`, `native_set_display_name`.
- **Why this matters:** you don't need LAN or a second process, it uses less RAM, there's no network lag, and it works in any single-player world.

### Phase 2: a Baritone-grade pathfinder (2 to 4 weeks, the biggest piece)
Replace `agent_navigation::find_path` with a `nav` module that has:
- **Moves:** 8 directions, diagonal corner checks, step up, jump up, falls with a damage-cost cutoff, water-bucket landings (later), swimming, ladders and vines, doors, fence gates and trapdoors, sprint jumps and parkour gaps, avoiding magma, campfires, cactus and powder snow.
- **Breaking and placing while pathing:** cost = break time from the held tool (the game's dig speed), pillar up, bridge across gaps, dig down in steps, a "don't break" list (chests, your builds, anything inside a protected area).
- **Costs in ticks** (as Baritone does), so A\* finds the *fastest* route, not the shortest.
- **Plan in segments:** plan about 64 blocks, start walking, plan the next part in the background on `horizon-threads`, and re-plan when a block changes on the route.
- **Following:** steer the movement keys with `native_simulate_player_move` so the bot's inputs match its physics. Stuck detection, then a re-plan or a short jump.
- **Goal types:** a block, XZ, Y, near an entity (follow), any block of a kind (`find-block` plus nearest), "inside a box".
- **Tests:** add a harness like the others in `tools/parity.py`: scripted scenes (a staircase, a ravine, a pillar up a cliff, a flooded cave) with a pass or fail on arrival time.

### Phase 3: a skill library (2 to 3 weeks, alongside Phase 2)
New ctl commands in `agent.rs`, each a small state machine that ticks at 20 Hz, can be stopped, and reports `skill_done` or `skill_failed{reason}` in `events`:

| Skill | What it does |
| --- | --- |
| `follow PLAYER [--dist N]` | Keep 2 to 4 blocks behind, teleport if more than 64 away (optional) |
| `mine BLOCK COUNT` | `find-block`, then path, pick the best tool, break, collect, repeat. Branch-mines when nothing of the kind is loaded |
| `gather wood\|food\|stone COUNT` | Wraps `mine` and `hunt` |
| `craft ITEM [COUNT]` | Works out the recipe tree from the recipe data, makes the sub-ingredients, places and uses a crafting table when needed |
| `smelt ITEM COUNT` | Finds or places a furnace, adds fuel, waits, collects |
| `deposit [chest]` / `fetch ITEM` | Uses the memory of chests |
| `guard PLAYER` / `fight` | Attacks hostiles within a radius, switches to the best weapon, uses the attack cooldown, shields |
| `build SCHEMATIC X Y Z` | Places blocks in order, gathers what's missing (later; Baritone-style) |
| `farm`, `sleep`, `explore`, `goto-surface` | Smaller ones |

**Reflexes** run underneath any skill, with priority:
- Eat when food is 14 or less.
- Get out of lava or fire.
- Swim up when air is low.
- Fight back when hit.
- Back away from a creeper that is about to explode.

These never wait for the brain; the brain only hears about them as events.

### Phase 2.5: the "nervous system", Kev-style (1 to 2 weeks)
Every input goes through this layer first: a speech transcript, a chat line, or a game event (hit, mob in sight, subtitle heard, item low, player died).
- **The model: Kev itself**, as in the video. Kev is Jared Palmer's open-weight copy of TypeSafe's closed **Jev** "decision model", Apache-2.0, at https://github.com/jaredpalmer/kev.
  - **What it does:** it doesn't generate text. You give it a text *state* plus a list of questions, and it answers them all in one pass.
  - **Question types:** `noul` (yes/no, returns P(yes)), `choice` (pick one option from a list, with probabilities) and `score` (a graded rating).
  - **Sizes:** 0.8B, 4B, 9B and 27B, all LoRA plus a small "pointer head" on Qwen bases. **Superseded:** use Kev-4B Q4_K_M (TurinTech GGUF) instead of Kev-0.8B; see [PLAN.md](PLAN.md), section 2b.
  - **Speed:** about 18 to 40 ms for six questions with the 4B on server GPUs. Expect it to be similar or faster with the 0.8B on yours.
  - **How to run it:** `uv run --extra serve python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009`, a local HTTP server that the brain calls.
  - **Each event becomes one Kev call:**
    - `choice` "what reflex now?" with the options [none, jump, crouch, stand, stop, follow, stay, attack, hold_fire, retreat, look_at_speaker, ...].
    - `noul` "is the player talking to the companion?"
    - `noul` "does this need careful thinking?" (the escalate-to-brain flag).
    - `score` "how threatening is this?"
  - **Fallback** while it's being set up: hand-written keyword rules.
- **Its output:** `{intent, slots, reflex_action, bark, needs_brain}`. For example:
  - "kevin jump": `{jump, reflex=jump, bark="THERE. SATISFIED?", needs_brain=false}`.
  - "can you stand by that tree": `{goto_target, needs_brain=true}`.
  - Took 6 damage from a zombie: `{under_attack, reflex=fight_back, bark=random_combat_line, needs_brain=maybe}`.
- **Intents** (about 30 to start): jump, crouch, stand, stop, come, follow, stay or wait, hold fire, open fire or attack, retreat, look, give item, quiet or whisper, louder, greet, insult, question, task request, persona instruction, plus game events.
- **Order of work:** carry out the reflex at once (straight on the ctl socket, as a running skill), play a short pre-written or cached bark through TTS, then hand the event to the brain *in parallel* when `needs_brain`. The brain's spoken reply arrives a second later, which feels like the reaction in the video.
- **Learning data:** log every (input, final brain decision) pair. Later the brain's choices relabel the classifier, so more decisions become instant over time.
- **Free will, cheaply:** the brain may answer `refuse` or `delay`, and the nervous system holds back reflexes for orders the persona would plausibly refuse. Only *physical* safety reflexes (lava, drowning) always run.

### Phase 4: brain quality (ongoing)
- **Observation**, kept short (500 tokens or less):
  - Position, biome and time.
  - Health, food and armor.
  - The top inventory items.
  - About 8 nearby entities with their distances.
  - The last 10 chat lines.
  - The current skill and its progress, and the last 5 events.
  - Relevant memories.
- **Output:** strict JSON: `{"say": "...", "action": {"skill": "mine", "args": {...}} | null, "remember": "..."}`. Use Ollama's JSON schema `format`, so the model can't produce invalid output.
- **Speed:**
  - Keep the model loaded (`keep_alive: -1`) and reuse the prompt cache with a fixed system prompt first.
  - Stream: start the `say` part as soon as it arrives.
  - A small 3 to 4B model is enough for chat-only replies; save the 12B for planning.
  - A **rule router** handles obvious commands ("stop", "follow me", "come here") without calling the LLM at all.
- **Memory:** a JSON or SQLite file per world, holding named places ("home", "the mine"), chest contents, goals in progress and facts about you. Retrieve memories by keyword.
- **Long goals:** "help me build a house": the LLM writes a short task list, and the brain works through it one skill at a time, re-asking the LLM only when a skill fails.
- **Personality:** a profile file (name, tone, what it likes doing, how bold it is, voice), as Mindcraft's profiles do. The video uses an uncensored model because a censored one refuses to swear or fight back; an abliterated Gemma covers that.
- **Context the brain always has:** the current "mission" (the goal you set, or one it set itself), what happened recently (deaths, fights, finds), its standing orders, and its relationship with you. If you hit it, it remembers that and may hit back.
- **Console injection:** `/kevin <text>` adds a system-level note ("you are a cat now"), and `/kevin reset` clears it.
- **Initiative:** an idle timer (30 to 60 s) lets it suggest or start things on its own: "I'm gonna go grab some coal".

### Phase 5: voice, ears and eyes, like the video (1 to 2 weeks)
- **Speech to text:** **Parakeet**, as in the video: NVIDIA Parakeet TDT 0.6B, which is fast and accurate. Run it through ONNX or sherpa-onnx. Use voice activity detection plus push-to-talk or a mute key. Use the companion's name as a wake word, or just listen all the time.
- **Text to speech:** a local expressive model that can do volume and emotion (shout, whisper). Play it through Horizon's audio as a positional sound at the companion's head. Past ~32 blocks, switch to a "radio" (band-pass filter, crackle, not positional), as Kevin's radio does.
- **Hearing the game:** turn every subtitle event (`G/subtitle_hud.rs`: sound, direction, distance) and every chat or system message into "heard" events for the nervous system, as Kevin hears the in-game voice lines.
- **Eyes:**
  1. Resolve "that / over there" from *your* crosshair target and look direction (the `looking-at` and `state` commands on your seat).
  2. Use the game's own world queries (`find-block`, `entities`) for "the tree", "the cow".
  3. Only for open questions ("what do you see?", "describe that build"), send a screenshot from the bot seat to Gemma 4's vision input. Gemma 4 12B is multimodal, so this needs no extra model.
- **GPU memory budget:** see section 1c. On a 12 GB card, use setup A (Kev-0.8B, Gemma Q4, Parakeet and TTS on the CPU) or setup B (Breeze on a second machine).

## 5. Where the code goes

| New or changed | Path |
| --- | --- |
| Headless bot seat | `crates/horizon-client/src/game/split.rs` (+ `companion.rs`) |
| Pathfinder v2 | `crates/horizon-client/src/game/nav/` (replaces `agent_navigation.rs`) |
| Skills and reflexes | `crates/horizon-client/src/game/agent_skills/` (one file per skill), registered in the ctl command table (`bin/horizon-ctl/commands.rs`) so they become MCP tools and docs too |
| Brain | `crates/horizon-companion/` (new binary: tokio, reqwest to Ollama, serde; speaks the ctl JSON-line protocol) |
| Settings UI | Horizon Settings > AI Companion (`agent_settings.rs` is next to it) |
| Tests | Unit tests for the planner, a `tools/test_companion_nav_parity.py` scene harness, a mocked-LLM brain test |

Respect `noAi` (`horizon-core/src/no_ai.rs`): when the player has turned AI off, the companion must not start.

## 6. Risks and open questions
- **Seat cost:** a full `Game` per seat. Measure the RAM with `horizon-ctl memory`. If it's heavy, a lighter "bot body" that only keeps the server-side player and a small chunk view could replace it later.
- **Multiplayer servers:** a seat only joins *your* world. To bring the companion onto a public server, use Phase 0's second headless client. Many servers ban bots, so make it opt-in only.
- **Model size:** a 12B model on a 3060 answers in about 1 to 2 s for a short JSON reply. That's fine for event-driven decisions, too slow per tick, which is why the reflexes and skills are in Rust.
- **Upstream:** Horizon is LGPL-3.0 with an active team. If you want this merged upstream rather than kept in a fork, open an issue or discussion first, because seats, agent control and `noAi` are areas they own.

## 7. First concrete steps
1. Build Horizon (`docs/native-client.md#run-from-a-checkout`) and get `horizon-ctl state` working against a world.
2. Try a second `--headless` client over LAN with `horizon-ctl` on its socket, and drive it by hand: `goto`, `hunt`, `chat`.
3. Write the roughly 300-line `horizon-companion` loop (Phase 0) against Ollama, with a keyword-rule "nervous system" in front of it from day one, so "jump", "stop" and "come here" are instant.
4. Then go deep on Phase 2, the pathfinder. It decides whether the companion feels smart or glitchy.
