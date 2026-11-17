"""Dig out a room: 'keve mine out a bigger room in here' / 'help me dig out this room'.

Keve finds the room you're standing in (the open floor joined to yours, on your level),
then pushes its walls out a ring at a time, from your floor up to the room's ceiling height.
It never digs the floor or the ceiling, so the room stays on your y level.

Fair as always: a wall block is only broken once Keve stands in the room and can see it.
If digging opens up lava or water, Keve plugs the hole and leaves that side alone.
"""
import math
import time

import sight
import world_names
from blocks import TOOLS
from skills import PICKAXES, Task, base

SIDES = ((1, 0), (-1, 0), (0, 1), (0, -1))
MAX_FLOOR = 400      # an open cave or the outdoors: stop measuring there
MAX_DIGS = 260
MINUTES = 12


def solid(name):
    return sight.blocks_body(name) and not sight.is_fluid(name)


def measure(snap, start, y, height, radius):
    """The room's floor cells (x, z) on level y joined to `start`: open at feet and head."""
    sx, _, sz = start
    room, todo = set(), [(sx, sz)]
    while todo and len(room) < MAX_FLOOR:
        x, z = todo.pop()
        if (x, z) in room or abs(x - sx) > radius or abs(z - sz) > radius:
            continue
        if solid(snap.name((x, y, z))) or solid(snap.name((x, y + 1, z))):
            continue
        if not solid(snap.name((x, y - 1, z))) and not solid(snap.name((x, y - 2, z))):
            continue  # a hole or a drop, not floor
        room.add((x, z))
        todo.extend((x + dx, z + dz) for dx, dz in SIDES)
    return room


def ceiling_height(snap, x, y, z, most=5):
    h = 0
    while h < most and not solid(snap.name((x, y + h, z))):
        h += 1
    return h


class DigRoom(Task):
    name = "dig_room"

    def run(self):
        ctx = self.ctx
        grow = int(self.args.get("size") or 2)
        o = ctx.owner()
        if o:
            centre = tuple(math.floor(v) for v in o[1])
        else:
            centre = tuple(ctx.state()["player"]["block_pos"])
        x0, y, z0 = centre
        self.floor_y = y
        snap = sight.Snapshot.read(ctx.senses, centre, rh=14, rv=6)
        height = self.args.get("height") or max(2, min(4, ceiling_height(snap, x0, y, z0)))
        room = measure(snap, centre, y, height, 12)
        if not room:
            ctx.say("I can't tell where the room is. stand inside it and ask me again!")
            return
        if len(room) >= MAX_FLOOR:
            ctx.say("this place is already huge and open, I'll just widen the walls near you.")
        import mining
        prov = mining.Provision(ctx, self)
        if prov.pick_tier() < 0 and not prov.ensure_pickaxe(0):
            if not self.done():
                ctx.say("I need a pickaxe to dig, and I can't make one yet.")
            return
        miner = mining.Mine(ctx, ore="coal")
        miner.cancelled = self.cancelled
        miner.prov = prov
        names = world_names.names()
        ctx.say(f"widening the room by {grow}, {height} high, right here at your level!")
        deadline = time.time() + MINUTES * 60
        dug, blocked, hazard_cols = 0, set(), set()
        for ring in range(grow):
            # The wall columns right outside the room, nearest to Keve first.
            cols = {(x + dx, z + dz) for x, z in room for dx, dz in SIDES} - room - hazard_cols
            opened = set()
            while cols and not self.done() and time.time() < deadline and dug < MAX_DIGS:
                me = ctx.state()["player"]["block_pos"]
                col = min(cols, key=lambda c: math.dist((c[0], c[1]), (me[0], me[2])))
                cols.discard(col)
                ok = self.dig_column(miner, names, col, y, height, blocked)
                if ok is None:      # lava or water behind it
                    hazard_cols.add(col)
                    continue
                dug += ok
                if ok >= 0 and all((col[0], y + h, col[1]) not in blocked for h in (0, 1)):
                    opened.add(col)
                if dug and dug % 8 == 0:
                    ctx.collect(5, self)
            if self.done():
                return
            if not opened:
                break
            room |= opened
        ctx.collect(6, self)
        if self.done():
            return
        if dug:
            ctx.say(f"room's bigger! dug out {dug} blocks. that's what I call RENOVATION!")
        else:
            ctx.say("I couldn't dig any of these walls from in here.")
        if hazard_cols:
            ctx.say("careful, there's lava or water behind one of the walls. I left that bit alone.")

    def dig_column(self, miner, names, col, y, height, blocked):
        """Break one wall column, top down (falling gravel lands where it gets dug).
        How many blocks came out; None when lava or water showed up."""
        ctx = self.ctx
        x, z = col
        cells = [(x, y + h, z) for h in reversed(range(height))]
        snap = sight.Snapshot.read(ctx.senses, (x, y, z), rh=2, rv=height + 1)
        todo = [c for c in cells if solid(snap.name(c))]
        if not todo:
            return 0
        n = 0
        for c in todo:
            if self.done():
                return n
            name = snap.name(c)
            if any(u in name for u in ("bedrock", "barrier", "chest", "furnace", "crafting_table",
                                       "spawner", "portal", "door", "bed")):
                blocked.add(c)
                continue
            if not self.reach_and_see(c):
                blocked.add(c)
                continue
            tool = names.tool_for(name)[0] if names else "pickaxe"
            ctx.select_best(TOOLS.get(tool, PICKAXES))
            if not miner.dig_through(c):
                blocked.add(c)
                continue
            n += 1
            fluid = miner.hazard_near([c])
            if fluid:
                if "lava" in fluid:
                    miner.plug([c])
                return None
        return n

    def reach_and_see(self, c):
        """Stand close enough to `c` (inside the room) and check Keve can really see it."""
        ctx = self.ctx
        target = (c[0] + .5, c[1] + .5, c[2] + .5)
        for attempt in range(2):
            eye = tuple(ctx.state()["player"]["eye"])
            if math.dist(eye, target) <= 4.3:
                snap = sight.Snapshot.read(ctx.senses, c, rh=5, rv=4)
                if snap.block_visible(eye, c, 6.0):
                    return True
            if attempt == 0:
                ctx.body.call(f"goto {c[0] + 0.5:.1f} {self.floor_y:.1f} {c[2] + 0.5:.1f} --near 2.6 --timeout 8")
                if self.done():
                    return False
        return False
