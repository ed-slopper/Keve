"""Learning the course: many runs, each a small change on the best so far.

A route is a few numbers per jump (see `Route`): when to jump after the last jump, when
and how long to strafe for a side step, and whether to ease off forward for a 1x1 landing.
It's turned into a tick timeline and run by a racer (runner.py; Horizon's tick script plays
it to the tick, so a route always runs the same way).

1. Jump by jump: for jump k, try its numbers a little either side of the current ones, run
   only up to just past jump k (short runs), keep what lands on platform k+1 soonest.
2. Polish: random small changes anywhere in the whole route, kept when it finishes faster.

Several racers on their own lanes run candidates at the same time. Every run goes in
runs.jsonl; the best route in best.json (a seed for the next session, and the jump table's
source). Seeds: your recorded run (demo.json) if there is one, else a guess from the shape.
"""
import copy
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import agents
import course
import runner

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs.jsonl"
BEST = HERE / "best.json"
DEMO = HERE / "demo.json"


class Route:
    """Per jump: delay (ticks after the previous jump; the first, after the start),
    strafe (start after the jump, length; 0 length none), brake (ticks of no forward
    starting 9 after the jump: 0 none)."""

    def __init__(self, delays, strafe=None, brake=None, looks=None):
        n = len(course.JUMPS)
        self.looks = [list(x) for x in (looks or [])]  # [tick, yaw, pitch]: your mouse, per tick
        self.delays = list(delays)
        self.strafe = [list(s) for s in (strafe or [[0, 0]] * n)]
        self.brake = list(brake or [0] * n)

    def to_json(self):
        return {"delays": self.delays, "strafe": self.strafe, "brake": self.brake, "looks": self.looks}

    @classmethod
    def from_json(cls, d):
        return cls(d["delays"], d.get("strafe"), d.get("brake"), d.get("looks"))

    def timeline(self, upto=None):
        """The key timeline, cut short after jump `upto` (0-based) when given."""
        tl = [(0, "w down"), (0, "ctrl down")]
        tl += [(lt, f"look {y} {p}") for lt, y, p in self.looks]
        t = 0
        for j, (gap, dy, dz, land, kind) in enumerate(course.JUMPS):
            t += self.delays[j]
            tl += [(t, "space down"), (t + 2, "space up")]
            s0, sl = self.strafe[j]
            if dz and sl > 0:
                key = "d" if dz > 0 else "a"
                tl += [(t + s0, f"{key} down"), (t + s0 + sl, f"{key} up")]
            if self.brake[j] > 0:
                tl += [(t + 9, "w up"), (t + 9 + self.brake[j], "w down"), (t + 9 + self.brake[j], "ctrl down")]
            if upto is not None and j >= upto:
                tl.append((t + 18, "w up"))  # stop after landing it: nothing more to see
                break
        return tl


def from_guess():
    tl = runner.guess(1)
    jumps = [t for t, a in tl if a == "space down"]
    delays = [jumps[0]] + [b - a for a, b in zip(jumps, jumps[1:])]
    strafe = [[0, 8] if dz else [0, 0] for (_, _, dz, _, _) in course.JUMPS]
    return Route(delays, strafe)


def seed():
    # Your newest run first (a fresh demo beats the bots' older best).
    if DEMO.exists() and (not BEST.exists() or DEMO.stat().st_mtime > BEST.stat().st_mtime):
        return Route.from_json(json.loads(DEMO.read_text()))
    if BEST.exists():
        return Route.from_json(json.loads(BEST.read_text()))
    if DEMO.exists():
        return Route.from_json(json.loads(DEMO.read_text()))
    return from_guess()


class Pool:
    """Racers 1..N on lanes 1..N, each runs one candidate at a time."""

    def __init__(self, n):
        self.free = list(range(1, n + 1))
        self.lock = threading.Condition()
        self.ex = ThreadPoolExecutor(max_workers=n)

    def run(self, route, upto=None, why=""):
        with self.lock:
            while not self.free:
                self.lock.wait()
            r = self.free.pop()
        try:
            res = runner.run(r, r, route.timeline(upto))
        finally:
            with self.lock:
                self.free.append(r)
                self.lock.notify()
        with open(RUNS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time()), "racer": r, "why": why, "upto": upto,
                                "route": route.to_json(), "reached": res.reached,
                                "finished": res.finished, "ticks": res.ticks,
                                "takeoffs": res.takeoffs, "landings": res.landings}) + "\n")
        return res

    def many(self, jobs):
        """jobs: [(route, upto, why)] -> results in order."""
        return list(self.ex.map(lambda j: self.run(*j), jobs))


