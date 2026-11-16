"""Going underground like a player: get the tools, dig a staircase down, branch-mine at
the ore's level, take the ores it can actually see, and keep away from lava.

No X-ray: an ore is only known once a face of it is visible (tunnel walls, floors,
ceilings and caves Keve opens up). Nothing behind a block is known until it's broken,
so after every break Keve looks into the hole and backs off from lava, water and drops.
"""
import math
import time

import craft
import sight
from skills import (GATHER, PICKAXES, Gather, Give, Task, base)

# ore: (blocks, drops, pickaxe tier needed, best Y)
ORES = {
    "coal": ({"coal_ore", "deepslate_coal_ore"}, {"coal"}, 0, 44),
    "copper": ({"copper_ore", "deepslate_copper_ore"}, {"raw_copper"}, 1, 48),
    "iron": ({"iron_ore", "deepslate_iron_ore"}, {"raw_iron"}, 1, 16),
    "lapis": ({"lapis_ore", "deepslate_lapis_ore"}, {"lapis_lazuli"}, 1, 0),
    "gold": ({"gold_ore", "deepslate_gold_ore"}, {"raw_gold"}, 2, -16),
    "redstone": ({"redstone_ore", "deepslate_redstone_ore"}, {"redstone"}, 2, -58),
    "diamond": ({"diamond_ore", "deepslate_diamond_ore"}, {"diamond"}, 2, -58),
    "emerald": ({"emerald_ore", "deepslate_emerald_ore"}, {"emerald"}, 2, 16),
}
PICK_TIER = {"wooden_pickaxe": 0, "golden_pickaxe": 0, "stone_pickaxe": 1, "iron_pickaxe": 2,
             "diamond_pickaxe": 3, "netherite_pickaxe": 4}
TIER_PICK = {0: "wooden_pickaxe", 1: "stone_pickaxe", 2: "iron_pickaxe"}
DIRS = [(0, 1), (-1, 0), (0, -1), (1, 0)]  # south, west, north, east (yaw 0, 90, 180, 270)
DANGER = ("lava", "water", "fire")
UNBREAKABLE = ("bedrock", "barrier", "end_portal_frame", "reinforced_deepslate")


def ore_of(name):
    b = base(name).removeprefix("minecraft:")
    for ore, (blocks, _, _, _) in ORES.items():
        if b in blocks:
            return ore
    return None


is_solid = sight.blocks_body


