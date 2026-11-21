"""One-on-one melee, in styles that can be compared in the practice arena.

What the fights are built on (from Horizon's mob code, see docs/future-training.md):
- melee mobs (zombie, enderman, wither skeleton) swing once every 20 ticks, and only reach
  about 0.8 of a block past their own hitbox;
- a diamond sword hits for full damage every 13 ticks (1.6 attacks a second);
- a shield blocks a frontal melee hit once it has been up for 5 ticks.

Styles:
- "plain": walk in and swing on the cooldown (what Keve did before).
- "shield": swing, then shield up toward it until the sword is ready again.
- "kite": swing, then a step back out of its reach so its next swing misses, then in again.
- "crit": jump and swing on the way down (half again the damage), shield up in between.
"""
import math
import time

from skills import WEAPONS as SWORDS  # a stone axe first


def _mob(ctx, mob_id):
    # 64 out: an enderman teleports up to 32 away, which isn't a kill.
    for e in ctx.senses.call("entities 64").get("entities", []):
        if e.get("id") == mob_id:
            return e
    return None


def fight(ctx, mob_ids, task=None, style="shield", timeout=90.0):
    """Several at once: the nearest still alive first. 'won' when all are down."""
    if style == "nook":
        return hold_nook(ctx, mob_ids, task, timeout)
    if style == "boat":
        r = "won"
        for i in mob_ids:
            r = boat_trap(ctx, i, task, timeout)
            if r != "won":
                return r
        return r
    end = time.time() + timeout
    left = list(mob_ids)
    while left and time.time() < end:
        alive = []
        for i in left:
            m = _mob(ctx, i)
            if m is not None and (m.get("health") is None or m["health"] > 0):
                alive.append(m)
        if not alive:
            return "won"
        target = min(alive, key=lambda m: m["distance"])
        r = duel(ctx, target["id"], task, style=style, timeout=end - time.time(), others=[m["id"] for m in alive])
        if r == "lost":
            return "lost"
        left = [m["id"] for m in alive]
    return "won" if not left else "timeout"


def _has_shield(ctx):
    try:
        off = ctx.body.call("inventory").get("offhand") or {}
    except Exception:
        return False
    return "shield" in str(off.get("item") if isinstance(off, dict) else off)


def duel(ctx, mob_id, task=None, style="shield", timeout=60.0, others=()):
    """Fight one mob until it's dead, he's dead, or the time's up. 'won', 'lost' or 'timeout'."""
    ctx.select_best(SWORDS)
    shield = _has_shield(ctx)
    end = time.time() + timeout
    last_swing = 0.0
    b = ctx.body
    try:
        while time.time() < end and not (task is not None and task.done()):
            try:
                hp = ctx.state()["player"].get("health", 20)
            except Exception:
                return "lost"
            if hp <= 0:
                return "lost"
            m = _mob(ctx, mob_id)
            if m is None or (m.get("health") is not None and m["health"] <= 0):
                return "won"
            d = m["distance"]
            if others and d > 3.5:
                near = [e for e in ctx.senses.call("entities 6").get("entities", [])
                        if e.get("id") in others and e["id"] != mob_id and e["distance"] < d - 1]
                if near:
                    return "switch"  # another is closer: that one first
            b.call(f"look-at entity {mob_id}")
            if d > 7.0:
                x, y, z = m["pos"]
                b.call(f"goto {x:.2f} {y:.2f} {z:.2f} --near 2.5 --sprint --timeout 1.5")
                continue
            held = (ctx.state().get("held") or {}).get("item", "") or ""
            ready = time.time() - last_swing >= (1.25 if held.endswith("_axe") else 0.65)  # axe 25 ticks, sword 13
            if d > 2.9:
                # In toward it (shield up on the way when it's a slow walk, not a sprint).
                b.call("move forward 0.25 --sprint")
                continue
            if not ready:
                time.sleep(0.05)
                continue
            if style == "crit":
                b.call("mouse right up")
                b.call("key space down")
                time.sleep(0.32)  # past the top of the jump: falling, so the hit is critical
                b.call(f"attack {mob_id}")
                b.call("key space up")
            else:
                b.call("mouse right up")
                b.call(f"attack {mob_id}")
            last_swing = time.time()
            if style in ("shield", "crit") and shield:
                b.call("mouse right down")
                time.sleep(0.55)
                b.call("mouse right up")
            elif style == "kite":
                b.call("move back 0.35 --sprint")
                time.sleep(0.2)
            else:
                time.sleep(0.55)
        return "timeout"
    finally:
        b.call("mouse right up")
        b.call("key space up")


