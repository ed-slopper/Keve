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
from skills import (FOODS, GATHER, PICKAXES, Gather, Give, Task, base)

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


RAW_NAMES = {"log": "logs", "cobble": "cobblestone", "iron_ingot": "iron ingots", "coal": "coal"}


class Provision:
    """Get an item by crafting it, gathering or mining what it needs first."""

    def __init__(self, ctx, task):
        self.ctx = ctx
        self.task = task
        self.crafter = craft.Crafter(ctx, task)
        self.goal = None           # the item asked for, so a nearby chest is checked for its recipe
        self.chest_checked = False

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
        if depth == 0 and self.goal is None:
            self.goal = item
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
        if not self.chest_checked and self.goal:
            # Like a player: look in the chest right here before walking off for materials.
            self.chest_checked = True
            import containers
            if containers.take_for_recipe(ctx, self.task, self.goal, quiet=True):
                return True
        if what == "log":
            ctx.say(f"need wood first, getting {n + 1} logs")
            self.sub(Gather, item="wood", count=n + 1)
        elif what == "cobble":
            if self.pick_tier() < 0 and not self.ensure("wooden_pickaxe", 1, depth + 1):
                return False
            ctx.say(f"getting {n + 2} cobblestone")
            before = self.crafter.count("cobble")
            # Stone close by and in sight first (a cliff, a cave mouth); otherwise dig down right
            # here, like a player would, instead of walking off to find bare stone.
            import blocks as _blocks
            eye = ctx.eye_and_view()[0]
            near = _blocks.nearest_visible(ctx, {"minecraft:stone", "minecraft:deepslate", "minecraft:andesite",
                                                 "minecraft:diorite", "minecraft:granite", "minecraft:tuff"},
                                           eye, radius=10)
            if near is not None and math.dist(near, eye) <= 10:
                t = Gather(ctx, item="stone", count=n + 2, quiet_fail=True, max_explores=0)
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
        elif what.endswith("_log") or what.startswith("tag:") and "log" in what:
            ctx.say(f"need wood first, getting {n + 1} logs")
            self.sub(Gather, item="wood", count=n + 1)  # any tree; the planks follow the wood
        elif what in GATHER:
            ctx.say(f"getting {n} {what.replace('_', ' ')} first")
            self.sub(Gather, item=what, count=n)
        elif what in ORES or what in ("diamond", "redstone", "lapis_lazuli", "emerald"):
            ore = {"lapis_lazuli": "lapis"}.get(what, what)
            if ore in ORES:
                ctx.say(f"I need {n} {what.replace('_', ' ')}, going mining for it.")
                self.sub(Mine, ore=ore, count=n)
            else:
                return False
        else:
            shown = what.removeprefix("tag:").removeprefix("any:").split(",")[0].replace("_", " ")
            ctx.say(f"I need {n} {shown} for that, and I don't know how to get it myself yet. "
                    f"if you give me some, I'll make it!")
            self.missing = (what, n)
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

    # --- getting any item, thinking it through out loud ----------------------------------
    def recipe_text(self, item):
        """'crafting table = 4 planks', 'stone pickaxe = 3 cobblestone + 2 sticks'."""
        size, pattern, makes = craft.RECIPES[item]
        parts = {}
        for ing in pattern.values():
            parts[ing] = parts.get(ing, 0) + 1
        words = {"cobble": "cobblestone", "planks": "planks", "stick": "sticks", "log": "logs",
                 "coal": "coal", "iron_ingot": "iron ingots"}
        made = f"{makes} " if makes > 1 else ""
        need = " + ".join(f"{n} {words.get(i, i.replace('_', ' '))}" for i, n in parts.items())
        table = ", at a crafting table" if size == 3 else ""
        return f"{made}{item.replace('_', ' ')} = {need}{table}"

    def obtain(self, item_id, count=1, talk=True):
        """Have `count` of any item: from the inventory, else by crafting it (its recipe,
        then what's missing, then where to get that), else by breaking that block.
        Says the plan as it goes. True when Keve has them."""
        ctx = self.ctx
        short = item_id.removeprefix("minecraft:")
        have = ctx.counts().get("minecraft:" + short, 0)
        if have >= count:
            return True
        if short in craft.RECIPES:
            if talk:
                missing = self.crafter.raw_needs(short, count - have)
                plan = self.recipe_text(short)
                if missing:
                    words = {"log": "logs", "cobble": "cobblestone", "coal": "coal",
                             "iron_ingot": "iron ingots", "raw_iron": "raw iron"}
                    gets = ", ".join(f"{n} {words.get(k, k.replace('_', ' '))}" for k, n in missing.items())
                    ctx.say(f"no {short.replace('_', ' ')} on me. {plan}. I'm missing {gets}, getting that first.")
                else:
                    ctx.say(f"no {short.replace('_', ' ')} on me, but I've got the stuff: {plan}. crafting!")
            try:
                ok = self.ensure(short, count)
            except RuntimeError as e:
                ctx.say(f"couldn't craft it: {e}")
                return False
            return ok and ctx.counts().get("minecraft:" + short, 0) >= count
        import world_names
        names = world_names.names()
        if names and item_id in names.blocks:
            # A block you get by breaking one (dirt, glass needs silk touch: it may drop nothing).
            if talk:
                ctx.say(f"no {short.replace('_', ' ')} on me, I'll go break some.")
            import blocks
            t = blocks.BreakBlocks(ctx, ids=[item_id], label=short.replace("_", " "),
                                   count=count - have, near_owner=False)
            t.cancelled = self.task.cancelled
            t.run()
            return ctx.counts().get("minecraft:" + short, 0) >= count
        if talk:
            ctx.say(f"I don't know how to get {short.replace('_', ' ')} yet.")
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
            self.ctx.last_item = "minecraft:" + item
            self.ctx.made_batch.append("minecraft:" + item)
            o = self.ctx.owner()
            if o:
                self.ctx.body.call(f"look-at entity {o[0]}")  # done at the table: back to you
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
    """'keve mine for diamonds' / 'go get 10 iron' / 'mine some coal'.

    Keve remembers every staircase he digs (memory.json: its top, each step, its bottom)
    and marks the first one as 'the mine'. Next time he goes mining near one, or near a
    place you called a mine, he walks down the old stairs and digs on from the bottom."""
    name = "mine"
    MAX_MINUTES = 20
    NEAR_MINE = 48
    track = None  # the staircase being dug (none for a quick dig for stone)
    steps = 0

    def run(self):
        self.track = None
        try:
            self._run()
        finally:
            self.save_track()

    # --- remembered staircases ---------------------------------------------------------
    def known_mines(self):
        import life
        mem = life.load_memory()
        mines = [dict(m) for m in mem.get("mines", [])]
        for name, pos in mem.get("places", {}).items():
            if "mine" in name and not any(math.dist(m["top"], pos) < 4 for m in mines):
                mines.append({"top": pos, "path": [], "name": name})
        return mines

    def save_track(self):
        t = self.track
        if not t or len(t["path"]) < 3:
            return
        import life
        mem = life.load_memory()
        mines = [m for m in mem.get("mines", []) if math.dist(m["top"], t["top"]) >= 3]
        t["bottom"] = t["path"][-1]
        t["updated"] = time.time()
        mines.append({k: t[k] for k in ("top", "path", "bottom", "dir", "updated")})
        mem["mines"] = mines[-12:]
        places = mem.setdefault("places", {})
        if "mine" not in places or math.dist(places["mine"], t["top"]) < 4:
            if "mine" not in places:
                x, y, z = t["top"]
                self.ctx.say(f"marked my mine at {x:.0f} {y:.0f} {z:.0f}, I'll use these stairs next time.")
            places["mine"] = [round(v, 2) for v in t["top"]]
        life.save_memory(mem)

    def reuse_staircase(self, best_y):
        """Walk down a staircase dug before, if one starts near here. True when used."""
        ctx = self.ctx
        here = ctx.state()["player"]["position"]
        near = [m for m in self.known_mines() if math.dist(m["top"], here) <= self.NEAR_MINE]
        if not near:
            return False
        m = min(near, key=lambda m: math.dist(m["top"], here))
        x, y, z = m["top"]
        ctx.say(f"I know a staircase at {x:.0f} {y:.0f} {z:.0f}, taking that down!")
        for _ in range(6):
            if self.done():
                return False
            if math.dist(ctx.state()["player"]["position"], m["top"]) < 2.5:
                break
            ctx.walk_to(tuple(m["top"]), near=1.5, timeout=20, task=self)
        if math.dist(ctx.state()["player"]["position"], m["top"]) > 4:
            ctx.say("couldn't get to the old stairs, I'll dig new ones here.")
            return False
        path = [tuple(p) for p in m.get("path", [])]
        self.track = {"top": list(m["top"]), "path": [list(p) for p in path], "dir": m.get("dir")}
        if m.get("dir"):
            self.dir = tuple(m["dir"])
        # The recorded steps, a few at a time (the steps are open, so the planner walks them).
        for wp in path[2::3] + path[-1:]:
            if self.done():
                return True
            if wp[1] < best_y - 1:
                break
            r = ctx.body.call(f"goto {wp[0] + 0.5:.2f} {wp[1]:.2f} {wp[2] + 0.5:.2f} --near 1.2 --timeout 10")
            if not r.get("arrived") and math.dist(ctx.state()["player"]["position"], wp) > 2.5:
                break  # caved in or blocked: dig on from here
        self.follow_open_stairs(best_y)
        return True

    def follow_open_stairs(self, best_y):
        """Keep walking down open steps Keve can see (a staircase it didn't record, or
        the rest of one). Stops where the stairs end."""
        ctx = self.ctx
        dirs = DIRS
        for _ in range(400):
            if self.done():
                return
            x, y, z = self.pos()
            if y <= best_y:
                return
            s = self.snap((x, y, z), 3)
            order = ([self.dir] if self.dir else []) + [d for d in dirs if d != self.dir]
            went = False
            for dx, dz in order:
                feet, head, top, floor = ((x + dx, y - 1, z + dz), (x + dx, y, z + dz),
                                          (x + dx, y + 1, z + dz), (x + dx, y - 2, z + dz))
                if any(is_solid(s.name(c)) or sight.is_fluid(s.name(c)) for c in (feet, head, top)):
                    continue
                if not is_solid(s.name(floor)):
                    continue
                if self.walk_to(feet):
                    self.dir = (dx, dz)
                    if self.track is not None:
                        self.track["path"].append(list(feet))
                        self.track["dir"] = list(self.dir)
                    went = True
                    break
            if not went:
                return

    def _run(self):
        ctx = self.ctx
        ore = self.args.get("ore", "iron")
        want = int(self.args.get("count", 5 if ore == "diamond" else 10))
        blocks, drops, tier, best_y = ORES[ore]
        self.prov = Provision(ctx, self)
        self.wanted = {ore, "coal"}  # coal on the way too: torches for the dark
        self.deadline = time.time() + self.MAX_MINUTES * 60
        self.drop_names = {"minecraft:" + d for d in drops}
        ctx.quest_ok = lambda i: i in self.drop_names or i in ("minecraft:raw_iron", "minecraft:coal")
        self.start_have = self.have()
        self.goal = want
        # 1. Tools: at least a stone pickaxe (iron comes from the mine itself).
        try:
            have_pick = self.prov.ensure_pickaxe(min(tier, 1))
        except RuntimeError as e:
            ctx.say(f"couldn't make a pickaxe: {e}")
            return
        if not have_pick:
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
        if not self.reuse_staircase(best_y) or self.track is None:
            self.track = {"top": list(ctx.state()["player"]["position"]), "path": [], "dir": list(self.dir)}
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
            if self.heal():
                return False  # patched up: on with the trip
            if self.done():
                return True
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

    def heal(self):
        """Hurt mid-trip: back up the stairs out of the fight, eat, and wait to heal up.
        True when he's well enough to go on (a couple of heals per trip at most)."""
        ctx = self.ctx
        self.heals = getattr(self, "heals", 0) + 1
        if self.heals > 3:
            return False
        ctx.say("ouch! backing off to heal up, then I'll keep going.")
        path = (self.track or {}).get("path") or []
        if len(path) > 6:
            back = path[-6]
            ctx.body.call(f"goto {back[0] + 0.5:.2f} {back[1]:.2f} {back[2] + 0.5:.2f} --near 1 --timeout 8 --sprint")
        end = time.time() + 90
        while time.time() < end and not self.done():
            if self.guard(owner_radius=0.0, self_radius=4.0):
                continue  # something followed him: deal with it
            ctx.maybe_eat(below=19)
            try:
                st = ctx.state()["player"]
            except Exception:
                return False
            if st.get("health", 0) >= 14:
                ctx.say("feeling better! back to it.")
                return True
            if st.get("food", 20) < 18 and not ctx.has(FOODS):
                break  # no food: he won't heal (health comes back only when well fed)
            time.sleep(2.0)
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

    # --- caves: where the mobs come from --------------------------------------------
    def seal_cave(self, opened, at):
        """Did digging just open a hole into a cave? Small openings get boarded up with
        cobblestone (the mobs in there can't get at him); a big cave means turning the
        staircase another way. True: carry on this way. False: this way is shut."""
        tunnel = {tuple(c) for c in opened} | {at, (at[0], at[1] + 1, at[2]), (at[0], at[1] + 2, at[2])}
        for p in ((self.track or {}).get("path") or [])[-12:]:
            p = tuple(p)
            tunnel |= {p, (p[0], p[1] + 1, p[2]), (p[0], p[1] + 2, p[2])}
        snap = self.snap(opened[0], 5)
        holes = set()
        for c in opened:
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                n = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if n in tunnel:
                    continue
                name = snap.name(n)
                if not is_solid(name) and not sight.is_fluid(name) and "torch" not in name:
                    holes.add(n)
        if not holes:
            return True
        # How big is the open space behind the holes? (A pocket of one or two is nothing.)
        seen, todo = set(holes), list(holes)
        while todo and len(seen) < 40:
            p = todo.pop()
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                n = (p[0] + d[0], p[1] + d[1], p[2] + d[2])
                if n in seen or n in tunnel or math.dist(n, at) > 6:
                    continue
                name = snap.name(n)
                if not is_solid(name) and not sight.is_fluid(name):
                    seen.add(n)
                    todo.append(n)
        if len(seen) < 4:
            return True
        cobble = self.counts_of("cobblestone") + self.counts_of("cobbled_deepslate")
        if len(seen) >= 40 or cobble < len(holes):
            self.ctx.say("a big cave! boarding it up and digging another way.")
            self.plug(sorted(opened, key=lambda c: -c[1]))
            self.cave_turns = getattr(self, "cave_turns", 0) + 1
            return False
        self.ctx.say("a cave! boarding it up.")
        self.plug(sorted(holes, key=lambda c: c[1]))
        return True

    def light_the_way(self):
        """Dark where he stands: a torch on the step behind him (making some first from
        coal and sticks if he has the coal)."""
        x, y, z = self.pos()
        if self.steps - getattr(self, "last_torch", -99) < 4 or not self.ctx.is_dark_at((x, y, z)):
            return
        if not self.counts_of("torch") and self.counts_of("coal") + self.counts_of("charcoal"):
            only = getattr(self.prov, "only_inventory", False)
            self.prov.only_inventory = True  # from what he carries: no trip for it
            try:
                self.prov.ensure("torch", 8)
            except Exception:
                pass
            self.prov.only_inventory = only
        if not self.counts_of("torch"):
            return
        dx, dz = self.dir
        for spot in ((x - dx, y, z - dz), (x - dx, y + 1, z - dz)):
            if not self.ctx.place(spot, "torch").get("error"):
                self.last_torch = self.steps
                return

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
        if not self.seal_cave(front, (x, y, z)):
            return False  # a big cave that way: boarded up, the stairs go another way
        floor = (x + dx, y - 2, z + dz)
        if not is_solid(self.snap(floor, 1).name(floor)):
            self.ctx.say("there's a drop here, going another way.")
            self.plug([front[2]])
            return False
        ok = self.walk_to((x + dx, y - 1, z + dz))
        if ok and getattr(self, "track", None) is not None:
            self.track["path"].append([x + dx, y - 1, z + dz])
            self.track["dir"] = list(self.dir)
        return ok

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
        if not self.seal_cave(front, (x, y, z)):
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
        self.light_the_way()
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