def land_tick(res, platform):
    return next((t for t, p in res.landings if p == platform), None)


def jump_by_jump(pool, route, start=0):
    """Settle each jump in turn: the variant that lands on the next platform soonest."""
    for k in range(start, len(course.JUMPS)):
        gap, dy, dz, land, kind = course.JUMPS[k]
        cands = []
        for d in range(-4, 5):
            r = copy.deepcopy(route)
            r.delays[k] = max(1, r.delays[k] + d)
            cands.append(r)
        if dz:
            for s0 in (0, 2, 4):
                for sl in (4, 6, 8, 10):
                    r = copy.deepcopy(route)
                    r.strafe[k] = [s0, sl]
                    cands.append(r)
        if land == 1:
            for br in (2, 4, 6):
                r = copy.deepcopy(route)
                r.brake[k] = br
                cands.append(r)
        res = pool.many([(c, k, f"jump {k + 1} ({kind})") for c in cands])
        ok = [(land_tick(x, k + 1), c) for x, c in zip(res, cands) if land_tick(x, k + 1) is not None]
        if not ok:
            print(f"jump {k + 1} ({kind}): none of {len(cands)} landed; widening")
            wide = []
            strafes = [(s0, sl) for s0 in (0, 2, 4) for sl in (3, 5, 7, 9)] if dz else [None]
            for d in range(-6, 7, 2 if dz else 1):
                for br in ((0, 3, 6) if land == 1 else (0,)):
                    for st in strafes:
                        r = copy.deepcopy(route)
                        r.delays[k] = max(1, r.delays[k] + d)
                        r.brake[k] = br
                        if st:
                            r.strafe[k] = list(st)
                        wide.append(r)
            # The landing before decides how he sets off: its brake too.
            if k and course.JUMPS[k - 1][3] == 1:
                for br in (0, 2, 4, 6, 8):
                    for d in (-2, 0, 2):
                        r = copy.deepcopy(route)
                        r.brake[k - 1] = br
                        r.delays[k] = max(1, r.delays[k] + d)
                        wide.append(r)
            res = pool.many([(c, k, f"jump {k + 1} wide") for c in wide])
            ok = [(land_tick(x, k + 1), c) for x, c in zip(res, wide) if land_tick(x, k + 1) is not None]
            if not ok:
                print(f"stuck at jump {k + 1} ({kind})")
                return route, k
        t, route = min(ok, key=lambda o: o[0])
        print(f"jump {k + 1} ({kind}): landed at tick {t}; {len(ok)}/{len(res)} variants made it")
        BEST.write_text(json.dumps(route.to_json()))
    return route, len(course.JUMPS)


def polish(pool, route, rounds=20, batch=None):
    """Random small changes over the whole route; keep what finishes faster."""
    batch = batch or len(pool.free) * 2
    best = pool.run(route, None, "polish base")
    best_ticks = best.ticks if best.finished else 10 ** 6
    print(f"polish: base {'finishes in ' + str(best_ticks) if best.finished else 'does not finish'}")
    for rnd in range(rounds):
        cands = []
        for _ in range(batch):
            r = copy.deepcopy(route)
            for _ in range(random.randint(1, 3)):
                k = random.randrange(len(course.JUMPS))
                what = random.random()
                if what < 0.6:
                    r.delays[k] = max(1, r.delays[k] + random.choice((-2, -1, 1, 2)))
                elif what < 0.8 and course.JUMPS[k][2]:
                    r.strafe[k][random.randrange(2)] = max(0, r.strafe[k][0] + random.choice((-1, 1)))
                else:
                    r.brake[k] = max(0, r.brake[k] + random.choice((-1, 1)))
            cands.append(r)
        res = pool.many([(c, None, f"polish {rnd + 1}") for c in cands])
        for x, c in zip(res, cands):
            if x.finished and x.ticks < best_ticks:
                best_ticks, route = x.ticks, c
                BEST.write_text(json.dumps(route.to_json()))
        print(f"polish round {rnd + 1}: best finish {best_ticks} ticks")
    return route, best_ticks


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for i in range(1, n + 1):
        course.build(i)
        if not agents.start(i):
            sys.exit(f"Racer{i} didn't start")
    pool = Pool(n)
    route = seed()
    first = int(sys.argv[2]) - 1 if len(sys.argv) > 2 else 0  # resume: py train.py 3 9
    route, reached = jump_by_jump(pool, route, first)
    if reached == len(course.JUMPS):
        polish(pool, route)


if __name__ == "__main__":
    main()
