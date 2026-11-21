"""The parkour course: its jumps, its blocks, and where a runner is on it.

The course runs east (+x) in the sky over the overworld, one lane per runner side by side
(lane 0 is yours, the rest are the agents'), so runners never get in each other's way.
Each jump is (gap, dy, dz, land): `gap` air blocks between the platforms along x, the next
platform `dy` higher and `dz` to the side, `land` blocks long. Platforms are one block wide
except where noted. Gold under a platform marks a checkpoint, emerald the finish.
"""
import subprocess
from dataclasses import dataclass

SERVER = r"C:\Users\pc5\AppData\Roaming\horizon-launcher\versions\nightly-2026-11-13-9f42064\horizon-server.exe"
SERVER_DIR = r"C:\Users\pc5\AppData\Local\Keve\server"

X0, Y0, Z0 = 800, 200, 600  # the start pad's west edge, its floor, lane 0's middle
LANE = 16                      # lanes apart (z)
START_LEN = 4                  # the start pad: 4 long, 3 wide

# (gap, dy, dz, land, kind) — kind is just a name for the jump table
JUMPS = [
    (1, 0, 0, 3, "gap1"),
    (2, 0, 0, 2, "gap2"),
    (3, 0, 0, 2, "gap3"),
    (1, 1, 0, 2, "up1 gap1"),
    (2, 1, 0, 1, "up1 gap2 to 1x1"),
    (2, -1, 0, 1, "down1 gap2 to 1x1"),
    (3, -1, 0, 2, "down1 gap3"),
    (1, 0, 1, 1, "gap1 side1 to 1x1"),
    (2, 0, -1, 1, "gap2 side1 to 1x1"),
    (3, -1, 0, 2, "down1 gap3"),
    (2, 0, 0, 1, "gap2 to 1x1"),
    (3, 0, 0, 3, "gap3 to finish"),
]
CHECKPOINTS = {3, 6, 9}  # after these jumps (1-based), a gold block


@dataclass
class Platform:
    index: int          # 0 is the start pad, n after jump n
    x0: int             # west edge (inclusive)
    x1: int             # east edge (inclusive)
    y: int              # the block you stand on
    z: int              # the middle of its width
    width: int          # 1 or 3
    kind: str = "start"


def platforms(lane=0):
    z = Z0 + lane * LANE
    out = [Platform(0, X0, X0 + START_LEN - 1, Y0, z, 3)]
    x, y = X0 + START_LEN - 1, Y0
    for n, (gap, dy, dz, land, kind) in enumerate(JUMPS, 1):
        x0 = x + gap + 1
        y += dy
        z += dz
        width = 3 if n == len(JUMPS) else 1
        out.append(Platform(n, x0, x0 + land - 1, y, z, width, kind))
        x = x0 + land - 1
    return out


def server(cmd):
    r = subprocess.run([SERVER, "--dir", SERVER_DIR, "cmd", cmd], capture_output=True, text=True)
    return (r.stdout or r.stderr).strip()


def build(lane=0):
    ps = platforms(lane)
    xs, xe = ps[0].x0 - 2, ps[-1].x1 + 2
    z = Z0 + lane * LANE
    server(f"forceload add {xs} {z - 6} {xe} {z + 6}")
    server(f"fill {xs} {Y0 - 6} {z - 6} {xe} {Y0 + 4} {z + 6} minecraft:air")  # clear the lane
    # A water floor under it: a fall ends the run, not the runner.
    server(f"fill {xs} {Y0 - 8} {z - 6} {xe} {Y0 - 8} {z + 6} minecraft:stone")
    server(f"fill {xs} {Y0 - 7} {z - 6} {xe} {Y0 - 7} {z + 6} minecraft:water")
    for p in ps:
        half = p.width // 2
        block = "minecraft:stone_bricks"
        if p.index == len(JUMPS):
            block = "minecraft:emerald_block"
        elif p.index in CHECKPOINTS:
            block = "minecraft:gold_block"
        server(f"fill {p.x0} {p.y} {p.z - half} {p.x1} {p.y} {p.z + half} {block}")
    # light, so nothing spawns on it at night
    for p in ps[::3]:
        server(f"setblock {p.x0} {p.y - 1} {p.z} minecraft:glowstone")
    return ps


def where(pos, lane=0, ps=None):
    """(platform index standing on or None, fell) for a position on this lane."""
    ps = ps or platforms(lane)
    x, y, z = pos
    low = min(p.y for p in ps)
    if y < low - 2:
        return None, True
    for p in ps:
        half = p.width / 2
        if p.x0 - 0.3 <= x <= p.x1 + 1.3 and abs(z - (p.z + 0.5)) <= half + 0.3 and abs(y - (p.y + 1)) < 0.05:
            return p.index, False
    return None, False


def start_pos(lane=0):
    p = platforms(lane)[0]
    return (p.x0 + 0.5, p.y + 1, p.z + 0.5)


if __name__ == "__main__":
    import sys
    for lane in (int(a) for a in (sys.argv[1:] or ["0"])):
        ps = build(lane)
        print(f"lane {lane}: {len(ps)} platforms, start {start_pos(lane)}, finish x {ps[-1].x0}..{ps[-1].x1}")
