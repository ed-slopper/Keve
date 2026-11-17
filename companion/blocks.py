"""Any block, by name: break it, use it, place it, or say what's around.

    "keve mine this coal"          -> the coal ore nearest you that Keve can see
    "keve break that glass"        -> the same, with the right tool (or bare hands)
    "keve get me 10 andesite"      -> ten of them, nearest first
    "keve open that door" / "pull the lever" / "press the button"
    "keve place a crafting table"  -> next to you
    "keve what do you see"         -> the notable things in sight

Names come from the game's own registry (world_names.py), so every block works.
Fair as always: a block has to be in Keve's sight before it's touched.
"""
import math
import time

import sight
import world_names
from skills import AXES, PICKAXES, Task, base

SHOVELS = ["netherite_shovel", "diamond_shovel", "iron_shovel", "stone_shovel", "golden_shovel",
           "wooden_shovel"]
HOES = ["netherite_hoe", "diamond_hoe", "iron_hoe", "stone_hoe", "golden_hoe", "wooden_hoe"]
TOOLS = {"pickaxe": PICKAXES, "axe": AXES, "shovel": SHOVELS, "hoe": HOES}
NOTABLE = ("ore", "chest", "barrel", "crafting_table", "furnace", "log", "water", "lava", "door",
           "bed", "spawner", "portal", "anvil", "enchanting", "brewing", "sugar_cane", "pumpkin",
           "melon", "wheat", "carrots", "potatoes", "beehive", "bee_nest", "torch", "lantern",
           "amethyst", "obsidian", "glowstone", "mushroom", "flower", "sapling", "rail")


def nearest_visible(ctx, ids, around, radius=10, need_fov=False):
    """The nearest block of `ids` to `around` that Keve can see from where it stands."""
    eye, yaw, pitch, _ = ctx.eye_and_view()
    snap = sight.Snapshot.read(ctx.senses, around, rh=radius, rv=min(radius, 6))
    found = [p for p, n in snap.blocks.items() if base(n) in ids]
    found.sort(key=lambda p: math.dist(p, around))
    for p in found[:40]:
        if (not need_fov or sight.in_fov(eye, yaw, pitch, (p[0] + .5, p[1] + .5, p[2] + .5))) \
                and snap.block_visible(eye, p, 24.0):
            return p
    return None


def find_target(ctx, task, ids, near_owner):
    """'this X' is by you: look from where Keve is, then walk over to you and look again,
    then turn around once. None when it's nowhere in sight."""
    o = ctx.owner()
    around = o[1] if (near_owner and o) else ctx.eye_and_view()[3]
    p = nearest_visible(ctx, ids, around)
    if p is None and o and near_owner and math.dist(ctx.eye_and_view()[3], o[1]) > 3:
        ctx.body.call(f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} --near 2.5 --timeout 10")
        if task.done():
            return None
        p = nearest_visible(ctx, ids, around)
    if p is None:
        ctx.look_around(lambda n: base(n) in ids)
        p = nearest_visible(ctx, ids, around)
    return p


def walk_to_reach(ctx, p):
    if math.dist(ctx.eye_and_view()[0], (p[0] + .5, p[1] + .5, p[2] + .5)) > 4.3:
        ctx.body.call(f"goto {p[0] + 0.5:.1f} {p[1]:.1f} {p[2] + 0.5:.1f} --near 2.8 --timeout 15")


class BreakBlocks(Task):
    """Break (mine, dig, chop) blocks of a kind and pick up what drops."""
    name = "break"

    def run(self):
        ctx = self.ctx
        ids = set(self.args["ids"])
        label = self.args.get("label", "block")
        want = int(self.args.get("count", 1))
        near_owner = self.args.get("near_owner", True)
        names = world_names.names()
        sample = next(iter(ids))
        tool, tier = names.tool_for(sample) if names else (None, 0)
        # The right tool: make one if it needs a pickaxe Keve doesn't have.
        if tool == "pickaxe":
            import mining
            prov = mining.Provision(ctx, self)
            if prov.pick_tier() < tier or prov.pick_tier() < 0:
                ctx.say(f"I need a better pickaxe for {label}, making one.")
                if not prov.ensure_pickaxe(max(tier, 0)):
                    if not self.done():
                        ctx.say(f"I can't make the pickaxe {label} needs yet.")
                    return
        done = 0
        endless = self.args.get("endless")
        explores = 0
        while done < want and not self.done():
            if endless and self.guard(owner_radius=8.0, self_radius=5.0):
                continue  # help with the fight, then back to it
            p = find_target(ctx, self, ids, near_owner)
            if p is None and endless and explores < 300:
                explores += 1  # none in sight: wander a bit and look again
                import random
                pos = ctx.eye_and_view()[3]
                ang = random.uniform(0, 2 * math.pi)
                ctx.body.call(f"goto {pos[0] + 12 * math.cos(ang):.1f} {pos[1]:.1f} "
                              f"{pos[2] + 12 * math.sin(ang):.1f} --near 3 --timeout 12 --direct")
                continue
            if p is None:
                break
            walk_to_reach(ctx, p)
            if tool in TOOLS:
                ctx.select_best(TOOLS[tool])
            ctx.body.call(f"look-at block {p[0]} {p[1]} {p[2]}")
            r = ctx.body.call(f"break {p[0]} {p[1]} {p[2]} --timeout 20")
            if self.done():
                return
            if r.get("error"):
                ctx.say(f"couldn't break that {label}: {r['error'].split(';')[0]}")
                break
            done += 1
            if endless and done % 16 == 0:
                inv = ctx.body.call("inventory")
                if len([s for s in inv.get("hotbar", []) + inv.get("main", []) if s.get("item")]) >= 35:
                    ctx.say(f"my pockets are FULL! {done} {label} so far.")
                    return
                ctx.say(f"{done} {label} and counting!")
            ctx.recent_breaks.append((p[0], p[1], p[2], time.time()))
            time.sleep(0.8)
            if not ctx.collect(5, self):
                time.sleep(0.6)  # the drop was still bouncing: once more
                ctx.collect(5, self)
        if self.done():
            return
        if done:
            ctx.say(f"broke the {label}." if want == 1 else f"got {done} {label}.")
        else:
            ctx.say(f"I don't see any {label} around here.")


