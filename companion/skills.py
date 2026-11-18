"""Keve's skills: small state machines that drive the body through whitelisted commands.

Every skill runs on the task thread, checks `self.cancelled` between steps, and reports
in chat. Long actions (goto, break, hunt) block in the game until done or until the main
thread sends `stop` on the other connection.
"""
import math
import random
import re
import threading
import time

import sight
from ctl import CtlError

# What a word in chat means: which blocks to look for and which items count.
def base(name):
    """minecraft:oak_log[axis=y] -> minecraft:oak_log"""
    return name.split("[", 1)[0]


def _is_log(b):
    b = base(b)
    return (b.endswith("_log") or b.endswith("_stem")) and "stripped" not in b


GATHER = {
    "wood": (_is_log, lambda i: i.endswith("_log") or i.endswith("_stem")),
    "dirt": (lambda b: base(b) in ("minecraft:dirt", "minecraft:grass_block"),
             lambda i: i == "minecraft:dirt"),
    "sand": (lambda b: base(b) == "minecraft:sand", lambda i: i == "minecraft:sand"),
    "gravel": (lambda b: base(b) == "minecraft:gravel",
               lambda i: i in ("minecraft:gravel", "minecraft:flint")),
    "stone": (lambda b: base(b) in ("minecraft:stone", "minecraft:cobblestone"),
              lambda i: i == "minecraft:cobblestone"),
    "sugar_cane": (lambda b: base(b) == "minecraft:sugar_cane", lambda i: i == "minecraft:sugar_cane"),
    "pumpkin": (lambda b: base(b) == "minecraft:pumpkin", lambda i: i == "minecraft:pumpkin"),
    "clay": (lambda b: base(b) == "minecraft:clay", lambda i: i == "minecraft:clay_ball"),
}
NEEDS_PICKAXE = {"stone"}

HOSTILE = {
    "zombie", "husk", "drowned", "zombie_villager", "skeleton", "stray", "bogged", "creeper",
    "cave_spider", "witch", "slime", "phantom", "pillager", "vindicator", "evoker",
    "ravager", "vex", "silverfish", "endermite", "blaze", "ghast", "magma_cube",
    "piglin_brute", "hoglin", "zoglin", "wither_skeleton", "guardian", "elder_guardian",
    "breeze", "creaking", "parched",
}
# Leave these alone unless they're after you: spiders are calm in the light, the rest only
# fight back when provoked (or, for spiders, in the dark: night or a cave).
NEUTRAL = {"spider", "enderman", "zombified_piglin", "piglin", "wolf", "bee", "iron_golem",
           "polar_bear", "llama", "trader_llama", "panda", "dolphin", "goat"}
WEAPONS = ["netherite_sword", "diamond_sword", "iron_sword", "netherite_axe", "diamond_axe",
           "stone_sword", "iron_axe", "golden_sword", "wooden_sword", "stone_axe", "golden_axe",
           "wooden_axe"]
AXES = ["netherite_axe", "diamond_axe", "iron_axe", "stone_axe", "golden_axe", "wooden_axe"]
PICKAXES = ["netherite_pickaxe", "diamond_pickaxe", "iron_pickaxe", "stone_pickaxe",
            "golden_pickaxe", "wooden_pickaxe"]
FOODS = ["golden_carrot", "cooked_beef", "cooked_porkchop", "cooked_mutton", "cooked_salmon",
         "cooked_chicken", "baked_potato", "bread", "cooked_cod", "cooked_rabbit", "apple",
         "carrot", "melon_slice", "sweet_berries", "cookie", "beef", "porkchop", "mutton"]


