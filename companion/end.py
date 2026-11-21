"""The last part of the run: eyes of ender to the stronghold, its portal, and the dragon.

Stronghold, like a player: throw an eye of ender and watch which way it flies, walk that
way a good stretch, throw again; when the eye goes down instead of on, the stronghold is
under him: dig down until stone bricks show, find the portal frames, put an eye in each
empty one, and jump in.

The dragon: the end crystals on the pillars heal it, so they go first, shot with a bow
(draw, aim at the crystal, let go); then the dragon is fought with the sword whenever it
lands on the fountain in the middle. Keve keeps off the pillar edges (the void).
"""
import math
import time

import journal
import sight
from skills import WEAPONS


def count(ctx, item):
    return ctx.counts().get("minecraft:" + item, 0)


def dimension(ctx):
    return str(ctx.body.call("state").get("dimension", ""))


class Stronghold:
    def __init__(self, task):
        self.task = task
        self.ctx = task.ctx

    def done(self):
        return self.task.done()

    def throw_eye(self):
        """Throw one eye of ender and watch it: (dx, dz) it flew, and whether it dipped down
        (the stronghold is right here) — or None if it couldn't be seen."""
        ctx = self.ctx
        if not count(ctx, "ender_eye"):
            return None
        ctx.to_hotbar("minecraft:ender_eye")
        ctx.body.call("select minecraft:ender_eye")
        p = ctx.state()["player"]
        ctx.body.call(f"look {p['yaw']:.0f} -10")
        ctx.body.call("use-item")
        seen = []
        for _ in range(12):
            time.sleep(0.25)
            for e in ctx.senses.call("entities 24").get("entities", []):
                if "eye_of_ender" in e.get("type", ""):
                    seen.append(tuple(e["pos"]))
                    break
        ctx.collect(6, self.task)  # it usually drops back down: pick it up
        if len(seen) < 3:
            return None
        a, b = seen[0], seen[-1]
        dx, dz = b[0] - a[0], b[2] - a[2]
        d = math.hypot(dx, dz)
        if d < 0.5:
            return (0.0, 0.0, True)  # it hung where it was / went down: right here
        return (dx / d, dz / d, b[1] < a[1] - 0.5)

    def find(self):
        """Throw, follow, repeat, then dig down to the portal room. True when he's in the End."""
        ctx = self.ctx
        import mining
        for leg in range(25):
            if self.done():
                return False
            if mining.underground(ctx):
                mining.go_to_surface(ctx, self.task)
            seen = self.throw_eye()
            if seen is None:
                journal.log("quest", "stronghold: lost sight of the eye")
                self.task.travel(*self.ahead(30))
                continue
            dx, dz, down = seen
            journal.log("quest", "stronghold: eye flew", dir=[round(dx, 2), round(dz, 2)], down=down)
            if down:
                ctx.say("the eye went down: the stronghold's right under us!")
                return self.dig_to_portal()
            pos = ctx.eye_and_view()[3]
            self.task.travel(pos[0] + dx * 150, pos[2] + dz * 150)
        return False

    def ahead(self, n):
        p = self.ctx.state()["player"]
        yaw = math.radians(p["yaw"])
        pos = p["position"]
        return pos[0] - math.sin(yaw) * n, pos[2] + math.cos(yaw) * n

    def dig_to_portal(self):
        """Down to the stronghold (stone bricks), then to the portal frames and fill them."""
        ctx = self.ctx
        import mining
        m = mining.Mine(ctx, ore="iron")
        m.cancelled = self.task.cancelled
        m.prov = mining.Provision(ctx, m)
        p = ctx.state()["player"]
        m.dir = mining.DIRS[round(((p["yaw"] % 360) / 90)) % 4]
        for _ in range(120):
            if self.done():
                return False
            frame = self.seen("end_portal_frame")
            if frame:
                return self.fill_frames(frame)
            bricks = self.seen("stone_bricks")
            if bricks and m.pos()[1] <= bricks[1] + 1:
                # In the stronghold: along it, toward the last eye's way.
                if not m.tunnel_step():
                    m.turn()
                continue
            if m.pos()[1] > 0:
                if not m.stair_step():
                    m.turn()
            else:
                if not m.tunnel_step():
                    m.turn()
        return False

    def seen(self, word, r=14):
        eye = tuple(self.ctx.state()["player"]["eye"])
        snap = sight.Snapshot.read(self.ctx.senses, eye, rh=r, rv=8)
        found = sorted((p for p, n in snap.blocks.items() if word in n), key=lambda p: math.dist(p, eye))
        for p in found[:20]:
            if snap.block_visible(eye, p, float(r) + 4):
                return p
        return None

    def fill_frames(self, near):
        """Put an eye in every empty frame block, then step into the portal."""
        ctx = self.ctx
        ctx.say("found the end portal! filling it with eyes.")
        ctx.walk_to(tuple(near), near=2, timeout=20, task=self.task)
        eye = tuple(ctx.state()["player"]["eye"])
        snap = sight.Snapshot.read(ctx.senses, eye, rh=8, rv=4)
        frames = [p for p, n in snap.blocks.items() if "end_portal_frame" in n and "eye=false" in n]
        for f in frames:
            if self.done() or not count(ctx, "ender_eye"):
                break
            ctx.body.call(f"goto {f[0] + 0.5:.1f} {f[1] + 1:.1f} {f[2] + 0.5:.1f} --near 2.5 --timeout 10")
            ctx.to_hotbar("minecraft:ender_eye")
            ctx.body.call("select minecraft:ender_eye")
            ctx.body.call(f"look-at block {f[0]} {f[1]} {f[2]}")
            ctx.body.call(f"interact {f[0]} {f[1]} {f[2]} up")
            time.sleep(0.3)
        time.sleep(1.0)
        portal = self.seen("end_portal", r=8)
        if portal is None or "frame" in str(portal):
            snap = sight.Snapshot.read(ctx.senses, eye, rh=8, rv=4)
            inside = [p for p, n in snap.blocks.items() if n.split("[")[0] == "minecraft:end_portal"]
            portal = inside[0] if inside else None
        if portal is None:
            ctx.say("the portal didn't open: some frames still need eyes.")
            return False
        import life
        mem = life.load_memory()
        mem.setdefault("places", {})["end_portal"] = list(portal)
        life.save_memory(mem)
        ctx.say("to the End!")
        ctx.body.call(f"goto {portal[0] + 0.5:.2f} {portal[1]:.2f} {portal[2] + 0.5:.2f} --near 0.3 --timeout 6 --direct")
        for _ in range(15):
            if "end" in dimension(ctx) and "nether" not in dimension(ctx):
                return True
            time.sleep(1)
        return False


