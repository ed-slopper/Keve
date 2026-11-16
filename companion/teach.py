"""Learning from you: "keve watch me place torches" ... "ok did u see".

While watching, Keve keeps its eyes on you and notes every block you place or break
that it can see (fair: only changes in its view, close enough to be yours), with the
light level before and whether it went on a floor or a wall. "did you see" ends the
lesson: it says what it saw and saves it as training data:

    %LOCALAPPDATA%\\Keve\\training\\demos.jsonl   one demonstration per line (append-only)

Later, "keve place torches" lights a room the way you did it (your light level, your
spacing), and "keve do it like I showed you" / "keve <what you called the lesson>"
repeats a shown build next to you. The saved lessons are also a dataset for training
Keve's models later.
"""
import difflib
import json
import math
import os
import statistics
import threading
import time
from pathlib import Path

import craft
import sight
from skills import Task, base

TRAINING = Path(os.environ.get("KEVE_HOME") or Path(os.environ.get("LOCALAPPDATA", ".")) / "Keve") / "training"
DEMOS = TRAINING / "demos.jsonl"
TORCHES = ("minecraft:torch", "minecraft:wall_torch", "minecraft:soul_torch", "minecraft:soul_wall_torch",
           "minecraft:lantern", "minecraft:soul_lantern")


def load_demos():
    out = []
    try:
        for line in DEMOS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return out


def save_demo(demo):
    TRAINING.mkdir(parents=True, exist_ok=True)
    with DEMOS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(demo) + "\n")


def find_demo(text):
    """The saved lesson whose name matches what you said (fuzzy), else None."""
    demos = load_demos()
    best, score = None, 0.0
    for d in demos:
        r = difflib.SequenceMatcher(None, text, d.get("instruction", "")).ratio()
        if r >= score:
            best, score = d, r
    return best if score >= 0.78 else None


def read_light(senses, lo, hi):
    """Block and sky light of a box: {(x, y, z): (block, sky)}."""
    r = senses.call(f"light {lo[0]} {lo[1]} {lo[2]} {hi[0]} {hi[1]} {hi[2]}")
    blk, sky = r.get("block", ""), r.get("sky", "")
    nx, nz = hi[0] - lo[0] + 1, hi[2] - lo[2] + 1
    out = {}
    for i, ch in enumerate(blk):
        if ch == ".":
            continue
        x = lo[0] + i % nx
        z = lo[2] + (i // nx) % nz
        y = lo[1] + i // (nx * nz)
        out[(x, y, z)] = (int(ch, 16), int(sky[i], 16) if i < len(sky) and sky[i] != "." else 0)
    return out


def torch_style():
    """What your torch lessons say: the light level you lit at, and your spacing."""
    lights, gaps, walls, n = [], [], 0, 0
    for d in load_demos():
        placed = [a for a in d.get("actions", []) if a["type"] == "place" and a["block"] in TORCHES]
        if not placed:
            continue
        for a in placed:
            n += 1
            walls += a.get("on") == "wall"
            if a.get("light_before") is not None:
                lights.append(a["light_before"])
        pts = [a["pos"] for a in placed]
        for p in pts:
            others = [math.dist(p, q) for q in pts if q is not p]
            if others:
                gaps.append(min(others))
    if not n:
        return None
    return {
        "light": min(12, max(2, int(statistics.median(lights)) + 1)) if lights else 7,
        "spacing": statistics.median(gaps) if gaps else 7.0,
        "walls": walls / n,
        "examples": n,
    }


# --- watching you ------------------------------------------------------------------------
class Watch(Task):
    """'keve watch me <do something>' ... 'ok did u see'."""
    name = "watch"

    def __init__(self, ctx, **args):
        super().__init__(ctx, **args)
        self.seen_it = threading.Event()

    def run(self):
        ctx = self.ctx
        what = self.args.get("what") or "this"
        o = ctx.owner()
        if not o:
            ctx.say("where are you? I can't see you.")
            return
        ctx.say(f"watching. show me how you {what}, then say 'did you see'.")
        start = tuple(o[1])
        actions, path = [], [(0.0, [round(v, 2) for v in start])]
        prev, prev_light = None, {}
        t0 = time.time()
        while not self.done() and not self.seen_it.is_set() and time.time() - t0 < 600:
            o = ctx.owner() or o
            pos = tuple(o[1])
            # Keep near and keep looking at you, like someone paying attention.
            me = ctx.eye_and_view()[3]
            if math.dist(me, pos) > 6:
                ctx.body.call(f"goto {pos[0]:.2f} {pos[1]:.2f} {pos[2]:.2f} --near 4 --timeout 3")
            ctx.body.call(f"look-at entity {o[0]}")
            eye = tuple(ctx.state()["player"]["eye"])
            c = [int(math.floor(v)) for v in pos]
            lo, hi = (c[0] - 7, c[1] - 3, c[2] - 7), (c[0] + 7, c[1] + 4, c[2] + 7)
            snap = sight.Snapshot.read(ctx.senses, pos, rh=7, rv=4)
            light = read_light(ctx.senses, lo, hi)
            if prev is not None:
                t = round(time.time() - t0, 1)
                for p in set(prev.blocks) | set(snap.blocks):
                    if not all(lo[i] <= p[i] <= hi[i] for i in range(3)):
                        continue
                    was, now = prev.blocks.get(p), snap.blocks.get(p)
                    if was == now or (was and now and base(was) == base(now)):
                        continue
                    if math.dist(p, pos) > 6.5:  # out of your reach: not you
                        continue
                    if now and not snap.block_visible(eye, p, 16.0) and not \
                            snap.point_visible(eye, (p[0] + 0.5, p[1] + 0.5, p[2] + 0.5), 16.0):
                        continue  # Keve didn't see it happen
                    below = (p[0], p[1] - 1, p[2])
                    kind = "place" if now else "break"
                    block = base(now or was)
                    on = None
                    if kind == "place":
                        on = "floor" if sight.blocks_body(snap.name(below)) else "wall"
                        if "wall_" in block:
                            on = "wall"
                    actions.append({
                        "t": t, "type": kind, "block": block, "pos": list(p),
                        "rel": [p[i] - c[i] for i in range(3)],
                        "light_before": prev_light.get(p, (None, None))[0],
                        "sky_before": prev_light.get(p, (None, None))[1],
                        "on": on,
                    })
                if not path or math.dist(path[-1][1], pos) > 1:
                    path.append((t, [round(v, 2) for v in pos]))
            prev, prev_light = snap, light
            time.sleep(0.5)
        if self.done():
            return
        self.finish(what, start, actions, path)

    def finish(self, what, start, actions, path):
        ctx = self.ctx
        if not actions:
            ctx.say("hmm, I didn't see you place or break anything. try again closer to me?")
            return
        demo = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "instruction": what,
                "player": ctx.owner_name, "start": [round(v, 2) for v in start],
                "actions": actions, "path": path}
        save_demo(demo)
        placed = [a for a in actions if a["type"] == "place"]
        broke = [a for a in actions if a["type"] == "break"]
        bits = []
        if placed:
            kinds = {}
            for a in placed:
                kinds[a["block"]] = kinds.get(a["block"], 0) + 1
            bits.append("placed " + ", ".join(f"{n} {k.removeprefix('minecraft:').replace('_', ' ')}"
                                              for k, n in kinds.items()))
        if broke:
            bits.append(f"broke {len(broke)} blocks")
        torches = [a for a in placed if a["block"] in TORCHES]
        extra = ""
        if len(torches) >= 2:
            st = torch_style()
            extra = (f" about {st['spacing']:.0f} blocks apart, where it was darker than light "
                     f"{st['light']}, {round(st['walls'] * 100)}% on walls")
        ctx.say(f"got it! you {' and '.join(bits)}{extra}. saved as '{what}'.")


