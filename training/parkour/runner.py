"""One run of the course: a timeline of key presses played tick by tick, scored.

A timeline is a list of (tick, action) from the start: "w down", "ctrl down", "space tap",
"a down", "a up", "d down", "d up", "w up". The racer is put on the start pad facing east;
`wait` between actions counts real game ticks, so the same timeline runs the same way.
While it plays, a second connection watches where the racer is (about 30 times a second)
for the score: the furthest platform landed on, whether it finished, and in how many ticks.
"""
import json
import threading
import time
from dataclasses import dataclass, field

import agents
import course
from agents import Connection


@dataclass
class Result:
    reached: int                 # furthest platform landed on (0: never left the start)
    finished: bool
    fell: bool
    ticks: int                   # ticks to the finish (or to where it stopped)
    takeoffs: list = field(default_factory=list)   # (tick, x, y, z) of each jump's takeoff
    landings: list = field(default_factory=list)   # (tick, platform) of each landing
    trace: list = field(default_factory=list)      # (tick, x) as seen, for exact takeoffs

    def score(self):
        """Bigger is better: platforms first, then speed (a finish beats any non-finish)."""
        return self.reached * 1000 + (1000 - min(self.ticks, 999) if self.finished else 0)


def write_recording(timeline, n):
    """The timeline as a Horizon recording (horizon-repro/1) in the racers' shared home."""
    import json
    import os
    name = f"pk{n}-{int(time.time() * 1000) % 100000000}"
    d = agents.KEVE_HOME / "home" / "recordings" / f"2000-01-01_00-00-00-{name}"
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"seq": i, "tick": t, "ms": 0, "origin": "agent", "kind": "command", "line": f"key {a}"}
            for i, (t, a) in enumerate(sorted(timeline))]
    end = (max(t for t, _ in timeline) if timeline else 0) + 1
    with open(d / "inputs.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + chr(10))
    (d / "events.jsonl").write_text("", encoding="utf-8")
    (d / "state.jsonl").write_text("", encoding="utf-8")
    json.dump({"created": "2000-01-01T00:00:00+00:00", "end_tick": end, "events": 0,
               "format": "horizon-repro/1", "game_version": "0.1.0", "inputs": len(rows),
               "mode": "remote", "name": name, "seconds": end / 20, "start": {}, "start_tick": 0,
               "state": 0, "world": None}, open(d / "session.json", "w", encoding="utf-8"))
    # old ones go (they pile up a few hundred an hour)
    for old in sorted((agents.KEVE_HOME / "home" / "recordings").glob(f"2000-01-01_00-00-00-pk{n}-*"))[:-20]:
        try:
            for f in old.iterdir():
                f.unlink()
            old.rmdir()
        except OSError:
            pass
    return name


def run(n, lane, timeline, max_ticks=600):
    act = Connection(str(agents.sock(n)), timeout=30)
    watch = Connection(str(agents.sock(n)), timeout=10)
    ps = course.platforms(lane)
    sx, sy, sz = course.start_pos(lane)
    st = act.call("state")
    if str(st.get("screen", "")) in ("dead", "death") or (st.get("player") or {}).get("health", 20) <= 0:
        act.call("respawn")  # (a fall into the void before the water went in)
        time.sleep(2)
    course.server(f"effect give Racer{n} minecraft:instant_health 1 5")
    course.server(f"tp Racer{n} {sx} {sy} {sz} -90 0")
    for k in ("w", "a", "s", "d", "space", "ctrl", "shift"):
        act.call(f"key {k} up")
    act.call("look -90 0")
    act.call("wait 10")  # settled on the pad

    seen = []
    stop = threading.Event()

    def watcher():
        while not stop.is_set():
            try:
                s = watch.call("state")
                p = s["player"]
                seen.append((s.get("ticks", 0), tuple(p["position"]), p.get("on_ground", False)))
            except Exception:
                pass
    th = threading.Thread(target=watcher, daemon=True)
    th.start()
    # Played by Horizon's tick script: every line runs right before its own tick (over the
    # socket, presses landed 0-3 ticks late at random, too loose for parkour).
    steps = {}
    for t, a in sorted(timeline):
        steps.setdefault(str(t), []).append(f"key {a}")
    end_tick = (max(t for t, _ in timeline) if timeline else 0) + 40  # then it runs on a little, keys held
    for k in ("w", "a", "d", "space", "ctrl"):
        steps.setdefault(str(end_tick), []).append(f"key {k} up")
    sp = agents.script_path(n)
    for ext in (".go", ".done"):
        try:
            sp.with_suffix(ext).unlink()
        except OSError:
            pass
    sp.write_text(json.dumps({"name": f"run{int(time.time())}", "ticks": end_tick + 1, "steps": steps}),
                  encoding="utf-8")
    t0 = act.call("status").get("ticks") or 0
    sp.with_suffix(".go").write_text("go", encoding="utf-8")
    try:
        end = time.time() + (end_tick + 40) / 20 + 5
        while time.time() < end and not sp.with_suffix(".done").exists():
            time.sleep(0.1)
            if seen:
                plat, fell = course.where(seen[-1][1], lane, ps)
                if fell or (plat == len(ps) - 1 and seen[-1][2]):
                    time.sleep(0.3)
                    break
    finally:
        # The script must be over before the next run (a new .go waits for it, and its last
        # tick lets the keys go: it was letting go of the next run's keys).
        stop_at = time.time() + (end_tick + 40) / 20 + 5
        while time.time() < stop_at and not sp.with_suffix(".done").exists():
            time.sleep(0.1)
        for k in ("w", "a", "d", "space", "ctrl"):
            act.call(f"key {k} up")
        stop.set()
        th.join(timeout=2)
    # The score, from what was seen.
    reached, finished, fell, fin_tick = 0, False, False, None
    takeoffs, landings = [], []
    was_ground = True
    for tick, pos, ground in seen:
        rel = (tick or 0) - t0
        plat, f = course.where(pos, lane, ps)
        if f:
            fell = True
            break
        if was_ground and not ground and pos[0] > ps[0].x0:
            takeoffs.append((rel, round(pos[0], 2), round(pos[1], 2), round(pos[2], 2)))
        if ground and plat is not None and plat > reached:
            reached = plat
            landings.append((rel, plat))
            if plat == len(ps) - 1 and not finished:
                finished, fin_tick = True, rel
        was_ground = ground
    ticks = fin_tick if finished else ((seen[-1][0] - t0) if seen else 0)
    trace = [((t or 0) - t0, round(pos[0], 3)) for t, pos, _ in seen]
    return Result(reached, finished, fell, ticks, takeoffs, landings, trace)


def guess(lane=0):
    """A first timeline from the course's shape alone: sprint all the way, jump a little before
    each edge (sprinting covers about 0.28 blocks a tick), strafe for the side steps."""
    ps = course.platforms(lane)
    tl = [(0, "w down"), (0, "ctrl down")]
    x = course.start_pos(lane)[0]
    tick = 0.0
    speed = 0.28
    for i, (gap, dy, dz, land, kind) in enumerate(course.JUMPS):
        edge = ps[i].x1 + 1.0  # the east face of the platform he's on
        tick += max(1.0, (edge - 0.3 - x) / speed)
        tl.append((round(tick), "space down"))  # held 2 ticks: a same-tick tap isn't seen
        tl.append((round(tick) + 2, "space up"))
        if dz:
            key = "d" if dz > 0 else "a"  # facing east: d is south (+z), a is north
            tl.append((round(tick), f"{key} down"))
            tl.append((round(tick) + 8, f"{key} up"))
        # in the air about 12 ticks, a bit more down, less up
        air = 12 - 2 * dy
        tick += air
        x = edge - 0.3 + air * speed
        x = max(x, ps[i + 1].x0 + 0.3)
    return tl


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    lane = int(sys.argv[2]) if len(sys.argv) > 2 else n
    r = run(n, lane, guess(lane))
    print(r)