class UseBlock(Task):
    """Right-click a block: open or close a door, gate or trapdoor, pull a lever, press a
    button, ring a bell..."""
    name = "use_block"

    def run(self):
        ctx = self.ctx
        ids = set(self.args["ids"])
        label = self.args.get("label", "block")
        p = find_target(ctx, self, ids, self.args.get("near_owner", True))
        if p is None:
            ctx.say(f"I don't see a {label} around here.")
            return
        walk_to_reach(ctx, p)
        ctx.body.call(f"look-at block {p[0]} {p[1]} {p[2]}")
        r = ctx.body.call(f"interact {p[0]} {p[1]} {p[2]}")
        if r.get("screen") not in (None, "playing"):
            ctx.body.call("close")  # it opened a menu (a chest...): nothing to do in it
        ctx.say(f"done." if not r.get("error") else f"couldn't use the {label}.")


class PlaceBlock(Task):
    """'keve place a crafting table' / 'put a torch here': next to you."""
    name = "place_block"

    def run(self):
        ctx = self.ctx
        item = self.args["item"]
        label = self.args.get("label", item.removeprefix("minecraft:").replace("_", " "))
        if not ctx.counts().get(item):
            import mining
            if not mining.Provision(ctx, self).obtain(item, 1):
                return
        o = ctx.owner()
        if o and math.dist(ctx.eye_and_view()[3], o[1]) > 3:
            ctx.body.call(f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} --near 2 --timeout 15")
        import craft
        for spot in craft.Crafter(ctx, self).free_spots():
            if not ctx.place(spot, item).get("error"):
                ctx.say(f"there's your {label}.")
                return
        ctx.say(f"no room to put the {label} down here.")


def notable_nearby(ctx, radius=10, limit=8):
    """What stands out in sight: [(name, count, nearest distance)], nearest first."""
    eye = ctx.eye_and_view()[0]
    snap = sight.Snapshot.read(ctx.senses, eye, rh=radius, rv=5)
    names = world_names.names()
    seen = {}
    for p, n in snap.blocks.items():
        b = base(n)
        if not any(k in b for k in NOTABLE):
            continue
        d = math.dist(p, eye)
        if d > radius or not snap.block_visible(eye, p, radius + 1.0):
            continue
        label = names.pretty(b) if names else b.removeprefix("minecraft:").replace("_", " ")
        c, dmin = seen.get(label, (0, 99.0))
        seen[label] = (c + 1, min(dmin, d))
    mobs = [e for e in ctx.senses.call(f"entities {radius}").get("entities", [])
            if e.get("kind") == "mob" and e.get("type") != "minecraft:player"]
    for m in mobs:
        p = tuple(m["pos"])
        if sight.entity_visible(snap, eye, 0, 0, p, need_fov=False):
            label = m["type"].removeprefix("minecraft:").replace("_", " ")
            c, dmin = seen.get(label, (0, 99.0))
            seen[label] = (c + 1, min(dmin, m["distance"]))
    out = sorted(((k, c, d) for k, (c, d) in seen.items()), key=lambda x: x[2])
    return out[:limit]


class LookAround(Task):
    """'keve what do you see' / 'what's around'."""
    name = "look_around"

    def run(self):
        ctx = self.ctx
        ctx.look_around(lambda n: False)  # actually turn its head around first
        seen = notable_nearby(ctx, radius=12)
        if not seen:
            ctx.say("nothing special around here. just blocks.")
            return
        parts = [f"{c} {k}" if c > 1 else f"a {k}" for k, c, d in seen]
        ctx.say("I see " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + ".")
