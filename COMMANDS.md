# Talking to Keve

Type in normal chat (no `/`). Start with **keve** (or **kev**). Keve also listens for about 20 seconds after it last spoke, so a quick follow-up doesn't need its name.

In game, type **`keve help`** for this list. Typing `/help keve` won't work: commands starting with `/` go straight to the server, and Keve can't see them.

## Moving

| You type | Keve does |
| --- | --- |
| `keve follow me` | Follows you, 3 to 4 blocks behind, eats when hungry, and **fights mobs it sees going for you** |
| `keve come here` | Walks or sprints to where you are |
| `keve stay` / `keve wait here` | Stops and waits (still hits back at mobs right next to it) |
| `keve stop` | Stops whatever it's doing. Between orders it stands by and fights back |
| `keve look at me` | Turns to face you |
| `keve jump` | Jumps |

## Getting things

| You type | Keve does |
| --- | --- |
| `keve get 10 wood` / `keve chop some trees` | Looks around, walks to trees it can see, chops the logs and picks them up |
| `keve grab 5 dirt`, `keve collect sand`, `keve get 8 gravel` | The same for dirt, sand and gravel |
| `keve get some sugar cane`, `keve get 3 pumpkins`, `keve get clay` | Sugar cane, pumpkins and clay too |
| `keve mine 20 stone` | Cobblestone (needs a pickaxe in its inventory) |
| `... and bring them to me` | When it's done, walks to you and drops them at you. Works with any of the above, e.g. `keve mine 10 sand and drop them to me` |
| `keve bring me the sand` / `keve give me your logs` / `keve bring them to me` | Hands over what it **already has**: the named item, or whatever it gathered last |
| `keve give me everything` | Hands over its whole inventory |
| `keve bring me 5 sand` / `keve bring me some sand` | With an amount, it gets new ones first, then brings them |

Numbers can be words: "a few", "some", "ten", "a stack". With no number it gets 10. Ask for something it can't get yet ("get me diamonds") and it says so, instead of guessing.

## Fighting

| You type | Keve does |
| --- | --- |
| `keve defend me` / `keve protect me` / `keve guard` | Fights hostile mobs it can see within 12 blocks of you, or right next to itself, then comes back to you |

Keve uses the best weapon it has, and swings on the weapon's real cooldown. **Barehanded it does 1 damage a hit, so a zombie takes it about 20 seconds; give it a sword.**

## Other

| You type | Keve does |
| --- | --- |
| `keve what you got` / `keve status` | Says its health, food and what it's carrying |
| `keve help` | Posts this list in chat |
| anything else with "keve" in it | Answers in chat (Gemma), in character |

## How it decides

1. **Reflexes** (instant, no model): plain `stop`, `follow me`, `come here`, `stay`, `jump`, `look at me` and `help`.
2. **Kev** reads everything else (the decision model, about 0.2 s). It's told what Keve is carrying and doing, and it picks:
   - what you want: get, get and bring, hand over, follow, come, stay, defend, status, or just talking;
   - which item you mean.
   So "give me 10 sand" with empty pockets means "go get 10 sand, then bring it". "bring me the sand" while carrying sand means "hand it over". "cut down some trees for me" is wood.
3. **A check against the inventory** catches the rest. If you ask for items Keve doesn't have, or more than it has, it gets the rest first, then brings them.
4. If it's not an order, **Gemma** writes a reply.

Without Ollama, the keyword rules do steps 1 and 2.

## Fair play

- **Sight:** Keve only knows the blocks and mobs a player in its body could see: ray casts from its eyes, in its field of view. It has to turn its head to look around.
- **Hearing:** mobs are noisy, so it notices hostiles all around it, but walls still block its view of them.
- **Its own drops:** it remembers where it just mined, so it can pick up drops that fell into its own holes.
- **Reach:** it can't mine or hit anything out of reach or behind a block.
- **Commands:** it can't send `/` commands, or any command that isn't on its whitelist (`companion/ctl.py`).
- **Where you are:** Keve always knows where you are, as the locator bar shows teammates.