class Provision:
    """Get an item by crafting it, gathering or mining what it needs first."""

    def __init__(self, ctx, task):
        self.ctx = ctx
        self.task = task
        self.crafter = craft.Crafter(ctx, task)

    def pick_tier(self):
        counts = self.ctx.counts()
        tiers = [t for p, t in PICK_TIER.items() if counts.get("minecraft:" + p, 0) > 0]
        return max(tiers) if tiers else -1

    def sub(self, cls, **args):
        """Run another skill as a step of this one (stopping this stops it too)."""
        t = cls(self.ctx, **args)
        t.cancelled = self.task.cancelled
        t.run()

    def ensure(self, item, count=1, depth=0):
        """Have at least `count` of a craftable item. False when it can't be done here."""
        if depth > 6 or self.task.done():
            return False
        for _ in range(8):
            if self.task.done():
                return False
            have = self.crafter.count(item) if item in craft.INGREDIENTS else 0
            if have >= count:
                return True
            try:
                self.crafter.craft(item, count - have)
            except craft.NeedMore as need:
                if not self.get_raw(need.what, need.count, depth):
                    return False
        return self.crafter.count(item) >= count

    def get_raw(self, what, n, depth):
        ctx = self.ctx
        if getattr(self, "only_inventory", False):
            self.missing = (what, n)
            return False
        if what == "log":
            ctx.say(f"need wood first, getting {n + 1} logs")
            self.sub(Gather, item="wood", count=n + 1)
        elif what == "cobble":
            if self.pick_tier() < 0 and not self.ensure("wooden_pickaxe", 1, depth + 1):
                return False
            ctx.say(f"getting {n + 2} cobblestone")
            before = self.crafter.count("cobble")
            # Stone in sight first; if there's none, dig down for it like a player would.
            t = Gather(ctx, item="stone", count=n + 2, quiet_fail=True, max_explores=1)
            t.cancelled = self.task.cancelled
            t.run()
            if self.crafter.count("cobble") - before < n:
                dig_for_stone(ctx, self.task, self.crafter.count("cobble") + n + 2)
        elif what == "iron_ingot":
            raw = self.crafter.count("raw_iron")
            if raw < n:
                return False  # needs mining: the caller handles it
            self.smelt("raw_iron", n)
        elif what in ("coal", "fuel"):
            ctx.say("need fuel, getting some wood")
            self.sub(Gather, item="wood", count=3)
        else:
            return False
        return True

    def smelt(self, raw, n):
        for _ in range(3):
            try:
                self.crafter.smelt(raw, n)
                return True
            except craft.NeedMore as need:
                if need.what == "furnace" or need.what == "cobble":
                    if not self.ensure("furnace", 1):
                        return False
                elif need.what == "fuel":
                    self.sub(Gather, item="wood", count=3)
                else:
                    return False
        return False

    def ensure_pickaxe(self, tier):
        """A pickaxe good enough for `tier` (0 wooden, 1 stone, 2 iron)."""
        if self.pick_tier() >= tier:
            return True
        if tier >= 2:
            if self.crafter.count("iron_ingot") < 3 and self.crafter.count("raw_iron") >= 3 - \
                    self.crafter.count("iron_ingot"):
                self.smelt("raw_iron", 3 - self.crafter.count("iron_ingot"))
            if self.crafter.count("iron_ingot") >= 3:
                return self.ensure("iron_pickaxe")
            return False
        return self.ensure(TIER_PICK[tier])


def dig_for_stone(ctx, task, target):
    """A short staircase down until Keve carries `target` cobblestone, then back up."""
    m = Mine(ctx, ore="coal")
    m.cancelled = task.cancelled
    m.prov = Provision(ctx, m)
    m.wanted = {"coal"}
    p = ctx.state()["player"]
    home = tuple(p["position"])
    m.dir = DIRS[round(((p["yaw"] % 360) / 90)) % 4]
    m.steps = 0
    ctx.say("no stone in sight, digging down for some.")
    for _ in range(24):
        if task.done() or m.prov.crafter.count("cobble") >= target:
            break
        ctx.select_best(PICKAXES)
        if not m.stair_step():
            m.turn()
            continue
        if m.steps % 3 == 0:
            ctx.collect(3, task)
        m.steps += 1
    ctx.collect(4, task)
    for _ in range(6):
        if task.done() or math.dist(ctx.state()["player"]["position"], home) < 2:
            break
        ctx.body.call(f"goto {home[0]:.2f} {home[1]:.2f} {home[2]:.2f} --near 1.5 --timeout 10")


class Craft(Task):
    """'keve make a stone pickaxe' / 'craft 16 torches'."""
    name = "craft"

    def run(self):
        item = self.args.get("item")
        count = int(self.args.get("count", 1))
        prov = Provision(self.ctx, self)
        shown = item.replace("_", " ")
        if item not in craft.RECIPES:
            self.ctx.say(f"I don't know how to make {shown} yet.")
            return
        if self.args.get("from_chest"):
            import containers
            containers.take_for_recipe(self.ctx, self, item)
            prov.only_inventory = True  # "from the chest": don't go gathering instead
            if self.args.get("count_auto"):
                # No number given: as many as the chest's things make (up to 64).
                makes = craft.RECIPES[item][2]
                n = 64
                while n > makes and prov.crafter.raw_needs(item, n):
                    n -= makes
                count = n
        try:
            ok = prov.ensure(item, prov.crafter.count(item) + count if item in craft.INGREDIENTS else count)
        except RuntimeError as e:
            self.ctx.say(f"couldn't make {shown}: {e}")
            return
        if ok:
            self.ctx.say(f"made {shown}!" if count == 1 else f"made {count} {shown}!")
            if self.args.get("give"):
                Give(self.ctx, item=None, items=[item]).run_inner(self)
        elif not self.done():
            missing = getattr(prov, "missing", None)
            if missing:
                self.ctx.say(f"not enough in there for {shown}: I'm short {missing[1]} "
                             f"{missing[0].replace('_', ' ')}.")
            else:
                need = "iron" if item.startswith("iron_") else "the stuff"
                self.ctx.say(f"couldn't make {shown}, I need {need} for it.")


