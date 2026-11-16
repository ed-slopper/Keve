# Talking to Keve

Type in normal chat (no `/`). Start with **keve** (or **kev**). Keve also listens for about 20 seconds after it last spoke, so a quick follow-up doesn't need its name.

**Or say it out loud**: every order below works by voice ("Keve, mine for diamonds"), and Keve says its replies aloud. Voice setup is in the README.

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
| `keve mine 20 stone` | Cobblestone. It makes itself a pickaxe first if it has none |
| `... and bring them to me` | When it's done, walks to you and drops them at you. Works with any of the above, e.g. `keve mine 10 sand and drop them to me` |
| `keve bring me the sand` / `keve give me your logs` / `keve bring them to me` | Hands over what it **already has**: the named item, or whatever it gathered last |
| `keve give me everything` | Hands over its whole inventory |
| `keve bring me 5 sand` / `keve bring me some sand` | With an amount, it gets new ones first, then brings them |

Numbers can be words: "a few", "some", "ten", "a stack". With no number it gets 10. Ask for something it can't get yet ("get me diamonds") and it says so, instead of guessing.

## Mining

| You type | Keve does |
| --- | --- |
| `keve mine for diamonds` / `keve get me 3 diamonds` | Goes all the way: makes its tools, digs a staircase down to y -58, takes the iron it sees on the way, smelts it into an iron pickaxe, branch-mines and comes back up |
| `keve get me 10 iron` / `keve go mine some coal` / `keve find gold` | The same for iron (y 16), coal, copper, lapis, gold, redstone and emerald |
| `keve go mining` | Iron, by default |
| `... and bring them to me` | Hands over what it found when it's back |

How it mines:
- **Tools:** it gets wood, makes a wooden pickaxe, digs for stone, makes a stone pickaxe, and later an iron one from iron it mined and smelted itself. A worn-out pickaxe gets replaced on the spot.
- **Staircase down:** never straight down. After every block it breaks, it looks into the hole. It plugs lava and water with cobblestone and goes around them, and turns away from drops.
- **Branch mining:** at the ore's level it digs 1x2 tunnels in a back-and-forth pattern. It only takes ores it can **see** (tunnel walls and caves), then follows the vein.
- **Stopping:** when it has enough, after 20 minutes, when it's hurt or its inventory is full, or when you say `stop`. Then it walks back up its own stairs.
- **On the way:** it places torches every 8 blocks if it has some, eats, fights what attacks it, and throws away junk stone (andesite, diorite, granite, dirt) when its inventory fills up.

## Crafting

| You type | Keve does |
| --- | --- |
| `keve make a stone pickaxe` / `keve craft an iron sword` | Wooden, stone and iron pickaxes, swords, axes and shovels |
| `keve craft 16 torches` / `keve make a furnace` / `keve make a crafting table` | Torches, furnaces, crafting tables, sticks, planks |
| `... and bring it to me` | Hands it over when it's made |

It crafts like a player: in its own 2x2 grid, or at a crafting table it puts down and then picks back up. It gathers or mines anything missing first. It smelts iron in a furnace it builds the same way.

## Places

| You type | Keve does |
| --- | --- |
| `keve this is home` / `keve set home` | Remembers where you're standing as home |
| `keve remember this as the mine` | Any name: the mine, the farm, base... |
| `keve go home` / `keve go to the mine` | Walks there |

Places are saved in `%LOCALAPPDATA%\Keve\memory.json`, so it remembers them next time.

## Playing together

| You type | Keve does |
| --- | --- |
| `keve play with me` / `keve be my buddy` / `keve do your own thing` | **Companion mode.** While you move, it keeps up. When you stop to do something, it finds something useful nearby, chosen by Kev from what it can see: ore in sight, a tree when it's low on wood, items on the ground, eating. It fights anything that goes for either of you |

When it finishes a job (handing something over, a gather, a craft, a mining trip), it crouches a few times, like players do to say "done!".

## Chests

| You type | Keve does |
| --- | --- |
| `keve craft me torches from the chest next to me` / `keve make a stone pickaxe from the stuff in the chest` | Goes to the chest by you, takes only what the recipe can use (coal, sticks, planks, logs...), and crafts. With no number, it makes as many as the chest's things allow. If the chest is short, it says what's missing instead of going off to gather |
| `keve get the coal from the chest` / `keve take 10 logs out of the chest and bring them to me` | Takes that item (or everything, if you don't name one) |
| `keve put your stuff in the chest` / `keve put the cobblestone in the chest` | Stores that item, or everything except its tools, torches and food |

"The chest" is the nearest chest or barrel within 8 blocks of you. Keve has to be able to see it when it walks up.

## Several things at once

Chain orders with **then**, **after that**, **and then** or **first … then**:

- `keve chop 10 wood then make a crafting table and then come back`
- `keve mine for iron then make an iron pickaxe then go home`
- `keve first get 5 dirt, then follow me`

Keve reads each step on its own (reflexes, then Kev, then the inventory check), says the plan back ("ok: get 10 wood, then make crafting table, then come back"), and does the steps in order. It says "all done!" at the end. If one step fails, it moves on to the next. `keve stop` cancels the rest.

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

1. **Reflexes** (instant, no model): plain `stop`, `follow me`, `come here`, `stay`, `jump`, `look at me`, `help`, the place orders (`this is home`, `go home`...) and `play with me`.
2. **Kev** reads everything else (the decision model, about 0.2 s). It's told what Keve is carrying and doing, and it picks:
   - what you want: get, get and bring, hand over, mine, craft, follow, come, stay, defend, status, companion, or just talking;
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
- **Survival:** it swims up when it's out of air, and steps out of lava or fire.
