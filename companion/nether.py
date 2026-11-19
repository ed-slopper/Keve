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
        for attempt in range(30):
            if self.done() or count(ctx, "obsidian") >= self.want:
                break
            self.mine_visible()
            if count(ctx, "obsidian") >= self.want:
                break
            if not count(ctx, "water_bucket") and not self.fill_water() and not self.surface_water():
                self.go_deep("water")
                continue
            if not self.pour_on_lava() and not (self.approach_lava() and self.pour_on_lava()):
                self.go_deep("lava")
        return count(ctx, "obsidian") >= self.want

    # --- the pieces ------------------------------------------------------------------
    def snap(self, r=12):
        eye = tuple(self.ctx.state()["player"]["eye"])
        return eye, sight.Snapshot.read(self.ctx.senses, eye, rh=r, rv=8)

    def mine_visible(self):
        """Obsidian already there (from a pour, or a lake that met water): mine it."""
        import blocks
        eye, snap = self.snap()
        obs = [p for p, n in snap.blocks.items() if base(n) == "minecraft:obsidian"]
        # Over lava, a broken obsidian's drop falls in and burns (and walking out on the lake
        # to it killed him): only ones with solid ground under them.
        unsafe = [p for p in obs if not sight.blocks_body(snap.name((p[0], p[1] - 1, p[2])))
                  or sight.is_fluid(snap.name((p[0], p[1] - 1, p[2])))]
        if len(unsafe) == len(obs):
            return
        t = blocks.BreakBlocks(self.ctx, ids=["minecraft:obsidian"], label="obsidian", skip=unsafe,
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
            ctx.to_hotbar("minecraft:bucket")
            ctx.body.call("select minecraft:bucket")
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
        # Shallow lava first (solid under it): the obsidian it turns into can be mined
        # without the drop falling into the lake.
        lava.sort(key=lambda p: (not solid((p[0], p[1] - 1, p[2])), math.dist(p, eye)))
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
                if math.dist(me, stand) > 1.5 and math.dist(me, stand) < 24:
                    # Seen through the rock from the tunnel: dig over to it.
                    import room
                    t = room.DigTo(ctx, target=(stand[0] + 0.5, stand[1], stand[2] + 0.5))
                    t.cancelled = self.task.cancelled
                    t.run()
                    me = ctx.state()["player"]["block_pos"]
                if math.dist(me, stand) > 1.5:
                    continue
                ctx.say("pouring water on the lava for obsidian!")
                # The bucket by name (select_best is for tools: it held something else and
                # "poured" a pickaxe on the bank a dozen times over).
                ctx.to_hotbar("minecraft:water_bucket")
                ctx.body.call("select minecraft:water_bucket")
                ctx.body.call(f"look-at block {bank[0]} {bank[1]} {bank[2]}")
                r = ctx.body.call(f"interact {bank[0]} {bank[1]} {bank[2]} up")
                if (r.get("inventory_change") or {}).get("minecraft:water_bucket", 0) >= 0:
                    journal.log("quest", "obsidian: the water didn't go down", at=list(bank))
                    continue
                time.sleep(3.0)  # the water runs over the lava
                # The water back into the bucket (or it floods the place): the bank's top,
                # where the water stands.
                ctx.to_hotbar("minecraft:bucket")
                ctx.body.call("select minecraft:bucket")
                ctx.body.call(f"look-at block {bank[0]} {bank[1]} {bank[2]}")
                ctx.body.call("use-item")
                time.sleep(0.5)
                journal.log("quest", "obsidian: poured water on lava", at=list(L),
                            back=bool(count(ctx, "water_bucket")))
                return True
        return False

    def approach_lava(self):
        """Lava seen through the rock (a lake in a cave next to the tunnel): tunnel over to
        it one block above its surface (lava can't climb into the tunnel), stop where the
        floor ahead is lava, and back off two: then the shore under the tunnel mouth is a
        bank to pour on. True when he's there."""
        ctx = self.ctx
        eye, snap = self.snap(10)
        here = tuple(ctx.state()["player"]["block_pos"])
        lava = [p for p, n in snap.blocks.items() if is_source(n, "lava")
                and not sight.blocks_body(snap.name((p[0], p[1] + 1, p[2])))
                and "lava" not in snap.name((p[0], p[1] + 1, p[2]))]
        tried = getattr(self, "tried_lava", [])
        lava = [p for p in lava if not any(math.dist(p, t) < 4 for t in tried)]
        if not lava:
            return False
        L = min(lava, key=lambda p: (not sight.blocks_body(snap.name((p[0], p[1] - 1, p[2]))), math.dist(p, here)))
        self.tried_lava = tried + [L]
        dx, dz = here[0] - L[0], here[2] - L[2]
        d = (1 if dx > 0 else -1, 0) if abs(dx) >= abs(dz) else (0, 1 if dz > 0 else -1)
        y = L[1] + 1
        journal.log("quest", "obsidian: tunnelling over to lava", lava=list(L))
        ctx.say("lava through the rock there: tunnelling over to it, carefully.")
        import room
        start = (L[0] + 3 * d[0], y, L[2] + 3 * d[1])
        t = room.DigTo(ctx, target=(start[0] + 0.5, y, start[2] + 0.5))
        t.cancelled = self.task.cancelled
        t.run()
        me = tuple(ctx.state()["player"]["block_pos"])
        if math.dist(me, start) > 1.5:
            return False
        ctx.body.call(f"goto {start[0] + 0.5:.2f} {y:.2f} {start[2] + 0.5:.2f} --near 0.4 --timeout 4")
        step = (-d[0], -d[1])  # toward the lava
        ctx.select_best(["netherite_pickaxe", "diamond_pickaxe", "iron_pickaxe", "stone_pickaxe"])
        for _ in range(4):
            if self.done():
                return False
            me = tuple(ctx.state()["player"]["block_pos"])
            front = (me[0] + step[0], me[1], me[2] + step[1])
            _, s = self.snap(4)
            if "lava" in s.name((front[0], front[1] - 1, front[2])):
                break  # the edge: the lake starts under the next block
            if "lava" in s.name(front) or "lava" in s.name((front[0], front[1] + 1, front[2])):
                return False  # lava at his own level: not this way
            for c in ((front[0], front[1] + 1, front[2]), front):
                if sight.blocks_body(s.name(c)):
                    ctx.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
                    ctx.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 12")
            time.sleep(0.3)
            _, s = self.snap(4)
            if "lava" in s.name((front[0], front[1] - 1, front[2])):
                break  # opened onto the lake: stay back, the shore is right here
            ctx.body.call(f"goto {front[0] + 0.5:.2f} {front[1]:.2f} {front[2] + 0.5:.2f} --near 0.4 --timeout 3 --direct")
        else:
            return False
        # Back two from the edge (the pour spot must keep clear of the lava).
        me = tuple(ctx.state()["player"]["block_pos"])
        back = (me[0] - step[0] * 2, me[1], me[2] - step[1] * 2)
        ctx.body.call(f"goto {back[0] + 0.5:.2f} {back[1]:.2f} {back[2] + 0.5:.2f} --near 0.5 --timeout 4")
        return True

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

    def surface_water(self):
        """Water's for the surface: a lake, a river, the sea (55 minutes at the bottom of
        the world near spawn found lava but never water). Up, then to the nearest open
        water in sight of the land round about, and fill the bucket there."""
        import mining
        ctx = self.ctx
        if not count(ctx, "bucket"):
            return False
        if mining.underground(ctx):
            mining.go_to_surface(ctx, self.task)
            if self.done():
                return False
        for leg in range(4):
            if self.done():
                return False
            bad = getattr(self, "bad_water", [])
            spots = [w for w in self.open_water_round() if not any(math.dist(w, b) < 8 for b in bad)]
            if spots:
                w = spots[0]
                ctx.say("I can see water over there, filling my bucket!")
                journal.log("quest", "obsidian: walking to water", at=list(w))
                self.task.travel(w[0] + 0.5, w[2] + 0.5)
                ctx.walk_to((w[0] + 0.5, w[1] + 1, w[2] + 0.5), near=3, timeout=20, task=self.task)
                if self.fill_water():
                    return True
                self.bad_water = bad + [w]  # couldn't get at it: not that one again
                journal.log("quest", "obsidian: couldn't reach that water", at=list(w))
                continue
            # None about: off a good stretch the way he's facing, and look again.
            p = ctx.state()["player"]
            yaw = math.radians(p["yaw"] + 60 * leg)
            pos = p["position"]
            self.task.travel(pos[0] - math.sin(yaw) * 80, pos[2] + math.cos(yaw) * 80)
        return False

    def open_water_round(self, r=48):
        """Open water (sky over it) round about, nearest first: what a player standing on
        the land sees of a lake or the sea. Read in four tiles (a read is capped)."""
        x, _, z = self.ctx.state()["player"]["block_pos"]
        water = []
        for x0, z0 in ((x - r, z - r), (x, z - r), (x - r, z), (x, z)):
            got = self.ctx.senses.call(f"blocks {x0} 56 {z0} {x0 + r} 67 {z0 + r}").get("blocks", [])
            filled = {(b[0], b[1], b[2]) for b in got}
            for b in got:
                if b[3].startswith("minecraft:water") and b[1] <= 66 and (b[0], b[1] + 1, b[2]) not in filled:
                    water.append((b[0], b[1], b[2]))
        # A lake or a river, not a puddle down a pit: open water with more round it.
        cells = set(water)
        water = [w for w in water if sum((w[0] + dx, w[1], w[2] + dz) in cells
                                         for dx in range(-2, 3) for dz in range(-2, 3)) >= 8]
        water.sort(key=lambda p: (p[0] - x) ** 2 + (p[2] - z) ** 2)
        return water

    def worth_a_look(self):
        """Down a mine: stop for what obsidian needs. Obsidian already there; a water source
        while he has no water; lava open on top once he has water."""
        ctx = self.ctx
        self._looks = getattr(self, "_looks", 0) + 1
        if self._looks % 2:
            return False  # every other step (a snapshot each time)
        eye, snap = self.snap(8)
        water = count(ctx, "water_bucket")
        for p, n in snap.blocks.items():
            if base(n) == "minecraft:obsidian":
                return True
            if not water and is_source(n, "water"):
                return True
            if water and is_source(n, "lava"):
                above = snap.name((p[0], p[1] + 1, p[2]))
                if not sight.blocks_body(above) and "lava" not in above:
                    return True
        return False

    def go_deep(self, what):
        """Nothing in sight: down to the bottom of the world, where lava lakes and the water
        of the aquifers are everywhere (a mountain top has neither), branch mining until
        one is in sight, and stay there."""
        import mining
        ctx = self.ctx
        journal.log("quest", f"obsidian: no {what} in sight, going deep")
        if ctx.state()["player"]["block_pos"][1] > -30:
            ctx.say(f"no {what} up here: down to the bottom, where the lava lakes are.")
        m = mining.Mine(ctx, ore="diamond", count=99)
        m.cancelled = self.task.cancelled
        m.stay_down = True
        m.stop_when = self.worth_a_look
        m.run()

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
        # A frame begun before (some obsidian already in it): finish that one.
        import life
        site = life.load_memory().get("places", {}).get("portal_site")
        here = ctx.state()["player"]["position"]
        built = 0
        if site and math.dist(site, here) < 48:
            sx, sy, sz = site
            got = ctx.senses.call(f"blocks {sx} {sy} {sz} {sx + 3} {sy + 4} {sz}").get("blocks", [])
            built = sum(1 for b in got if "obsidian" in b[3])
        if count(ctx, "obsidian") + built < 10:
            ctx.say("I need 10 obsidian for a portal.")
            return False
        if not count(ctx, "flint_and_steel") and not self.flint_and_steel():
            return False
        spot = tuple(site) if built else self.find_spot()
        if spot is None:
            ctx.say("no flat open spot for a portal here.")
            return False
        x, y, z = spot
        ctx.say(f"building a nether portal at {x} {y} {z}!")
        # From a pit (an old hiding hole) there's no walking round the frame: out first.
        if ctx.in_hole():
            ctx.climb_out(self.task)
        r = ctx.body.call(f"goto {x + 1.5:.2f} {y:.2f} {z + 2.5:.2f} --near 2.5 --timeout 15")
        if r.get("error") and "no walking path" in str(r["error"]):
            ctx.climb_out(self.task)
        helper = next((i for i in ("cobblestone", "cobbled_deepslate", "dirt") if count(ctx, i)), None)
        import life
        mem = life.load_memory()
        mem.setdefault("places", {})["portal_site"] = [x, y, z]
        life.save_memory(mem)
        # Stand in front of it, two back (or behind: the front was a dip in the ground).
        stand = None
        for sz in (z + 2, z - 2):
            ctx.body.call(f"goto {x + 1.5:.2f} {y:.2f} {sz + 0.5:.2f} --near 0.6 --timeout 15")
            p = ctx.state()["player"]["position"]
            if abs(p[0] - (x + 1.5)) < 1.0 and abs(p[2] - (sz + 0.5)) < 1.0:
                stand = sz
                break
        if stand is None:
            ctx.walk_to((x + 1.5, y, z + 2.5), near=1.5, timeout=15, task=self.task)
        # Grass, flowers, leaf litter where the frame goes: a block can't be put in them.
        for i in range(4):
            for h in range(5):
                c = (x + i, y + h, z)
                n = ctx.senses.call(f"blocks {c[0]} {c[1]} {c[2]} {c[0]} {c[1]} {c[2]}").get("blocks", [])
                if n and not sight.blocks_body(n[0][3]) and not sight.is_fluid(n[0][3]):
                    ctx.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
                    ctx.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 3")

        def put(cells):
            for cell, item in cells:
                if self.task.done() or item is None:
                    continue
                n = ctx.senses.call(f"blocks {cell[0]} {cell[1]} {cell[2]} {cell[0]} {cell[1]} {cell[2]}").get("blocks", [])
                if n and sight.blocks_body(n[0][3]):
                    continue  # already there (a frame half built last time)
                r = ctx.place(cell, "minecraft:" + item)
                if r.get("error") and item == "obsidian":
                    journal.log("quest", "portal: a frame block wouldn't go", at=list(cell), error=str(r["error"])[:150])

        # A block goes on top of another only if he can see that top face: from the ground
        # his eye is below the frame's upper half. So like a player: the bottom from the
        # ground, then up a pillar under himself (jump, block below) a level at a time.
        put([((x, y, z), helper), ((x + 3, y, z), helper),
             ((x + 1, y, z), "obsidian"), ((x + 2, y, z), "obsidian")])
        self.pillar_to(y + 1)
        put([((x, y + 1, z), "obsidian"), ((x + 3, y + 1, z), "obsidian"),
             ((x, y + 2, z), "obsidian"), ((x + 3, y + 2, z), "obsidian")])
        self.pillar_to(y + 2)
        put([((x, y + 3, z), "obsidian"), ((x + 3, y + 3, z), "obsidian")])
        self.pillar_to(y + 3)
        put([((x, y + 4, z), helper), ((x + 3, y + 4, z), helper),
             ((x + 1, y + 4, z), "obsidian"), ((x + 2, y + 4, z), "obsidian")])
        # Light it: flint and steel on the inside of the bottom.
        ctx.to_hotbar("minecraft:flint_and_steel")
        ctx.body.call("select minecraft:flint_and_steel")
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

    def pillar_to(self, feet_y):
        """Up a pillar of blocks under himself until his feet are at feet_y."""
        ctx = self.ctx
        block = next((i for i in ("cobblestone", "cobbled_deepslate", "dirt", "netherrack") if count(ctx, i)), None)
        if block is None:
            return False
        for _ in range(6):
            p = ctx.state()["player"]
            x, y, z = p["block_pos"]
            if y >= feet_y:
                return True
            ctx.to_hotbar("minecraft:" + block)
            ctx.body.call(f"select minecraft:{block}")
            ctx.body.call("look 0 90")
            ctx.body.call("key space down")
            time.sleep(0.35)
            ctx.body.call(f"place {x} {y} {z}")
            ctx.body.call("key space up")
            time.sleep(0.8)
        return ctx.state()["player"]["block_pos"][1] >= feet_y

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
        # Gone out (it does: the frame stood empty when he came back): light it again.
        ix, iy, iz = math.floor(p[0]), math.floor(p[1]), math.floor(p[2])
        n = ctx.senses.call(f"blocks {ix} {iy} {iz} {ix} {iy} {iz}").get("blocks", [])
        if not (n and "nether_portal" in n[0][3]) and count(ctx, "flint_and_steel"):
            ctx.body.call(f"goto {p[0]:.2f} {p[1]:.2f} {p[2] + 2:.2f} --near 1 --timeout 6")
            ctx.to_hotbar("minecraft:flint_and_steel")
            ctx.body.call("select minecraft:flint_and_steel")
            ctx.body.call(f"look-at block {ix} {iy - 1} {iz}")
            ctx.body.call(f"interact {ix} {iy - 1} {iz} up")
            time.sleep(1.0)
            journal.log("quest", "portal: relit it")
        ctx.body.call(f"goto {p[0]:.2f} {p[1]:.2f} {p[2]:.2f} --near 0.3 --timeout 4 --direct")
        for _ in range(20):
            if "nether" in str(ctx.body.call("state").get("dimension", "")):
                return True
            time.sleep(1)
        return False


class NetherHunt:
    """In the Nether: tunnel along at fortress height through the netherrack (it mines in
    an instant) looking for nether bricks; at a fortress, find the blaze spawner and fight
    the blazes that come for him until he has the rods. Endermen met on the way are
    hunted for pearls."""

    FORTRESS_Y = 68

    def __init__(self, task, rods=6, pearls=0):
        self.task = task
        self.ctx = task.ctx
        self.rods = rods
        self.pearls = pearls

    def done(self):
        return self.task.done()

    def in_nether(self):
        return "nether" in str(self.ctx.body.call("state").get("dimension", ""))

    def have_enough(self):
        return count(self.ctx, "blaze_rod") + count(self.ctx, "blaze_powder") // 2 >= self.rods and \
            count(self.ctx, "ender_pearl") + count(self.ctx, "ender_eye") >= self.pearls

    def run(self):
        import mining
        ctx = self.ctx
        if not self.in_nether():
            ctx.say("I'm not in the nether.")
            return False
        m = mining.Mine(ctx, ore="gold")
        m.cancelled = self.task.cancelled
        m.prov = mining.Provision(ctx, m)
        m.wanted = {"gold"}
        m.open_ok = True  # caverns are the way through here, not caves to board up
        # What a trip's run() would set up (its checks read them).
        m.drop_names, m.start_have, m.goal = {"minecraft:gold_nugget"}, 0, 10 ** 6
        m.deadline, m._stop, m.need_tier = time.time() + 3 * 3600, False, 0
        p = ctx.state()["player"]
        m.dir = mining.DIRS[round(((p["yaw"] % 360) / 90)) % 4]
        # Level with the fortresses first.
        for _ in range(60):
            if self.done():
                return False
            y = m.pos()[1]
            if abs(y - self.FORTRESS_Y) <= 2:
                break
            ok = m.stair_up() if y < self.FORTRESS_Y else m.stair_step()
            if not ok:
                m.turn()
        steps = 0
        while not self.done() and not self.have_enough() and steps < 800:
            fortress = self.seen("nether_bricks")
            if fortress:
                journal.log("quest", "nether: found a fortress", at=list(fortress))
                ctx.say("a nether fortress! hunting blazes.")
                self.blazes(fortress)
                if self.have_enough():
                    break
            self.endermen()
            if not m.tunnel_step():
                m.turn()
                continue
            m.after_step()
            steps += 1
            if steps % 40 == 0:
                journal.log("quest", f"nether: tunnelled {steps} blocks", at=list(m.pos()))
        return self.have_enough()

    def seen(self, word, r=16):
        eye = tuple(self.ctx.state()["player"]["eye"])
        snap = sight.Snapshot.read(self.ctx.senses, eye, rh=r, rv=8)
        found = sorted((p for p, n in snap.blocks.items() if word in n), key=lambda p: math.dist(p, eye))
        for p in found[:20]:
            if snap.block_visible(eye, p, float(r) + 4):
                return p
        return None

    def blazes(self, fortress):
        """Into the fortress: to the blaze spawner if one shows, fight blazes near it."""
        ctx = self.ctx
        ctx.walk_to(tuple(fortress), near=3, timeout=30, task=self.task)
        end = time.time() + 15 * 60
        while time.time() < end and not self.done() and not self.have_enough():
            spawner = self.seen("spawner", r=20)
            if spawner:
                ctx.walk_to((spawner[0] + 3, spawner[1], spawner[2]), near=3, timeout=20, task=self.task)
            fought = False
            for e in ctx.senses.call("entities 16").get("entities", []):
                if e.get("type") == "minecraft:blaze" and (e.get("health") or 1) > 0:
                    ctx.select_best(["netherite_sword", "diamond_sword", "iron_sword", "stone_sword"])
                    ctx.hunt(e["id"], 15.0, self.task)
                    fought = True
                    break
            time.sleep(0.5)
            ctx.collect(8, self.task)
            if not fought and not spawner:
                # No spawner, no blazes here: along the fortress a bit.
                b = self.seen("nether_bricks", r=20)
                if b:
                    ctx.walk_to(tuple(b), near=2, timeout=15, task=self.task)
            if self.task.guard(owner_radius=0.0, self_radius=5.0):
                continue

    def endermen(self):
        ctx = self.ctx
        if count(ctx, "ender_pearl") >= self.pearls:
            return
        for e in ctx.senses.call("entities 16").get("entities", []):
            if e.get("type") == "minecraft:enderman":
                ctx.select_best(["netherite_sword", "diamond_sword", "iron_sword", "stone_sword"])
                ctx.hunt(e["id"], 20.0, self.task)
                time.sleep(0.6)
                ctx.collect(6, self.task)
                return