class Mine(Task):
    """'keve mine for diamonds' / 'go get 10 iron' / 'mine some coal'."""
    name = "mine"
    MAX_MINUTES = 20

    def run(self):
        ctx = self.ctx
        ore = self.args.get("ore", "iron")
        want = int(self.args.get("count", 5 if ore == "diamond" else 10))
        blocks, drops, tier, best_y = ORES[ore]
        self.prov = Provision(ctx, self)
        self.wanted = {ore}
        self.deadline = time.time() + self.MAX_MINUTES * 60
        self.drop_names = {"minecraft:" + d for d in drops}
        self.start_have = self.have()
        self.goal = want
        # 1. Tools: at least a stone pickaxe (iron comes from the mine itself).
        if not self.prov.ensure_pickaxe(min(tier, 1)):
            if not self.done():
                ctx.say("I couldn't make a pickaxe.")
            return
        if tier >= 2 and self.prov.pick_tier() < 2:
            self.wanted |= {"iron", "coal"}
            ctx.say(f"{ore} needs an iron pickaxe, I'll grab iron on the way down.")
        ctx.select_best(PICKAXES)
        p = ctx.state()["player"]
        self.home = tuple(p["position"])
        self.dir = DIRS[round(((p["yaw"] % 360) / 90)) % 4]
        self.steps = 0
        ctx.say(f"heading down to y {best_y} for {ore}.")
        # 2. Staircase down to the ore's level (taking ores seen on the way).
        while not self.finished() and ctx.state()["player"]["block_pos"][1] > best_y:
            if not self.stair_step():
                if not self.turn():
                    break
            self.after_step()
        # 3. Branch mine at that level.
        leg, legs = 0, 0
        while not self.finished():
            if tier >= 2 and self.prov.pick_tier() < 2 and self.counts_of("raw_iron") >= 3:
                self.upgrade_to_iron()
            if leg >= 20:  # serpentine: 20 forward, 3 across, 20 back
                self.turn(right=(legs % 2 == 0))
                for _ in range(3):
                    if not self.tunnel_step():
                        break
                self.turn(right=(legs % 2 == 0))
                leg, legs = 0, legs + 1
            if not self.tunnel_step():
                if not self.turn():
                    break
            leg += 1
            self.after_step()
        self.wrap_up(ore)

    # --- state ------------------------------------------------------------------------
    def counts_of(self, short):
        return self.ctx.counts().get("minecraft:" + short, 0)

    def have(self):
        c = self.ctx.counts()
        return sum(n for i, n in c.items() if i in self.drop_names)

    def finished(self):
        if self.done() or getattr(self, "fell", False):
            return True
        self._checks = getattr(self, "_checks", 0) + 1
        if self._checks % 2 == 0:
            return False  # the heavier checks below every other step
        if self.have() - self.start_have >= self.goal:
            return True
        if time.time() > self.deadline:
            self.ctx.say("been at it a while, coming back up.")
            return True
        st = self.ctx.state()["player"]
        if st["health"] <= 6:
            self.ctx.say("I'm hurt, getting out of here!")
            return True
        inv = self.ctx.body.call("inventory")
        used = sum(1 for s in inv.get("hotbar", []) + inv.get("main", []) if s.get("item"))
        if used >= 35:
            self.ctx.say("my inventory is full.")
            return True
        if self.prov.pick_tier() < 0:
            if not self.prov.ensure_pickaxe(1):
                self.ctx.say("my pickaxe broke and I can't make another.")
                return True
            self.ctx.select_best(PICKAXES)
        return False

    def upgrade_to_iron(self):
        self.ctx.say("got iron, making an iron pickaxe.")
        if self.prov.ensure_pickaxe(2):
            self.ctx.say("iron pickaxe ready!")
            self.ctx.select_best(PICKAXES)

    # --- moving underground -----------------------------------------------------------
    def pos(self):
        return tuple(self.ctx.state()["player"]["block_pos"])

    def turn(self, right=True):
        i = DIRS.index(self.dir)
        self.dir = DIRS[(i + (1 if right else -1)) % 4]
        self.face()
        return True

    def face(self):
        dx, dz = self.dir
        yaw = {(0, 1): 0, (-1, 0): 90, (0, -1): 180, (1, 0): -90}[self.dir]
        self.ctx.body.call(f"look {yaw} 20")

    def snap(self, around, r=4):
        return sight.Snapshot.read(self.ctx.senses, around, rh=r, rv=r)

    def dig(self, cell):
        """Break one block if it's there; False if it's unbreakable or the dig failed."""
        s = self.snap(cell, 1)
        name = s.name(cell)
        if sight.is_fluid(name) or base(name) in ("minecraft:fire", "minecraft:soul_fire"):
            return False
        if not is_solid(name):
            return True
        if any(u in name for u in UNBREAKABLE):
            return False
        self.ctx.body.call(f"look-at block {cell[0]} {cell[1]} {cell[2]}")
        r = self.ctx.body.call(f"break {cell[0]} {cell[1]} {cell[2]} --timeout 12")
        if r.get("error"):
            return False
        self.ctx.recent_breaks.append((cell[0], cell[1], cell[2], time.time()))
        return True

    FALLING = ("gravel", "sand", "concrete_powder", "pointed_dripstone")

    def dig_through(self, cell):
        """Dig a cell clear: again if sand or gravel falls into it."""
        for _ in range(5):
            name = self.snap(cell, 1).name(cell)
            if not is_solid(name):
                return True
            if not self.dig(cell):
                return False
            if not any(f in name for f in self.FALLING):
                return True  # only falling blocks come back
            time.sleep(0.3)
        return not is_solid(self.snap(cell, 1).name(cell))

    def hazard_near(self, cells):
        """Lava or water Keve can now see within 2 blocks of the cells it just opened."""
        eye = tuple(self.ctx.state()["player"]["eye"])
        snap = self.snap(cells[0], 3)
        for pos, name in snap.blocks.items():
            if not sight.is_fluid(name):
                continue
            if min(math.dist(pos, c) for c in cells) <= 2.0 and snap.block_visible(eye, pos):
                return name
        return None

    def plug(self, cells):
        """Fill opened cells back in with cobblestone (before lava flows in)."""
        for c in cells:
            for item in ("cobblestone", "cobbled_deepslate", "dirt"):
                if self.counts_of(item):
                    self.ctx.place(c, item)
                    break

    def walk_to(self, cell):
        """Step into a cell whose floor has been checked. Never a blind step: if the
        walk doesn't arrive, stay put (and if Keve ends up lower than planned, stop)."""
        x, y, z = cell
        self.ctx.body.call(f"goto {x + 0.5:.2f} {y:.2f} {z + 0.5:.2f} --near 0.4 --timeout 3 --direct")
        now = self.pos()
        if now[1] < y - 1:
            self.fell = True
            self.ctx.say("whoa, I fell! stopping here.")
            return False
        return math.dist(now, cell) <= 1.0

    def stair_step(self):
        """One step down the staircase. False when this direction is blocked."""
        x, y, z = self.pos()
        dx, dz = self.dir
        front = [(x + dx, y + 1, z + dz), (x + dx, y, z + dz), (x + dx, y - 1, z + dz)]
        self.face()
        for c in front:
            if not self.dig_through(c):
                return False
        bad = self.hazard_near(front)
        if bad:
            self.ctx.say(f"{base(bad).removeprefix('minecraft:')} ahead, going around it.")
            self.plug(front[::-1])
            return False
        floor = (x + dx, y - 2, z + dz)
        if not is_solid(self.snap(floor, 1).name(floor)):
            self.ctx.say("there's a drop here, going another way.")
            self.plug([front[2]])
            return False
        return self.walk_to((x + dx, y - 1, z + dz))

    def tunnel_step(self):
        """One block of 1x2 tunnel forward."""
        x, y, z = self.pos()
        dx, dz = self.dir
        front = [(x + dx, y + 1, z + dz), (x + dx, y, z + dz)]
        self.face()
        for c in front:
            if not self.dig_through(c):
                return False
        bad = self.hazard_near(front)
        if bad:
            self.ctx.say(f"{base(bad).removeprefix('minecraft:')}! turning back.")
            self.plug(front[::-1])
            return False
        floor = (x + dx, y - 1, z + dz)
        if not is_solid(self.snap(floor, 1).name(floor)):
            # A hole in the floor: put a block in it rather than fall.
            self.plug([floor])
            if not is_solid(self.snap(floor, 1).name(floor)):
                return False
        return self.walk_to((x + dx, y, z + dz))

    def after_step(self):
        """Look around the new spot, take the ores in sight, eat, fight, light the way."""
        self.steps += 1
        if self.guard(owner_radius=0.0, self_radius=4.0):
            return
        self.take_visible_ores()
        if self.steps % 4 == 0:
            self.ctx.collect(3, self)  # the dug blocks' drops
        if self.prov.pick_tier() < 1 and self.prov.crafter.count("cobble") >= 3:
            if self.prov.ensure_pickaxe(1):
                self.ctx.say("made a stone pickaxe.")
        if self.steps % 16 == 0:
            self.ctx.say(f"y {self.pos()[1]}, {self.have() - self.start_have} so far.")
        if self.steps % 8 == 0 and self.counts_of("torch"):
            x, y, z = self.pos()
            dx, dz = self.dir
            self.ctx.place((x - dx, y, z - dz), "torch")
        self.ctx.maybe_eat()
        if self.steps % 6 == 0:
            self.ctx.drop_junk()
        self.ctx.select_best(PICKAXES)

    def take_visible_ores(self):
        """Mine every wanted ore Keve can see from here (and the vein behind it)."""
        for _ in range(12):  # an ore at a time, then look again (veins open up)
            if self.done():
                return
            eye = tuple(self.ctx.state()["player"]["eye"])
            snap = self.snap(eye, 6)
            seen = []
            for pos, name in snap.blocks.items():
                o = ore_of(name)
                if o in self.wanted and ORES[o][2] <= max(self.prov.pick_tier(), 0) and \
                        snap.block_visible(eye, pos, 6.0):
                    seen.append(pos)
            if not seen:
                return
            t = min(seen, key=lambda p: math.dist(p, eye))
            if math.dist((t[0] + 0.5, t[1] + 0.5, t[2] + 0.5), eye) > 4.4:
                self.ctx.body.call(f"goto {t[0] + 0.5:.1f} {t[1]:.1f} {t[2] + 0.5:.1f} --near 3 --timeout 6")
            self.ctx.body.call(f"look-at block {t[0]} {t[1]} {t[2]}")
            r = self.ctx.body.call(f"break {t[0]} {t[1]} {t[2]} --timeout 12")
            if r.get("error"):
                return
            self.ctx.recent_breaks.append((t[0], t[1], t[2], time.time()))
            time.sleep(0.6)
            self.ctx.collect(5, self)

    def wrap_up(self, ore):
        ctx = self.ctx
        got = self.have() - self.start_have
        if self.done():
            return
        ctx.say(f"got {got} {ore}! heading back up." if got else f"no {ore} this time, heading back up.")
        # Back up the staircase (1-block steps, so the path planner can walk it).
        for _ in range(30):
            if self.done():
                return
            if math.dist(ctx.state()["player"]["position"], self.home) < 3:
                break
            h = self.home
            ctx.body.call(f"goto {h[0]:.2f} {h[1]:.2f} {h[2]:.2f} --near 2 --sprint --timeout 15")
        if self.args.get("give") and got:
            Give(ctx, item=None, items=sorted(self.drop_names)).run_inner(self)