# --- lighting a room ----------------------------------------------------------------------
class LightUp(Task):
    """'keve place torches in this room' / 'light up this cave'."""
    name = "light_up"

    def run(self):
        ctx = self.ctx
        style = torch_style() or {"light": 7, "spacing": 6.0, "walls": 0.0, "examples": 0}
        target = style["light"]
        o = ctx.owner()
        centre = tuple(o[1]) if o else ctx.eye_and_view()[3]
        have = ctx.counts().get("minecraft:torch", 0)
        if have < 2:
            have = self.get_torches(have)
            if have == 0:
                return
        spots = self.plan(centre, target, style["spacing"], min(have, 24))
        if not spots:
            ctx.say("it's already lit up enough here.")
            return
        how = f" (like you showed me: light {target}, ~{style['spacing']:.0f} apart)" if style["examples"] else ""
        ctx.say(f"placing {len(spots)} torches{how}.")
        placed = 0
        for attempt in range(3):  # place, look again, fill what's still dark
            if attempt:
                left = ctx.counts().get("minecraft:torch", 0)
                spots = self.plan(centre, target, style["spacing"] * 0.75, min(left, 12)) if left else []
                if not spots:
                    break
            got = self.place_all(spots)
            placed += got
            if not got:
                break
        ctx.say(f"lit it up: {placed} torches." if placed else "I couldn't reach the dark spots.")

    def place_all(self, spots):
        ctx = self.ctx
        placed = 0
        for p in spots:
            if self.done():
                return placed
            if math.dist(ctx.eye_and_view()[3], p) > 3.8:
                ctx.body.call(f"goto {p[0] + 0.5:.1f} {p[1]:.1f} {p[2] + 0.5:.1f} --near 2.5 --timeout 10")
            eye = tuple(ctx.state()["player"]["eye"])
            snap = sight.Snapshot.read(ctx.senses, p, rh=3, rv=2)
            below = (p[0], p[1] - 1, p[2])
            # Fair: it has to see the spot (the floor block's top) it's putting a torch on.
            if not (snap.block_visible(eye, below, 5.0) or snap.point_visible(
                    eye, (p[0] + 0.5, p[1] + 0.1, p[2] + 0.5), 5.0)):
                continue
            r = ctx.place(p, "torch")
            if not r.get("error"):
                placed += 1
        return placed

    def get_torches(self, have):
        ctx = self.ctx
        import mining
        prov = mining.Provision(ctx, self)
        prov.only_inventory = True
        coal = prov.crafter.count("coal")
        if coal and prov.ensure("torch", min(16, coal * 4)):
            return ctx.counts().get("minecraft:torch", 0)
        ctx.say("I need torches, or coal and sticks to make some.")
        return have

    def plan(self, centre, target, spacing, budget):
        """Floor spots for torches so the room you're in reaches the light level."""
        ctx = self.ctx
        c = [int(math.floor(v)) for v in centre]
        lo, hi = (c[0] - 9, c[1] - 3, c[2] - 9), (c[0] + 9, c[1] + 4, c[2] + 9)
        snap = sight.Snapshot.read(ctx.senses, centre, rh=9, rv=4)
        light = read_light(ctx.senses, lo, hi)

        def free(p):
            return not sight.blocks_body(snap.blocks.get(p, "minecraft:air")) and \
                not sight.is_fluid(snap.blocks.get(p, "minecraft:air"))

        # The room: what you can walk to from where you stand, inside the box.
        start = (c[0], c[1], c[2])
        room, todo = {start}, [start]
        while todo and len(room) < 4000:
            p = todo.pop()
            for d in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0)):
                q = (p[0] + d[0], p[1] + d[1], p[2] + d[2])
                if q in room or not all(lo[i] <= q[i] <= hi[i] for i in range(3)) or not free(q):
                    continue
                room.add(q)
                todo.append(q)
        floor = [p for p in room if sight.blocks_body(snap.name((p[0], p[1] - 1, p[2])))
                 and base(snap.blocks.get(p, "minecraft:air")) not in TORCHES]
        if not floor:
            return []
        indoor = [p for p in floor if light.get(p, (0, 0))[1] < 10]
        cells = indoor or floor  # a room under a roof; out in the open, everything
        lit = {p: light.get(p, (0, 0))[0] for p in cells}
        existing = [p for p, n in snap.blocks.items() if base(n) in TORCHES]
        chosen = []
        for _ in range(budget):
            dark = [p for p in cells if lit[p] < target]
            if not dark:
                break
            best, gain = None, 0
            for cand in floor:
                if any(math.dist(cand, t) < spacing * 0.7 for t in existing + chosen):
                    continue
                g = sum(1 for p in dark if 14 - _manhattan(cand, p) >= target)
                if g > gain:
                    best, gain = cand, g
            if best is None:
                break
            chosen.append(best)
            for p in cells:
                lit[p] = max(lit[p], 14 - _manhattan(best, p))
        # Visit them in a sensible order: nearest first, then nearest to the last one.
        order, here = [], tuple(c)
        while chosen:
            nxt = min(chosen, key=lambda p: math.dist(p, here))
            order.append(nxt)
            chosen.remove(nxt)
            here = nxt
        return order


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


