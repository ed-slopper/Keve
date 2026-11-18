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
ANIMALS = ("cow", "pig", "sheep", "chicken")


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
            for attempt in range(self.TRIES):
                if self.done():
                    return
                said_before = len(getattr(ctx, "said_log", []))
                try:
                    do()
                except Exception as e:  # a skill crashing is a thing to fix: write it down
                    journal.log("quest", f"{name}: crashed", error=repr(e)[:300])
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
        """Hunt what's around, then cook it (raw meat is poor food)."""
        from skills import Hunt
        for kind in ANIMALS:
            if self.done() or have(self.ctx, *FOOD, *RAW_MEAT, n=10):
                break
            self.sub(Hunt, mob=kind, count=3)
        self.cook()

    def cook(self):
        import craft
        import mining
        raw = sum(self.ctx.counts().get("minecraft:" + m, 0) for m in RAW_MEAT)
        if not raw:
            return
        prov = mining.Provision(self.ctx, self)
        try:
            prov.ensure("furnace", 1)
            prov.crafter.smelt("raw_meat", raw)
        except (craft.NeedMore, RuntimeError) as e:
            if getattr(e, "what", "") == "fuel":
                prov.get_raw("log", 4, 0)
                prov.crafter.smelt("raw_meat", raw)
            else:
                raise

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
