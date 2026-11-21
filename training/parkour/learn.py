"""The jump table: what all the runs say about each kind of jump.

For every run that reached a jump, the takeoff point (how far before the platform's edge he
left the ground) and whether he landed on the next platform. Per kind of jump: how many
tries, the takeoff distances that landed, the best one (the middle of the landing range),
and the strafe and brake the landed tries used. That's what generalises: a new jump of the
same kind (same gap, height and landing) wants the same takeoff, wherever it is.

    py -3.11 learn.py          -> jump_table.json, and a summary
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

import course

HERE = Path(__file__).resolve().parent


def table():
    ps = course.platforms(1)  # every lane has the same shape
    tries = defaultdict(list)  # k -> [(before_edge, landed, strafe, brake)]
    for line in (HERE / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        lane_dz = (r["racer"] - 1) * course.LANE
        takeoffs = r["takeoffs"]
        landed = {p for _, p in r["landings"]}
        for k in range(len(course.JUMPS)):
            if k >= len(takeoffs) or (k > 0 and k not in landed):
                break
            _, x, y, z = takeoffs[k]
            tr = r.get("trace")
            if tr:
                # Exact: where he was on the jump's own tick (the press lands the tick after).
                jt = sum(r["route"]["delays"][:k + 1]) + 1
                before = [p for p in tr if p[0] <= jt]
                after = [p for p in tr if p[0] > jt]
                if before and after:
                    (t1, x1), (t2, x2) = before[-1], after[0]
                    x = x1 + (x2 - x1) * (jt - t1) / max(1, t2 - t1)
            edge = ps[k].x1 + 1.0
            tries[k].append((round(edge - x, 2), (k + 1) in landed,
                             r["route"]["strafe"][k], r["route"]["brake"][k]))
    out = {}
    for k, ts in sorted(tries.items()):
        gap, dy, dz, land, kind = course.JUMPS[k]
        good = sorted(b for b, ok, _, _ in ts if ok)
        entry = {"gap": gap, "dy": dy, "dz": dz, "land": land, "tries": len(ts), "landed": len(good)}
        if good:
            entry["takeoff_before_edge"] = {"lo": good[0], "hi": good[-1],
                                           "best": round(statistics.median(good), 2)}
            ok = [(s, b) for _, l, s, b in ts if l]
            if dz:
                entry["strafe"] = max(set(tuple(s) for s, _ in ok), key=lambda s: sum(tuple(x) == s for x, _ in ok))
            if land == 1:
                entry["brake"] = statistics.median(b for _, b in ok)
        out[kind if kind not in out else f"{kind} #{k + 1}"] = entry
    return out


if __name__ == "__main__":
    t = table()
    (HERE / "jump_table.json").write_text(json.dumps(t, indent=1))
    for kind, e in t.items():
        tk = e.get("takeoff_before_edge")
        print(f"{kind:22s} landed {e['landed']:3d}/{e['tries']:<3d}"
              + (f"  take off {tk['best']:.2f} before the edge ({tk['lo']:.2f}..{tk['hi']:.2f})" if tk else ""))
