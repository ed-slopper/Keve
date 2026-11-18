"""Keve as a friend rather than a tool: companion mode (it decides what to do while
you play), remembered places (home, the mine...), and the little things (crouching
to say "done", swimming up for air).
"""
import json
import math
import os
import random
import time
from pathlib import Path

import craft
import mining
import sight
from skills import FOODS, GATHER, Gather, Task

MEMORY = Path(os.environ.get("KEVE_HOME") or Path(os.environ.get("LOCALAPPDATA", ".")) / "Keve") / "memory.json"


def load_memory():
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"places": {}}


def save_memory(mem):
    MEMORY.parent.mkdir(parents=True, exist_ok=True)
    MEMORY.write_text(json.dumps(mem, indent=1), encoding="utf-8")


# --- dangerous places: where Keve died or nearly did ----------------------------------
DANGER_HOURS = 12


def note_danger(pos, why):
    mem = load_memory()
    now = time.time()
    spots = [d for d in mem.get("danger", []) if now - d["t"] < DANGER_HOURS * 3600]
    spots.append({"pos": [round(v, 1) for v in pos], "why": why, "t": now})
    mem["danger"] = spots[-40:]
    save_memory(mem)


def dangers():
    now = time.time()
    return [d for d in load_memory().get("danger", []) if now - d["t"] < DANGER_HOURS * 3600]


def near_danger(pos, radius=6.0, spots=None):
    return any(math.dist(d["pos"], pos) <= radius for d in (dangers() if spots is None else spots))


class SetHome(Task):
    """'keve this is home' / 'keve remember this as the mine': where you're standing."""
    name = "set_home"

    def run(self):
        name = self.args.get("name", "home")
        o = self.ctx.owner()
        pos = o[1] if o else self.ctx.eye_and_view()[3]
        mem = load_memory()
        mem.setdefault("places", {})[name] = [round(v, 2) for v in pos]
        save_memory(mem)
        self.ctx.say(f"ok, {name} is at {pos[0]:.0f} {pos[1]:.0f} {pos[2]:.0f}.")


class GoPlace(Task):
    """'keve go home' / 'keve go to the mine'."""
    name = "go_place"

    def run(self):
        name = self.args.get("name", "home")
        places = load_memory().get("places", {})
        if name not in places:
            known = ", ".join(places) or "nowhere yet"
            self.ctx.say(f"I don't know where {name} is. I know: {known}. "
                         f"say 'keve remember this as {name}' there.")
            return
        x, y, z = places[name]
        for _ in range(30):  # legs: the path planner only sees loaded terrain
            if self.done():
                return
            pos = self.ctx.eye_and_view()[3]
            if math.dist(pos, (x, y, z)) < 3:
                self.ctx.say(f"made it to {name}.")
                return
            r = self.ctx.walk_to((x, y, z), near=2, timeout=15, task=self)
            if not r.get("arrived") and r.get("distance", 99) > math.dist(pos, (x, y, z)) - 1:
                self.ctx.body.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near 2 --sprint --timeout 8 --direct")
        self.ctx.say(f"I can't find a way to {name} from here.")


