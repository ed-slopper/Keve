# Talking to Keve

Type in normal chat (no `/`). Start with **keve** (or **kev**). Keve also listens for about 20 seconds after it last spoke, so a quick follow-up doesn't need its name.

**Or say it out loud**: every order below works by voice ("Keve, mine for diamonds"), and Keve says its replies aloud. Voice setup is in the README.

In game, type **`keve help`** for this list. Typing `/help keve` won't work: commands starting with `/` go straight to the server, and Keve can't see them.

## Moving

| You type | Keve does |
| --- | --- |
| `keve follow me` | Follows you, 3 to 4 blocks behind (swimming across water too), eats when hungry, and **fights mobs it sees going for you** |
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

## Any block, any animal

Keve knows every block and item in the game by name. It reads the game's own registry, tags and English names from your Horizon install, so you can point at anything.

| You type | Keve does |
| --- | --- |
| `keve mine this coal` / `keve break that glass` / `keve dig this dirt` / `keve chop that birch log` | Breaks the nearest one by you that it can see, with the right tool, and picks up the drop. If the block needs a better pickaxe, it makes one first (stone for iron, iron for diamonds) |
| `keve get me 10 andesite` / `keve break 5 glass` | Any block, as many as you say, nearest first |
| `keve open that door` / `keve pull the lever` / `keve press the button` / `keve close the trapdoor` | Walks up and uses it |
| `keve place a crafting table` / `keve put down a furnace` | Puts that item down next to you (it has to be carrying it) |
| `keve what do you see` / `keve what's around` | Turns around and says what stands out: ores, chests, logs, water, lava, doors, beds, animals, mobs... |
| `keve kill this cow` / `keve kill 3 pigs` / `keve attack that creeper` | Kills the nearest one it can see, by you first |
| `keve kill the zombies` | All of them in sight (up to 5) |
| `keve get me some leather` / `keve get me 5 beef` / `keve get some wool` | Hunts the animal that drops it (3 by default) and brings you the drops |

- **"this" and "that"** mean the nearest one by you. If Keve can't see it from where it is, it walks over to you, then looks around.
- **Mining trips:** "mine this coal" is that one block; "mine 10 iron" or "mine for diamonds" is still a mining trip.
- **Kev's view:** it's told what Keve can see right now ("coal ore, 3 blocks away", "cow, 5 blocks away"), so "that" makes sense to it too.

## Planting

| You type | Keve does |
| --- | --- |
| `keve plant the sapling` / `keve plant 3 oak saplings` | Plants on grass or dirt next to you, with room above to grow, not right against another sapling |
| `keve plant the seeds` / `keve plant the carrots` | On farmland |

No sapling on hand: Keve breaks nearby leaves until one drops, then plants it.

## Torches

| You type | Keve does |
| --- | --- |
| `keve place torches in this room` / `keve light up this cave` / `keve put some torches down` | Lights up the room you're standing in |

How it lights a room:
- **What counts as the room:** the space you could walk to from where you stand, inside walls, within about 9 blocks.
- **Where the torches go:** on the floor where they light the most dark spots, until every spot reaches the light level, then it checks again and fills what's still dark.
- **What it uses:** torches it carries. If it has none, it makes some from coal and sticks.
- **Your style:** if you've taught it (below), it lights to your level and spaces torches like you do.

## Teaching Keve (watch me)

1. Say `keve watch me place torches`. Anything works after "watch me": `keve watch me build a wall`, `keve watch me dig a doorway`.
2. Do it. Keve stays near you and watches.
3. Say `ok did u see` (or `did you see`, `got it?`, `that's it`). You don't need to say "keve" during a lesson.

Keve then says what it saw, e.g. "got it! you placed 3 torch about 6 blocks apart, where it was darker than light 7, 0% on walls. saved as 'place torches'".

| Afterwards you type | Keve does |
| --- | --- |
| `keve place torches` | Lights the room your way: your light level and your spacing |
| `keve copy what i did` / `keve do it like i showed you` | Repeats your last lesson. Torches light the room you're in; a build is placed the same way around where you stand now |
| `keve place torches` (the lesson's name) | A saved lesson's name works as an order too |

**Fair:** Keve only learns what it saw happen, close enough to have been you.

**Training data:** every lesson is appended to `%LOCALAPPDATA%\Keve\training\demos.jsonl`, one JSON object per line. Each holds:
- what you called it;
- every block you placed or broke: its type, position and position relative to you, the light level before, and floor or wall;
- the path you walked.

These lessons are the dataset for teaching Keve's models later (see the README).

**Known limits:**
- A build is copied facing the same direction as when you showed it; it isn't turned to match where you face now.
- Keve needs the same blocks in its inventory to copy a build.

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
2. **The translator** (Gemma, about 1 second): rewrites whatever you said into Keve's own command wording, then the tested rules run it. It:
   - fixes voice mishearings ("plan a sapling" → plant, "Kevin"/"Diva" → keve);
   - understands slang ("chuck me some logs" → get 10 wood and bring it to me);
   - splits several orders ("grab wood, make a table, then come find me" → three steps, in order);
   - works out "that" and "those" from what Keve carries and can see;
   - tells chatting and teasing from orders, and orders from talking to someone else.

   Every translation is in the session log, so a wrong one is easy to spot. `Keve.bat --no-translate` turns it off.
3. **Kev** (the decision model, about 0.2 s): the fallback when the translator isn't running or can't say. It's told what Keve is carrying, doing and seeing, and picks the task and the item.
4. **A check against the inventory:** if you ask for items Keve doesn't have, or more than it has, it gets the rest first, then brings them.
5. If it's not an order, **Gemma** writes a reply in character.

Without Ollama, the keyword rules do all of this on their own.

## Fair play

- **Sight:** Keve only knows the blocks and mobs a player in its body could see: ray casts from its eyes, in its field of view. It has to turn its head to look around.
- **Hearing:** mobs are noisy, so it notices hostiles all around it, but walls still block its view of them.
- **Its own drops:** it remembers where it just mined, so it can pick up drops that fell into its own holes.
- **Reach:** it can't mine or hit anything out of reach or behind a block.
- **Commands:** it can't send `/` commands, or any command that isn't on its whitelist (`companion/ctl.py`).
- **Where you are:** Keve always knows where you are, as the locator bar shows teammates.
- **Survival:** it swims up when it's out of air, and steps out of lava or fire.
