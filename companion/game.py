"""'keve beat the game': the whole run, stage by stage, from punching trees to the dragon.

Each stage has a check (is it done? from what Keve carries and wears) and a way to do it
(the skills he already has). Progress lives in memory.json under "quest", so the run
carries on after a death or a restart. When a stage won't go after a few tries, Keve says
where he's stuck and why (and the session log has it), and the run waits there: that's
the bit to teach him next.

Stages Keve can't do yet say so plainly ("not learned yet") instead of pretending.
"""
import time

import journal
import life
from skills import Task

FOOD = ("cooked_beef", "cooked_porkchop", "cooked_mutton", "cooked_chicken", "cooked_rabbit",
        "bread", "baked_potato", "cooked_cod", "cooked_salmon", "apple", "carrot", "golden_carrot")
RAW_MEAT = ("beef", "porkchop", "mutton", "chicken", "rabbit", "cod", "salmon")
ANIMALS = ("cow", "pig", "sheep", "chicken", "rabbit", "goat")


def have(ctx, *names, n=1):
    counts = ctx.counts()
    return sum(counts.get("minecraft:" + x, 0) for x in names) >= n


def wearing(ctx, piece):
    try:
        inv = ctx.body.call("inventory")
    except Exception:
        return False
    return any(piece in (a.get("item") or "") for a in inv.get("armor", []))


