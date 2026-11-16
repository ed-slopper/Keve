"""Keve's skills: small state machines that drive the body through whitelisted commands.

Every skill runs on the task thread, checks `self.cancelled` between steps, and reports
in chat. Long actions (goto, break, hunt) block in the game until done or until the main
thread sends `stop` on the other connection.
"""
import math
import random
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
        self.say = say            # send a chat line
        self.owner_name = owner_name
        self.self_name = self_name
        self.memory = {}          # (x, y, z) -> (block name, time seen); filled only by sight
        self.bad_targets = {}     # (x, y, z) -> failures
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

    def drop_junk(self, keep_cobble=64):
        """When the inventory is getting full, throw away stone and dirt it doesn't need."""
        inv = self.body.call("inventory")
        slots = [s for s in inv.get("hotbar", []) + inv.get("main", []) if s.get("item")]
        if len(slots) < 30:
            return
        yaw = self.state()["player"]["yaw"]
        self.body.call(f"look {yaw + 180:.0f} 20")  # throw it behind, back up the tunnel
        cobble = 0
        for s in slots:
            it = s["item"]
            if it == "minecraft:cobblestone":
                cobble += s.get("count", 0)
                if cobble <= keep_cobble:
                    continue
            elif not any(j in it for j in self.JUNK):
                continue
            self.body.call("open-inventory")
            self.body.call(f"click-slot {s['slot']}")
            self.body.call("close")  # a stack held on the cursor is thrown when it closes

    def select_best(self, short_names):
        n = self.has(short_names)
        if n:
            self.body.call(f"select minecraft:{n}")
        return n

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
            items = [e for e in ents if e.get("kind") == "item" and e["id"] not in tried]
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
            mob = next((e for e in ents if e["id"] == mob_id), None)
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
        if p.get("air", 300) < 120:
            self.body.call("key space down")
            self.body.call("wait 15")
            self.body.call("key space up")
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
        acted = False
        for _ in range(12):
            px, py, pz = p["position"]
            x, y, z = p["block_pos"]
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
                    self.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 10")
            acted = True
            self.body.call("wait 10")  # fall
            try:
                p = self.state()["player"]
            except Exception:
                return acted
        return acted
    def maybe_eat(self):
        try:
            food = self.state()["player"]["food"]
        except Exception:
            return
        if food <= 14:
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
        if not targets:
            return False
        m = min(targets, key=lambda m: m["distance"])
        if not getattr(self, "_announced", False):
            ctx.say(random.choice(["got one!", "behind you!", "I see it!", "on it!"]))
            self._announced = True
        ctx.select_best(WEAPONS)
        ctx.hunt(m["id"], 10.0, self)
        return True


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
        else:
            self.ctx.say(f"couldn't get to you ({r.get('error', 'no path')}).")


class Follow(Task):
    name = "follow"

    def run(self):
        stuck = 0
        last_eat = 0.0
        while not self.done():
            # A friend who follows you also fights what's attacking you.
            if self.guard():
                continue
            self._announced = False
            o = self.ctx.owner()
            if not o:
                time.sleep(1.0)
                continue
            eye, _, _, pos = self.ctx.eye_and_view()
            d = math.dist(pos, o[1])
            if d > 4.5:
                r = self.ctx.walk_to(o[1], near=3, timeout=4, task=self)
                if self.done():
                    return
                stuck = 0 if r.get("arrived") or r.get("distance", 99) < d - 1 else stuck + 1
                if stuck == 4:
                    self.ctx.say("wait up, I'm stuck!")
                    self.ctx.body.call("jump")
            else:
                self.ctx.body.call(f"look-at entity {o[0]}")
                time.sleep(0.5)
            if time.time() - last_eat > 10:
                self.ctx.maybe_eat()
                last_eat = time.time()


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
    """What Keve does between orders: stand by and fight back."""
    name = "idle"


class Gather(Task):
    name = "gather"

    def run(self):
        what = self.args.get("item", "wood")
        want = int(self.args.get("count", 10))
        block_ok, item_ok = GATHER[what]
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
            # Don't keep digging while something is eating it.
            if self.guard(owner_radius=0.0, self_radius=4.0):
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
                       if block_ok(n) and ctx.bad_targets.get(p, 0) < 2]
            if not targets:
                if not ctx.look_around(block_ok):
                    if explores >= self.args.get("max_explores", 6):
                        if not self.args.get("quiet_fail"):
                            ctx.say(f"I can't find any {shown} I can see around here.")
                        return
                    explores += 1
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
                    continue
            seen = ctx.still_there_and_visible(t, block_ok)
            if seen == "gone":
                continue
            if seen == "hidden":
                ctx.bad_targets[t] = ctx.bad_targets.get(t, 0) + 1
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
            # Pick up the drop. A fresh drop can't be picked up for 10 ticks (0.5 s), so
            # wait that out first; sand and gravel can also fall and drops can roll.
            time.sleep(0.7)
            ctx.collect(5, self)
            if self.done():
                return
            # Look up and around the broken spot: the log above is visible now.
            ctx.look_around(block_ok, pitches=(-40.0, 0.0))
            ctx.maybe_eat()


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
            gone = not any(e["id"] == target["id"] for e in
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
        if exact:
            ids = {i if ":" in i else "minecraft:" + i for i in exact}
            item_ok = lambda i: i in ids  # noqa: E731
            what = ", ".join(sorted(i.removeprefix("minecraft:").replace("_", " ") for i in ids))
        else:
            if what is None and not self.args.get("everything") and ctx.last_item:
                what = ctx.last_item  # "bring them to me": what it just gathered
            item_ok = GATHER[what][1] if what in GATHER else (lambda i: True)
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
        for item in items:
            for _ in range(40):  # one stack per drop
                if task.done():
                    return
                n = ctx.counts().get(item, 0)
                if n <= 0:
                    break
                o = ctx.owner() or o
                # Measured: from about 2 blocks away, aimed at the feet, a dropped stack
                # lands within a few tenths of a block of them. Closer than 1.5 and it lands
                # under both players and Keve picks it back up; farther and it falls short.
                for _ in range(10):
                    _, _, _, pos = ctx.eye_and_view()
                    d = math.dist(pos, o[1])
                    if 1.5 <= d <= 2.5 or task.done():
                        break
                    if d < 1.5:
                        ctx.body.call(f"look-at entity {o[0]}")
                        ctx.body.call("move back 0.15")
                    else:  # they moved off mid hand-over: catch up again
                        ctx.body.call(f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} "
                                      f"--near 2 --sprint --timeout 2")
                    o = ctx.owner() or o
                ctx.body.call(f"look-at {o[1][0]:.2f} {o[1][1] + 0.1:.2f} {o[1][2]:.2f}")
                if not ctx.body.call(f"select {item}").get("error"):
                    r = ctx.body.call("drop all")
                    given += (r.get("dropped_from") or {}).get("count", 0)
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
    "place torches in this room / watch me <do something> ... ok did u see / copy what i did",
    "any block or animal: mine this coal / open that door / kill this cow / what do you see",
    "plant the sapling / plant 3 oak saplings / plant the seeds",
    "give me your sand / give me everything / what you got / or just talk to me.",
]

SKILLS = {c.name: c for c in (Come, Follow, Stay, Idle, Gather, Give, Hunt, Defend, Status, Jump, LookAtMe, Help)}
