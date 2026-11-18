"""Crafting and smelting, done the way a player does: in the inventory's 2x2 grid, at a
crafting table Keve places, or in a furnace Keve places, by clicking slots.

Slot ids (Horizon's menus): 0-35 inventory, 100-103 the inventory's 2x2 grid,
100-108 a crafting table's 3x3 grid (row by row), 200 the result;
furnace 300 input, 301 fuel, 302 output. Menu clicks need Keve's game to have a
renderer, so it runs --offscreen, not --headless.
"""
import math
import time

import sight

# What an ingredient may be (Minecraft accepts any of these).
INGREDIENTS = {
    "log": lambda i: (i.endswith("_log") or i.endswith("_stem")) and "stripped" not in i,
    "planks": lambda i: i.endswith("_planks"),
    "stick": lambda i: i == "minecraft:stick",
    "cobble": lambda i: i in ("minecraft:cobblestone", "minecraft:cobbled_deepslate",
                              "minecraft:blackstone"),
    "coal": lambda i: i in ("minecraft:coal", "minecraft:charcoal"),
    "iron_ingot": lambda i: i == "minecraft:iron_ingot",
    "raw_iron": lambda i: i == "minecraft:raw_iron",
    "crafting_table": lambda i: i == "minecraft:crafting_table",
    "furnace": lambda i: i == "minecraft:furnace",
    "chest": lambda i: i == "minecraft:chest",
    "raw_meat": lambda i: i in ("minecraft:beef", "minecraft:porkchop", "minecraft:mutton", "minecraft:chicken",
                                "minecraft:rabbit", "minecraft:cod", "minecraft:salmon"),
}
for _tool in ("wooden", "stone", "iron", "diamond", "golden", "netherite"):
    for _kind in ("pickaxe", "sword", "axe", "shovel", "hoe"):
        INGREDIENTS[f"{_tool}_{_kind}"] = (lambda name: (lambda i: i == "minecraft:" + name))(
            f"{_tool}_{_kind}")
INGREDIENTS["torch"] = lambda i: i == "minecraft:torch"

# Shaped recipes: (grid 2 or 3, {cell: ingredient}, how many it makes).
# Cells count row by row: 2x2 is 0 1 / 2 3; 3x3 is 0 1 2 / 3 4 5 / 6 7 8.
RECIPES = {
    "planks": (2, {0: "log"}, 4),
    "stick": (2, {0: "planks", 2: "planks"}, 4),
    "crafting_table": (2, {0: "planks", 1: "planks", 2: "planks", 3: "planks"}, 1),
    "torch": (2, {0: "coal", 2: "stick"}, 4),
    "furnace": (3, {i: "cobble" for i in range(9) if i != 4}, 1),
    "chest": (3, {i: "planks" for i in range(9) if i != 4}, 1),
}
for _tool, _mat in (("wooden", "planks"), ("stone", "cobble"), ("iron", "iron_ingot")):
    RECIPES[f"{_tool}_pickaxe"] = (3, {0: _mat, 1: _mat, 2: _mat, 4: "stick", 7: "stick"}, 1)
    RECIPES[f"{_tool}_sword"] = (3, {1: _mat, 4: _mat, 7: "stick"}, 1)
    RECIPES[f"{_tool}_axe"] = (3, {0: _mat, 1: _mat, 3: _mat, 4: "stick", 7: "stick"}, 1)
    RECIPES[f"{_tool}_shovel"] = (3, {1: _mat, 4: "stick", 7: "stick"}, 1)
    RECIPES[f"{_tool}_hoe"] = (3, {0: _mat, 1: _mat, 4: "stick", 7: "stick"}, 1)

FUELS = ["coal", "charcoal", "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log",
         "dark_oak_log", "cherry_log", "mangrove_log", "pale_oak_log", "oak_planks", "birch_planks",
         "spruce_planks", "jungle_planks", "acacia_planks", "dark_oak_planks", "cherry_planks",
         "mangrove_planks", "pale_oak_planks", "stick"]
FUEL_ITEMS = {"coal": 8, "charcoal": 8, "stick": 0.5}  # items smelted per fuel item; logs and planks 1.5


def fuel_value(item):
    short = item.removeprefix("minecraft:")
    if short in FUEL_ITEMS:
        return FUEL_ITEMS[short]
    if short.endswith("_log") or short.endswith("_planks"):
        return 1.5
    return 0