DIRS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def make_nook(ctx, task=None, r=10, threats=()):
    """A pocket two deep and two high dug into the nearest thick wall: a wither skeleton is
    2.4 tall, so it can't come in, and from the back of it he reaches the opening (about 3
    blocks) while its reach (about 1.5) doesn't reach him. True when he's standing in it."""
    import sight
    x, y, z = ctx.state()["player"]["block_pos"]
    snap = sight.Snapshot.read(ctx.senses, (x, y, z), rh=r + 2, rv=4)

    def solid(c):
        n = snap.name(c)
        return sight.blocks_body(n) and not sight.is_fluid(n)

    def open_(c):
        n = snap.name(c)
        return not sight.blocks_body(n) and not sight.is_fluid(n)
    best = None
    for dx, dz in DIRS4:
        for k in range(1, r):
            w1 = (x + dx * k, y, z + dz * k)
            w2 = (x + dx * (k + 1), y, z + dz * (k + 1))
            if not solid(w1):
                continue
            # the pocket: two cells deep, two high, a solid roof and floor, closed at the back
            cells = [w1, (w1[0], y + 1, w1[2]), w2, (w2[0], y + 1, w2[2])]
            roof = [(w1[0], y + 2, w1[2]), (w2[0], y + 2, w2[2])]
            floor = [(w1[0], y - 1, w1[2]), (w2[0], y - 1, w2[2])]
            back = [(x + dx * (k + 2), y, z + dz * (k + 2)), (x + dx * (k + 2), y + 1, z + dz * (k + 2))]
            path = [(x + dx * i, yy, z + dz * i) for i in range(1, k) for yy in (y, y + 1)]
            if all(solid(c) for c in cells + roof + floor + back) and all(open_(c) for c in path):
                # Away from them: a wall on their side meant walking into them to dig it.
                toward = sum(1 for t in threats if (t[0] - x) * dx + (t[2] - z) * dz > 0)
                score = k + 6 * toward
                if best is None or score < best[0]:
                    best = (score, (dx, dz), w1, w2, k)
            break  # the first solid block that way is the wall
    if best is None:
        return False
    _, (dx, dz), w1, w2, k = best
    stand = (x + dx * (k - 1), y, z + dz * (k - 1))
    ctx.body.call(f"goto {stand[0] + 0.5:.2f} {y:.2f} {stand[2] + 0.5:.2f} --near 0.4 --timeout 4")
    ctx.select_best(["netherite_pickaxe", "diamond_pickaxe", "iron_pickaxe", "stone_pickaxe"])
    for c in ((w1[0], y + 1, w1[2]), w1, (w2[0], y + 1, w2[2]), w2):
        ctx.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
        ctx.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 10")
    ctx.body.call(f"goto {w2[0] + 0.5:.2f} {y:.2f} {w2[2] + 0.5:.2f} --near 0.3 --timeout 4 --direct")
    me = ctx.state()["player"]["block_pos"]
    ctx.nook = (tuple(w2), (-dx, -dz))
    return me[0] == w2[0] and me[2] == w2[2]


def hold_nook(ctx, mob_ids, task=None, timeout=90.0):
    """In the pocket: hit whatever comes to the opening, shield up in between, never out."""
    threats = [tuple(m["pos"]) for m in (_mob(ctx, i) for i in mob_ids) if m is not None]
    if not make_nook(ctx, task, threats=threats):
        return fight(ctx, mob_ids, task, style="shield", timeout=timeout)
    ctx.select_best(SWORDS)
    shield = _has_shield(ctx)
    b = ctx.body
    end = time.time() + timeout
    last = 0.0
    try:
        while time.time() < end and not (task is not None and task.done()):
            try:
                if ctx.state()["player"].get("health", 20) <= 0:
                    return "lost"
            except Exception:
                return "lost"
            alive = [m for m in (_mob(ctx, i) for i in mob_ids) if m is not None
                     and (m.get("health") is None or m["health"] > 0)]
            if not alive:
                return "won"
            m = min(alive, key=lambda m: m["distance"])
            b.call(f"look-at entity {m['id']}")
            held = (ctx.state().get("held") or {}).get("item", "") or ""
            ready = time.time() - last >= (1.25 if held.endswith("_axe") else 0.65)
            if m["distance"] <= 3.4 and ready:
                b.call("mouse right up")
                b.call(f"attack {m['id']}")
                last = time.time()
            elif shield:
                b.call("mouse right down")
            time.sleep(0.15)
        return "timeout"
    finally:
        b.call("mouse right up")


