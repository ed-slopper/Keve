"""The practice arena (training only): a walled, roofed box high over the overworld where
Keve fights one summoned mob at a time, so a fighting style can be tried twenty times in
ten minutes instead of once per death at a Nether fortress.

Started with launch.py --keep-inventory --quest arena (the server command hook it needs is
only there in training). Each round: Keve healed and put in the middle, any mob left over
cleared, one mob summoned eight blocks off, the duel fought, the result written to
arena_results.jsonl in Keve's folder (mob, style, won/lost/timeout, health left, seconds).
The mobs and styles to try come from KEVE_ARENA (e.g. "enderman:shield,enderman:kite"),
default: each melee mob against each style.
"""
import json
import os
import time

import combat
import journal
from skills import Task

X, Y, Z = 600, 180, 600  # the floor's middle (y is the floor block)
R = 10  # half width
DEFAULT = [f"{mob}:{style}" for mob in ("zombie", "wither_skeleton", "enderman")
           for style in ("plain", "shield", "kite", "crit")]


RUN = round(time.time())  # this launch: a respawn restarts the task, not the run


def results_path():
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.path.join(base, "Keve", "arena_results.jsonl")


class Arena(Task):
    name = "arena"

    def cmd(self, line):
        run = getattr(self.ctx, "server_cmd", None)
        if run is None:
            raise RuntimeError("the arena needs training's server command hook (launch.py --keep-inventory)")
        return run(line)

    def build(self):
        c = self.cmd
        # Solid, then the room hollowed out: walls three thick (room for a pocket two deep),
        # a room three high (a wither skeleton fits; a two-high pocket in the wall it doesn't).
        c(f"fill {X - R} {Y} {Z - R} {X + R} {Y + 5} {Z + R} minecraft:stone")
        c(f"fill {X - R + 3} {Y + 1} {Z - R + 3} {X + R - 3} {Y + 3} {Z + R - 3} minecraft:air")
        for dx, dz in ((-4, -4), (4, -4), (-4, 4), (4, 4)):  # light, so nothing spawns in it by itself
            c(f"setblock {X + dx} {Y + 4} {Z + dz} minecraft:glowstone")

    def reset(self):
        c = self.cmd
        for kind in ("zombie", "wither_skeleton", "enderman", "blaze", "skeleton", "item", "experience_orb", "oak_boat"):
            c(f"kill @e[type=minecraft:{kind},x={X},y={Y},z={Z},distance=..20]")
        c(f"execute in minecraft:overworld run tp Keve {X + 0.5} {Y + 1} {Z + 0.5}")
        c("effect clear Keve")
        c("effect give Keve minecraft:instant_health 1 10")
        c("effect give Keve minecraft:saturation 1 10")
        time.sleep(1.5)

    def summon(self, mob, offset=0.0):
        before = {e["id"] for e in self.ctx.senses.call("entities 24").get("entities", [])}
        self.cmd(f"execute in minecraft:overworld run summon minecraft:{mob} {X + 5.5} {Y + 1} {Z + 0.5 + offset - 2}")
        for _ in range(20):
            time.sleep(0.25)
            for e in self.ctx.senses.call("entities 24").get("entities", []):
                if e.get("type") == f"minecraft:{mob}" and e["id"] not in before:
                    return e["id"]
        return None

    def write(self, row):
        row = dict(row, t=round(time.time()))
        journal.log("arena", f"{row['mob']} {row['style']}: {row['result']}", **row)
        with open(results_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        self.mark(None)

    def mark(self, pending):
        with open(results_path() + ".pending", "w", encoding="utf-8") as f:
            f.write(json.dumps(pending))

    def progress(self):
        """This run's rounds already fought, and the one he died in (if any)."""
        done = set()
        try:
            for line in open(results_path(), encoding="utf-8"):
                r = json.loads(line)
                if r.get("run") == RUN:
                    done.add((r["mob"], r["style"], r["round"]))
        except OSError:
            pass
        try:
            pending = json.load(open(results_path() + ".pending", encoding="utf-8"))
        except (OSError, ValueError):
            pending = None
        if pending and pending.get("run") != RUN:
            pending = None
        return done, pending

    def run(self):
        ctx = self.ctx
        plan = [p for p in (os.environ.get("KEVE_ARENA") or ",".join(DEFAULT)).split(",") if p]
        rounds = int(os.environ.get("KEVE_ARENA_ROUNDS", "3"))
        ctx.say("practice arena! let's see which way of fighting works.")
        self.cmd(f"forceload add {X - R} {Z - R} {X + R} {Z + R}")
        done, pending = self.progress()
        if pending:
            # Died in that round: the death stopped the task before it could write it down.
            self.write(dict(pending, result="lost", hp=0, secs=None))
            done.add((pending["mob"], pending["style"], pending["round"]))
        if not done:
            self.reset()
            self.build()
        for entry in plan:
            mob, style = entry.split(":")
            for n in range(rounds):
                if self.done():
                    return
                if (mob, style, n + 1) in done:
                    continue
                self.reset()
                ids = []
                for k, part in enumerate(mob.split("+")):  # "wither_skeleton*2+blaze"
                    kind, _, many = part.partition("*")
                    for j in range(int(many or 1)):
                        i = self.summon(kind, offset=(k * 2 + j) * 1.5)
                        if i is not None:
                            ids.append((kind, i))
                if not ids:
                    journal.log("arena", "summon failed", mob=mob)
                    continue
                for kind, i in ids:
                    if kind == "enderman":
                        ctx.body.call(f"look-at entity {i}")  # a stare is what sets it on him
                        time.sleep(0.6)
                t0 = time.time()
                self.mark({"run": RUN, "mob": mob, "style": style, "round": n + 1})
                result = combat.fight(ctx, [i for _, i in ids], self, style=style, timeout=90)
                try:
                    hp = round(ctx.state()["player"].get("health", 0), 1)
                except Exception:
                    hp = 0
                if self.done():
                    return  # stopped (or died: the next start writes that one down as lost)
                if result == "won":
                    time.sleep(0.6)
                    ctx.collect(8, self)  # what it dropped, before the next round clears the floor
                self.write({"run": RUN, "mob": mob, "style": style, "round": n + 1,
                            "result": result, "hp": hp, "secs": round(time.time() - t0, 1)})
                if result == "lost":
                    time.sleep(6)  # respawned with his things (training): back in for the next one
        ctx.say("arena done!")