class Dragon:
    """The fight: crystals first (bow), then the dragon at the fountain (sword)."""

    def __init__(self, task):
        self.task = task
        self.ctx = task.ctx

    def done(self):
        return self.task.done()

    def run(self):
        ctx = self.ctx
        end = time.time() + 40 * 60
        while time.time() < end and not self.done():
            if self.dragon_dead():
                return True
            crystals = [e for e in ctx.senses.call("entities 120").get("entities", [])
                        if "end_crystal" in e.get("type", "")]
            if crystals and count(ctx, "bow") and count(ctx, "arrow"):
                c = min(crystals, key=lambda e: e["distance"])
                self.shoot(c)
                continue
            dragon = next((e for e in ctx.senses.call("entities 120").get("entities", [])
                           if "ender_dragon" in e.get("type", "")), None)
            if dragon is None:
                time.sleep(1)
                continue
            # On the fountain (perched, low and slow near 0,0): go and hit it.
            dx, dz = dragon["pos"][0], dragon["pos"][2]
            if math.hypot(dx, dz) < 12 and dragon["pos"][1] < 75:
                ctx.select_best(WEAPONS)
                ctx.hunt(dragon["id"], 8.0, self.task)
            else:
                # Wait near the fountain, out of the way, shield up.
                ctx.body.call("goto 6.5 64 6.5 --near 3 --timeout 8")
                self.task.guard(owner_radius=0.0, self_radius=6.0)
                time.sleep(0.5)
        return self.dragon_dead()

    def shoot(self, crystal):
        ctx = self.ctx
        x, y, z = crystal["pos"]
        ctx.to_hotbar("minecraft:bow")
        ctx.body.call("select minecraft:bow")
        ctx.body.call(f"look-at {x:.2f} {y + 0.5:.2f} {z:.2f}")
        ctx.body.call("use-item --hold 1.1")  # full draw, then let go
        time.sleep(0.6)

    def dragon_dead(self):
        dragon = [e for e in self.ctx.senses.call("entities 200").get("entities", [])
                  if "ender_dragon" in e.get("type", "")]
        if not dragon:
            return False
        return (dragon[0].get("health") or 1) <= 0
