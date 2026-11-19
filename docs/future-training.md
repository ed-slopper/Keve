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