class BeatTheGame(Task):
    name = "beat_game"
    TRIES = 3

    def stages(self):
        c = self.ctx
        return [
            ("stone tools", lambda: have(c, "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe")
                and have(c, "stone_sword", "iron_sword", "diamond_sword")
                and have(c, "stone_axe", "iron_axe", "diamond_axe"), self.stone_tools),
            ("food", lambda: have(c, *FOOD, n=8), self.food),
            ("iron", lambda: self.iron_done(), self.iron),
            ("iron gear", lambda: have(c, "iron_pickaxe", "diamond_pickaxe") and have(c, "iron_sword", "diamond_sword")
                and have(c, "bucket", "water_bucket", "lava_bucket") and wearing(c, "chestplate"), self.iron_gear),
            ("diamonds", lambda: have(c, "diamond_pickaxe") and have(c, "diamond_sword"), self.diamonds),
            ("obsidian", lambda: have(c, "obsidian", n=10), self.not_yet("making obsidian (water on lava)")),
            ("nether portal", lambda: self.flag("portal"), self.not_yet("building and lighting a nether portal")),
            ("blaze rods", lambda: have(c, "blaze_rod", "blaze_powder", n=6), self.not_yet("finding a nether fortress and blazes")),
            ("ender pearls", lambda: have(c, "ender_pearl", "ender_eye", n=12), self.not_yet("hunting endermen")),
            ("eyes of ender", lambda: have(c, "ender_eye", n=12), self.not_yet("crafting eyes of ender")),
            ("stronghold", lambda: self.flag("end_portal"), self.not_yet("following eyes of ender to the stronghold")),
            ("the dragon", lambda: self.flag("dragon"), self.not_yet("fighting the ender dragon")),
        ]

    # --- progress, kept between deaths and sessions ---------------------------------
    def progress(self):
        return life.load_memory().get("quest", {"done": [], "stuck": {}, "flags": {}})

    def save(self, q):
        mem = life.load_memory()
        mem["quest"] = q
        life.save_memory(mem)

    def flag(self, name):
        return bool(self.progress().get("flags", {}).get(name))

    def run(self):
        ctx = self.ctx
        q = self.progress()
        ctx.say("ok, let's BEAT THE GAME! stage by stage, all the way to the dragon.")
        if not self.night() and ctx.in_hole():
            ctx.climb_out(self)
        for name, check, do in self.stages():
            if self.done():
                return
            if check():
                if name not in q["done"]:
                    q["done"].append(name)
                    self.save(q)
                continue
            journal.log("quest", f"stage: {name}")
            ctx.say(f"next up: {name}!")
            self.shelter()  # dark out? wait for morning first
            for attempt in range(self.TRIES):
                if self.done():
                    return
                said_before = len(getattr(ctx, "said_log", []))
                try:
                    do()
                except Exception as e:  # a skill crashing is a thing to fix: write it down
                    import traceback
                    journal.log("quest", f"{name}: crashed", error=repr(e)[:300],
                                trace=traceback.format_exc()[-1500:])
                if self.done():
                    return
                if check():
                    break
                why = getattr(ctx, "said_log", [])[said_before:][-3:]
                q = self.progress()
                q["stuck"].setdefault(name, []).append({"t": time.time(), "said": why})
                self.save(q)
                journal.log("quest", f"{name}: try {attempt + 1} didn't finish it", said=why)
                if getattr(self, "_cant", False):
                    break
            if not check():
                journal.log("quest", f"stuck at: {name}")
                ctx.say(f"I'm stuck at {name}. that's where I need to get better!")
                return
            q = self.progress()
            if name not in q["done"]:
                q["done"].append(name)
            self.save(q)
            journal.log("quest", f"done: {name}")
            ctx.say(f"{name}: done!")
        ctx.say("WE BEAT THE GAME!!!")

    def sub(self, cls, **args):
        t = cls(self.ctx, **args)
        t.cancelled = self.cancelled
        t.run()

    # --- the stages ---------------------------------------------------------------
    def stone_tools(self):
        import life as _life
        steps = [(s, {"item": s, "count": 1}) for s in ("stone_pickaxe", "stone_sword", "stone_axe")
                 if not have(self.ctx, s)]
        self.sub(_life.Sequence, steps=[("craft", a) for _, a in steps])

    def food(self):
        """Hunt what's around, then cook it (raw meat is poor food). Nothing in sight: go
        looking, a good walk in a new direction each time, like a player would."""
        import math
        import random
        from skills import Hunt
        ctx = self.ctx
        heading = random.uniform(0, 2 * math.pi)
        # Somewhere he found animals before: go there first.
        herds = life.load_memory().get("herds", [])
        if herds and not self.done():
            here = ctx.eye_and_view()[3]
            spot = min(herds, key=lambda h: math.dist((h[0], h[2]), (here[0], here[2])))
            if math.dist((spot[0], spot[2]), (here[0], here[2])) > 24:
                ctx.say(f"I found animals around {spot[0]:.0f} {spot[2]:.0f} before, heading there!")
                journal.log("quest", "food: going to a herd I know", to=spot)
                for _ in range(5):  # travel goes ~120 blocks a go: far ones take a few
                    here = ctx.eye_and_view()[3]
                    if self.done() or math.dist((spot[0], spot[2]), (here[0], here[2])) < 20:
                        break
                    if self.travel(spot[0], spot[2], step=12) < 3:
                        break  # not getting anywhere
        for trip in range(6):
            if self.done() or have(ctx, *FOOD, *RAW_MEAT, n=10):
                break
            seen = {e.get("type", "").removeprefix("minecraft:") for e in
                    ctx.senses.call("entities 40").get("entities", []) if e.get("kind") == "mob"}
            for kind in [a for a in ANIMALS if a in seen]:
                if self.done() or have(ctx, *FOOD, *RAW_MEAT, n=10):
                    break
                # Behind a hill or a tree: walk over to where it is, then hunt it.
                near = [e for e in ctx.senses.call("entities 40").get("entities", [])
                        if e.get("type", "").removeprefix("minecraft:") == kind]
                if near:
                    t = min(near, key=lambda e: e["distance"])["pos"]
                    ctx.walk_to(tuple(t), near=4, timeout=20, task=self)
                    self.remember_herd(t)
                self.sub(Hunt, mob=kind, count=4)
            if have(ctx, *FOOD, *RAW_MEAT, n=10):
                break
            pos = ctx.eye_and_view()[3]
            heading += random.uniform(-0.5, 0.5)  # mostly straight on: out of a bare biome (a desert)
            tx, tz = pos[0] + 40 * math.cos(heading), pos[2] + 40 * math.sin(heading)
            journal.log("quest", "food: no animals here, looking further", to=[round(tx), round(tz)])
            moved = self.travel(tx, tz)
            journal.log("quest", f"food: walked {moved:.0f} blocks")
        self.cook()

    # --- nights: dig in, like a player without a bed ------------------------------
    def night(self):
        try:
            t = self.ctx.body.call("status").get("day_time", 6000) % 24000
        except Exception:
            return False
        return 12000 <= t <= 23300  # from dusk: skeletons are out in the shade before full dark

    def shelter(self):
        """Dark out and he's on the surface: two blocks down, a block over his head, wait
        for morning, climb out. (The mobs are out at night; a hole is safe.)"""
        import mining
        ctx = self.ctx
        if not self.night() or mining.underground(ctx):
            return
        ctx.say("it's getting dark, digging in for the night!")
        journal.log("quest", "night: sheltering")
        m = mining.Mine(ctx, ore="coal")
        m.cancelled = self.cancelled
        m.prov = mining.Provision(ctx, m)
        x, y, z = m.pos()
        # Three down: the lid then sits in the ground layer, with dirt round it to hold it
        # (two down, it'd float in the air at surface height and can't be placed).
        for c in ((x, y - 1, z), (x, y - 2, z), (x, y - 3, z)):
            m.dig_through(c)
        ctx.body.call(f"goto {x + 0.5:.2f} {y - 3:.2f} {z + 0.5:.2f} --near 0.4 --timeout 3 --direct")
        if not ctx.roof_over():
            journal.log("quest", "night: couldn't cover the shelter")
        end = time.time() + 12 * 60
        while self.night() and time.time() < end and not self.done():
            if self.guard(owner_radius=0.0, self_radius=3.0):
                continue
            ctx.maybe_eat()
            time.sleep(5)
        if self.done():
            return
        ctx.say("morning! back to it.")
        ctx.climb_out(self)

    def travel(self, tx, tz, step=10):
        """Walk toward (tx, tz) over whatever's in the way, in straight legs of `step`
        blocks (the path planner wants a real spot to stand on, which a point 40 blocks
        off usually isn't: inside a hill, up in the air). How far he got."""
        import math
        ctx = self.ctx
        start = ctx.eye_and_view()[3]
        stuck = 0
        for _ in range(12):
            if self.done():
                break
            if self.night():
                self.shelter()
            pos = ctx.eye_and_view()[3]
            d = math.hypot(tx - pos[0], tz - pos[2])
            if d < 4:
                break
            k = min(1.0, step / d)
            lx, lz = pos[0] + (tx - pos[0]) * k, pos[2] + (tz - pos[2]) * k
            if self.safe_line(pos, lx, lz):
                ctx.body.call(f"goto {lx:.1f} {pos[1]:.1f} {lz:.1f} --near 2 --timeout 8 --direct --sprint")
            else:
                # A cliff or tree tops that way: let the path planner (it won't drop more
                # than three blocks) find the way, or turn a bit.
                r = ctx.walk_to((lx, pos[1], lz), near=4, timeout=10, task=self)
                if not r.get("arrived") and r.get("distance", 99) > 6:
                    ang = math.atan2(tz - pos[2], tx - pos[0]) + 1.0
                    dist = math.hypot(tx - pos[0], tz - pos[2])
                    tx, tz = pos[0] + dist * math.cos(ang), pos[2] + dist * math.sin(ang)
            if self.guard(owner_radius=0.0, self_radius=5.0):
                continue
            after = ctx.eye_and_view()[3]
            if math.hypot(after[0] - pos[0], after[2] - pos[2]) < 2:
                stuck += 1
                if stuck >= 3:
                    break
                self.climb_out(tx, tz)  # down a hole (the one he dug for stone): up out of it
            else:
                stuck = 0
        end = ctx.eye_and_view()[3]
        return math.hypot(end[0] - start[0], end[2] - start[2])

    def safe_line(self, pos, lx, lz):
        """Can he walk straight there? No drop of more than three blocks on the way, and no
        walking over tree tops (he'd fall off the leaves)."""
        import math
        import sight
        ctx = self.ctx
        snap = sight.Snapshot.read(ctx.senses, pos, rh=12, rv=8)
        y0 = math.floor(pos[1])
        n = max(2, int(math.hypot(lx - pos[0], lz - pos[2])))
        for i in range(1, n + 1):
            f = i / n
            x, z = math.floor(pos[0] + (lx - pos[0]) * f), math.floor(pos[2] + (lz - pos[2]) * f)
            floor = None
            for y in range(y0 + 2, y0 - 6, -1):
                name = snap.name((x, y - 1, z))
                if sight.blocks_body(name) or sight.is_fluid(name):
                    floor = (y, name)
                    break
            if floor is None or y0 - floor[0] > 3 or "leaves" in floor[1] or "dripstone" in floor[1]                     or "lava" in floor[1] or "magma" in floor[1]:
                return False
        return True

    def climb_out(self, tx, tz, steps=6):
        """Out of a pit: dig steps up toward where he's headed, a few blocks."""
        import math
        import mining
        m = mining.Mine(self.ctx, ore="coal")
        m.cancelled = self.cancelled
        m.prov = mining.Provision(self.ctx, m)
        pos = self.ctx.eye_and_view()[3]
        ang = math.atan2(tz - pos[2], tx - pos[0])
        m.dir = min(mining.DIRS, key=lambda d: abs((math.atan2(d[1], d[0]) - ang + math.pi) % (2 * math.pi) - math.pi))
        for _ in range(steps):
            if self.done() or not m.stair_up():
                break

    def remember_herd(self, pos):
        mem = life.load_memory()
        herds = [h for h in mem.get("herds", []) if ((h[0] - pos[0]) ** 2 + (h[2] - pos[2]) ** 2) ** 0.5 > 30]
        mem["herds"] = (herds + [[round(pos[0]), round(pos[1]), round(pos[2])]])[-12:]
        life.save_memory(mem)

    def cook(self):
        import craft
        import mining
        prov = mining.Provision(self.ctx, self)
        # One kind at a time (a furnace cooks one stack): all the beef, then the chicken...
        for meat in RAW_MEAT:
            raw = min(64, self.ctx.counts().get("minecraft:" + meat, 0))
            if not raw or self.done():
                continue
            try:
                prov.ensure("furnace", 1)
                prov.crafter.smelt(meat, raw)
            except (craft.NeedMore, RuntimeError) as e:
                if getattr(e, "what", "") == "fuel":
                    prov.get_raw("log", max(3, raw // 4), 0)
                    try:
                        prov.crafter.smelt(meat, min(raw, self.ctx.counts().get("minecraft:" + meat, 0)))
                    except (craft.NeedMore, RuntimeError):
                        pass
                # else: the meat's gone (he died, or ate it): nothing to cook

    IRON = 17  # pickaxe 3, sword 2, bucket 3, chestplate 8, flint and steel 1

    def iron_done(self):
        c = self.ctx.counts()
        spent = 3 * c.get("minecraft:iron_pickaxe", 0) + 2 * c.get("minecraft:iron_sword", 0) \
            + 3 * (c.get("minecraft:bucket", 0) + c.get("minecraft:water_bucket", 0)) \
            + (8 if wearing(self.ctx, "iron_chestplate") else 8 * c.get("minecraft:iron_chestplate", 0))
        return c.get("minecraft:iron_ingot", 0) + c.get("minecraft:raw_iron", 0) + spent >= self.IRON

    def iron(self):
        import mining
        c = self.ctx.counts()
        need = self.IRON - c.get("minecraft:iron_ingot", 0) - c.get("minecraft:raw_iron", 0)
        if need > 0:
            self.sub(mining.Mine, ore="iron", count=need)
        raw = self.ctx.counts().get("minecraft:raw_iron", 0)
        if raw:
            prov = mining.Provision(self.ctx, self)
            prov.smelt("raw_iron", raw)

    def iron_gear(self):
        import life as _life
        steps = [("craft", {"item": i, "count": 1}) for i in ("iron_pickaxe", "iron_sword", "bucket", "iron_chestplate")
                 if not have(self.ctx, i) and not (i == "iron_chestplate" and wearing(self.ctx, "chestplate"))]
        if steps:
            self.sub(_life.Sequence, steps=steps)
        self.wear("iron_chestplate")

    def wear(self, item):
        """Right-click armour in hand to put it on, like a player."""
        if wearing(self.ctx, item.split("_")[-1]) or not have(self.ctx, item):
            return
        self.ctx.body.call(f"select minecraft:{item}")
        self.ctx.body.call("use-item")
        time.sleep(0.3)

    def diamonds(self):
        import life as _life
        import mining
        n = self.ctx.counts().get("minecraft:diamond", 0)
        if n < 5:
            self.sub(mining.Mine, ore="diamond", count=5 - n)
        steps = [("craft", {"item": i, "count": 1}) for i in ("diamond_pickaxe", "diamond_sword") if not have(self.ctx, i)]
        if steps:
            self.sub(_life.Sequence, steps=steps)

    def not_yet(self, what):
        def run():
            self._cant = True
            self.ctx.say(f"I don't know how to do this part yet: {what}.")
        return run
