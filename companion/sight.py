"""Fair sight: only what a player standing in Keve's body could see.

The game hands us a box of block states (an X-ray read), and we keep only what
survives a ray cast from Keve's eyes inside its field of view: the first thing each
ray hits. Ores inside stone, trees behind hills and mobs in caves stay unknown.
"""
import math

# Blocks a ray passes through (you can see past them). Everything else is opaque.
_SEE_THROUGH = (
    "glass", "leaves", "minecraft:water", "short_grass", "tall_grass", "fern", "dead_bush",
    "sapling", "flower", "dandelion", "poppy", "orchid", "allium", "azure_bluet",
    "tulip", "oxeye", "cornflower", "lily_of_the_valley", "torchflower", "pitcher",
    "rose_bush", "peony", "lilac", "sunflower", "wildflowers", "bush", "vine", "torch",
    "button", "lever", "rail", "sign", "ladder", "iron_bars", "chain", "fence",
    "sugar_cane", "kelp", "seagrass", "mushroom", "cobweb", "pressure_plate",
    "redstone_wire", "tripwire", "lily_pad", "candle", "lantern", "snow[layers=1]",
    "carpet", "flower_pot", "bamboo", "sweet_berry", "cave_vines", "moss_carpet",
    "glow_lichen", "hanging_roots", "spore_blossom", "leaf_litter", "firefly_bush",
    "pane", "barrier", "light[", "structure_void", "frogspawn", "big_dripleaf",
    "small_dripleaf", "pink_petals", "cactus_flower", "dry_grass", "short_dry_grass",
)

FOV_H = 110.0  # degrees, whole width
FOV_V = 70.0   # degrees, whole height


def see_through(name):
    return any(s in name for s in _SEE_THROUGH)


# See-through is not walk-through: leaves, glass, fences and bars still block a body.
_SEE_BUT_SOLID = ("glass", "leaves", "pane", "iron_bars", "fence", "lantern", "bamboo",
                  "cactus", "chain", "barrier", "big_dripleaf", "flower_pot", "candle")


def is_fluid(name):
    """Water or lava itself (not a block with 'waterlogged' in its state)."""
    return name.split("[", 1)[0] in ("minecraft:water", "minecraft:lava", "minecraft:bubble_column")


def blocks_body(name):
    """Something a player stands on or bumps into (not air, plants, torches or fluids)."""
    if not name or name == "minecraft:air" or is_fluid(name):
        return False
    return not see_through(name) or any(k in name for k in _SEE_BUT_SOLID)


def view_dir(yaw, pitch):
    """Minecraft angles: yaw 0 faces +Z, 90 faces -X; pitch 90 looks straight down."""
    y, p = math.radians(yaw), math.radians(pitch)
    return (-math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p))


def angles_to(eye, point):
    dx, dy, dz = point[0] - eye[0], point[1] - eye[1], point[2] - eye[2]
    yaw = math.degrees(math.atan2(-dx, dz))
    pitch = math.degrees(-math.atan2(dy, math.hypot(dx, dz)))
    return yaw, pitch


def in_fov(eye, yaw, pitch, point):
    py, pp = angles_to(eye, point)
    dyaw = (py - yaw + 180.0) % 360.0 - 180.0
    return abs(dyaw) <= FOV_H / 2 and abs(pp - pitch) <= FOV_V / 2


class Snapshot:
    """A box of the world around Keve: (x, y, z) -> block state name (non-air only)."""

    def __init__(self, blocks):
        self.blocks = blocks

    @classmethod
    def read(cls, senses, center, rh=19, rv=10):
        cx, cy, cz = (int(math.floor(c)) for c in center)
        reply = senses.call(f"blocks {cx - rh} {cy - rv} {cz - rh} {cx + rh} {cy + rv} {cz + rh}")
        if "blocks" not in reply:
            raise RuntimeError(f"blocks failed: {reply}")
        return cls({(b[0], b[1], b[2]): b[3] for b in reply["blocks"]})

    def name(self, pos):
        return self.blocks.get(pos, "minecraft:air")

    def opaque(self, pos):
        n = self.blocks.get(pos)
        return n is not None and not see_through(n)

    def first_hit(self, eye, target, max_dist=64.0):
        """Walk the voxels from eye towards target; the first opaque cell, or None."""
        dx, dy, dz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-6:
            return None
        dx, dy, dz = dx / length, dy / length, dz / length
        length = min(length, max_dist)
        x, y, z = (int(math.floor(c)) for c in eye)
        step = [1 if d > 0 else -1 for d in (dx, dy, dz)]
        t_max, t_delta = [], []
        for c, d, cell in ((eye[0], dx, x), (eye[1], dy, y), (eye[2], dz, z)):
            if abs(d) < 1e-9:
                t_max.append(math.inf)
                t_delta.append(math.inf)
            else:
                nxt = cell + (1 if d > 0 else 0)
                t_max.append((nxt - c) / d)
                t_delta.append(abs(1.0 / d))
        t = 0.0
        cell = [x, y, z]
        while t <= length:
            axis = t_max.index(min(t_max))
            t = t_max[axis]
            if t > length:
                break
            cell[axis] += step[axis]
            t_max[axis] += t_delta[axis]
            if self.opaque(tuple(cell)):
                return tuple(cell)
        return None

    def block_visible(self, eye, pos, max_dist=48.0):
        """True when a ray from the eye reaches some face of block `pos` first."""
        cx, cy, cz = pos[0] + 0.5, pos[1] + 0.5, pos[2] + 0.5
        if math.dist(eye, (cx, cy, cz)) > max_dist:
            return False
        for n in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            # Only faces turned towards the eye can be seen.
            if (eye[0] - cx) * n[0] + (eye[1] - cy) * n[1] + (eye[2] - cz) * n[2] <= 0.5:
                continue
            # The face centre, then two points nearer its edges.
            for inset in (0.0, 0.3, -0.3):
                u = (n[1], n[2], n[0])  # a direction lying in the face
                p = (cx + n[0] * 0.499 + u[0] * inset,
                     cy + n[1] * 0.499 + u[1] * inset,
                     cz + n[2] * 0.499 + u[2] * inset)
                hit = self.first_hit(eye, p, max_dist)
                if hit is None or hit == tuple(pos):
                    if self.opaque(tuple(pos)) or hit is None:
                        return True
        return False

    def point_visible(self, eye, point, max_dist=48.0):
        return math.dist(eye, point) <= max_dist and self.first_hit(eye, point, max_dist) is None


def visible_blocks(snap, eye, yaw, pitch, wanted, max_dist=40.0):
    """Blocks whose name matches `wanted(name)` and that Keve sees from this view."""
    out = []
    for pos, name in snap.blocks.items():
        if not wanted(name):
            continue
        centre = (pos[0] + 0.5, pos[1] + 0.5, pos[2] + 0.5)
        if not in_fov(eye, yaw, pitch, centre):
            continue
        if snap.block_visible(eye, pos, max_dist):
            out.append((pos, name))
    return out


def entity_visible(snap, eye, yaw, pitch, pos, height=1.8, max_dist=40.0, need_fov=True):
    for frac in (0.85, 0.5, 0.15):
        p = (pos[0], pos[1] + height * frac, pos[2])
        if need_fov and not in_fov(eye, yaw, pitch, p):
            continue
        if snap.point_visible(eye, p, max_dist):
            return True
    return False