class Companion(Task):
    """Play alongside you: keep up while you move, and when you stop to do something,
    find something useful nearby (ore it can see, a tree, drops, a mob to fight).
    Kev picks what to do from what Keve can see; without Kev, simple rules do."""
    name = "companion"
    DECIDE_EVERY = 4.0

    OPTIONS = {
        "follow": "Stay close to the player",
        "ore": "Mine the ore it can see nearby",
        "wood": "Chop the tree it can see nearby (it's low on wood)",
        "items": "Pick up the items lying on the ground nearby",
        "eat": "Eat something (it's hungry)",
        "watch": "Stand by the player and keep watch",
    }

    def run(self):
        ctx = self.ctx
        self.kev = getattr(ctx, "kev", None)
        trail = []  # (time, owner position)
        last_decide = 0.0
        last_line = 0.0
        while not self.done():
            if self.guard(owner_radius=10.0, self_radius=5.0):
                continue
            self._announced = False
            o = ctx.owner()
            if not o:
                time.sleep(1.0)
                continue
            now = time.time()
            trail.append((now, o[1]))
            trail = [t for t in trail if now - t[0] < 8]
            moving = math.dist(trail[0][1], o[1]) > 2.0 if trail else False
            pos = ctx.eye_and_view()[3]
            d = math.dist(pos, o[1])
            # Keep up first: you're walking off, or it's too far.
            if d > 9 or (moving and d > 4):
                ctx.walk_to(o[1], near=3, timeout=3, task=self)
                continue
            if now - last_decide < self.DECIDE_EVERY:
                time.sleep(0.4)
                continue
            last_decide = now
            seen = self.look()
            choice = self.choose(seen, moving, d)
            if choice != "follow" and choice != "watch" and now - last_line > 25:
                lines = {"ore": ["ooh, {o}. mine.", "grabbing that {o}"], "wood": ["need wood, one sec"],
                         "items": ["free loot"], "eat": ["snack time"]}
                ctx.say(random.choice(lines.get(choice, [""])).format(o=seen.get("ore_name", "ore")))
                last_line = now
            self.do(choice, seen)

    def look(self):
        """What Keve can see right now (fairly): nearest ore, tree, drops."""
        ctx = self.ctx
        eye, yaw, pitch, pos = ctx.eye_and_view()
        snap = sight.Snapshot.read(ctx.senses, eye, rh=8, rv=5)
        tier = mining.Provision(ctx, self).pick_tier()
        out = {}
        best = None
        for p, name in snap.blocks.items():
            ore = mining.ore_of(name)
            if ore and mining.ORES[ore][2] <= max(tier, -1) and snap.block_visible(eye, p, 8.0):
                d = math.dist(p, eye)
                if best is None or d < best[0]:
                    best = (d, p, ore)
        if best:
            out["ore"], out["ore_name"] = best[1], best[2]
        logs = [p for p, n in snap.blocks.items() if GATHER["wood"][0](n) and math.dist(p, eye) < 9
                and snap.block_visible(eye, p, 9.0)]
        if logs:
            out["log"] = min(logs, key=lambda p: math.dist(p, eye))
        counts = ctx.counts()
        out["wood"] = sum(n for i, n in counts.items() if GATHER["wood"][1](i))
        out["food"] = ctx.state()["player"]["food"]
        out["has_food"] = any(counts.get("minecraft:" + f) for f in FOODS)
        items = [e for e in ctx.senses.call("entities 6").get("entities", []) if e.get("kind") == "item"]
        out["items"] = len(items)
        out["tier"] = tier
        return out

    def choose(self, seen, moving, d):
        feasible = {"follow", "watch"}
        if "ore" in seen:
            feasible.add("ore")
        if "log" in seen and seen["wood"] < 16:
            feasible.add("wood")
        if seen["items"]:
            feasible.add("items")
        if seen["food"] <= 14 and seen["has_food"]:
            feasible.add("eat")
        if feasible == {"follow", "watch"}:
            return "watch" if d < 5 else "follow"
        if self.kev and self.kev.ok:
            state = (f"Keve is playing Minecraft next to its friend, who is "
                     f"{'walking' if moving else 'standing still'} {d:.0f} blocks away. "
                     f"Keve's food: {seen['food']}/20. Wood carried: {seen['wood']}. "
                     + (f"Keve can see {seen['ore_name']} ore close by. " if "ore" in seen else "")
                     + ("Keve can see a tree close by. " if "log" in seen else "")
                     + (f"There are {seen['items']} items on the ground nearby. " if seen["items"] else ""))
            crit = {k: v for k, v in self.OPTIONS.items() if k in feasible}
            pick = self.kev.choose(state, "What should Keve do now?", crit)
            if pick in feasible:
                return pick
        for c in ("eat", "ore", "items", "wood"):  # rules: the obvious order
            if c in feasible:
                return c
        return "watch"

    def do(self, choice, seen):
        ctx = self.ctx
        if choice == "eat":
            ctx.maybe_eat()
        elif choice == "items":
            ctx.collect(6, self)
        elif choice == "ore":
            m = mining.Mine(ctx, ore=seen["ore_name"])
            m.cancelled = self.cancelled
            m.prov = mining.Provision(ctx, m)
            m.wanted = set(mining.ORES)
            ctx.select_best(craft.PICKAXES_ALL)
            m.take_visible_ores()
        elif choice == "wood":
            g = Gather(ctx, item="wood", count=2, max_explores=0, quiet_fail=True)
            g.cancelled = self.cancelled
            g.run()
        elif choice == "watch":
            o = ctx.owner()
            if o:
                ctx.body.call(f"look-at entity {o[0]}")
            time.sleep(0.6)