# Everything else a player can craft, from the game's own recipe files.
try:
    import recipes as _recipes
    import world_names as _world_names
    LOADED_RECIPES = _recipes.Loader(_world_names.game_data_dir()).load(RECIPES, INGREDIENTS)
except Exception as _e:  # no game data found: the hand-written recipes still work
    LOADED_RECIPES = 0


class NeedMore(Exception):
    """Crafting can't go on: something raw has to be gathered or mined first."""

    def __init__(self, what, count):
        super().__init__(f"need {count} {what}")
        self.what = what
        self.count = count


class Crafter:
    def __init__(self, ctx, task):
        self.ctx = ctx
        self.task = task

    # --- inventory --------------------------------------------------------------------
    def count(self, ingredient):
        ok = INGREDIENTS[ingredient]
        return sum(n for i, n in self.ctx.counts().items() if ok(i))

    def menu(self):
        return self.ctx.body.call("menu")

    def slots(self):
        return {s["slot"]: s["stack"] for s in self.menu().get("slots", [])}

    def click(self, slot, right=False, shift=False):
        line = f"click-slot {slot}" + (" right" if right else "") + (" shift" if shift else "")
        r = self.ctx.body.call(line)
        if r.get("error"):
            raise RuntimeError(f"{line}: {r['error']}")

    # --- planning ---------------------------------------------------------------------
    def inventory_by_ingredient(self):
        counts = self.ctx.counts()
        return {ing: sum(n for i, n in counts.items() if ok(i)) for ing, ok in INGREDIENTS.items()}

    def raw_needs(self, item, count):
        """The raw materials still missing to make `count` of `item`, e.g. {'log': 2}."""
        return self.raw_needs_many([(item, count)])

    def raw_needs_many(self, wanted):
        """The raw materials missing for a whole list [(item, count)...] made one after
        another from the same inventory: what a quest needs, to gather in one go."""
        inv = self.inventory_by_ingredient()
        out = {}
        tables = [inv.get("crafting_table", 0) > 0]

        making = []

        def need(ing, n):
            use = min(inv.get(ing, 0), n)
            inv[ing] = inv.get(ing, 0) - use
            n -= use
            if n <= 0:
                return
            if ing not in RECIPES or ing in making or len(making) > 8:
                out[ing] = out.get(ing, 0) + n  # raw (or a recipe that loops back): get it
                return
            making.append(ing)
            size, pattern, makes = RECIPES[ing]
            batches = math.ceil(n / makes)
            if size == 3 and not tables[0]:
                tables[0] = True  # one table, kept and reused
                need("crafting_table", 1)
            for part in pattern.values():
                need(part, batches)
            making.pop()
            inv[ing] = inv.get(ing, 0) + batches * makes - n

        for item, count in wanted:
            need(item, count)
        return out

    # --- crafting ---------------------------------------------------------------------
    def craft(self, item, count=1):
        """Make at least `count` more of `item` (crafting what it needs on the way).
        Raises NeedMore when a raw material must be gathered first."""
        missing = self.raw_needs(item, count + self.count(item) if item in INGREDIENTS else count)
        for raw, n in missing.items():
            raise NeedMore(raw, n)  # gather everything at once, then come back
        size, pattern, makes = RECIPES[item]
        batches = math.ceil(count / makes)
        if size == 3 and self.count("crafting_table") == 0:
            self.craft("crafting_table", 1)  # before the ingredients: it uses planks too
        need = {}
        for ing in pattern.values():
            need[ing] = need.get(ing, 0) + batches
        # Make the intermediate ingredients, re-checking after each (sticks use planks...).
        for _ in range(8):
            short = [(ing, n - self.count(ing)) for ing, n in need.items() if self.count(ing) < n]
            if not short:
                break
            ing, n = short[0]
            if ing not in RECIPES:
                raise NeedMore(ing, n)
            self.craft(ing, n)
        if size == 3:
            table = self.ensure_station("crafting_table")
            self.ctx.body.call(f"look-at block {table[0]} {table[1]} {table[2]}")
            self.ctx.body.call(f"interact {table[0]} {table[1]} {table[2]}")
            grid = {cell: 100 + cell for cell in range(9)}
        else:
            self.ctx.body.call("open-inventory")
            grid = {cell: 100 + cell for cell in range(4)}
        try:
            for _ in range(batches):
                if self.task.done():
                    return
                self._fill(pattern, grid)
                result = None
                for _ in range(8):  # the result slot fills a tick or two after the grid
                    result = self.slots().get(200)
                    if result:
                        break
                    time.sleep(0.06)
                if not result:
                    raise RuntimeError(f"the {item} recipe didn't show a result")
                self.click(200, shift=True)
                time.sleep(0.05)
        finally:
            self.ctx.body.call("close")
            # The table stays out while there's crafting to do; Keve packs it up once he's
            # been idle a while (skills.Idle), like a player would.
            self.ctx.last_craft_time = time.time()

    def _fill(self, pattern, grid):
        """Put one ingredient in each cell of the pattern."""
        by_ing = {}
        for cell, ing in pattern.items():
            by_ing.setdefault(ing, []).append(grid[cell])
        for ing, cells in by_ing.items():
            ok = INGREDIENTS[ing]
            placed = 0
            while placed < len(cells):
                slots = self.slots()
                # One stack that fills every cell first: a boat out of one kind of planks.
                mine = [(s, st) for s, st in slots.items() if s < 100 and ok(st["item"])]
                whole = [s for s, st in mine if st["count"] >= len(cells) - placed]
                src = whole[0] if whole else (mine[0][0] if mine else None)
                if src is None:
                    raise RuntimeError(f"ran out of {ing} while crafting")
                self.click(src)  # pick the stack up
                have = slots[src]["count"]
                while placed < len(cells) and have > 0:
                    self.click(cells[placed], right=True)  # put one down
                    placed += 1
                    have -= 1
                self.click(src)  # put the rest back

    # --- placing a crafting table / furnace next to Keve -------------------------------
    def placed_station(self, kind):
        """A table or furnace already standing within reach that Keve can see (his own from
        the last craft, or yours): use that instead of putting another one down."""
        eye = tuple(self.ctx.state()["player"]["eye"])
        snap = sight.Snapshot.read(self.ctx.senses, eye, rh=5, rv=3)
        spots = sorted((p for p, n in snap.blocks.items() if n.split("[")[0] == "minecraft:" + kind),
                       key=lambda p: math.dist(p, eye))
        for p in spots:
            if math.dist(eye, (p[0] + .5, p[1] + .5, p[2] + .5)) <= 4.3 and snap.block_visible(eye, p, 5.0):
                return p
        return None

    def ensure_station(self, kind):
        """A placed table or furnace within reach: one that's already out, or Keve places his own."""
        there = self.placed_station(kind)
        if there:
            return there
        if self.count(kind) == 0:
            if kind not in RECIPES:
                raise NeedMore(kind, 1)
            self.craft(kind, 1)
        last = "no room"
        for attempt in range(4):
            for spot in self.free_spots():
                r = self.ctx.place(spot, kind)
                if not r.get("error"):
                    if kind == "crafting_table":
                        self.ctx.placed_stations.append(tuple(spot))
                    return spot
                last = r["error"]
            if self.task.done():
                break
            # Boxed in (inside a tree trunk's gap, a 1-wide tunnel): a few steps to open
            # ground, toward you first, then try again.
            pos = self.ctx.eye_and_view()[3]
            o = self.ctx.owner() if attempt == 0 else None
            if o and math.dist(o[1], pos) > 2:
                tx, tz = o[1][0], o[1][2]
            else:
                ang = attempt * 2.1
                tx, tz = pos[0] + 4 * math.cos(ang), pos[2] + 4 * math.sin(ang)
            self.ctx.body.call(f"goto {tx:.1f} {pos[1]:.1f} {tz:.1f} --near 2 --timeout 6")
        raise RuntimeError(f"couldn't put a {kind.replace('_', ' ')} down ({last})")

    def pick_up_station(self, pos):
        """Break the table or furnace again and keep it (a furnace needs a pickaxe)."""
        if self.task.done():
            return
        pick = self.ctx.select_best(PICKAXES_ALL)
        name = self.ctx.senses.call(f"blocks {pos[0]} {pos[1]} {pos[2]} {pos[0]} {pos[1]} {pos[2]}")
        if not name.get("blocks"):
            return
        if "furnace" in name["blocks"][0][3] and not pick:
            return  # would drop nothing: leave it
        self.ctx.body.call(f"look-at block {pos[0]} {pos[1]} {pos[2]}")
        self.ctx.body.call(f"break {pos[0]} {pos[1]} {pos[2]} --timeout 10")
        time.sleep(0.6)
        self.ctx.recent_breaks.append((pos[0], pos[1], pos[2], time.time()))
        self.ctx.collect(4, self.task)

    def free_spots(self):
        """Empty blocks next to Keve, at its feet, with something solid under them,
        that Keve isn't standing in (a player is 0.6 wide, so it can overlap two cells)."""
        p = self.ctx.state()["player"]
        bx, by, bz = p["block_pos"]
        px, _, pz = p["position"]
        # Other players (you) standing close: a block can't go where a body is.
        others = [tuple(e["pos"]) for e in self.ctx.senses.call("entities 4").get("entities", [])
                  if e.get("type") == "minecraft:player" or e.get("kind") == "mob"]
        box = self.ctx.senses.call(f"blocks {bx - 2} {by - 1} {bz - 2} {bx + 2} {by + 1} {bz + 2}")
        solid = {(b[0], b[1], b[2]) for b in box.get("blocks", []) if sight.blocks_body(b[3])}
        # Cells with anything in them (leaf litter, flowers...) can refuse a block: skip them.
        occupied = {(b[0], b[1], b[2]) for b in box.get("blocks", [])
                    if not b[3].startswith(("minecraft:short_grass", "minecraft:tall_grass"))}
        out = []
        dirs = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))
        for dy in (0, 1, -1):  # at its feet first, then a step up or down
            for dx, dz in dirs:
                c = (bx + dx, by + dy, bz + dz)
                # The player's box reaches 0.3 past its centre: keep clear of it.
                near_x = max(c[0], min(px, c[0] + 1)) - px
                near_z = max(c[2], min(pz, c[2] + 1)) - pz
                if abs(near_x) < 0.35 and abs(near_z) < 0.35 and dy >= 0:
                    continue
                if any(abs(o[0] - (c[0] + 0.5)) < 0.85 and abs(o[2] - (c[2] + 0.5)) < 0.85
                       and o[1] - 2 < c[1] < o[1] + 2 for o in others):
                    continue
                if c not in occupied and (c[0], c[1] - 1, c[2]) in solid:
                    out.append(c)
        if not out:
            # Nowhere free (a tunnel, a slope): dig a spot out at its feet.
            for dx, dz in dirs[:4]:
                c = (bx + dx, by, bz + dz)
                if c in solid and (c[0], c[1] - 1, c[2]) in solid:
                    self.ctx.body.call(f"look-at block {c[0]} {c[1]} {c[2]}")
                    if not self.ctx.body.call(f"break {c[0]} {c[1]} {c[2]} --timeout 10").get("error"):
                        out.append(c)
                        break
        return out

    # --- smelting ---------------------------------------------------------------------
    def smelt(self, raw, count):
        """Smelt `count` of a raw ingredient (raw_iron) in a furnace Keve places."""
        if self.count(raw) < count:
            raise NeedMore(raw, count - self.count(raw))
        fuel_needed = count
        fuel = sorted(((i, n) for i, n in self.ctx.counts().items() if fuel_value(i) > 0),
                      key=lambda kv: -fuel_value(kv[0]))
        if sum(fuel_value(i) * n for i, n in fuel) < fuel_needed:
            raise NeedMore("fuel", 1)
        furnace = self.ensure_station("furnace")
        self.ctx.body.call(f"look-at block {furnace[0]} {furnace[1]} {furnace[2]}")
        self.ctx.body.call(f"interact {furnace[0]} {furnace[1]} {furnace[2]}")
        try:
            slots = self.slots()
            src = next(s for s, st in slots.items() if s < 100 and INGREDIENTS[raw](st["item"]))
            self.click(src)
            for _ in range(count):
                self.click(300, right=True)
            self.click(src)
            # Fuel: enough for the batch, best fuel first.
            left = fuel_needed
            for item, n in fuel:
                if left <= 0:
                    break
                slots = self.slots()
                src = next((s for s, st in slots.items() if s < 100 and st["item"] == item), None)
                if src is None:
                    continue
                self.click(src)
                while left > 0 and n > 0:
                    self.click(301, right=True)
                    n -= 1
                    left -= fuel_value(item)
                self.click(src)
            # About 10 s an item.
            end = time.time() + count * 10.5 + 5
            while time.time() < end and not self.task.done():
                out = self.slots().get(302)
                if out and out["count"] >= count:
                    break
                time.sleep(1.0)
            if self.slots().get(302):
                self.click(302, shift=True)
            if self.slots().get(301):
                self.click(301, shift=True)  # take leftover fuel back
        finally:
            self.ctx.body.call("close")
            self.pick_up_station(furnace)


PICKAXES_ALL = ["netherite_pickaxe", "diamond_pickaxe", "iron_pickaxe", "stone_pickaxe",
                "golden_pickaxe", "wooden_pickaxe"]
