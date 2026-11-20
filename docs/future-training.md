# Future training

Ideas for training Keve more deeply with Horizon's source and server tools, saved for when
there's more usage to spend. Ask Claude to "do the future training note" to pick these up.

## How the source has been used so far (debugging only)

- **Junk throwing:** read the item-throw code to find out why junk bounced back to him.
  Throws keep a 2-second pickup delay and start from his eye height, which led to the
  "throw into a pit" fix.
- **Control commands:** found the ones needed in `horizon-ctl`: jump, place, mouse (holding
  the shield up), and connect/disconnect (rejoining when he's dead with no respawn screen).
- **Server limits:** found the 32,768-block cap on reading blocks, which shaped the water
  search.
- **Blaze AI** (started): `horizon-client/src/mobs/nether.rs`, `BlazeAttackGoal`. Blazes only
  shoot what they can see. Each volley is 3 fireballs after a 3-second charge, followed by a
  5-second rest. While they see the target they hover where they are, and they only close in
  to melee within 2 blocks. This led to the "stand by the spawner, shield up, hit what comes
  in reach" tactic.

## Still to do

1. **Read the rest of the Nether mob AI:** wither skeleton and ghast. Their exact attack
   ranges, fireball timing and when they lose sight of him would let his tactics be designed
   properly instead of guessed from death logs.
   - Snowballs deal 3 damage to blazes (`creatures.rs`, `Snowball.onHitEntity`), so cheap
     snowballs would be a real ranged weapon for the blaze stage.
2. **Build practice arenas:** use server commands (fill, setblock, summon) to set up a
   walled-in blaze spawner or a few wither skeletons. Then he could practise fighting without
   the deadly walk across the cavern every time.
3. **Add better tools to Horizon itself:** for example, a control command for combat that
   blocks and attacks properly, instead of approximating it from Python. So far Keve has been
   kept to his own fair-play rules and Horizon hasn't been changed.

One limit: the game can't be sped up. His client runs at 20 ticks a second.

## Known gaps this would help with

- Crossing the open Nether cavern to the fortress: blazes at the spawner have line of sight
  and burn him on the bridge he builds. Training uses a teleport assist for this walk for now.
- Fights at the fortress: wither skeletons plus blazes beat him even with a diamond sword,
  a diamond chestplate and the shield.

## Where training stopped (2026-11-19, about 18:30)

Later the same day, grinding on (deaths keep items in training): all 6 blaze rods (about 5
hours of dying and retrying at the spawner), then the ender pearl stage: about 3 hours hunting
endermen in the overworld at night, 0 pearls. Endermen are sparse, he keeps ending up in caves
where they're out of sight, and at night with no armour he's mobbed and dies within seconds.
Next for pearls: stay on open surface ground at night, armour that lasts, or another source
(piglin bartering with gold, or endermen in a warped forest). Then eyes of ender, bow and
arrows, stronghold and the dragon, none of which have run yet.

## Earlier stop (2026-11-19, about 08:00)

Done in training: stone tools, food, iron, iron gear, diamonds (diamond pickaxe and sword),
armor (diamond chestplate), obsidian, nether portal (built, lit, through). In the Nether he
found a fortress and its blaze spawner at (46, 63, -50) and got 1 of the 6 blaze rods.

Stopped there because the spawner area is crowded (two wither skeletons, about seven blazes,
skeletons, magma cubes): he dies within about 20 seconds every time, even with the shield,
falling back and Easy difficulty. More of the same costs usage without getting further. The
next step is items 1–3 above: wither skeleton AI, a practice arena, better combat commands.

Training-only helpers (in Claude's scratchpad, not the repo): runloop.sh restarts Keve when
he's dead with no death screen (exit code 75); assist.sh teleported him from the portal to
the spawner; watch.sh wakes on loops, stalls, deaths and not moving for 4 minutes.