def boat_trap(ctx, mob_id, task=None, timeout=60.0):
    """An enderman in a boat can't teleport (Horizon's enderman only dodges when it isn't
    riding) and can't walk. So: a boat on the floor two blocks ahead, stare to set it on him,
    it walks into the boat and boards, then hit it from two back: his reach is 3, its reach
    about 1.4. 'won', 'lost', 'timeout' or 'noboat'."""
    b = ctx.body
    boat_items = [i for i in ctx.counts() if i.endswith("_boat") and "chest" not in i]
    if not boat_items:
        import mining
        try:
            mining.Provision(ctx, task).ensure("oak_boat", 1)
        except Exception:
            pass
        boat_items = [i for i in ctx.counts() if i.endswith("_boat") and "chest" not in i]
    if not boat_items:
        return "noboat"
    m = _mob(ctx, mob_id)
    if m is None:
        return "won"
    p = ctx.state()["player"]
    x, y, z = p["block_pos"]
    mx, _, mz = m["pos"]
    dx, dz = mx - (x + 0.5), mz - (z + 0.5)
    step = (1 if dx > 0 else -1, 0) if abs(dx) >= abs(dz) else (0, 1 if dz > 0 else -1)
    floor = (x + 2 * step[0], y - 1, z + 2 * step[1])
    # (Boats aren't in the entity list: placing it is told by the boat leaving his hands.)
    ctx.to_hotbar(boat_items[0])
    b.call(f"select {boat_items[0]}")
    b.call(f"look-at block {floor[0]} {floor[1]} {floor[2]}")
    before = ctx.counts().get(boat_items[0], 0)
    b.call(f"interact {floor[0]} {floor[1]} {floor[2]} up")
    time.sleep(0.5)
    if ctx.counts().get(boat_items[0], 0) >= before:
        import journal
        journal.log("note", "boat trap: the boat didn't go down", at=list(floor))
        return "noboat"
    seat = (floor[0] + 0.5, y, floor[2] + 0.5)
    ctx.select_best(SWORDS)
    end = time.time() + timeout
    last = 0.0
    try:
        while time.time() < end and not (task is not None and task.done()):
            try:
                if ctx.state()["player"].get("health", 20) <= 0:
                    return "lost"
            except Exception:
                return "lost"
            m = _mob(ctx, mob_id)
            if m is None or (m.get("health") is not None and m["health"] <= 0):
                time.sleep(0.6)
                # The boat back: a few hits on it where it sits breaks it into an item.
                b.call(f"look-at {seat[0]:.2f} {seat[1] + 0.25:.2f} {seat[2]:.2f}")
                for _ in range(4):
                    b.call("attack")
                    time.sleep(0.25)
                time.sleep(0.4)
                ctx.collect(6, task)  # the pearl and the boat
                return "won"
            mp = m["pos"]
            # In the boat: sitting on the seat (a little above the floor), right where it went.
            boarded = math.dist((mp[0], mp[2]), (seat[0], seat[2])) < 1.0 and 0.05 < mp[1] - y < 0.8
            b.call(f"look-at entity {mob_id}")  # the stare: it comes for him, and into the boat
            held = (ctx.state().get("held") or {}).get("item", "") or ""
            ready = time.time() - last >= (1.25 if held.endswith("_axe") else 0.65)
            if boarded:
                if m["distance"] <= 3.2 and ready:
                    b.call(f"attack {mob_id}")
                    last = time.time()
                elif m["distance"] > 3.2:
                    b.call("move forward 0.15")
            elif m["distance"] < 2.6:
                # On him and not in the boat: fight it here, then back to the trap.
                if ready:
                    b.call(f"attack {mob_id}")
                    last = time.time()
            time.sleep(0.1)
        return "timeout"
    finally:
        b.call("mouse right up")
