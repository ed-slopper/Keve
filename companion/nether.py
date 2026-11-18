"""Getting to the Nether: obsidian (water poured on lava) and a portal built and lit.

Obsidian, like a player at a lava lake: fill a bucket at a water source, stand on solid
ground a couple of blocks from the lava, pour the water on the bank next to it (it runs
over the lava, which turns to obsidian), pick the water back up, then mine the obsidian
with the diamond pickaxe. All of it by sight: only lava and water Keve can see.

The portal: ten obsidian in a 4 x 5 frame (corners left out, held up by cobblestone
while it's built), on flat open ground, lit with flint and steel; then into it.
"""
import math
import time

import journal
import sight
from skills import base

SIDES = ((1, 0), (-1, 0), (0, 1), (0, -1))


def count(ctx, item):
    return ctx.counts().get("minecraft:" + item, 0)


def is_source(name, fluid):
    return name.startswith("minecraft:" + fluid) and "level=0" in name


class Obsidian:
    """Makes and mines obsidian until `want` is carried. Used by the quest."""

    def __init__(self, task, want=10):
        self.task = task
        self.ctx = task.ctx
        self.want = want

    def done(self):
        return self.task.done()

    def run(self):
        ctx = self.ctx
        if not count(ctx, "diamond_pickaxe"):
            ctx.say("obsidian needs a diamond pickaxe first.")
            return False
        for attempt in range(10):
            if self.done() or count(ctx, "obsidian") >= self.want:
                break
            self.mine_visible()
            if count(ctx, "obsidian") >= self.want:
                break
            if not count(ctx, "water_bucket") and not self.fill_water():
                self.look_elsewhere("water")
                continue
            if not self.pour_on_lava():
                self.look_elsewhere("lava")
        return count(ctx, "obsidian") >= self.want

    # --- the pieces ------------------------------------------------------------------
    def snap(self, r=12):
        eye = tuple(self.ctx.state()["player"]["eye"])
        return eye, sight.Snapshot.read(self.ctx.senses, eye, rh=r, rv=8)

    def mine_visible(self):
        """Obsidian already there (from a pour, or a lake that met water): mine it."""
        import blocks
        eye, snap = self.snap()
        if not any(base(n) == "minecraft:obsidian" for n in snap.blocks.values()):
            return
        t = blocks.BreakBlocks(self.ctx, ids=["minecraft:obsidian"], label="obsidian",
                               count=self.want - count(self.ctx, "obsidian"), near_owner=False)
        t.cancelled = self.task.cancelled
        t.run()

    def fill_water(self):
        """Fill the empty bucket at a water source in sight."""
        ctx = self.ctx
        if not count(ctx, "bucket"):
            return False
        eye, snap = self.snap()
        found = sorted((p for p, n in snap.blocks.items() if is_source(n, "water")),
                       key=lambda p: math.dist(p, eye))
        for p in found[:6]:
            if self.done():
                return False
            if math.dist(eye, (p[0] + .5, p[1] + .5, p[2] + .5)) > 4.0:
                ctx.body.call(f"goto {p[0] + 0.5:.1f} {p[1]:.1f} {p[2] + 0.5:.1f} --near 2.5 --timeout 12")
            eye = tuple(ctx.state()["player"]["eye"])
            if math.dist(eye, (p[0] + .5, p[1] + .5, p[2] + .5)) > 4.5:
                continue
            ctx.select_best(["bucket"])
            ctx.body.call(f"look-at block {p[0]} {p[1]} {p[2]}")
            ctx.body.call("use-item")
            time.sleep(0.4)
            if count(ctx, "water_bucket"):
                journal.log("quest", "obsidian: filled a water bucket")
                return True
        return False

    def pour_on_lava(self):
        """Lava in sight: pour water on the bank right next to a lava source, from a safe
        spot, wait for it to turn, take the water back. True when it was done once."""
        ctx = self.ctx
        if not count(ctx, "water_bucket"):
            return False
        eye, snap = self.snap()

        def solid(p):
            return sight.blocks_body(snap.name(p))
        lava = [p for p, n in snap.blocks.items() if is_source(n, "lava")
                and not solid((p[0], p[1] + 1, p[2])) and "lava" not in snap.name((p[0], p[1] + 1, p[2]))]
        lava.sort(key=lambda p: math.dist(p, eye))
        for L in lava[:8]:
            if self.done():
                return False
            # A bank block beside the lava, level with it, with room above for the water.
            for dx, dz in SIDES:
                bank = (L[0] + dx, L[1], L[2] + dz)
                above = (bank[0], bank[1] + 1, bank[2])
                if not solid(bank) or solid(above) or sight.is_fluid(snap.name(above)):
                    continue
                stand = self.safe_spot(snap, bank, lava)
                if stand is None:
                    continue
                ctx.body.call(f"goto {stand[0] + 0.5:.2f} {stand[1]:.2f} {stand[2] + 0.5:.2f} --near 0.6 --timeout 15")
                me = ctx.state()["player"]["block_pos"]
                if math.dist(me, stand) > 1.5:
                    continue
                ctx.say("pouring water on the lava for obsidian!")
                ctx.select_best(["water_bucket"])
                ctx.body.call(f"look-at block {bank[0]} {bank[1]} {bank[2]}")
                ctx.body.call(f"interact {bank[0]} {bank[1]} {bank[2]} up")
                time.sleep(3.0)  # the water runs over the lava
                # The water back into the bucket (or it floods the place).
                ctx.select_best(["bucket"])
                ctx.body.call(f"look-at block {above[0]} {above[1]} {above[2]}")
                ctx.body.call("use-item")
                time.sleep(0.5)
                journal.log("quest", "obsidian: poured water on lava", at=list(L))
                return True
        return False

    def safe_spot(self, snap, target, lava):
        """Where to stand to pour on `target`: solid floor, room for a body, in reach of it,
        and no lava within two blocks."""
        best = None
        for dx in range(-4, 5):
            for dz in range(-4, 5):
                for dy in (-1, 0, 1, 2):
                    c = (target[0] + dx, target[1] + dy, target[2] + dz)
                    if not sight.blocks_body(snap.name((c[0], c[1] - 1, c[2]))):
                        continue
                    if sight.blocks_body(snap.name(c)) or sight.blocks_body(snap.name((c[0], c[1] + 1, c[2]))):
                        continue
                    if sight.is_fluid(snap.name(c)) or sight.is_fluid(snap.name((c[0], c[1] - 1, c[2]))):
                        continue
                    eye = (c[0] + 0.5, c[1] + 1.62, c[2] + 0.5)
                    d = math.dist(eye, (target[0] + .5, target[1] + 1, target[2] + .5))
                    if d > 4.2 or d < 1.5:
                        continue
                    if any(math.dist(c, L) < 2.5 for L in lava):
                        continue
                    if best is None or d < best[0]:
                        best = (d, c)
        return best[1] if best else None

    def look_elsewhere(self, what):
        """Nothing in sight: tunnel on a stretch and look again (lava lakes are common at the
        bottom of the world, water everywhere)."""
        import mining
        ctx = self.ctx
        journal.log("quest", f"obsidian: no {what} in sight, moving on")
        m = mining.Mine(ctx, ore="diamond")
        m.cancelled = self.task.cancelled
        m.prov = mining.Provision(ctx, m)
        p = ctx.state()["player"]
        m.dir = mining.DIRS[round(((p["yaw"] % 360) / 90)) % 4]
        for _ in range(16):
            if self.done():
                return
            if not m.tunnel_step():
                m.turn()