def crouch(ctx, times=3):
    """A quick 'done!' crouch, like players do to each other."""
    for _ in range(times):
        ctx.body.call("key shift down")
        ctx.body.call("wait 3")
        ctx.body.call("key shift up")
        ctx.body.call("wait 3")


class Sequence(Task):
    """Several orders in a row ('chop 10 wood, then make a table, then come back')."""
    name = "sequence"

    def gather_up_front(self, steps):
        """Several things to craft: add up what they all need first and get it in one trip
        ('a full set of stone tools' is 2 logs and 11 cobblestone, not five trips)."""
        crafts = [(a["item"], int(a.get("count", 1))) for s, a in steps
                  if s == "craft" and not a.get("from_chest") and a.get("item")]
        if len(crafts) < 2:
            return
        import mining
        prov = mining.Provision(self.ctx, self)
        prov.goal = crafts[0][0]
        try:
            needs = prov.crafter.raw_needs_many(crafts)
        except Exception:
            return
        if not needs:
            return
        shown = ", ".join(f"{n} {mining.RAW_NAMES.get(k, k.replace('_', ' '))}" for k, n in needs.items())
        self.ctx.say(f"for all that I need {shown}. getting it all first!")
        for raw, n in needs.items():
            if self.done():
                return
            if not prov.get_raw(raw, n, 0):
                return  # the crafts themselves will say what's missing
            if self.done():
                return

    def run(self):
        import skills
        steps = self.args.get("steps", [])
        self.gather_up_front(steps)
        for i, (skill, args) in enumerate(steps):
            self.at = i  # where it's up to: after a death, the plan goes on from here
            if self.done():
                return
            cls = skills.SKILLS.get(skill)
            if cls is None or skill in ("stop", "idle"):
                continue
            t = cls(self.ctx, **args)
            t.cancelled = self.cancelled
            try:
                t.run()
            except Exception as e:  # one step going wrong doesn't end the plan
                self.ctx.say(f"step {i + 1} went wrong ({e}), moving on.")
        if not self.done() and len(steps) > 1:
            import brain
            self.ctx.say(brain.line("done", "all done!"))


class Ride(Task):
    """'keve get in the boat with me': hop into the boat you're sitting in, then sit tight
    while you steer. 'keve get out' (or any other order) gets him out.

    Fair: Keve can't see a boat's id, only you. You're in the seat, so he walks up and
    right-clicks the boat just below you on his side, like a player would, checking each
    time whether he's sitting yet."""
    name = "ride"

    def riding(self):
        try:
            return self.ctx.body.call("status").get("riding") is not None
        except Exception:
            return False

    def run(self):
        ctx = self.ctx
        if self.riding():
            ctx.say("already in!")
        elif not self.board():
            if not self.done():
                ctx.say("I can't get in. hop in the boat first and I'll climb in with you!")
            return
        else:
            ctx.say("in the boat! row, row, row your boat!")
        while not self.done() and self.riding():
            time.sleep(0.5)
        if not self.done():
            ctx.say("and we're ashore!")

    def board(self):
        ctx = self.ctx
        for _ in range(3):
            if self.done():
                return False
            o = ctx.owner()
            if not o:
                return False
            ox, oy, oz = o[1]
            pos = ctx.eye_and_view()[3]
            d = math.dist((pos[0], pos[2]), (ox, oz))
            if d > 2.2:
                ctx.walk_to((ox, oy, oz), near=1.6, timeout=10, task=self)
                pos = ctx.eye_and_view()[3]
                d = math.dist((pos[0], pos[2]), (ox, oz)) or 1.0
            # The boat's edge on Keve's side, a little lower than where you sit.
            ux, uz = (pos[0] - ox) / d, (pos[2] - oz) / d
            for out, dy, side in ((0.55, 0.15, 0.0), (0.55, 0.0, 0.0), (0.45, 0.3, 0.0),
                                  (0.55, 0.15, 0.45), (0.55, 0.15, -0.45), (0.7, -0.1, 0.0)):
                if self.done():
                    return False
                tx = ox + ux * out - uz * side
                tz = oz + uz * out + ux * side
                ctx.body.call(f"look-at {tx:.2f} {oy + dy:.2f} {tz:.2f}")
                ctx.body.call("mouse right click")
                time.sleep(0.35)
                if self.riding():
                    return True
        return False


