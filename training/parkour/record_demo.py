"""Your run of the course, recorded as the trainer's first route.

Start your Horizon game, join the Keve server, then run this. It puts you on lane 0's start
pad facing east, and from your first press of W it reads your own key presses straight from
your game's input log (every press with the tick it happened on), and watches where you are
until you stand on the emerald finish or fall in the water. Then it turns your jumps, strafes
and moments off W into a route (demo.json) and keeps the raw presses (demo_raw.json).

    py -3.11 record_demo.py [your-name]
"""
import json
import os
import sys
import time
from pathlib import Path

import course
from agents import Connection

HERE = Path(__file__).resolve().parent
NAME = sys.argv[1] if len(sys.argv) > 1 else "LilPwoop"
SOCKET = Path(os.environ.get("HORIZON_CONTROL") or (Path(os.environ.get("TEMP", "")) / "horizon-control.json"))


def main():
    if not SOCKET.exists():
        sys.exit(f"your game's control socket isn't there ({SOCKET}): start Horizon and join the server first")
    c = Connection(str(SOCKET), timeout=10)
    ps = course.platforms(0)
    sx, sy, sz = course.start_pos(0)
    print(course.server(f"tp {NAME} {sx} {sy} {sz} -90 0"))
    course.server(f"title {NAME} title {{\"text\":\"Parkour!\"}}")
    course.server(f"title {NAME} subtitle {{\"text\":\"run when you're ready: W starts the clock\"}}")
    since = c.call("input-log --limit 1").get("last", 0)
    presses, seen, start = [], [], None
    print("waiting for you to press W...")
    deadline = time.time() + 600
    while time.time() < deadline:
        log = c.call(f"input-log --origin user --since {since}")
        since = log.get("last", since)
        for e in log.get("events", []):
            if e.get("kind") != "key":
                continue
            key, action = e.get("key"), e.get("action")
            if start is None and key == "w" and action == "down":
                start = e["tick"]
                print("go!")
            if start is not None and key in ("w", "a", "s", "d", "space", "ctrl", "shift"):
                presses.append((e["tick"] - start, key, action))
        s = c.call("state")
        p = s["player"]
        if start is not None:
            seen.append((s.get("ticks", 0) - start, p["position"], p.get("on_ground")))
            plat, fell = course.where(p["position"], 0, ps)
            if fell:
                print("in the water: try again (run me again)")
                break
            if plat == len(ps) - 1 and p.get("on_ground"):
                print(f"finished in {seen[-1][0]} ticks ({seen[-1][0] / 20:.1f} s)!")
                break
        time.sleep(0.03)
    (HERE / "demo_raw.json").write_text(json.dumps({"presses": presses, "seen": seen}))
    # Your presses as a route: each jump's delay, the strafe around it, any time off W.
    jumps = [t for t, k, a in presses if k == "space" and a == "down"]
    n = len(course.JUMPS)
    if len(jumps) < n:
        print(f"only {len(jumps)} jumps of {n}: the route keeps the guess for the rest")
    import train
    route = train.from_guess()
    for j, t in enumerate(jumps[:n]):
        route.delays[j] = t - (jumps[j - 1] if j else 0)
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
    (HERE / "demo.json").write_text(json.dumps(route.to_json()))
    print("saved demo.json: the trainer starts from your run next time")


if __name__ == "__main__":
    main()
