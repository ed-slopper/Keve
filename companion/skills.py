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
}
NEEDS_PICKAXE = {"stone"}

HOSTILE = {
    "zombie", "husk", "drowned", "zombie_villager", "skeleton", "stray", "bogged", "creeper",
    "spider", "cave_spider", "witch", "slime", "phantom", "pillager", "vindicator", "evoker",
    "ravager", "vex", "silverfish", "endermite", "blaze", "ghast", "magma_cube",
    "piglin_brute", "hoglin", "zoglin", "wither_skeleton", "guardian", "elder_guardian",
    "breeze", "creaking", "parched",
}
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

    # --- own state -------------------------------------------------------------------
    def state(self):
        return self.body.call("state")

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

    def visible_hostiles(self, around, radius):
        eye, yaw, pitch, _ = self.eye_and_view()
        mobs = self.senses.call(f"entities {radius + 16:.0f}").get("entities", [])
        mobs = [m for m in mobs if m.get("type", "").removeprefix("minecraft:") in HOSTILE]
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

    # --- reflexes --------------------------------------------------------------------
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


class Come(Task):
    name = "come"

    def run(self):
        o = self.ctx.owner()
        if not o:
            self.ctx.say("I can't find you!")
            return
        r = self.ctx.body.call(f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} --near 2.5 --sprint --timeout 40")
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
            o = self.ctx.owner()
            if not o:
                time.sleep(1.0)
                continue
            eye, _, _, pos = self.ctx.eye_and_view()
            d = math.dist(pos, o[1])
            if d > 4.5:
                r = self.ctx.body.call(
                    f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} --near 3 --sprint --timeout 4")
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
        while not self.done():
            time.sleep(0.5)


class Gather(Task):
    name = "gather"

    def run(self):
        what = self.args.get("item", "wood")
        want = int(self.args.get("count", 10))
        block_ok, item_ok = GATHER[what]
        ctx = self.ctx

        def have():
            return sum(n for i, n in ctx.counts().items() if item_ok(i))

        start = have()
        goal = start + want
        if what in NEEDS_PICKAXE and not ctx.has(PICKAXES):
            ctx.say(f"I need a pickaxe for {what}.")
            return
        explores = 0
        breaks = 0
        while not self.done():
            got = have()
            if got >= goal:
                ctx.body.call("collect 8")
                ctx.say(f"got {got - start} {what}!")
                return
            # The nearest remembered target that hasn't failed too often.
            _, _, _, pos = ctx.eye_and_view()
            targets = [p for p, (n, _) in ctx.memory.items()
                       if block_ok(n) and ctx.bad_targets.get(p, 0) < 2]
            if not targets:
                if not ctx.look_around(block_ok):
                    if explores >= 6:
                        ctx.say(f"I can't find any {what} around here.")
                        return
                    explores += 1
                    ang = random.uniform(0, 2 * math.pi)
                    tx, tz = pos[0] + 14 * math.cos(ang), pos[2] + 14 * math.sin(ang)
                    ctx.body.call(f"goto {tx:.1f} {pos[1]:.1f} {tz:.1f} --near 3 --timeout 12 --direct")
                continue
            # Lowest first (tree trunks from the bottom), then nearest.
            t = min(targets, key=lambda p: (math.dist(p, pos) // 4, p[1], math.dist(p, pos)))
            if math.dist((t[0] + 0.5, t[1] + 0.5, t[2] + 0.5), pos) > 4.0:
                ctx.body.call(f"goto {t[0] + 0.5:.1f} {t[1]:.1f} {t[2] + 0.5:.1f} --near 3 --timeout 20")
                if self.done():
                    return
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
            breaks += 1
            # Look up and around the broken spot: the log above is visible now.
            ctx.look_around(block_ok, pitches=(-40.0, 0.0))
            if breaks % 3 == 0:
                ctx.body.call("collect 6")
            ctx.maybe_eat()


class Defend(Task):
    name = "defend"

    def run(self):
        ctx = self.ctx
        while not self.done():
            o = ctx.owner()
            if not o:
                time.sleep(1.0)
                continue
            mobs = ctx.visible_hostiles(o[1], 12.0)
            if mobs:
                m = mobs[0]
                ctx.select_best(WEAPONS)
                ctx.body.call(f"look-at entity {m['id']}")
                ctx.body.call(f"hunt {m['id']} --timeout 12")
                if self.done():
                    return
                continue
            _, _, _, pos = ctx.eye_and_view()
            if math.dist(pos, o[1]) > 6:
                ctx.body.call(f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} --near 3 --sprint --timeout 4")
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


SKILLS = {c.name: c for c in (Come, Follow, Stay, Gather, Defend, Status, Jump, LookAtMe)}