# --- doing what you showed ----------------------------------------------------------------
class Replay(Task):
    """'keve do it like I showed you' / 'keve <a lesson's name>': the shown blocks again,
    laid out the same way around where you stand now (torch lessons light the room instead)."""
    name = "replay"

    def run(self):
        ctx = self.ctx
        demo = self.args.get("demo") or (load_demos() or [None])[-1]
        if not demo:
            ctx.say("you haven't shown me anything yet. say 'keve watch me ...' first.")
            return
        placed = [a for a in demo["actions"] if a["type"] == "place"]
        if placed and all(a["block"] in TORCHES for a in placed):
            t = LightUp(ctx)
            t.cancelled = self.cancelled
            t.run()
            return
        o = ctx.owner()
        if not o:
            ctx.say("I can't see you.")
            return
        c = [int(math.floor(v)) for v in o[1]]
        ctx.say(f"doing '{demo['instruction']}' like you showed me.")
        done = 0
        for a in demo["actions"]:
            if self.done():
                return
            p = tuple(c[i] + a["rel"][i] for i in range(3))
            if math.dist(ctx.eye_and_view()[3], p) > 3.8:
                ctx.body.call(f"goto {p[0] + 0.5:.1f} {p[1]:.1f} {p[2] + 0.5:.1f} --near 2.5 --timeout 10")
            if a["type"] == "break":
                ctx.body.call(f"look-at block {p[0]} {p[1]} {p[2]}")
                r = ctx.body.call(f"break {p[0]} {p[1]} {p[2]} --timeout 10")
            else:
                item = a["block"].replace("wall_torch", "torch")
                if not ctx.counts().get(item):
                    continue
                r = ctx.place(p, item)
            done += not r.get("error")
        ctx.say(f"done: {done} of {len(demo['actions'])} steps." if done else
                "I couldn't do any of it here (missing blocks, or no room).")