class Portal:
    """A nether portal: a 4 x 5 obsidian frame (no corners) on flat ground, lit."""

    def __init__(self, task):
        self.task = task
        self.ctx = task.ctx

    def run(self):
        ctx = self.ctx
        import mining
        if mining.underground(ctx):
            mining.go_to_surface(ctx, self.task)
        if count(ctx, "obsidian") < 10:
            ctx.say("I need 10 obsidian for a portal.")
            return False
        if not count(ctx, "flint_and_steel") and not self.flint_and_steel():
            return False
        spot = self.find_spot()
        if spot is None:
            ctx.say("no flat open spot for a portal here.")
            return False
        x, y, z = spot
        ctx.say(f"building a nether portal at {x} {y} {z}!")
        helper = next((i for i in ("cobblestone", "cobbled_deepslate", "dirt") if count(ctx, i)), None)
        # Order matters: everything placed has something to stick to.
        plan = [((x, y, z), helper), ((x + 3, y, z), helper),
                ((x + 1, y, z), "obsidian"), ((x + 2, y, z), "obsidian")]
        for h in (1, 2, 3):
            plan += [((x, y + h, z), "obsidian"), ((x + 3, y + h, z), "obsidian")]
        plan += [((x, y + 4, z), helper), ((x + 3, y + 4, z), helper),
                 ((x + 1, y + 4, z), "obsidian"), ((x + 2, y + 4, z), "obsidian")]
        ctx.body.call(f"goto {x + 1.5:.2f} {y:.2f} {z + 2.5:.2f} --near 0.8 --timeout 15")
        for cell, item in plan:
            if self.task.done():
                return False
            if item is None:
                continue
            r = ctx.place(cell, "minecraft:" + item)
            if r.get("error") and item == "obsidian":
                journal.log("quest", "portal: a frame block wouldn't go", at=list(cell), error=str(r["error"])[:150])
        # Light it: flint and steel on the inside of the bottom.
        ctx.select_best(["flint_and_steel"])
        ctx.body.call(f"look-at block {x + 1} {y} {z}")
        ctx.body.call(f"interact {x + 1} {y} {z} up")
        time.sleep(1.0)
        inside = (x + 1, y + 1, z)
        n = ctx.senses.call(f"blocks {inside[0]} {inside[1]} {inside[2]} {inside[0]} {inside[1]} {inside[2]}").get("blocks", [])
        lit = bool(n) and "nether_portal" in n[0][3]
        journal.log("quest", f"portal: {'lit' if lit else 'did not light'}", at=[x, y, z])
        if lit:
            import life
            mem = life.load_memory()
            mem.setdefault("places", {})["portal"] = [x + 1.5, y + 1, z + 0.5]
            life.save_memory(mem)
        return lit

    def flint_and_steel(self):
        """Flint (from gravel) and an iron ingot."""
        ctx = self.ctx
        import blocks
        import mining
        if not count(ctx, "flint"):
            for _ in range(3):
                if count(ctx, "flint") or self.task.done():
                    break
                t = blocks.BreakBlocks(ctx, ids=["minecraft:gravel"], label="gravel", count=10, near_owner=False)
                t.cancelled = self.task.cancelled
                t.run()
        if not count(ctx, "flint"):
            ctx.say("I can't find flint (gravel gives it).")
            return False
        prov = mining.Provision(ctx, self.task)
        try:
            return prov.ensure("flint_and_steel", 1)
        except Exception as e:
            ctx.say(f"couldn't make flint and steel: {e}")
            return False

    def find_spot(self):
        """Flat solid ground 4 wide, open 5 high, near Keve."""
        ctx = self.ctx
        x0, y0, z0 = ctx.state()["player"]["block_pos"]
        snap = sight.Snapshot.read(ctx.senses, (x0, y0, z0), rh=10, rv=6)
        for r in range(2, 10):
            for dx in range(-r, r + 1):
                for dz in (-r, r):
                    for dy in (0, -1, 1):
                        x, y, z = x0 + dx, y0 + dy, z0 + dz
                        if all(sight.blocks_body(snap.name((x + i, y - 1, z))) for i in range(4)) and \
                                all(not sight.blocks_body(snap.name((x + i, y + h, z))) and
                                    not sight.is_fluid(snap.name((x + i, y + h, z)))
                                    for i in range(4) for h in range(5)) and \
                                all(not sight.blocks_body(snap.name((x + i, y + h, z + 1))) for i in range(4) for h in range(2)):
                            return (x, y, z)
        return None

    def go_through(self):
        """Into the portal and wait for the Nether."""
        ctx = self.ctx
        import life
        p = life.load_memory().get("places", {}).get("portal")
        if not p:
            return False
        ctx.walk_to(tuple(p), near=1.5, timeout=30, task=self.task)
        ctx.body.call(f"goto {p[0]:.2f} {p[1]:.2f} {p[2]:.2f} --near 0.3 --timeout 4 --direct")
        for _ in range(20):
            if "nether" in str(ctx.body.call("state").get("dimension", "")):
                return True
            time.sleep(1)
        return False
