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
    "sugar_cane": (lambda b: base(b) == "minecraft:sugar_cane", lambda i: i == "minecraft:sugar_cane"),
    "pumpkin": (lambda b: base(b) == "minecraft:pumpkin", lambda i: i == "minecraft:pumpkin"),
    "clay": (lambda b: base(b) == "minecraft:clay", lambda i: i == "minecraft:clay_ball"),
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
        self.recent_breaks = []   # (x, y, z, time): Keve saw these break, so it knows the drops are there
        self.last_item = None     # what it gathered last ("bring them to me")

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

    def slot_of(self, item):
        """The inventory slot id (0-35) holding `item`, or None."""
        inv = self.body.call("inventory")
        for s in inv.get("hotbar", []) + inv.get("main", []):
            it = s.get("item")
            if it and it.get("item") == item:
                return s["slot"]
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
        while not self.done():
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
                    if explores >= 6:
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


class Give(Task):
    """Walk to the owner, face them and drop the items (all of a kind, or everything)."""
    name = "give"

    def run(self):
        self.run_inner(self)

    def run_inner(self, task):
        ctx = self.ctx
        what = self.args.get("item")  # a GATHER word, or None for everything
        if what is None and not self.args.get("everything") and ctx.last_item:
            what = ctx.last_item  # "bring them to me": what it just gathered
        item_ok = GATHER[what][1] if what in GATHER else (lambda i: True)
        items = [i for i, n in ctx.counts().items() if n > 0 and item_ok(i)]
        if not items:
            ctx.say(f"I don't have any {what or 'items'}.")
            return
        o = ctx.owner()
        if not o:
            ctx.say("where are you? I can't find you.")
            return
        r = ctx.body.call(f"goto {o[1][0]:.2f} {o[1][1]:.2f} {o[1][2]:.2f} --near 2 --sprint --timeout 40")
        if task.done():
            return
        if not r.get("arrived") and r.get("distance", 99) > 5:
            ctx.say("I can't get to you to hand them over.")
            return
        # The planner stops a little short; step in the rest of the way so the stack
        # lands at their feet (a dropped stack flies about a block and a half).
        for _ in range(10):
            o = ctx.owner() or o
            _, _, _, pos = ctx.eye_and_view()
            if math.dist(pos, o[1]) <= 1.8:
                break
            ctx.body.call(f"look-at entity {o[0]}")
            if (ctx.body.call("move forward 0.15").get("moved") or 0) < 0.05:
                break
        given = 0
        for item in items:
            for _ in range(40):  # one stack per drop
                if task.done():
                    return
                n = ctx.counts().get(item, 0)
                if n <= 0:
                    break
                o = ctx.owner() or o
                # Aim at their head, so the stack flies to them instead of to Keve's feet.
                ctx.body.call(f"look-at {o[1][0]:.2f} {o[1][1] + 0.9:.2f} {o[1][2]:.2f}")
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


class Help(Task):
    name = "help"

    def run(self):
        for line in HELP_LINES:
            self.ctx.say(line)
            time.sleep(0.35)


HELP_LINES = [
    "things you can tell me (start with 'keve'):",
    "follow me / come here / stay / stop / look at me / jump",
    "get 10 wood, grab 5 dirt, collect sand, mine 20 stone (needs a pickaxe), gravel",
    "...and bring them to me / give me your sand / give me everything",
    "defend me (I fight mobs I can see near you) / what you got",
    "or just talk to me.",
]

SKILLS = {c.name: c for c in (Come, Follow, Stay, Idle, Gather, Give, Defend, Status, Jump, LookAtMe, Help)}