def get_out(ctx):
    """Shift gets you out of a boat or off a horse."""
    ctx.body.call("key shift down")
    time.sleep(0.3)
    ctx.body.call("key shift up")


class GetOut(Task):
    """'keve get out of the boat'."""
    name = "get_out"

    def run(self):
        get_out(self.ctx)


class Recover(Task):
    """After dying in the middle of a job: back to where he died for the dropped things
    (they last 5 minutes), then on with the job from where it was."""
    name = "recover"

    def run(self):
        ctx = self.ctx
        where = self.args.get("where")
        try:
            t = ctx.body.call("status").get("day_time", 6000) % 24000
        except Exception:
            t = 6000
        if where and 12800 <= t <= 23200:
            ctx.say("it's night, the mobs are out. leaving my stuff!")
            where = None
        if where and self.args.get("cause", "") and any(k in self.args["cause"] for k in
                                                        ("mob", "arrow", "explosion", "player"))                 and where[1] < 50:
            ctx.say("whatever got me is still down there. leaving my stuff!")
            where = None
        if where and len([d for d in dangers() if math.dist(d["pos"], where) < 8]) >= 2:
            ctx.say("I keep dying back there, my stuff isn't worth it. leaving it!")
            where = None
        if where and math.dist(ctx.eye_and_view()[3], where) < 300:
            ctx.say("going back for my stuff!")
            for _ in range(12):
                if self.done():
                    return
                if math.dist(ctx.eye_and_view()[3], where) < 3:
                    break
                ctx.walk_to(tuple(where), near=2, timeout=15, task=self)
            for _ in range(3):
                if self.done() or not ctx.collect(8, self):
                    break
        resume = self.args.get("resume")
        if resume and not self.done():
            import skills
            skill, args = resume
            ctx.say("ok, back to it!")
            t = skills.SKILLS[skill](ctx, **args)
            t.cancelled = self.cancelled
            t.run()


class Sleep(Task):
    """'keve sleep in this bed' / 'go to bed': the bed by you that Keve can see, walked to
    and right-clicked, like a player. Only works at night (or in a thunderstorm)."""
    name = "sleep"

    def run(self):
        ctx = self.ctx
        import blocks
        import containers
        import world_names
        names = world_names.names()
        beds = set(names.tag("beds")) if names else set()
        if not beds:
            ctx.say("I don't know what a bed looks like!")
            return
        p = blocks.find_target(ctx, self, beds, near_owner=True)
        if p is None:
            ctx.say("I don't see a bed. put one down and I'll hop in!")
            return
        try:
            t = ctx.body.call("status").get("day_time", 0) % 24000
        except Exception:
            t = 18000
        if 0 <= t < 12542:
            ctx.say("it's daytime, I can only sleep at night! (or in a thunderstorm)")
            return
        ch = containers.Chests(ctx, self)
        if not ch.open(p):  # walks to a spot it can reach the bed from, and right-clicks it
            ctx.say("I can't get to that bed.")
            return
        ctx.say("goodnight, buddy! zzz...")
        while not self.done():
            time.sleep(1.0)
            try:
                t = ctx.body.call("status").get("day_time", 0) % 24000
            except Exception:
                break
            if t < 12542:
                ctx.say("good morning!")
                break
