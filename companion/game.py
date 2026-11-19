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
                and (have(c, "stone_axe", "iron_axe", "diamond_axe") or have(c, "oak_log", "birch_log", "spruce_log",
                     "jungle_log", "acacia_log", "dark_oak_log", "mangrove_log", "cherry_log", n=16)), self.stone_tools),
            # (an axe is for wood: with a stack of logs he doesn't need one, and making one by
            # the sea had him digging for cobblestone into the water)
            ("food", lambda: have(c, *FOOD, n=5), self.food),
            ("iron", lambda: self.iron_done(), self.iron),
            ("iron gear", lambda: have(c, "iron_pickaxe", "diamond_pickaxe") and have(c, "iron_sword", "diamond_sword")
                and have(c, "bucket", "water_bucket", "lava_bucket") and self.has_shield(), self.iron_gear),
            ("diamonds", lambda: have(c, "diamond_pickaxe"), self.diamonds),  # the sword is a bonus
            # Armour before the Nether: bare, a ghast's fireball knocked him off a ledge into
            # the lava and piglins took him apart in seconds. (His head slot is his robot head.)
            ("armor", lambda: wearing(c, "chestplate"), self.armor),
            ("obsidian", lambda: have(c, "obsidian", n=10) or self.flag("portal"), self.obsidian),
            ("nether portal", lambda: self.flag("portal"), self.nether_portal),
            ("blaze rods", lambda: c.counts().get("minecraft:blaze_rod", 0) + c.counts().get("minecraft:blaze_powder", 0) // 2
                + c.counts().get("minecraft:ender_eye", 0) // 2 >= 6, self.blaze_rods),
            ("ender pearls", lambda: have(c, "ender_pearl", "ender_eye", n=12), self.ender_pearls),
            ("eyes of ender", lambda: have(c, "ender_eye", n=12), self.eyes),
            ("bow and arrows", lambda: have(c, "bow") and have(c, "arrow", n=24), self.bow),
            ("stronghold", lambda: self.flag("end"), self.stronghold),
            ("the dragon", lambda: self.flag("dragon"), self.dragon),
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
        self.fix_offhand()
        if not self.night() and ctx.in_hole():
            ctx.climb_out(self)
        for name, check, do in self.stages():
            if self.done():
                return
            if name == "food" and name in q["done"] and have(ctx, *FOOD, n=2):
                continue  # done before; he's eaten some since, but he isn't out
            if name == "food" and name in q["done"]:
                try:
                    full = ctx.state()["player"].get("food", 20) >= 14
                except Exception:
                    full = True
                if full:
                    continue  # not hungry: on with the run (the animals round spawn are hunted
                    # out; a 500-block walk for meat he doesn't need yet got the stage stuck)
            if name == "armor" and "armor" in q["done"]:
                c0 = ctx.counts()
                if c0.get("minecraft:diamond", 0) < 8 and c0.get("minecraft:iron_ingot", 0) + c0.get("minecraft:raw_iron", 0) < 8:
                    continue  # worn out again with nothing to hand for a new one: on without it
                    # (an hour and a half round the mined-out spawn found no iron)
            if name in ("iron", "iron gear") and "iron gear" in q["done"]:
                continue  # done before: worn-out tools are the mining trip's business (it
                # gets iron for a new pickaxe itself), not 13 more iron from scratch
            if check():
                if name not in q["done"]:
                    q["done"].append(name)
                    self.save(q)
                continue
            journal.log("quest", f"stage: {name}")
            ctx.say(f"next up: {name}!")
            self.shelter()  # dark out? wait for morning first
            attempt, waits = 0, 0
            while attempt < self.TRIES:
                if self.done():
                    return
                said_before = len(getattr(ctx, "said_log", []))
                try:
                    do()
                except Exception as e:  # a skill crashing is a thing to fix: write it down
                    if ("isn't in the world" in str(e) or "no world open" in str(e)) and waits < 5:
                        waits += 1
                        # Between worlds (a portal, a reconnect): wait for the world to load,
                        # it isn't a failed try (two were gone in two seconds).
                        for _ in range(60):
                            time.sleep(1)
                            try:
                                ctx.state()
                                break
                            except Exception:
                                if self.done():
                                    return
                        continue
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
                attempt += 1
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
        import mining
        if mining.underground(ctx):
            mining.go_to_surface(ctx, self)  # animals live up top
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
            if self.done() or have(ctx, *FOOD, *RAW_MEAT, n=6):
                break
            seen = {e.get("type", "").removeprefix("minecraft:") for e in
                    ctx.senses.call("entities 40").get("entities", []) if e.get("kind") == "mob"}
            for kind in [a for a in ANIMALS if a in seen]:
                if self.done() or have(ctx, *FOOD, *RAW_MEAT, n=6):
                    break
                # Behind a hill or a tree: walk over to where it is, then hunt it.
                near = [e for e in ctx.senses.call("entities 40").get("entities", [])
                        if e.get("type", "").removeprefix("minecraft:") == kind]
                if near:
                    t = min(near, key=lambda e: e["distance"])["pos"]
                    ctx.walk_to(tuple(t), near=4, timeout=20, task=self)
                    self.remember_herd(t)
                self.sub(Hunt, mob=kind, count=4)
            if have(ctx, *FOOD, *RAW_MEAT, n=6):
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
        if not self.night():
            return
        if getattr(self, "night_hunt", False):
            return  # out on purpose: endermen only walk the overworld at night
        skip = getattr(ctx, "skip_night", None)
        if skip:  # training with nights skipped (Keve.bat --skip-nights): straight to morning
            journal.log("quest", "night: skipped (training)")
            skip()
            time.sleep(1)
            return
        if mining.underground(ctx):
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

    IRON = 13  # two pickaxes 6 (one wears out on the way to diamonds), sword 2, bucket 3, shield 1, flint and steel 1 (a shield beats a
               # chestplate for the iron: it stops arrows, and 8 iron is an hour of digging)

    def iron_done(self):
        c = self.ctx.counts()
        spent = 3 * c.get("minecraft:iron_pickaxe", 0) + 2 * c.get("minecraft:iron_sword", 0) \
            + 3 * (c.get("minecraft:bucket", 0) + c.get("minecraft:water_bucket", 0)) \
            + (1 if self.has_shield() else 0)
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
        steps = [("craft", {"item": i, "count": 1}) for i in ("iron_sword", "bucket", "shield")
                 if not have(self.ctx, i) and not (i == "shield" and self.has_shield())]
        picks = self.ctx.counts().get("minecraft:iron_pickaxe", 0)
        if picks < 2 and self.ctx.counts().get("minecraft:iron_ingot", 0) >= 3 * (2 - picks) + 3 * (not have(self.ctx, "bucket")):
            steps.insert(0, ("craft", {"item": "iron_pickaxe", "count": 2 - picks}))
        elif not picks:
            steps.insert(0, ("craft", {"item": "iron_pickaxe", "count": 1}))
        if steps:
            self.sub(_life.Sequence, steps=steps)
        self.hold_shield()

    def has_shield(self):
        if have(self.ctx, "shield"):
            return True
        try:
            inv = self.ctx.body.call("inventory")
        except Exception:
            return False
        return "shield" in str(inv.get("offhand") or "")

    def hold_shield(self):
        """The shield goes in the off hand (F swaps hands), where it blocks. Only when the
        shield really is in his hand: F with anything else in hand sends that to the off hand
        (it sent his iron pickaxe there, and he dug with a torch)."""
        if not have(self.ctx, "shield"):
            return
        self.ctx.to_hotbar("minecraft:shield")
        self.ctx.body.call("select minecraft:shield")
        held = (self.ctx.body.call("inventory").get("held") or {}).get("item", "")
        if "shield" not in held:
            return
        self.ctx.body.call("key f tap")
        time.sleep(0.3)

    def fix_offhand(self):
        """A tool stuck in the off hand (from a swap gone wrong): back into the hand."""
        inv = self.ctx.body.call("inventory")
        off = inv.get("offhand")
        off = (off.get("item") or "") if isinstance(off, dict) else str(off or "")
        if any(k in off for k in ("pickaxe", "sword", "_axe", "shovel")):
            empty = next((s["slot"] for s in inv.get("hotbar", []) if not s.get("item")), None)
            if empty is not None:
                self.ctx.body.call(f"select {empty}")
            self.ctx.body.call("key f tap")  # the off hand's tool comes to the hand
            time.sleep(0.3)

    def wear(self, item):
        """Right-click armour in hand to put it on, like a player."""
        if wearing(self.ctx, item.split("_")[-1]) or not have(self.ctx, item):
            return
        # Shift-click it in the inventory: it goes to its armour slot. (Right-clicking it in
        # hand ran into the inventory screen still being open and did nothing.)
        b = self.ctx.body
        b.call("close")
        time.sleep(0.3)
        slot = self.ctx.slot_of(f"minecraft:{item}")
        if slot is None:
            return
        b.call("open-inventory")
        time.sleep(0.4)
        b.call(f"click-slot {slot} shift")
        time.sleep(0.3)
        b.call("close")
        time.sleep(0.3)

    def armor(self):
        """A chestplate (diamond from the spare diamonds, else iron), and leggings and boots
        if the makings are there; put on."""
        import life as _life
        import mining
        c = self.ctx.counts()
        diamonds = c.get("minecraft:diamond", 0)
        iron = c.get("minecraft:iron_ingot", 0) + c.get("minecraft:raw_iron", 0)
        if not have(self.ctx, "diamond_chestplate", "iron_chestplate"):
            if diamonds >= 8:
                piece = "diamond_chestplate"
            else:
                piece = "iron_chestplate"
                if iron < 8:
                    self.ctx.say("getting iron for a chestplate: no armour is how I keep dying.")
                    self.sub(mining.Mine, ore="iron", count=8 - iron)
                    if self.done():
                        return
            self.sub(_life.Sequence, steps=[("craft", {"item": piece, "count": 1})])
        # The rest with what's left over.
        c = self.ctx.counts()
        extra = []
        for part, d_cost, i_cost in (("boots", 4, 4), ("leggings", 7, 7)):
            if have(self.ctx, f"diamond_{part}", f"iron_{part}") or wearing(self.ctx, part):
                continue
            if c.get("minecraft:diamond", 0) >= d_cost:
                extra.append(("craft", {"item": f"diamond_{part}", "count": 1}))
                c["minecraft:diamond"] = c.get("minecraft:diamond", 0) - d_cost
            elif c.get("minecraft:iron_ingot", 0) + c.get("minecraft:raw_iron", 0) >= i_cost:
                extra.append(("craft", {"item": f"iron_{part}", "count": 1}))
        if extra:
            self.sub(_life.Sequence, steps=extra)
        for piece in ("diamond_chestplate", "iron_chestplate", "diamond_leggings", "iron_leggings",
                      "diamond_boots", "iron_boots"):
            self.wear(piece)
        if wearing(self.ctx, "chestplate"):
            self.ctx.say("suited up!")

    def diamonds(self):
        import life as _life
        import mining
        # Three for the pickaxe (obsidian needs it); the sword's two more only if they turn
        # up (an iron one does for the dragon, and deepslate eats an iron pickaxe in half an hour).
        n = self.ctx.counts().get("minecraft:diamond", 0) + 3 * have(self.ctx, "diamond_pickaxe")
        if n < 3:
            # Diamond needs an iron pickaxe, and deepslate wears one out: two of them before
            # going down (iron at y 16 is quick; at y -58 with stone pickaxes he could see
            # diamonds and not mine them, and the stone ones wore out in minutes).
            c = self.ctx.counts()
            picks = c.get("minecraft:iron_pickaxe", 0) + c.get("minecraft:diamond_pickaxe", 0)
            iron = c.get("minecraft:iron_ingot", 0) + c.get("minecraft:raw_iron", 0)
            if picks < 2 and iron < 3 * (2 - picks):
                self.ctx.say("diamonds need iron pickaxes: getting iron for two first.")
                self.sub(mining.Mine, ore="iron", count=3 * (2 - picks) - iron)
                if self.done():
                    return
            prov = mining.Provision(self.ctx, self)
            for _ in range(2):
                c = self.ctx.counts()
                if c.get("minecraft:iron_pickaxe", 0) + c.get("minecraft:diamond_pickaxe", 0) >= 2:
                    break
                if c.get("minecraft:iron_ingot", 0) + c.get("minecraft:raw_iron", 0) < 3:
                    break
                c0 = c.get("minecraft:iron_pickaxe", 0)
                try:
                    if prov.crafter.count("iron_ingot") < 3:
                        prov.smelt("raw_iron", 3 - prov.crafter.count("iron_ingot"))
                    prov.ensure("iron_pickaxe", c0 + 1)
                except Exception as e:
                    journal.log("quest", "iron pickaxe failed", err=str(e)[:80])
                    break
            if self.done():
                return
            self.sub(mining.Mine, ore="diamond", count=3 - n)
        steps = [("craft", {"item": "diamond_pickaxe", "count": 1})] if not have(self.ctx, "diamond_pickaxe") else []
        if self.ctx.counts().get("minecraft:diamond", 0) >= 2 + 3 * (not have(self.ctx, "diamond_pickaxe")) \
                and not have(self.ctx, "diamond_sword"):
            steps.append(("craft", {"item": "diamond_sword", "count": 1}))
        if steps:
            self.sub(_life.Sequence, steps=steps)

    def obsidian(self):
        import nether
        nether.Obsidian(self, want=10).run()

    def nether_portal(self):
        import nether
        p = nether.Portal(self)
        if p.run() and p.go_through():
            q = self.progress()
            q.setdefault("flags", {})["portal"] = True
            self.save(q)
            self.ctx.say("WE'RE IN THE NETHER!")

    # --- the Nether, the stronghold, the End ------------------------------------------
    def dim(self):
        return str(self.ctx.body.call("state").get("dimension", ""))

    def set_flag(self, name):
        q = self.progress()
        q.setdefault("flags", {})[name] = True
        self.save(q)

    def to_nether(self):
        import nether
        if "nether" in self.dim():
            return True
        # Up out of the mine and over to it first: a 30-second walk at the portal from y 12
        # underground failed all three tries.
        import mining
        if mining.underground(self.ctx):
            mining.go_to_surface(self.ctx, self)
        p = life.load_memory().get("places", {}).get("portal")
        if p and not self.done():
            self.travel(p[0], p[2])
        ok = nether.Portal(self).go_through()
        if ok:
            p = self.ctx.state()["player"]["position"]
            mem = life.load_memory()
            mem.setdefault("places", {})["portal_nether_side"] = [round(v, 2) for v in p]
            life.save_memory(mem)
        return ok

    def to_overworld(self):
        if "overworld" in self.dim():
            return True
        p = life.load_memory().get("places", {}).get("portal_nether_side")
        if not p:
            self.ctx.say("I don't know where the portal back is!")
            return False
        self.ctx.walk_to(tuple(p), near=1.5, timeout=60, task=self)
        self.ctx.body.call(f"goto {p[0]:.2f} {p[1]:.2f} {p[2]:.2f} --near 0.3 --timeout 4 --direct")
        for _ in range(20):
            if "overworld" in self.dim():
                return True
            time.sleep(1)
        return False

    def blaze_rods(self):
        import nether
        if not self.to_nether():
            return
        nether.NetherHunt(self, rods=6, pearls=0).run()

    def ender_pearls(self):
        """Endermen walk the overworld at night: hunted there, on open ground, not across
        the Nether's lava caverns (the way to the fortress killed him again and again)."""
        import mining
        ctx = self.ctx
        if not self.to_overworld():
            return
        if mining.underground(ctx):
            mining.go_to_surface(ctx, self)
        self.night_hunt = True
        try:
            for _ in range(6):
                if self.done() or have(ctx, "ender_pearl", "ender_eye", n=12):
                    return
                if not self.night():
                    make = getattr(ctx, "make_night", None)
                    if make:
                        make()  # training: no waiting ten minutes for dusk
                        time.sleep(1)
                    else:
                        ctx.say("waiting for night: that's when the endermen are out.")
                        time.sleep(30)
                        continue
                ctx.say("night: hunting endermen for pearls!")
                self.hunt_for(["enderman"], "ender_pearl", 12)
        finally:
            self.night_hunt = False

    def eyes(self):
        import mining
        prov = mining.Provision(self.ctx, self)
        try:
            prov.ensure("ender_eye", 12)
        except Exception as e:
            self.ctx.say(f"couldn't make eyes of ender: {e}")

    def hunt_for(self, kinds, item, n):
        """Like the food hunt: the animal or mob that drops `item`, found by walking out."""
        import math
        import random
        from skills import Hunt
        ctx = self.ctx
        heading = random.uniform(0, 2 * math.pi)
        for trip in range(8):
            if self.done() or have(ctx, item, n=n):
                return
            seen = {e.get("type", "").removeprefix("minecraft:") for e in
                    ctx.senses.call("entities 40").get("entities", []) if e.get("kind") == "mob"}
            for kind in [k for k in kinds if k in seen]:
                self.sub(Hunt, mob=kind, count=3)
            if have(ctx, item, n=n):
                return
            pos = ctx.eye_and_view()[3]
            heading += random.uniform(-0.6, 0.6)
            self.travel(pos[0] + 40 * math.cos(heading), pos[2] + 40 * math.sin(heading))

    def bow(self):
        import mining
        import nether
        ctx = self.ctx
        if not self.to_overworld():
            return
        if not have(ctx, "bow"):
            self.hunt_for(["spider", "cave_spider"], "string", 3)
        if not have(ctx, "flint", n=6):
            nether.Portal(self).flint_and_steel()  # its gravel digging gives flint too
        self.hunt_for(["chicken"], "feather", 6)
        prov = mining.Provision(ctx, self)
        for item, n in (("bow", 1), ("arrow", 24)):
            try:
                prov.ensure(item, n)
            except Exception as e:
                ctx.say(f"couldn't make {item}: {e}")

    def stronghold(self):
        import end
        if not self.to_overworld():
            return
        if end.Stronghold(self).find():
            self.set_flag("end")
            self.ctx.say("WE'RE IN THE END!")

    def dragon(self):
        import end
        if "end" not in self.dim() or "nether" in self.dim():
            return
        if end.Dragon(self).run():
            self.set_flag("dragon")

    def not_yet(self, what):
        def run():
            self._cant = True
            self.ctx.say(f"I don't know how to do this part yet: {what}.")
        return run