class Ctx:
    """Everything a skill can use. Built once by keve.py."""

    def __init__(self, body, senses, say, owner_name, self_name):
        self.body = body          # action connection (task thread)
        self.senses = senses      # raw reads, only through sight helpers below
        self.said_log = []        # what Keve said lately (a quest reads it to see why a stage failed)

        def say_and_note(text, _say=say):
            self.said_log = (self.said_log + [text])[-60:]
            return _say(text)
        self.say = say_and_note   # send a chat line
        self.owner_name = owner_name
        self.self_name = self_name
        self.memory = {}          # (x, y, z) -> (block name, time seen); filled only by sight
        self.bad_targets = {}     # (x, y, z) -> failures
        self.placed_stations = []  # tables Keve put down and will pack up when idle
        self.last_craft_time = 0.0
        self.last_item = None
        self.made_batch = []
        self.quest_ok = None      # what the current job is collecting: a double crouch hands it over
        self.store_chest = None   # a chest Keve made for the job: full pockets go in there      # everything made for the latest order: 'give them to me'     # what Keve last made or got: 'give it to me' means this
        self.recent_breaks = []   # (x, y, z, time): Keve saw these break, so it knows the drops are there
        self.last_item = None     # what it gathered last ("bring them to me")
        self.provoked = {}        # mob type -> when it last hurt Keve or you

    # --- own state -------------------------------------------------------------------
    def state(self):
        st = self.body.call("state")
        if not st.get("player"):
            # Not in the world (dead, between worlds, or the game is quitting): stop here.
            raise CtlError("Keve isn't in the world right now")
        return st

    def eye_and_view(self):
        p = self.state()["player"]
        return tuple(p["eye"]), p["yaw"], p["pitch"], tuple(p["position"])

    def counts(self):
        return self.body.call("inventory").get("counts", {}) or {}

    def has(self, short_names):
        counts = self.counts()
        for n in short_names:
            if counts.get("minecraft:" + n, 0) > 0:
                return n
        return None

    def slot_of(self, item):
        """The inventory slot id (0-35) holding `item`, or None."""
        inv = self.body.call("inventory")
        for s in inv.get("hotbar", []) + inv.get("main", []):
            if s.get("item") == item:
                return s["slot"]
        return None

    # --- getting around, water included ---------------------------------------------------
    def water_between(self, a, b):
        """Is Keve in water, or is there water along the straight line to b?"""
        x0, y0, z0 = (int(math.floor(v)) for v in a)
        x1, z1 = int(math.floor(b[0])), int(math.floor(b[2]))
        lo, hi = (min(x0, x1), y0 - 2, min(z0, z1)), (max(x0, x1), y0 + 1, max(z0, z1))
        if (hi[0] - lo[0] + 1) * (hi[2] - lo[2] + 1) * 4 > 30000:
            return False
        blocks = self.senses.call(f"blocks {lo[0]} {lo[1]} {lo[2]} {hi[0]} {hi[1]} {hi[2]}").get("blocks", [])
        water = {(bx, bz) for bx, by, bz, n in blocks if n.split("[", 1)[0] == "minecraft:water"}
        if (x0, z0) in water:
            return True
        n = max(abs(x1 - x0), abs(z1 - z0), 1)
        return any((int(math.floor(a[0] + (b[0] - a[0]) * i / n)), int(math.floor(a[2] + (b[2] - a[2]) * i / n)))
                   in water for i in range(n + 1))

    def swim_toward(self, target, near=2.5, seconds=20.0, task=None):
        """Swim straight at a point: face it, sprint and hold jump (keeps the head above
        water), a short stroke at a time, until out of the water or there."""
        end = time.time() + seconds
        best = None
        stalls = 0
        while time.time() < end and not (task and task.done()):
            p = self.state()["player"]
            pos = tuple(p["position"])
            d = math.dist(pos, target)
            if d <= near:
                return True
            yaw = math.degrees(math.atan2(-(target[0] - pos[0]), target[2] - pos[2]))
            self.body.call(f"look {yaw:.1f} 0")
            r = self.body.call("move forward 0.5 --sprint --jump")
            if best is None or d < best - 0.3:
                best, stalls = d, 0
            else:
                stalls += 1
                if stalls >= 6:  # a wall or a cliff: let the walker try again
                    return False
            if not self.water_between(pos, target) and p.get("on_ground") and (r.get("moved") or 0) > 0:
                return False  # out of the water: walking is better from here
        return False

    def walk_to(self, target, near=3.0, timeout=4.0, sprint=True, task=None):
        """Get to a point: the path planner, and across water by swimming. The goto reply."""
        x, y, z = target
        r = self.body.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near {near} "
                           f"{'--sprint ' if sprint else ''}--timeout {timeout}")
        if r.get("arrived") or (task and task.done()):
            return r
        pos = tuple(self.state()["player"]["position"])
        if self.water_between(pos, target):
            self.swim_toward(target, near=near, seconds=max(timeout * 3, 12.0), task=task)
            r = self.body.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near {near} --timeout {timeout}")
        return r

    def to_hotbar(self, item):
        """Make sure `item` is on the hotbar (placing and using need it there): swap it
        in from the backpack through the inventory screen. True when it's there."""
        item = item if ":" in item else "minecraft:" + item
        slot = self.slot_of(item)
        if slot is None:
            return False
        if slot < 9:
            return True
        inv = self.body.call("inventory")
        hot = inv.get("hotbar", [])
        # An empty hotbar slot, else the last one that isn't a tool or food.
        target = next((s["slot"] for s in hot if not s.get("item")), None)
        if target is None:
            keep = ("pickaxe", "sword", "axe", "shovel", "torch") + tuple(FOODS)
            target = next((s["slot"] for s in reversed(hot)
                           if not any(k in s["item"] for k in keep)), 8)
        self.body.call("open-inventory")
        self.body.call(f"click-slot {slot}")
        self.body.call(f"click-slot {target}")
        self.body.call(f"click-slot {slot}")
        self.body.call("close")
        return (self.slot_of(item) or 99) < 9

    def place(self, pos, item):
        """Place `item` at pos (moving it to the hotbar first). The reply."""
        self.to_hotbar(item)
        short = item.removeprefix("minecraft:")
        return self.body.call(f"place {pos[0]} {pos[1]} {pos[2]} --item {short}")

    JUNK = ("andesite", "diorite", "granite", "tuff", "dirt", "gravel", "leaf_litter",
            "sapling", "flint", "calcite", "dripstone", "netherrack", "cobbled_deepslate")

    # What's worth carrying; anything else (terracotta, clay, stone of every kind, flowers...)
    # goes when the pockets fill up.
    KEEP_WORDS = ("pickaxe", "axe", "shovel", "hoe", "sword", "bow", "arrow", "shield", "helmet", "chestplate",
                  "leggings", "boots", "ore", "raw_iron", "raw_gold", "ingot", "nugget", "diamond", "emerald",
                  "coal", "torch", "stick", "planks", "_log", "crafting_table", "furnace", "chest", "bucket",
                  "obsidian", "flint", "string", "leather", "ender", "blaze", "observer", "bed", "boat", "cooked_",
                  "beef", "porkchop", "mutton", "chicken", "rabbit", "bread", "apple", "carrot", "potato", "cod",
                  "salmon", "melon_slice", "wheat", "book", "gunpowder", "bone", "quartz", "gold",
                  "netherrack", "food")

    def outclassed(self, item, slots):
        """A wooden or stone tool when he carries the iron (or better) one of its kind:
        junk. (Stone pickaxes stay: spares for the trip.)"""
        name = item.removeprefix("minecraft:")
        for low in ("wooden_", "stone_", "golden_"):
            if name.startswith(low) and not name.endswith("pickaxe"):
                kind = name[len(low):]
                return any(s["item"].endswith(("iron_" + kind, "diamond_" + kind, "netherite_" + kind))
                           for s in slots)
        return False

    def safe_close(self):
        """Close a screen without throwing what's on the cursor: it goes into an empty slot
        first (closing with a stack held throws it on the ground)."""
        inv = self.body.call("inventory")
        if inv.get("carried"):
            empty = next((s["slot"] for s in inv.get("main", []) + inv.get("hotbar", []) if not s.get("item")), None)
            if empty is not None:
                self.body.call(f"click-slot {empty}")
        self.body.call("close")

    def junk_pit(self):
        """Where to throw junk so he doesn't walk over it and pick it straight back up (in a
        1-wide tunnel it lands at his feet): a pocket dug two blocks into the side wall,
        looked into. Returns the pocket's mouth (to seal after), or None on open ground,
        where he just throws it ahead."""
        p = self.state()["player"]
        x, y, z = p["block_pos"]
        yaw = math.radians(p["yaw"])
        fx, fz = -math.sin(yaw), math.cos(yaw)
        sides = [(round(fz), round(-fx)), (round(-fz), round(fx))]  # left and right of facing
        r = self.senses.call(f"blocks {x - 3} {y} {z - 3} {x + 3} {y} {z + 3}").get("blocks", [])
        solid = {(b[0], b[1], b[2]) for b in r if sight.blocks_body(b[3])}
        open_round = sum(1 for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)) if (x + dx, y, z + dz) not in solid)
        if open_round >= 3:
            self.body.call(f"look {p['yaw']:.0f} 10")  # open ground: just throw it ahead
            return None
        for sx, sz in sides:
            a, b = (x + sx, y, z + sz), (x + 3 * sx, y, z + 3 * sz)
            mid = (x + 2 * sx, y, z + 2 * sz)
            if a not in solid or mid not in solid or b not in solid:
                continue
            self.select_best(PICKAXES)
            for c in (a, mid, b):
                self.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
                self.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 8")
            self.body.call(f"look-at {b[0] + 0.5:.2f} {y + 0.3:.2f} {b[2] + 0.5:.2f}")
            return a
        self.body.call(f"look {p['yaw'] + 180:.0f} -20")
        return None

    def seal_pit(self, mouth):
        for item in ("cobblestone", "cobbled_deepslate", "dirt", "netherrack"):
            if self.counts().get("minecraft:" + item):
                self.place(mouth, "minecraft:" + item)
                return

    def drop_junk(self, keep_cobble=64):
        """When the inventory is getting full, throw out what isn't worth carrying (see
        KEEP_WORDS): each junk stack is put in the last hotbar slot and thrown with Q, like a
        player clearing his pockets. (Clicking stacks out of the screen one after another
        was too quick for the game: one stack in five went.)"""
        inv = self.body.call("inventory")
        slots = [s for s in inv.get("hotbar", []) + inv.get("main", []) if s.get("item")]
        if len(slots) < 30:
            return
        self.body.call("close")  # a furnace or chest left open would take the clicks
        pit = self.junk_pit()
        cobble = 0
        junk = []
        for s in slots:
            it = s["item"]
            if it in ("minecraft:cobblestone", "minecraft:cobbled_deepslate"):
                cobble += s.get("count", 0)
                if cobble <= keep_cobble:
                    continue  # a stack for building, plugging and pickaxes
            elif it == "minecraft:wheat_seeds" or it.endswith("copper_ingot"):
                pass  # junk all the same
            elif any(k in it for k in self.KEEP_WORDS):
                if not self.outclassed(it, slots):
                    continue
            junk.append(s)
        thrown = []
        p = self.state()["player"]
        if not pit:
            self.body.call(f"look {p['yaw']:.0f} -15")  # throw it well ahead
        for s in junk:
            # To the hotbar (shift-click moves a pack stack there), then thrown with Q (it goes
            # further than one dropped out of the screen), stepping back from where it
            # lands so he doesn't pick it straight back up.
            if s["slot"] > 8:
                self.body.call("open-inventory")
                time.sleep(0.35)
                self.body.call(f"click-slot {s['slot']} shift")
                self.safe_close()
                time.sleep(0.1)
            r = self.body.call(f"select {s['item']}")
            if r.get("error"):
                # Hotbar full: out of the screen instead (pick it up, close: it's thrown).
                slot = self.slot_of(s["item"])
                if slot is None:
                    continue
                self.body.call("open-inventory")
                time.sleep(0.35)
                self.body.call(f"click-slot {slot}")
                if (self.body.call("inventory").get("carried") or {}).get("item") != s["item"]:
                    self.safe_close()
                    continue
                self.body.call("close")
            else:
                self.body.call("drop all")
            thrown.append(s["item"][10:])
            if not pit:
                self.body.call("move back 0.25")
        if pit:
            time.sleep(0.3)
            self.seal_pit(pit)
        now = self.body.call("inventory")
        after = [s for s in now.get("hotbar", []) + now.get("main", []) if s.get("item")]
        import journal
        journal.log("note", f"dropped junk: {len(slots)} slots -> {len(after)}", pit=bool(pit), thrown=thrown[:8])

    # --- ground where breaking doesn't stick (spawn protection, a claim) --------------
    def block_came_back(self, p, ok):
        """Broken, but the server put it back a moment later. Checked on the first few
        breaks and every tenth after (it costs a quarter of a second)."""
        self._break_checks = getattr(self, "_break_checks", 0) + 1
        if self._break_checks > 3 and self._break_checks % 10:
            return False
        time.sleep(0.25)
        r = self.senses.call(f"blocks {p[0]} {p[1]} {p[2]} {p[0]} {p[1]} {p[2]}").get("blocks", [])
        return bool(r) and ok(r[0][3])

    def no_break_here(self, p):
        """Remember a no-break zone round `p` (spawn protection is a square of up to 16
        blocks each way) and walk out of it."""
        zones = getattr(self, "zones", [])
        if not any(math.dist(z, p) < 20 for z in zones):
            zones.append(tuple(p))
            self.zones = zones
            self.say("the world won't let me break blocks here (spawn protection?). I'll go further out.")
        pos = self.eye_and_view()[3]
        dx, dz = pos[0] - p[0], pos[2] - p[2]
        d = math.hypot(dx, dz) or 1.0
        self.body.call(f"goto {p[0] + dx / d * 24:.1f} {pos[1]:.1f} {p[2] + dz / d * 24:.1f} --near 4 --timeout 20")

    def protected(self, p):
        return any(abs(p[0] - z[0]) <= 18 and abs(p[2] - z[2]) <= 18 for z in getattr(self, "zones", []))

    def escape_water(self, p):
        """Out of air: swim to the nearest dry spot (air for the head, ideally higher up);
        nowhere dry close by, dig up through the block over his head while swimming.
        (Just holding jump drowned him in a flooded 1-wide staircase.)"""
        x, y, z = p["block_pos"]
        snap = sight.Snapshot.read(self.senses, (x, y, z), rh=4, rv=4)

        def dry(c):
            a, b = snap.name(c), snap.name((c[0], c[1] + 1, c[2]))
            return not sight.blocks_body(a) and not sight.is_fluid(a) and not sight.blocks_body(b)                 and not sight.is_fluid(b)
        spots = [(x + dx, y + dy, z + dz) for dx in range(-4, 5) for dy in range(-1, 5) for dz in range(-4, 5)
                 if dry((x + dx, y + dy, z + dz))]
        self.body.call("key space down")
        try:
            if spots:
                c = min(spots, key=lambda c: math.dist(c, (x, y, z)) - 0.5 * (c[1] - y))
                self.body.call(f"goto {c[0] + 0.5:.2f} {c[1]:.2f} {c[2] + 0.5:.2f} --near 0.6 --timeout 4 --direct")
            else:
                for dy in (2, 3):
                    c = (x, y + dy, z)
                    if sight.blocks_body(snap.name(c)):
                        self.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
                        self.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 6")
                self.body.call("wait 15")
        finally:
            self.body.call("key space up")

    def hide(self, task):
        """Two blocks down, a block over the head, eat, and wait to heal (or for the mobs to
        go); then out again. On the surface or in a tunnel alike."""
        self.say("ouch, I'm hurt! hiding to heal up.")
        x, y, z = self.state()["player"]["block_pos"]
        for c in ((x, y - 1, z), (x, y - 2, z), (x, y - 3, z)):  # three: the lid needs ground round it
            n = self.senses.call(f"blocks {c[0]} {c[1]} {c[2]} {c[0]} {c[1]} {c[2]}").get("blocks", [])
            if n and sight.blocks_body(n[0][3]) and not any(u in n[0][3] for u in ("bedrock", "lava", "water")):
                import mining
                self.select_best(PICKAXES + ["netherite_shovel", "diamond_shovel", "iron_shovel", "stone_shovel", "wooden_shovel"])
                self.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
                self.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 8")
        self.body.call(f"goto {x + 0.5:.2f} {y - 3:.2f} {z + 0.5:.2f} --near 0.4 --timeout 2 --direct")
        if not self.roof_over():
            self.say("nothing to cover the hole with!")
        end = time.time() + 90
        while time.time() < end and not task.done():
            self.maybe_eat(below=19)
            hp = self.state()["player"].get("health", 20)
            if hp >= 16:
                break
            time.sleep(2)
        if not task.done():
            self.say("patched up!")
            self.climb_out(task)

    def roof_over(self):
        """A block over his head (the hole's lid). The dirt he just dug out lands with him:
        pick it up first if he has nothing else. True when the lid is really there."""
        time.sleep(0.8)
        self.collect(2)
        x, y, z = self.state()["player"]["block_pos"]
        lid = (x, y + 2, z)
        for item in ("cobblestone", "cobbled_deepslate", "dirt", "netherrack", "andesite", "diorite", "granite",
                     "sand", "gravel", "oak_planks"):
            if not self.counts().get("minecraft:" + item):
                continue
            self.place(lid, "minecraft:" + item)
            r = self.senses.call(f"blocks {lid[0]} {lid[1]} {lid[2]} {lid[0]} {lid[1]} {lid[2]}").get("blocks", [])
            if r and sight.blocks_body(r[0][3]):
                return True
        return False

    def clear_leaves_around(self):
        """Leaves (or bushes) at head or foot height round him: break them, like a player
        punching out of a thicket. True when any were broken."""
        x, y, z = self.state()["player"]["block_pos"]
        r = self.senses.call(f"blocks {x - 2} {y} {z - 2} {x + 2} {y + 1} {z + 2}").get("blocks", [])
        soft = [(b[0], b[1], b[2]) for b in r if any(k in b[3] for k in ("leaves", "azalea", "bush", "vine"))]
        soft.sort(key=lambda c: math.dist(c, (x, y, z)))
        broke = 0
        for c in soft[:12]:
            self.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
            if not self.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 4").get("error"):
                broke += 1
        if broke:
            import journal
            journal.log("note", f"cleared {broke} leaves to get out")
        return broke > 0

    def in_hole(self):
        """In a pit: ground at foot height on all four sides (the night shelter, a hole he dug,
        a 1-wide shaft), so walking won't get him out."""
        x, y, z = self.state()["player"]["block_pos"]
        r = self.senses.call(f"blocks {x - 1} {y} {z - 1} {x + 1} {y} {z + 1}").get("blocks", [])
        walls = {(b[0], b[2]) for b in r if sight.blocks_body(b[3])}
        return all((x + dx, z + dz) in walls for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    def climb_out(self, task, steps=4):
        """Out of a hole: dig steps up, whichever way gives."""
        import mining
        m = mining.Mine(self, ore="coal")
        m.cancelled = task.cancelled
        m.prov = mining.Provision(self, m)
        start_y = m.pos()[1]
        for d in mining.DIRS:
            m.dir = d
            for _ in range(steps):
                if task.done() or not m.stair_up():
                    break
            if m.pos()[1] > start_y and not self.in_hole():
                return True
        return False

    def quest_items(self):
        """Item ids Keve carries that belong to the job: what it's gathering or mining,
        and what it made for the latest order."""
        ok = self.quest_ok
        return [i for i, n in self.counts().items()
                if n > 0 and ((ok is not None and ok(i)) or i in self.made_batch)]

    def select_best(self, short_names):
        """The best of these he has, in hand. If it's in the backpack, it's moved onto the
        hotbar first (select only reaches the hotbar: a pickaxe pushed into the pack had
        him breaking deepslate with a torch, 12 s a block, failing)."""
        counts = self.counts()
        for n in short_names:  # best first; one he can't get into his hand: the next one
            if counts.get("minecraft:" + n, 0) <= 0:
                continue
            if not self.body.call(f"select minecraft:{n}").get("error"):
                return n
            self.to_hotbar("minecraft:" + n)
            if not self.body.call(f"select minecraft:{n}").get("error"):
                return n
        return None

    # --- where the owner is (a teammate's position, as the locator bar shows it) --------
    def owner(self):
        """(entity id, position) of the nearest other player, or None."""
        r = self.senses.call("entities 128 minecraft:player")
        best = None
        for e in r.get("entities", []):
            if best is None or e["distance"] < best["distance"]:
                best = e
        return (best["id"], tuple(best["pos"])) if best else None

    # --- fair sight ------------------------------------------------------------------
    def look_around(self, wanted, pitches=(0.0, 35.0)):
        """Turn the head around like a player and remember the wanted blocks it sees."""
        eye, yaw, pitch, _ = self.eye_and_view()
        snap = sight.Snapshot.read(self.senses, eye)
        found = []
        for dyaw in (0, 90, 180, 270):
            for p in pitches:
                y = (yaw + dyaw + 180.0) % 360.0 - 180.0
                self.body.call(f"look {y:.1f} {p:.1f}")
                for pos, name in sight.visible_blocks(snap, eye, y, p, wanted):
                    self.memory[pos] = (name, time.time())
                    found.append(pos)
        return found

    def still_there_and_visible(self, pos, wanted):
        eye, _, _, _ = self.eye_and_view()
        snap = sight.Snapshot.read(self.senses, pos, rh=6, rv=6)
        name = snap.name(pos)
        if not wanted(name):
            self.memory.pop(pos, None)
            return "gone"
        return "visible" if snap.block_visible(eye, pos) else "hidden"

    def is_dark_at(self, pos):
        """Too dark for a spider to stay calm: night with no lamp, or a cave."""
        x, y, z = (int(math.floor(v)) for v in pos)
        r = self.senses.call(f"light {x} {y} {z} {x} {y + 1} {z}")
        block = max((int(c, 16) for c in r.get("block", "") if c != "."), default=0)
        sky = max((int(c, 16) for c in r.get("sky", "") if c != "."), default=0)
        try:
            t = self.body.call("status").get("day_time", 6000) % 24000
        except Exception:
            t = 6000
        sun = sky if t < 12500 or t > 23500 else max(0, sky - 11)
        return max(block, sun) < 7

    def wants_a_fight(self, m):
        """Is this mob actually after someone? Hostiles always; neutral ones only when
        provoked, a spider also in the dark."""
        kind = m.get("type", "").removeprefix("minecraft:")
        if kind in HOSTILE:
            return True
        if kind not in NEUTRAL:
            return False
        if time.time() - self.provoked.get(kind, 0) < 60:
            return True
        return kind == "spider" and self.is_dark_at(tuple(m["pos"]))

    def on_hurt(self, event):
        """Keve got hurt: remember who did it (neutral mobs fight back when provoked)."""
        text = str(event).lower()
        self.hits = [t for t in getattr(self, "hits", []) if time.time() - t < 6] + [time.time()]
        if "arrow" in text or "trident" in text:
            self.shot_at = time.time()  # an archer somewhere out there: look further for it
        for kind in NEUTRAL | HOSTILE:
            if kind in text:
                self.provoked[kind] = time.time()
                return
        # The event didn't say who: the nearest mob next to Keve did it.
        near = [e for e in self.senses.call("entities 4").get("entities", [])
                if e.get("kind") == "mob" and e.get("type") != "minecraft:player"]
        if near:
            kind = min(near, key=lambda e: e["distance"])["type"].removeprefix("minecraft:")
            self.provoked[kind] = time.time()

    def under_attack(self):
        """Hit twice in the last few seconds: something's on him, seen or not."""
        return len([t for t in getattr(self, "hits", []) if time.time() - t < 4]) >= 2

    def visible_hostiles(self, around, radius):
        eye, yaw, pitch, _ = self.eye_and_view()
        mobs = self.senses.call(f"entities {radius + 16:.0f}").get("entities", [])
        mobs = [m for m in mobs if m.get("type", "").removeprefix("minecraft:") in HOSTILE | NEUTRAL]
        # You just got hit (your hurt time is up) by a neutral mob close to you: it's provoked.
        owner = next((e for e in self.senses.call(f"entities {radius + 16:.0f} minecraft:player")
                      .get("entities", []) if e.get("hurt_time", 0) > 0), None) if self.owner_name else None
        if owner:
            for m in mobs:
                if math.dist(tuple(m["pos"]), tuple(owner["pos"])) < 3.5:
                    self.provoked[m["type"].removeprefix("minecraft:")] = time.time()
        mobs = [m for m in mobs if self.wants_a_fight(m)]
        if not mobs:
            return []
        snap = sight.Snapshot.read(self.senses, eye)
        out = []
        for m in mobs:
            pos = tuple(m["pos"])
            if math.dist(pos, around) > radius:
                continue
            # Hostiles are noisy: Keve hears them and turns, so no field-of-view limit here,
            # but walls still block the view.
            if sight.entity_visible(snap, eye, yaw, pitch, pos, need_fov=False):
                out.append(m)
        out.sort(key=lambda m: m["distance"])
        return out

    # --- pick-up and fighting (horizon-ctl does these on its own side, so they're
    # ported here: the game's socket has no `collect` or `hunt`) -------------------------
    def collect(self, radius=6.0, task=None):
        """Walk over the dropped items Keve can see within `radius`, nearest first."""
        tried = set()
        picked = 0
        for _ in range(12):
            if task is not None and task.done():
                break
            ents = self.senses.call(f"entities {radius:.0f}").get("entities", [])
            items = [e for e in ents if e.get("kind") == "item" and e.get("id") not in tried]
            if not items:
                break
            eye, _, _, _ = self.eye_and_view()
            snap = sight.Snapshot.read(self.senses, eye, rh=int(radius) + 1, rv=5)
            now = time.time()
            self.recent_breaks = [r for r in self.recent_breaks if now - r[3] < 90]

            def known(e):
                p = tuple(e["pos"])
                if sight.entity_visible(snap, eye, 0, 0, p, height=0.3, need_fov=False):
                    return True
                # A drop from a block Keve broke itself: it watched it fall into the hole.
                return any(math.dist(p, (r[0] + 0.5, r[1] + 0.5, r[2] + 0.5)) < 2.5
                           for r in self.recent_breaks)

            items = [e for e in items if known(e)]
            o = self.owner()
            if o:  # what lies at your feet is yours (Keve may just have handed it over)
                items = [e for e in items if math.dist(e["pos"], o[1]) > 2.0]
            if not items:
                break
            it = min(items, key=lambda e: e["distance"])
            tried.add(it["id"])
            before = sum(self.counts().values())
            x, y, z = it["pos"]
            r = self.body.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near 0.4 --timeout 4")
            if not r.get("arrived"):
                self.body.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near 0.4 --timeout 3 --direct")
            self.body.call("wait 4")
            picked += max(0, sum(self.counts().values()) - before)
        return picked

    def hunt(self, mob_id, timeout=12.0, task=None):
        """Walk up to a mob and hit it (respecting the attack cooldown) until it's gone."""
        end = time.time() + timeout
        last = None
        held = (self.state().get("held") or {}).get("item", "") or ""
        # Ticks until a full-strength hit again (vanilla attack speed): fists 4/s,
        # swords 1.6/s, axes about 0.8-1/s, anything else 4/s like a fist.
        cooldown = 13 if held.endswith("_sword") else 22 if held.endswith("_axe") else 5
        stalled = 0
        while time.time() < end and not (task is not None and task.done()):
            ents = self.senses.call("entities 24").get("entities", [])
            mob = next((e for e in ents if e.get("id") == mob_id), None)
            if mob is None or (mob.get("health") is not None and mob["health"] <= 0):
                break
            last = mob
            x, y, z = mob["pos"]
            d = mob["distance"]
            if d > 7.0:
                # Far: let the path planner get close (a short leg; the mob moves).
                self.body.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near 2.5 --sprint --timeout 1.5")
                continue
            self.body.call(f"look-at entity {mob_id}")
            if d > 2.9:
                # Close: run straight at it, a few ticks at a time, jumping over bumps.
                r = self.body.call(f"move forward 0.25 --sprint{' --jump' if stalled > 1 else ''}")
                stalled = 0 if (r.get("moved") or 0) > 0.15 else stalled + 1
                continue
            if not self.body.call(f"attack {mob_id}").get("error"):
                self.body.call(f"wait {cooldown}")
            else:
                self.body.call("move forward 0.15")
        if last:  # walk over the drops
            x, y, z = last["pos"]
            self.body.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near 0.5 --timeout 4")
            self.body.call("wait 10")

    # --- reflexes --------------------------------------------------------------------
    def survive(self):
        """Out of air: swim up. Standing in lava or fire: get out. True when it acted."""
        try:
            p = self.state()["player"]
        except Exception:
            return False
        if p.get("air", 300) < 160:
            self.escape_water(p)
            return True
        x, y, z = p["block_pos"]
        r = self.senses.call(f"blocks {x} {y - 1} {z} {x} {y + 1} {z}")
        hot = [b for b in r.get("blocks", []) if any(h in b[3] for h in ("minecraft:lava", "fire"))]
        if hot:
            self.body.call("move back 0.6 --sprint --jump")
            self.body.call("move left 0.4 --jump")
            return True
        return self.get_down_from_tree(p)

    def get_down_from_tree(self, p):
        """Stuck on a treetop (it spawned there, or climbed up): the path planner won't drop
        more than 3 blocks, so do what a player does: break the leaves (or log) underfoot
        and fall, until it stands on the ground. True when it acted."""
        def tree(name):
            b = name.split("[", 1)[0]
            return b.endswith("_leaves") or b.endswith("_log") or b.endswith("_wood")
        import journal
        acted = False
        stuck = 0
        last_y = None
        for _ in range(16):
            px, py, pz = p["position"]
            x, y, z = p["block_pos"]
            if last_y is not None:
                stuck = stuck + 1 if y >= last_y else 0
            last_y = y
            if stuck >= 2:
                # Breaking underfoot isn't working: walk off the edge of the tree instead.
                journal.log("note", "tree: breaking underfoot didn't drop me, stepping off the edge", y=y)
                if self.step_off_tree(p, tree):
                    stuck = 0
                    acted = True
                    try:
                        p = self.state()["player"]
                    except Exception:
                        return acted
                    continue
                return acted
            col = self.senses.call(f"blocks {x} {y - 10} {z} {x} {y - 1} {z}").get("blocks", [])
            below = {b[1]: b[3] for b in col}
            if not tree(below.get(y - 1, "")):
                return acted
            # How far down is real ground (not tree)? Close enough: walking handles it.
            ground = next((yy for yy in range(y - 1, y - 11, -1)
                           if below.get(yy) and not tree(below[yy])), y - 11)
            if y - ground <= 3 and acted is False:
                return False
            # Every tree block the body stands on (a body is 0.6 wide: up to four).
            cells = {(int(math.floor(px + dx)), y - 1, int(math.floor(pz + dz)))
                     for dx in (-0.29, 0.29) for dz in (-0.29, 0.29)}
            if not acted:
                self.say("whoa, I'm up a tree! coming down.")
            for c in cells:
                n = self.senses.call(f"blocks {c[0]} {c[1]} {c[2]} {c[0]} {c[1]} {c[2]}").get("blocks", [])
                if n and tree(n[0][3]):
                    if n[0][3].split("[", 1)[0].endswith(("_log", "_wood")):
                        self.select_best(AXES)
                    self.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
                    r = self.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 10")
                    if r.get("error"):
                        journal.log("note", "tree: couldn't break underfoot", block=n[0][3].split("[")[0],
                                    at=list(c), error=str(r["error"])[:200])
            acted = True
            self.body.call("wait 10")  # fall
            try:
                p = self.state()["player"]
            except Exception:
                return acted
        return acted
    def step_off_tree(self, p, tree):
        """Off the canopy's edge: the nearest open spot beside the tree at foot level (air
        to walk into), walked to straight. A fall, but out of the tree."""
        x, y, z = p["block_pos"]
        box = self.senses.call(f"blocks {x - 4} {y - 6} {z - 4} {x + 4} {y + 1} {z + 4}").get("blocks", [])
        filled = {(b[0], b[1], b[2]) for b in box if sight.blocks_body(b[3]) or tree(b[3])}
        ground = {(b[0], b[1], b[2]) for b in box if sight.blocks_body(b[3]) and not tree(b[3])
                  and "dripstone" not in b[3]}
        best = None
        for dx in range(-4, 5):
            for dz in range(-4, 5):
                c = (x + dx, y, z + dz)
                if (dx, dz) == (0, 0) or c in filled or (c[0], y + 1, c[2]) in filled                         or (c[0], y - 1, c[2]) in filled:
                    continue
                # Only where there's ground (not more leaves, not a cliff) within 4 below.
                if not any((c[0], y - k, c[2]) in ground for k in range(1, 6)):
                    continue
                d = math.hypot(dx, dz)
                if best is None or d < best[0]:
                    best = (d, c)
        if best is None:
            return False
        c = best[1]
        self.say("I'm jumping for it!")
        # Leaves in the way at foot or head height on the way there get broken.
        steps = max(1, int(best[0] * 2))
        for s in range(1, steps + 1):
            f = s / steps
            cx = math.floor(x + 0.5 + (c[0] - x) * f)
            cz = math.floor(z + 0.5 + (c[2] - z) * f)
            for cy in (y, y + 1):
                if (cx, cy, cz) in filled and (cx, cz) != (x, z):
                    self.body.call(f"look-at block {cx} {cy} {cz}")
                    self.body.call(f"break {cx} {cy} {cz} --timeout 5")
        self.body.call(f"goto {c[0] + 0.5:.2f} {y:.2f} {c[2] + 0.5:.2f} --near 0.3 --timeout 4 --direct")
        self.body.call("move forward 0.4")
        self.body.call("wait 30")  # the fall
        return True

    def maybe_eat(self, below=14):
        """Eat when hungry. Healing needs a nearly full belly (18+), so a hurt Keve eats
        sooner (below=19)."""
        try:
            food = self.state()["player"]["food"]
        except Exception:
            return
        if food <= below:
            f = self.select_best(FOODS)
            if f:
                self.body.call("use-item --hold 1.8")


class Task:
    name = "task"

    def __init__(self, ctx, **args):
        self.ctx = ctx
        self.args = args
        self.cancelled = threading.Event()

    def run(self):
        raise NotImplementedError

    def done(self):
        return self.cancelled.is_set()

    def guard(self, owner_radius=10.0, self_radius=5.0):
        """Reflex: fight a hostile it can see that is close to the owner or to Keve.
        True when it fought something (the caller then loops again)."""
        ctx = self.ctx
        if ctx.survive():
            return True
        o = ctx.owner()
        _, _, _, pos = ctx.eye_and_view()
        targets = ctx.visible_hostiles(pos, self_radius)
        if o:
            targets += ctx.visible_hostiles(o[1], owner_radius)
        if not targets and ctx.under_attack():
            # Getting hit by something he can't see (behind him, round a corner of the
            # stairs): he feels it, so he turns on whatever is right next to him.
            near = [e for e in ctx.senses.call("entities 4").get("entities", [])
                    if e.get("kind") == "mob" and e.get("type", "").removeprefix("minecraft:") in HOSTILE | NEUTRAL]
            if near:
                targets = [min(near, key=lambda e: e["distance"])]
        if not targets:
            # A creeper creeping up (behind him, round the tunnel bend): a player hears the
            # hiss and turns on it. Unseen, one blew him up at y 7 for 19 hearts' worth.
            hiss = [e for e in ctx.senses.call("entities 7 minecraft:creeper").get("entities", [])
                    if e.get("distance", 99) < 7]
            if hiss:
                targets = [min(hiss, key=lambda e: e["distance"])]
        if not targets and time.time() - getattr(ctx, "shot_at", 0) < 5:
            # Shot at: the archer is further off. Go get it (if he's not too hurt for it).
            try:
                health = ctx.state()["player"].get("health", 20)
            except Exception:
                health = 20
            if health > 7:
                targets = [m for m in ctx.visible_hostiles(pos, 20)
                           if m.get("type", "").removeprefix("minecraft:") in RANGED]
        if not targets:
            return False
        try:
            hp = ctx.state()["player"].get("health", 20)
        except Exception:
            hp = 20
        m = min(targets, key=lambda m: m["distance"])
        close = [t for t in targets if t["distance"] < 6]
        melee = m["distance"] < 3.5 and m.get("type", "").removeprefix("minecraft:") not in RANGED
        if hp <= 8 and melee and len(close) <= 2 and hp > 2:
            # One or two right on him: digging a hole takes seconds of free hits (a zombie
            # killed him mid-dig at y 8). Finish it off instead, then hide if still hurt.
            pass
        elif hp <= 8 and not getattr(self, "_hiding", False):
            # Losing: don't slug it out. Dig in and heal, like a player would.
            self._hiding = True
            try:
                ctx.hide(self)
            finally:
                self._hiding = False
            return True
        m = min(targets, key=lambda m: m["distance"])
        if not getattr(self, "_announced", False):
            ctx.say(random.choice(["got one!", "behind you!", "I see it!", "on it!"]))
            self._announced = True
        ctx.select_best(WEAPONS)
        ctx.hunt(m["id"], 10.0, self)
        return True


RANGED = {"skeleton", "stray", "bogged", "pillager", "piglin", "drowned", "witch", "blaze", "ghast", "parched"}


class Come(Task):
    name = "come"

    def run(self):
        o = self.ctx.owner()
        if not o:
            self.ctx.say("I can't find you!")
            return
        r = self.ctx.walk_to(o[1], near=2.5, timeout=40, task=self)
        if self.done():
            return
        if r.get("arrived"):
            self.ctx.body.call(f"look-at entity {o[0]}")
            self.ctx.say(random.choice(["here.", "what's up?", "made it.", "I'm here."]))
            return
        pos = self.ctx.eye_and_view()[3]
        o = self.ctx.owner() or o
        if math.dist(pos, o[1]) < 80:
            # No way to walk there (you're through the rock, down a shaft...): dig to you.
            self.ctx.say("no way through, I'll dig to you!")
            import room
            t = room.DigTo(self.ctx)
            t.cancelled = self.cancelled
            t.run()
        else:
            self.ctx.say(f"couldn't get to you ({r.get('error', 'no path')}).")


class Follow(Task):
    """Follow you like a friend would: along the way you went, not just toward you.

    Keve keeps your trail (where you were, a few times a second) and walks it point by
    point, so he goes where you went: over the same blocks, across the same water
    (swimming), and where you jumped (left the ground on the way), he takes a sprint-jump
    from where you took off. He sprints when you do or when he falls behind. When the trail
    is no help (you teleported, it led nowhere), he finds his own way to you."""
    name = "follow"
    KEEP = 4.0       # how close is close enough
    SPRINT_GAP = 7.0

    def run(self):
        ctx = self.ctx
        stuck = 0
        last_eat = 0.0
        trail = []          # [(x, y, z, t, airborne)]
        last_sample = None
        while not self.done():
            # A friend who follows you also fights what's attacking you.
            if self.guard():
                continue
            self._announced = False
            o = ctx.owner()
            if not o:
                time.sleep(1.0)
                continue
            now = time.time()
            op = tuple(o[1])
            speed = 0.0
            if last_sample is not None:
                dt = max(now - last_sample[3], 1e-3)
                speed = math.dist((op[0], op[2]), (last_sample[0], last_sample[2])) / dt
            if last_sample is None or math.dist(op, last_sample[:3]) > 0.35:
                # In the air: not standing on a block or slab top, and going up or down
                # (walking on snow or carpet is off the grid too, but stays level).
                airborne = abs(op[1] - round(op[1] * 2) / 2) > 0.08 and last_sample is not None                     and abs(op[1] - last_sample[1]) > 0.15
                trail.append((op[0], op[1], op[2], now, airborne))
                trail = trail[-200:]
                last_sample = (op[0], op[1], op[2], now)
            _, _, _, pos = ctx.eye_and_view()
            d = math.dist(pos, op)
            if d <= self.KEEP:
                ctx.body.call(f"look-at entity {o[0]}")
                trail = trail[-3:]
                time.sleep(0.25)
            else:
                sprint = speed > 5.0 or d > self.SPRINT_GAP
                self._your_speed = speed
                if not self.walk_trail(trail, pos, sprint):
                    # The trail didn't help: find a way there.
                    r = ctx.walk_to(op, near=3, timeout=4, task=self)
                    if self.done():
                        return
                    stuck = 0 if r.get("arrived") or r.get("distance", 99) < d - 1 else stuck + 1
                    if stuck == 4:
                        ctx.say("wait up, I'm stuck!")
                        ctx.body.call("jump")
                    trail = trail[-3:]
                else:
                    stuck = 0
            if now - last_eat > 10:
                ctx.maybe_eat()
                last_eat = now

    def walk_trail(self, trail, pos, sprint):
        """One short leg along your trail. False when there's no usable trail."""
        ctx = self.ctx
        if not trail:
            return False
        # Where on your trail Keve is: the nearest point to him (in the last ~40 points).
        recent = trail[-40:]
        k = min(range(len(recent)), key=lambda n: math.dist(pos, recent[n][:3]))
        if math.dist(pos, recent[k][:3]) > 6:
            return False  # nowhere near where you went
        ahead = recent[k + 1:]
        if not ahead:
            return False
        jump = self.jump_ahead(recent[k], ahead)
        if jump:
            return self.parkour(*jump, sprint=sprint)
        # Otherwise a leg of about 2 blocks along it, straight (the trail already goes
        # around things). Short legs, so your next moves are seen soon.
        target = ahead[-1]
        walked = 0.0
        prev = recent[k][:3]
        for pt in ahead:
            walked += math.dist(prev, pt[:3])
            prev = pt[:3]
            if walked >= 2.0:
                target = pt
                break
        r = ctx.body.call(f"goto {target[0]:.2f} {target[1]:.2f} {target[2]:.2f} --near 0.7 --timeout 0.8 --direct"
                          + (" --sprint" if sprint else ""))
        if self.done():
            return True
        after = ctx.eye_and_view()[3]
        return math.dist(after, target[:3]) < math.dist(pos, target[:3]) - 0.3 or r.get("arrived", False)

    def jump_ahead(self, here, ahead):
        """(take-off, landing) if the next few blocks of your trail are a jump: you were in
        the air there, or the trail crosses a gap with nothing to stand on, or climbs a
        block over a gap. None for plain walking (one-block steps are walked)."""
        for n, pt in enumerate(ahead[:6]):
            if pt[4]:
                take_off = ahead[n - 1] if n > 0 else here
                land = next((q for q in ahead[n:] if not q[4]), None)
                if land is not None:
                    return take_off, land
                return None
        snap = None
        prev = here
        for pt in ahead[:8]:
            if math.dist((prev[0], prev[2]), (here[0], here[2])) > 4.0:
                break
            if snap is None:
                snap = sight.Snapshot.read(self.ctx.senses, here[:3], rh=6, rv=4)
            # Look under the straight line from prev to pt for somewhere to stand.
            steps = max(2, int(math.dist((prev[0], prev[2]), (pt[0], pt[2])) / 0.3))
            for s in range(1, steps):
                f = s / steps
                x, y, z = (prev[0] + (pt[0] - prev[0]) * f, min(prev[1], pt[1]), prev[2] + (pt[2] - prev[2]) * f)
                bx, by, bz = math.floor(x), math.floor(y + 0.01), math.floor(z)
                if not any(sight.blocks_body(snap.name((bx, by - d, bz))) for d in (1, 2)):
                    return prev, next((q for q in ahead if math.dist((q[0], q[2]), (x, z)) > 0.8
                                       and q[3] >= pt[3]), pt)
            prev = pt
        return None

    # --- jumps: learned per kind of jump (gap length, height), kept in memory.json -------
    @staticmethod
    def jump_kind(take_off, land):
        span = math.hypot(land[0] - take_off[0], land[2] - take_off[2])
        return f"{round(span * 2) / 2:.1f}/{round(land[1] - take_off[1]):+d}"

    def technique(self, kind):
        """How to do this kind of jump: a run-up (blocks), sprinting time before the jump
        (s), and how long to hold forward in the air. Starts from what the physics needs
        (a bigger gap or a climb needs a run-up), then whatever has worked best."""
        import life
        book = life.load_memory().get("parkour", {})
        t = book.get(kind)
        if t:
            return t
        span, dy = float(kind.split("/")[0]), int(kind.split("/")[1])
        run = 0.4 if span <= 1.5 and dy <= 0 else 1.2 if span <= 2.5 else 2.2
        return {"run": run, "lead": round(run / 4.0, 2), "air": 0.75, "tries": 0, "wins": 0, "seen": 0}

    def learn_jump(self, kind, t, made, short_by=0.0):
        """After a go: keep what works; on a miss, change the run-up or the timing."""
        import life
        t = dict(t)
        t["tries"] = t.get("tries", 0) + 1
        if made:
            t["wins"] = t.get("wins", 0) + 1
        elif short_by > 0.3:
            t["run"] = min(3.0, round(t["run"] + 0.4, 2))   # fell short: more speed
            t["lead"] = round(t["run"] / 4.0, 2)
        else:
            t["lead"] = round(max(0.05, t["lead"] - 0.06), 2)  # went off the edge first: jump earlier
            t["air"] = min(1.2, round(t["air"] + 0.1, 2))
        mem = life.load_memory()
        mem.setdefault("parkour", {})[kind] = t
        life.save_memory(mem)

    def saw_you_jump(self, take_off, land, speed):
        """You made this jump: note it (a kind you can do is one worth practising)."""
        import life
        kind = self.jump_kind(take_off, land)
        t = self.technique(kind)
        t["seen"] = t.get("seen", 0) + 1
        if speed > 5.0 and t["run"] < 1.2:
            t["run"], t["lead"] = 1.2, 0.3  # you sprinted into it: so will he
        mem = life.load_memory()
        mem.setdefault("parkour", {})[kind] = t
        life.save_memory(mem)

    def parkour(self, take_off, land, sprint=True):
        """Jump from where you took off to where you landed, the way that's worked for this
        kind of jump: back up for a run-up, sprint to the edge, jump, check he made it.
        Two goes, learning from each."""
        ctx = self.ctx
        dx, dz = land[0] - take_off[0], land[2] - take_off[2]
        span = math.hypot(dx, dz) or 1.0
        ux, uz = dx / span, dz / span
        kind = self.jump_kind(take_off, land)
        key = (round(take_off[0], 1), round(take_off[2], 1), round(land[0], 1), round(land[2], 1))
        if key not in getattr(self, "_seen_jumps", set()):
            self._seen_jumps = getattr(self, "_seen_jumps", set()) | {key}
            self.saw_you_jump(take_off, land, getattr(self, "_your_speed", 0.0))
        for attempt in range(2):
            if self.done():
                return True
            t = self.technique(kind)
            ctx.body.call(f"goto {take_off[0]:.2f} {take_off[1]:.2f} {take_off[2]:.2f} --near 0.5 --timeout 3")
            back = (take_off[0] - ux * t["run"], take_off[1], take_off[2] - uz * t["run"])
            ctx.body.call(f"goto {back[0]:.2f} {back[1]:.2f} {back[2]:.2f} --near 0.3 --timeout 1.5 --direct")
            here = ctx.eye_and_view()[3]
            ctx.body.call(f"look-at {land[0]:.2f} {here[1] + 1.6:.2f} {land[2]:.2f}")
            if math.dist((here[0], here[2]), (take_off[0], take_off[2])) > 0.2:
                ctx.body.call(f"move forward {t['lead']:.2f} --sprint")
            ctx.body.call(f"move forward {t['air']:.2f} --sprint --jump")
            ctx.body.call(f"goto {land[0]:.2f} {land[1]:.2f} {land[2]:.2f} --near 0.6 --timeout 1.2 --direct --sprint")
            after = ctx.eye_and_view()[3]
            made = math.dist((after[0], after[2]), (land[0], land[2])) < 1.3 and after[1] >= land[1] - 0.4
            # Short: he ended up back before the landing. Long/off the side: past or beside it.
            along = (after[0] - take_off[0]) * ux + (after[2] - take_off[2]) * uz
            self.learn_jump(kind, t, made, short_by=max(0.0, span - along))
            if made:
                return True
            if after[1] < take_off[1] - 1.5:
                return False  # fell off: find another way up
        return False


class Stay(Task):
    name = "stay"

    def run(self):
        self.ctx.body.call("stop")
        home = self.ctx.eye_and_view()[3]
        while not self.done():
            # Stays put, but doesn't stand there and take hits.
            if self.guard(owner_radius=0.0, self_radius=4.0):
                p = home
                self.ctx.body.call(f"goto {p[0]:.2f} {p[1]:.2f} {p[2]:.2f} --near 1 --timeout 6")
                continue
            self._announced = False
            time.sleep(0.5)


class Idle(Stay):
    """What Keve does between orders: stand by, fight back, and once nothing's been crafted
    for a while, pack up the crafting table he left out."""
    name = "idle"
    PACK_AFTER = 20

    def run(self):
        ctx = self.ctx
        ctx.body.call("stop")
        home = ctx.eye_and_view()[3]
        while not self.done():
            if self.guard(owner_radius=0.0, self_radius=4.0):
                ctx.body.call(f"goto {home[0]:.2f} {home[1]:.2f} {home[2]:.2f} --near 1 --timeout 6")
                continue
            if ctx.placed_stations and time.time() - ctx.last_craft_time > self.PACK_AFTER:
                self.pack_up()
            time.sleep(0.5)

    def pack_up(self):
        import craft
        ctx = self.ctx
        crafter = craft.Crafter(ctx, self)
        here = ctx.eye_and_view()[3]
        for pos in list(ctx.placed_stations):
            if self.done():
                return
            ctx.placed_stations.remove(pos)
            if math.dist(here, pos) > 6:
                continue  # left behind somewhere else: it's part of the world now
            r = ctx.senses.call(f"blocks {pos[0]} {pos[1]} {pos[2]} {pos[0]} {pos[1]} {pos[2]}")
            if not any("crafting_table" in b[3] for b in r.get("blocks", [])):
                continue
            crafter.pick_up_station(pos)


class Gather(Task):
    name = "gather"

    def run(self):
        what = self.args.get("item", "wood")
        want = int(self.args.get("count", 10))
        block_ok, item_ok = GATHER[what]
        self.ctx.quest_ok = item_ok
        ctx = self.ctx
        shown = what.replace("_", " ")

        def have():
            return sum(n for i, n in ctx.counts().items() if item_ok(i))

        start = have()
        goal = start + want
        if what in NEEDS_PICKAXE and not ctx.has(PICKAXES):
            ctx.say(f"I need a pickaxe for {shown}.")
            return
        explores = 0
        breaks = 0
        # Never mine much more than asked, even when drops go missing (fell in a hole,
        # landed out of reach): a few spare blocks, then pick up what's around and stop.
        max_breaks = want + max(3, want // 3)
        deadline = time.time() + float(self.args.get("max_seconds", 180 + 20 * want))
        while not self.done():
            if time.time() > deadline:
                got = have() - start
                if not self.args.get("quiet_fail"):
                    ctx.say(f"I could only get {got} {shown}, the rest is out of reach." if got else
                            f"I can't reach any {shown} from here.")
                return
            # Don't keep digging while something is eating it (on a nonstop job, help you
            # with yours too), then carry on.
            if self.guard(owner_radius=8.0 if self.args.get("endless") else 0.0, self_radius=4.0):
                continue
            got = have()
            if got >= goal or breaks >= max_breaks:
                ctx.last_item = what
                for _ in range(2):
                    time.sleep(0.7)
                    ctx.collect(10, self)
                    got = have()
                    if got >= goal:
                        break
                if got - start >= want:
                    ctx.say(f"got {got - start} {shown}!")
                else:
                    ctx.say(f"mined {breaks} but only picked up {got - start} {shown}, some drops got away.")
                if self.args.get("give"):
                    Give(ctx, item=what).run_inner(self)
                return
            # The nearest remembered target that hasn't failed too often.
            _, _, _, pos = ctx.eye_and_view()
            targets = [p for p, (n, _) in ctx.memory.items()
                       if block_ok(n) and ctx.bad_targets.get(p, 0) < 2 and not ctx.protected(p)]
            if what == "wood" and targets:
                targets = self.easy_trunks(targets, block_ok, pos)
            if not targets:
                if not ctx.look_around(block_ok):
                    if what in ("wood", "sand", "dirt", "sugar_cane", "pumpkin", "melon") and explores == 0                             and not getattr(self, "_went_up", False):
                        import mining
                        self._went_up = True
                        if mining.underground(ctx) and mining.go_to_surface(ctx, self):
                            continue  # look again up here
                    if explores >= self.args.get("max_explores", 6):
                        if not self.args.get("quiet_fail"):
                            ctx.say(f"I can't find any {shown} I can see around here.")
                        return
                    explores += 1
                    if ctx.in_hole():
                        ctx.climb_out(self)  # down a pit (last night's shelter): out first
                    ang = random.uniform(0, 2 * math.pi)
                    tx, tz = pos[0] + 14 * math.cos(ang), pos[2] + 14 * math.sin(ang)
                    ctx.body.call(f"goto {tx:.1f} {pos[1]:.1f} {tz:.1f} --near 3 --timeout 12 --direct")
                continue
            # Lowest first (tree trunks from the bottom), then nearest.
            t = min(targets, key=lambda p: (math.dist(p, pos) // 4, p[1], math.dist(p, pos)))
            if math.dist((t[0] + 0.5, t[1] + 0.5, t[2] + 0.5), pos) > 4.0:
                r = ctx.body.call(f"goto {t[0] + 0.5:.1f} {t[1]:.1f} {t[2] + 0.5:.1f} --near 3 --timeout 20")
                if self.done():
                    return
                if not r.get("arrived") and r.get("distance", 99) > 4.5:
                    ctx.bad_targets[t] = 2  # no way to it: don't keep trying this one
                    import journal
                    journal.log("note", f"gather {what}: can't walk to {t}", why=str(r.get("error", ""))[:120])
                    self._no_path = getattr(self, "_no_path", 0) + 1
                    if self._no_path >= 3 and ctx.clear_leaves_around():
                        # Boxed in under leaves (a low canopy at head height): punched
                        # out, so try those trees again.
                        self._no_path = 0
                        for k in [k for k, v in ctx.bad_targets.items() if v >= 2]:
                            ctx.bad_targets.pop(k, None)
                    continue
            seen = ctx.still_there_and_visible(t, block_ok)
            if seen == "gone":
                continue
            if seen == "hidden":
                ctx.bad_targets[t] = ctx.bad_targets.get(t, 0) + 1
                import journal
                journal.log("note", f"gather {what}: {t} is hidden from where I stand")
                continue
            if what == "wood":
                # Like a player: knock out the bottom of the trunk, step into its spot, and
                # chop straight up. The logs drop on Keve's head instead of rolling off.
                self.reverted = False
                n = self.fell_tree(t, block_ok)
                if self.done():
                    return
                if self.reverted:
                    ctx.no_break_here(t)
                    continue
                if n == 0:
                    ctx.bad_targets[t] = ctx.bad_targets.get(t, 0) + 1
                    import journal
                    journal.log("note", f"gather wood: couldn't chop the trunk at {t}")
                    continue
                breaks += n
                time.sleep(0.6)
                ctx.collect(6, self)
                if self.args.get("endless") and breaks // 16 != (breaks - n) // 16:
                    if self.endless_check(what, shown, have, start) == "stop":
                        return
                    start = getattr(self, "_restart", start)
                ctx.look_around(block_ok, pitches=(-40.0, 0.0))
                ctx.maybe_eat()
                continue
            if what == "wood":
                ctx.select_best(AXES)
            elif what in NEEDS_PICKAXE:
                ctx.select_best(PICKAXES)
            ctx.body.call(f"look-at block {t[0]} {t[1]} {t[2]}")
            r = ctx.body.call(f"break {t[0]} {t[1]} {t[2]} --timeout 15")
            if self.done():
                return
            if r.get("error"):
                ctx.bad_targets[t] = ctx.bad_targets.get(t, 0) + 1
                continue
            ctx.memory.pop(t, None)
            ctx.recent_breaks.append((t[0], t[1], t[2], time.time()))
            breaks += 1
            if self.args.get("endless") and breaks % 16 == 0:
                if self.endless_check(what, shown, have, start) == "stop":
                    return
                start = getattr(self, "_restart", start)
            # Pick up the drop. A fresh drop can't be picked up for 10 ticks (0.5 s), so
            # wait that out first; sand and gravel can also fall and drops can roll.
            time.sleep(0.7)
            ctx.collect(5, self)
            if self.done():
                return
            # Look up and around the broken spot: the log above is visible now.
            ctx.look_around(block_ok, pitches=(-40.0, 0.0))
            ctx.maybe_eat()


    def easy_trunks(self, logs, block_ok, pos):
        """Only the easy logs: the foot of a trunk that stands on the ground. A log up in
        the leaves (a branch, the top of a tall tree already chopped) means climbing the
        tree, so it's skipped. Each trunk is aimed at its bottom log."""
        snap = sight.Snapshot.read(self.ctx.senses, pos, rh=18, rv=10)
        bases = set()
        for x, y, z in logs:
            b = y
            while block_ok(snap.name((x, b - 1, z))) and b > y - 12:
                b -= 1
            ground = snap.name((x, b - 1, z))
            if not sight.blocks_body(ground) or "leaves" in ground or b > pos[1] + 6:
                continue
            if self.ctx.bad_targets.get((x, b, z), 0) < 2:
                bases.add((x, b, z))
        return list(bases)

    def endless_check(self, what, shown, have, start):
        """Every 16 blocks of a nonstop job: say the count; full pockets go in the job's
        chest if there is one (then carry on), else stop. 'stop' when the job should end."""
        ctx = self.ctx
        inv = ctx.body.call("inventory")
        used = [s for s in inv.get("hotbar", []) + inv.get("main", []) if s.get("item")]
        if self.args.get("new_chest") and not ctx.store_chest:
            import containers
            t = containers.NewChest(ctx, put=what)  # 'and put it in a new chest': once there's wood for one
            t.cancelled = self.cancelled
            t.run()
            self._restart = have()
            return "go"
        if len(used) >= 35 and ctx.store_chest:
            ctx.say(f"pockets full! dropping the {shown} off in the chest.")
            import containers
            t = containers.PutInChest(ctx, item=what, pos=ctx.store_chest)
            t.cancelled = self.cancelled
            t.run()
            self._restart = have()
            return "go"
        if len(used) >= 35:
            ctx.say(f"my pockets are FULL! {have() - start} {shown} so far. "
                    f"take some, or tell me to make a chest for them.")
            return "stop"
        ctx.say(f"{have() - start} {shown} and counting!")
        return "go"

    def fell_tree(self, t, block_ok):
        """Chop one trunk column the way a player does: break the bottom one or two logs
        from the side, step into the gap, then break straight up as far as Keve reaches.
        How many logs came down."""
        ctx = self.ctx
        x, _, z = t
        snap = sight.Snapshot.read(ctx.senses, t, rh=2, rv=8)
        base = t[1]
        while block_ok(snap.name((x, base - 1, z))) and base > t[1] - 8:
            base -= 1
        broken = 0

        def chop(p):
            ctx.select_best(AXES)
            ctx.body.call(f"look-at block {p[0]} {p[1]} {p[2]}")
            r = ctx.body.call(f"break {p[0]} {p[1]} {p[2]} --timeout 15")
            for _ in range(3):  # leaves (or a bush) in front of the trunk: through them first
                m = re.search(r"(minecraft:[a-z_]+) at \[(-?\d+), (-?\d+), (-?\d+)\] is in the way", str(r.get("error", "")))
                if not m or not any(k in m.group(1) for k in ("leaves", "litter", "grass", "fern", "bush", "vine", "flower")):
                    break
                q = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
                ctx.body.call(f"look-at block {q[0]} {q[1]} {q[2]}")
                ctx.body.call(f"break {q[0]} {q[1]} {q[2]} --timeout 5")
                ctx.body.call(f"look-at block {p[0]} {p[1]} {p[2]}")
                r = ctx.body.call(f"break {p[0]} {p[1]} {p[2]} --timeout 15")
            if r.get("error"):
                import journal
                journal.log("note", f"chop {p}: {str(r['error'])[:160]}")
                return False
            if ctx.block_came_back(p, block_ok):
                self.reverted = True  # the server put it back: protected ground
                return False
            ctx.memory.pop(p, None)
            ctx.recent_breaks.append((p[0], p[1], p[2], time.time()))
            return True

        for y in (base, base + 1):
            p = (x, y, z)
            if not block_ok(sight.Snapshot.read(ctx.senses, p, rh=1, rv=1).name(p)):
                break
            if self.done():
                return broken
            if math.dist(ctx.eye_and_view()[0], (x + .5, y + .5, z + .5)) > 4.3:
                ctx.body.call(f"goto {x + 0.5:.1f} {base:.1f} {z + 0.5:.1f} --near 2.5 --timeout 10")
            if not chop(p):
                return broken
            broken += 1
        if broken == 0 or not sight.blocks_body(snap.name((x, base - 1, z))):
            return broken  # a lone log, or the trunk doesn't stand on the ground
        # Step into the trunk's spot (both blocks are open now) and work upward.
        ctx.body.call(f"goto {x + 0.5:.2f} {base:.2f} {z + 0.5:.2f} --near 0.3 --timeout 4 --direct")
        me = ctx.state()["player"]["block_pos"]
        if (me[0], me[2]) != (x, z):
            return broken  # couldn't get under it: the next pass takes what's left
        for y in range(base + 2, base + 12):
            if self.done():
                return broken
            p = (x, y, z)
            eye = ctx.eye_and_view()[0]
            if math.dist(eye, (x + .5, y + .5, z + .5)) > 4.5:
                break  # out of reach: the rest of a tall tree comes later
            s = sight.Snapshot.read(ctx.senses, p, rh=1, rv=1)
            if not block_ok(s.name(p)) or not s.block_visible(eye, p, 5.0):
                break
            if not chop(p):
                break
            broken += 1
        return broken


ANIMAL_WORDS = {
    "cow": "cow", "cows": "cow", "pig": "pig", "pigs": "pig", "sheep": "sheep", "chicken": "chicken",
    "chickens": "chicken", "rabbit": "rabbit", "rabbits": "rabbit", "goat": "goat", "goats": "goat",
    "mooshroom": "mooshroom", "zombie": "zombie", "zombies": "zombie", "skeleton": "skeleton",
    "skeletons": "skeleton", "spider": "spider", "spiders": "spider", "creeper": "creeper",
    "creepers": "creeper", "slime": "slime", "slimes": "slime", "witch": "witch", "husk": "husk",
    "drowned": "drowned", "enderman": "enderman", "squid": "squid", "salmon": "salmon", "cod": "cod",
}
# What you can ask for that comes from an animal.
DROP_ANIMALS = {"beef": "cow", "steak": "cow", "leather": "cow", "pork": "pig", "porkchop": "pig",
                "porkchops": "pig", "bacon": "pig", "mutton": "sheep", "wool": "sheep",
                "feathers": "chicken", "feather": "chicken", "eggs": "chicken", "rabbit hide": "rabbit"}


class Hunt(Task):
    """'keve kill this cow' / 'kill 3 pigs' / 'get me some leather': the nearest of that
    animal Keve can see (near you), until enough are down."""
    name = "hunt"

    def run(self):
        ctx = self.ctx
        kind = self.args.get("mob")  # e.g. "cow"; None: the nearest animal or mob by you
        want = int(self.args.get("count", 1))
        killed = 0
        misses = 0
        while killed < want and not self.done():
            target = self.find(kind)
            if target is None:
                misses += 1
                if misses > 2:
                    break
                ctx.look_around(lambda n: False)  # turn around and look
                continue
            misses = 0
            ctx.select_best(WEAPONS)
            ctx.hunt(target["id"], 20.0, self)
            if self.done():
                return
            gone = not any(e.get("id") == target["id"] for e in
                           ctx.senses.call("entities 24").get("entities", []))
            if gone:
                killed += 1
        shown = (kind or "mob").replace("_", " ")
        if self.done():
            return
        if killed:
            ctx.collect(6, self)
            ctx.say(f"got the {shown}." if want == 1 else f"killed {killed} {shown}s.")
            if self.args.get("give"):
                drops = [i for i in ctx.counts() if any(k in i for k in
                         ("beef", "leather", "porkchop", "mutton", "wool", "chicken", "feather",
                          "rabbit", "string", "bone", "rotten_flesh", "gunpowder"))]
                if drops:
                    Give(ctx, items=drops).run_inner(self)
        else:
            ctx.say(f"I don't see any {shown} around here.")

    def find(self, kind):
        """The nearest visible mob of that kind, near the player first (for 'this cow')."""
        ctx = self.ctx
        eye, yaw, pitch, pos = ctx.eye_and_view()
        o = ctx.owner()
        mobs = [e for e in ctx.senses.call("entities 32").get("entities", [])
                if e.get("kind") == "mob" and e.get("type") != "minecraft:player"
                and (kind is None or e.get("type", "").removeprefix("minecraft:") == kind)
                and (e.get("health") is None or e["health"] > 0)]
        if not mobs:
            return None
        snap = sight.Snapshot.read(ctx.senses, eye)
        seen = [m for m in mobs if sight.entity_visible(snap, eye, yaw, pitch, tuple(m["pos"]),
                                                        height=1.2, need_fov=False)]
        if not seen:
            return None
        around = o[1] if o else pos
        return min(seen, key=lambda m: math.dist(tuple(m["pos"]), around))


class Give(Task):
    """Walk to the owner, face them and drop the items (all of a kind, or everything)."""
    name = "give"

    def run(self):
        self.run_inner(self)

    def run_inner(self, task):
        ctx = self.ctx
        what = self.args.get("item")  # a GATHER word, or None for everything
        exact = self.args.get("items")  # exact item ids, e.g. from mining or crafting
        import craft
        if exact:
            ids = {i if ":" in i else "minecraft:" + i for i in exact}
            # A family name ("boat", "bed") means any of them: an oak boat is a boat.
            tests = [craft.INGREDIENTS.get(i.removeprefix("minecraft:")) for i in ids]
            item_ok = lambda i: i in ids or any(t is not None and t(i) for t in tests)  # noqa: E731
            what = ", ".join(sorted(i.removeprefix("minecraft:").replace("_", " ") for i in ids))
        else:
            if what is None and not self.args.get("everything") and ctx.last_item:
                what = ctx.last_item  # "bring them to me": what it just gathered
            short = (what or "").removeprefix("minecraft:")
            if what in GATHER:
                item_ok = GATHER[what][1]
            elif short in craft.INGREDIENTS:
                item_ok = craft.INGREDIENTS[short]  # something it made: that, not everything
                what = short
            elif what and not self.args.get("everything"):
                item_ok = lambda i, w=what: i == w or i == "minecraft:" + w  # noqa: E731
            else:
                item_ok = lambda i: True  # noqa: E731
        items = [i for i, n in ctx.counts().items() if n > 0 and item_ok(i)]
        if not items and exact and len(exact) == 1:
            # "give me a stone pickaxe" with none on hand: get one first, then hand it over.
            import mining
            if mining.Provision(ctx, task).obtain(next(iter(ids)), int(self.args.get("count", 1))):
                items = [i for i, n in ctx.counts().items() if n > 0 and item_ok(i)]
        if not items:
            ctx.say(f"I don't have any {what or 'items'}.")
            return
        o = ctx.owner()
        if not o:
            ctx.say("where are you? I can't find you.")
            return
        # Chase them: you keep walking, so re-read where you are every short leg
        # instead of walking to where you stood when you asked.
        end = time.time() + 60
        stuck = 0
        last_d = None
        told = False
        while True:
            if task.done():
                return
            o = ctx.owner() or o
            _, _, _, pos = ctx.eye_and_view()
            d = math.dist(pos, o[1])
            if d <= 2.4:
                break
            if time.time() > end or stuck >= 6:
                ctx.say("I can't catch up with you. stand still a sec?" if not told else
                        "I can't get to you to hand them over.")
                if told:
                    return
                told, end, stuck = True, time.time() + 20, 0
                continue
            if d > 4.0:
                ctx.walk_to(o[1], near=2, timeout=2, task=task)
            else:
                # Close: step straight in (the planner stops a little short).
                ctx.body.call(f"look-at entity {o[0]}")
                ctx.body.call("move forward 0.2 --sprint")
            stuck = stuck + 1 if last_d is not None and d > last_d - 0.3 else 0
            last_d = d
        given = 0
        start_counts = ctx.counts()
        total = sum(start_counts.get(i, 0) for i in items)
        for item in items:
            for _ in range(40):  # one stack per drop
                if task.done():
                    return
                n = ctx.counts().get(item, 0)
                if n <= 0 or given >= total:
                    break  # all handed over (or what's back in his pockets was picked up again)
                o = ctx.owner() or o
                # Measured: from about 2 blocks away, aimed at the feet, a dropped stack
                # lands within a few tenths of a block of them. Closer than 1.5 and it lands
                # under both players and Keve picks it back up; farther and it falls short.
                for _ in range(12):
                    _, _, _, pos = ctx.eye_and_view()
                    d = math.dist(pos, o[1])
                    if 1.8 <= d <= 2.6 or task.done():
                        break
                    if d < 1.8:  # you walked right up to him: back off, or it lands at his feet
                        ctx.body.call(f"look-at entity {o[0]}")
                        ctx.body.call("move back 0.3")
                    else:  # they moved off mid hand-over: catch up again
                        ctx.body.call(f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} "
                                      f"--near 2 --sprint --timeout 2")
                    o = ctx.owner() or o
                ctx.body.call(f"look-at {o[1][0]:.2f} {o[1][1] + 0.1:.2f} {o[1][2]:.2f}")
                if not ctx.body.call(f"select {item}").get("error"):
                    r = ctx.body.call("drop all")
                    given += (r.get("dropped_from") or {}).get("count", 0)
                    ctx.body.call("move back 0.4")  # out of reach of the stack before it can be picked up
                else:
                    # Not on the hotbar: open the inventory, pick the stack up and close it.
                    # A stack still held on the cursor when the screen closes is thrown.
                    slot = ctx.slot_of(item)
                    if slot is None:
                        break
                    ctx.body.call("open-inventory")
                    ctx.body.call(f"click-slot {slot}")
                    ctx.body.call("close")
                    given += n - ctx.counts().get(item, 0)
                time.sleep(0.2)
        if given:
            # Step back: a dropped stack can be picked up again after 2 s, by anyone close.
            ctx.body.call("move back 0.8")
        ctx.say(f"here you go: {given} {(what or 'items').replace('_', ' ')}." if given else
                "couldn't hand them over.")


class Defend(Task):
    name = "defend"

    def run(self):
        ctx = self.ctx
        while not self.done():
            if self.guard(owner_radius=12.0, self_radius=5.0):
                continue
            self._announced = False
            o = ctx.owner()
            if not o:
                time.sleep(1.0)
                continue
            _, _, _, pos = ctx.eye_and_view()
            if math.dist(pos, o[1]) > 6:
                ctx.walk_to(o[1], near=3, timeout=4, task=self)
            else:
                time.sleep(0.4)
            ctx.maybe_eat()


class Status(Task):
    name = "status"

    def run(self):
        st = self.ctx.state()["player"]
        counts = self.ctx.counts()
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
        items = ", ".join(f"{n} {k.removeprefix('minecraft:')}" for k, n in top) or "nothing"
        self.ctx.say(f"hp {st['health']:.0f}/20, food {st['food']}/20. carrying: {items}")


class Jump(Task):
    name = "jump"

    def run(self):
        self.ctx.body.call("jump")


class LookAtMe(Task):
    name = "look"

    def run(self):
        o = self.ctx.owner()
        if o:
            self.ctx.body.call(f"look-at entity {o[0]}")


class Help(Task):
    name = "help"

    def run(self):
        for line in HELP_LINES:
            self.ctx.say(line)
            time.sleep(0.35)


HELP_LINES = [
    "things you can tell me (start with 'keve'):",
    "follow me / come here / stay / stop / play with me (I do my own thing alongside you)",
    "get 10 wood, grab 5 dirt, collect sand, get some sugar cane ...and bring them to me",
    "mine for diamonds / get me 10 iron / go mine some coal (I make my own pickaxes)",
    "make a stone pickaxe / craft 16 torches / make a furnace",
    "defend me / this is home / go home / remember this as the mine / go to the mine",
    "craft torches from the chest / get the coal from the chest / put your stuff in the chest",
    "chain orders: get 10 wood then make a crafting table then come back",
    "dig out this room bigger / replace the floor or walls with cobblestone / place torches in this room / watch me <do something> ... ok did u see / copy what i did",
    "any block or animal: mine this coal / open that door / kill this cow / what do you see",
    "plant the sapling / plant 3 oak saplings / plant the seeds",
    "give me your sand / give me everything / what you got / or just talk to me.",
]

class HandOver(Task):
    """You crouched twice next to Keve: he drops what he's got for the job (the wood he's
    chopping, what he made for you), then carries on with the job."""
    name = "handover"

    def run(self):
        ctx = self.ctx
        import brain
        ctx.say(brain.line("handover", "here, catch!"))
        Give(ctx, items=self.args.get("items")).run_inner(self)
        resume = self.args.get("resume")
        if resume and not self.done():
            skill, args = resume
            t = SKILLS[skill](ctx, **args)
            t.cancelled = self.cancelled
            t.run()


SKILLS = {c.name: c for c in (Come, Follow, Stay, Idle, Gather, Give, Hunt, Defend, Status, Jump, LookAtMe,
                              Help, HandOver)}
