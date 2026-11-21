"""Your runs of the course, recorded: the trainer's first route is your fastest finish.

You're put on lane 0's start pad facing east. The clock starts when you move (or press a
movement key), every key you press is read from your game's input log with its tick, and
when you land on the emerald (a finish) or fall in the water, you're put straight back on
the start pad for the next run. The fastest finish so far is saved as demo.json (a route)
and demo_raw.json (your presses and path). Close the window to stop.

    py -3.11 record_demo.py [your-name]     (Parkour.bat runs it for you)
"""
import json
import os
import sys
import time
from pathlib import Path

import course
from agents import Connection

HERE = Path(__file__).resolve().parent
SOCKET = Path(os.environ.get("HORIZON_CONTROL") or (Path(os.environ.get("TEMP", "")) / "horizon-control.json"))
# Horizon's key names (input_trace.rs): key.keyboard.w ...
KEYS = {"key.keyboard.w": "w", "key.keyboard.a": "a", "key.keyboard.s": "s", "key.keyboard.d": "d",
        "key.keyboard.space": "space", "key.keyboard.left.control": "ctrl", "key.keyboard.right.control": "ctrl",
        "key.keyboard.left.shift": "shift"}


def short(key):
    return KEYS.get(key) or (key or "").removeprefix("key.keyboard.")


def to_start(c, name):
    sx, sy, sz = course.start_pos(0)
    course.server(f"tp {name} {sx} {sy} {sz} -90 0")
    time.sleep(0.4)


def one_run(c, name, since):
    """Wait for the start, record until the finish or a fall. (result, presses, seen, since)."""
    ps = course.platforms(0)
    sx, sy, sz = course.start_pos(0)
    presses, seen, start = [], [], None
    pending = []  # presses before the clock starts (the W that starts it)
    while True:
        log = c.call(f"input-log --origin user --since {since}")
        since = log.get("last", since)
        for e in log.get("events", []):
            if e.get("kind") != "key" or e.get("action") == "repeat":
                continue
            k = short(e.get("key"))
            if k in ("w", "a", "s", "d", "space", "ctrl", "shift"):
                (presses if start is not None else pending).append([e["tick"], k, e.get("action")])
        s = c.call("state")
        p = s["player"]
        tick = s.get("ticks", 0)
        pos = p["position"]
        if start is None:
            moved = abs(pos[0] - sx) > 0.25 or abs(pos[2] - sz) > 0.25
            w = [x for x in pending if x[1] == "w" and x[2] == "down"]
            if moved or w:
                start = w[-1][0] if w else tick
                presses = [x for x in pending if x[0] >= start - 1]
                print("  go!")
            elif abs(pos[1] - sy) > 3 or abs(pos[0] - sx) > 6:
                to_start(c, name)  # wandered off before starting
            time.sleep(0.03)
            continue
        seen.append([tick - start, [round(v, 3) for v in pos], bool(p.get("on_ground"))])
        plat, fell = course.where(pos, 0, ps)
        if fell or pos[1] < min(q.y for q in ps) - 1.5:
            return ("fell", None), [[t - start, k, a] for t, k, a in presses], seen, since
        if plat == len(ps) - 1 and p.get("on_ground"):
            return ("finished", tick - start), [[t - start, k, a] for t, k, a in presses], seen, since
        time.sleep(0.03)


def route_from(presses):
    """Your presses as the trainer's route: each jump's delay, strafes round it, time off W."""
    import train
    route = train.from_guess()
    jumps = [t for t, k, a in presses if k == "space" and a == "down"]
    n = len(course.JUMPS)
    for j, t in enumerate(jumps[:n]):
        route.delays[j] = max(1, t - (jumps[j - 1] if j else 0))
        dz = course.JUMPS[j][2]
        if dz:
            key = "d" if dz > 0 else "a"
            downs = [tt for tt, k, a in presses if k == key and a == "down" and abs(tt - t) < 12]
            ups = [tt for tt, k, a in presses if k == key and a == "up" and downs and tt > downs[0]]
            if downs and ups:
                route.strafe[j] = [max(0, downs[0] - t), ups[0] - downs[0]]
        offs = [tt for tt, k, a in presses if k == "w" and a == "up" and t < tt < t + 20]
        ons = [tt for tt, k, a in presses if k == "w" and a == "down" and offs and tt > offs[0]]
        if offs and ons:
            route.brake[j] = ons[0] - offs[0]
    return route, len(jumps)


def loop(name="LilPwoop"):
    if not SOCKET.exists():
        sys.exit(f"your game's control link isn't there ({SOCKET}): start it with Parkour.bat")
    c = Connection(str(SOCKET), timeout=10)
    best = None
    try:
        old = json.loads((HERE / "demo_raw.json").read_text())
        best = old.get("ticks")
    except Exception:
        pass
    runs = 0
    print("On the start pad: run east to the emerald. The clock starts when you move.")
    print("Fall in or finish and you're back on the pad. Close this window to stop.")
    while True:
        to_start(c, name)
        course.server(f"title {name} actionbar {{\"text\":\"Go when you're ready\"}}")
        since = c.call("input-log --limit 1").get("last", 0)
        (how, ticks), presses, seen, _ = one_run(c, name, since)
        runs += 1
        if how == "finished":
            secs = ticks / 20
            msg = f"run {runs}: finished in {ticks} ticks ({secs:.2f} s)"
            if best is None or ticks < best:
                best = ticks
                route, nj = route_from(presses)
                (HERE / "demo.json").write_text(json.dumps(route.to_json()))
                (HERE / "demo_raw.json").write_text(json.dumps({"ticks": ticks, "presses": presses, "seen": seen}))
                msg += f"  - your best! saved ({nj} jumps seen)"
            print(msg)
            course.server(f"title {name} actionbar {{\"text\":\"{secs:.2f} s\"}}")
        else:
            print(f"run {runs}: in the water")
        time.sleep(0.8)


if __name__ == "__main__":
    loop(sys.argv[1] if len(sys.argv) > 1 else "LilPwoop")
