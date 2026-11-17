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


class ReplaceFloor(Task):
    """'keve replace the floor with cobblestone (it's in the chest)': every floor block of the
    room you're in, swapped for that block. Takes it from a nearby chest if Keve is short."""
    name = "floor"
    MAX_CELLS = 160

    def run(self):
        ctx = self.ctx
        item = self.args.get("item") or "minecraft:cobblestone"
        shown = item.removeprefix("minecraft:").replace("_", " ")
        o = ctx.owner()
        centre = tuple(math.floor(v) for v in (o[1] if o else ctx.state()["player"]["position"]))
        y = centre[1]
        snap = sight.Snapshot.read(ctx.senses, centre, rh=14, rv=4)
        room = measure(snap, centre, y, 2, 12)
        self.room = room
        if not room:
            ctx.say("I can't tell where the floor is. stand in the room and ask again!")
            return
        cells = [(x, y - 1, z) for x, z in room if base(snap.name((x, y - 1, z))) != item]
        if len(room) >= MAX_FLOOR:
            ctx.say("this place is huge, I'll do the floor around you.")
        cells.sort(key=lambda c: math.dist(c, centre))
        cells = cells[:self.MAX_CELLS]
        if not cells:
            ctx.say(f"the floor's already all {shown}!")
            return
        have = ctx.counts().get(item, 0)
        if have < len(cells):
            self.fetch(item, len(cells) - have)
            have = ctx.counts().get(item, 0)
        if have <= 0:
            ctx.say(f"I don't have any {shown}, and there's none in a chest near you.")
            return
        if have < len(cells):
            ctx.say(f"I've only got {have} {shown} for {len(cells)} floor blocks, doing what I can.")
            cells = cells[:have]
        ctx.say(f"new floor coming up: {len(cells)} blocks of {shown}!")
        names = world_names.names()
        done = 0
        for c in cells:
            if self.done():
                return
            if self.swap(c, item, names):
                done += 1
            if done and done % 10 == 0:
                ctx.collect(5, self)
        ctx.collect(6, self)
        if self.done():
            return
        ctx.say(f"floor's done! {done} blocks of {shown}. fancy!" if done else
                "I couldn't swap any of the floor from here.")
        if getattr(self, "under_you", False):
            ctx.say("I skipped the block you're standing on. step off it and ask again to finish!")

    def fetch(self, item, n):
        import containers
        ch = containers.Chests(self.ctx, self)
        pos = ch.find() or ch.find(near_owner=False)
        if pos is None or not ch.open(pos):
            return 0
        try:
            got = ch.take(lambda i: i == item, n)
        finally:
            ch.close()
        if got:
            self.ctx.say(f"grabbed {got} {item.removeprefix('minecraft:').replace('_', ' ')} from the chest.")
        return got

    def swap(self, c, item, names):
        """Break one floor block and put the new one in its place. Keve never stands on it."""
        ctx = self.ctx
        x, y, z = c
        me = ctx.state()["player"]["block_pos"]
        if (me[0], me[2]) == (x, z) or math.dist((me[0], me[2]), (x, z)) > 3.5:
            # Stand on a neighbouring floor block of the room, never the one being dug.
            spots = [(x + dx, z + dz) for dx, dz in SIDES if (x + dx, z + dz) in self.room]
            spots.sort(key=lambda p: math.dist(p, (me[0], me[2])))
            for sx, sz in spots[:2]:
                ctx.body.call(f"goto {sx + 0.5:.1f} {y + 1:.1f} {sz + 0.5:.1f} --near 0.6 --timeout 6")
                me = ctx.state()["player"]["block_pos"]
                if (me[0], me[2]) != (x, z) and math.dist((me[0], me[2]), (x, z)) <= 3.5:
                    break
            if (me[0], me[2]) == (x, z) or self.done():
                return False
        o = ctx.owner()
        if o and (math.floor(o[1][0]), math.floor(o[1][2])) == (x, z):
            self.under_you = True
            return False  # you're standing on it
        eye = tuple(ctx.state()["player"]["eye"])
        snap = sight.Snapshot.read(ctx.senses, c, rh=3, rv=2)
        name = snap.name(c)
        if base(name) == item:
            return True
        if not snap.block_visible(eye, c, 5.0):
            return False
        if solid(name):
            if any(u in name for u in ("bedrock", "chest", "furnace", "crafting_table", "door", "bed")):
                return False
            tool = names.tool_for(name)[0] if names else "pickaxe"
            ctx.select_best(TOOLS.get(tool, PICKAXES))
            ctx.body.call(f"look-at block {x} {y} {z}")
            r = ctx.body.call(f"break {x} {y} {z} --timeout 12")
            if r.get("error"):
                return False
            ctx.recent_breaks.append((x, y, z, time.time()))
        r = ctx.place(c, item)  # right away, so whatever was under it stays covered
        return not r.get("error")
