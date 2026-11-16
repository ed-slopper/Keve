# Talking to Keve

Type in normal chat (no `/`). Start with **keve** (or **kev**). Keve also listens for about 20 seconds after it last spoke, so a quick follow-up doesn't need its name.

In game, type **`keve help`** for this list. Typing `/help keve` won't work: commands starting with `/` go straight to the server, and Keve can't see them.

## Moving

| You type | Keve does |
| --- | --- |
| `keve follow me` | Follows you, stays 3 to 4 blocks behind and eats when hungry |
| `keve come here` | Walks or sprints to where you are |
| `keve stay` / `keve wait here` | Stops and waits |
| `keve stop` | Stops whatever it's doing |
| `keve look at me` | Turns to face you |
| `keve jump` | Jumps |

## Getting things

| You type | Keve does |
| --- | --- |
| `keve get 10 wood` / `keve chop some trees` | Looks around, walks to trees it can see, chops the logs and picks them up |
| `keve grab 5 dirt`, `keve collect sand`, `keve get 8 gravel` | The same for dirt, sand and gravel |
| `keve mine 20 stone` | Cobblestone (needs a pickaxe in its inventory) |
| `... and bring them to me` | When it's done, walks to you and drops them at you. Works with any of the above, e.g. `keve mine 10 sand and drop them to me` |
| `keve give me your sand` / `keve give me everything` | Hands over what it's carrying |

Numbers can be words: "a few", "some", "ten", "a stack". With no number it gets 10.

## Fighting

| You type | Keve does |
| --- | --- |
| `keve defend me` / `keve protect me` / `keve guard` | Fights hostile mobs it can see within 12 blocks of you (best weapon first, waits for the attack cooldown), then comes back to you |

## Other

| You type | Keve does |
| --- | --- |
| `keve what you got` / `keve status` | Says its health, food and what it's carrying |
| `keve help` | Posts this list in chat |
| anything else with "keve" in it | Answers in chat (Gemma), in character |

## How it decides

1. **Rules** (instant) catch the orders above.
2. If the rules don't match, **Kev** (the decision model, about 0.1 s) works out which order you meant, even when it's worded differently. For example, "kev can you go cut down a tree" is gather wood.
3. If it's not an order, **Gemma** writes a reply.

## Fair play

- **Sight:** Keve only knows the blocks and mobs a player in its body could see: ray casts from its eyes, in its field of view. It has to turn its head to look around.
- **Hearing:** mobs are noisy, so it notices hostiles all around it, but walls still block its view of them.
- **Its own drops:** it remembers where it just mined, so it can pick up drops that fell into its own holes.
- **Reach:** it can't mine or hit anything out of reach or behind a block.
- **Commands:** it can't send `/` commands, or any command that isn't on its whitelist (`companion/ctl.py`).
- **Where you are:** Keve always knows where you are, as the locator bar shows teammates.
