"""Planting: 'keve plant the sapling' / 'plant 3 oak saplings' / 'plant the seeds'.

Saplings go on soil next to you (grass, dirt, podzol, moss...) with room above them to
grow, not right against another sapling; seeds and crops go on farmland. With no
sapling on hand, Keve breaks leaves until one drops, as a player would.
"""
import math
import time

import sight
import world_names
from blocks import find_target, walk_to_reach
from skills import Task, base

SOIL = ("minecraft:grass_block", "minecraft:dirt", "minecraft:podzol", "minecraft:coarse_dirt",
        "minecraft:rooted_dirt", "minecraft:moss_block", "minecraft:mud", "minecraft:muddy_mangrove_roots")
CROPS = {"minecraft:wheat_seeds", "minecraft:carrot", "minecraft:potato", "minecraft:beetroot_seeds",
         "minecraft:melon_seeds", "minecraft:pumpkin_seeds", "minecraft:torchflower_seeds",
         "minecraft:pitcher_pod"}


def plantable(item):
    return bool(item) and (item.endswith("_sapling") or item.endswith("_propagule") or item in CROPS)


class Plant(Task):
    name = "plant"

    def run(self):
        ctx = self.ctx
        want = int(self.args.get("count", 1))
        item = self.args.get("item")
        if not plantable(item):
            item = None  # "plant this here": whatever sapling Keve has

        def pick():
            counts = ctx.counts()
            if item:
                return item if counts.get(item) else None
            return next((i for i in counts if i.endswith("_sapling") or i.endswith("_propagule")), None)

        seed = pick()
        if seed is None and (item is None or item.endswith("_sapling")):
            seed = self.sapling_from_leaves(item)
        if seed is None:
            if not self.done():
                what = (item or "minecraft:sapling").removeprefix("minecraft:").replace("_", " ")
                ctx.say(f"I don't have a {what} to plant.")
            return
        crop = seed in CROPS
        planted = 0
        tried = set()
        for _ in range(want):
            if self.done() or not ctx.counts().get(seed):
                break
            done = False
            for _try in range(6):  # a refused spot (a mob in it, out of reach): the next one
                spots = [sp for sp in self.spots(crop) if sp not in tried]
                if not spots:
                    break
                spot = spots[0]
                tried.add(spot)
                if math.dist(ctx.eye_and_view()[3], spot) > 2.5:
                    ctx.walk_to(spot, near=2.0, timeout=10, task=self)
                r = ctx.place(spot, seed)
                if not r.get("error"):
                    planted += 1
                    done = True
                    break
            if not done:
                ctx.say("I need farmland for that." if crop else "no good ground to plant on here.")
                break
        if planted:
            what = seed.removeprefix("minecraft:").replace("_", " ")
            ctx.say(f"planted {planted} {what}{'s' if planted > 1 else ''}! grow, little buddy, GROW!")

    def sapling_from_leaves(self, item):
        """Break leaves (of the kind asked for, or any) until a sapling drops."""
        ctx = self.ctx
        names = world_names.names()
        if names is None:
            return None
        kind = item.removeprefix("minecraft:").removesuffix("_sapling") if item else None
        leaves = set(names.tag("leaves"))
        if kind:
            leaves = {b for b in leaves if b.removeprefix("minecraft:").startswith(kind)} or leaves
        ctx.say("no sapling on me, shaking some leaves for one.")
        for _ in range(25):
            if self.done():
                return None
            p = find_target(ctx, self, leaves, near_owner=False)
            if p is None:
                return None
            walk_to_reach(ctx, p)
            ctx.body.call(f"look-at block {p[0]} {p[1]} {p[2]}")
            if ctx.body.call(f"break {p[0]} {p[1]} {p[2]} --timeout 5").get("error"):
                continue
            ctx.recent_breaks.append((p[0], p[1], p[2], time.time()))
            time.sleep(0.7)
            ctx.collect(5, self)
            got = next((i for i in ctx.counts() if (item and i == item) or
                        (not item and i.endswith("_sapling"))), None)
            if got:
                return got
        return None

    def spot(self, crop):
        sp = self.spots(crop)
        return sp[0] if sp else None

    def spots(self, crop):
        """Free cells by you on soil (or farmland), room above, not crowding a sapling;
        the best first."""
        ctx = self.ctx
        o = ctx.owner()
        centre = o[1] if o else ctx.eye_and_view()[3]
        c = [int(math.floor(v)) for v in centre]
        snap = sight.Snapshot.read(ctx.senses, centre, rh=5, rv=3)
        ground = ("minecraft:farmland",) if crop else SOIL
        me = ctx.eye_and_view()[3]
        found = []
        for dx in range(-4, 5):
            for dz in range(-4, 5):
                for dy in (0, -1, 1):
                    cell = (c[0] + dx, c[1] + dy, c[2] + dz)
                    if base(snap.name((cell[0], cell[1] - 1, cell[2]))) not in ground:
                        continue
                    here = snap.name(cell)
                    if here != "minecraft:air" and not here.startswith(("minecraft:short_grass",
                                                                         "minecraft:tall_grass")):
                        continue
                    if not crop and snap.name((cell[0], cell[1] + 1, cell[2])) != "minecraft:air":
                        continue
                    # Not where you or Keve stand; saplings not right next to another one.
                    if (abs(cell[0] + .5 - centre[0]) < .9 and abs(cell[2] + .5 - centre[2]) < .9) or \
                            (abs(cell[0] + .5 - me[0]) < .9 and abs(cell[2] + .5 - me[2]) < .9):
                        continue
                    if not crop and any("sapling" in snap.name((cell[0] + a, cell[1], cell[2] + b))
                                        for a in (-1, 0, 1) for b in (-1, 0, 1)):
                        continue
                    d = math.dist(cell, centre)
                    if d >= 1.5:
                        found.append((d, cell))
        found.sort()
        return [cell for _, cell in found]
