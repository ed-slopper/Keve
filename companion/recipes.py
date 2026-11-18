"""Every crafting recipe in the game, read from the game's own data (data/minecraft/recipe),
so Keve can make anything a player can: a boat, a bucket, a ladder, a bed, a shield...

craft.py has hand-written recipes for the basics (tools, table, furnace, torches, chest).
This adds the rest in the same shape: (grid 2 or 3, {cell: ingredient}, how many it makes).
Ingredients that are a group a player would use any of ("any planks", "any logs",
"cobblestone or blackstone", "coal or charcoal") use craft.py's group names, so Keve's
gathering already knows how to get them. Wood families (oak_boat, birch_boat...) also get
one plain name ("boat") that takes whatever planks Keve has.
"""
import json
from pathlib import Path

WOODS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "pale_oak",
         "bamboo", "crimson", "warped")
GROUP_TAGS = {
    "minecraft:planks": "planks",
    "minecraft:logs": "log", "minecraft:logs_that_burn": "log",
    "minecraft:stone_tool_materials": "cobble", "minecraft:stone_crafting_materials": "cobble",
    "minecraft:coals": "coal",
    "minecraft:wooden_tool_materials": "planks",
    "minecraft:iron_tool_materials": "iron_ingot",
    "minecraft:diamond_tool_materials": "diamond",
    "minecraft:gold_tool_materials": "gold_ingot",
}
# Mined, smelted or farmed, never crafted by Keve (the game has 'iron ingot from nuggets'
# and 'nuggets from an ingot', which would go round in circles).
RAW = {"iron_ingot", "gold_ingot", "copper_ingot", "netherite_ingot", "diamond", "emerald", "coal",
       "charcoal", "redstone", "lapis_lazuli", "raw_iron", "raw_gold", "raw_copper", "wheat", "slime_ball",
       "string", "leather", "feather", "bone", "bone_meal", "gunpowder", "flint", "clay_ball", "glowstone_dust",
       "quartz", "amethyst_shard", "iron_nugget", "gold_nugget", "copper_nugget", "honey_bottle", "resin_clump",
       "dried_kelp", "melon_slice", "sugar", "paper", "blaze_powder", "ender_pearl"}
COLOURS = ("white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan",
           "purple", "blue", "brown", "green", "red", "black")
SINGLE = {"minecraft:stick": "stick", "minecraft:iron_ingot": "iron_ingot", "minecraft:cobblestone": "cobble",
          "minecraft:coal": "coal", "minecraft:crafting_table": "crafting_table", "minecraft:furnace": "furnace",
          "minecraft:chest": "chest", "minecraft:torch": "torch", "minecraft:raw_iron": "raw_iron"}


class Loader:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "data" / "minecraft"
        self.tag_cache = {}

    def item_tag(self, name):
        """An item tag's items, nested tags resolved."""
        name = name.lstrip("#")
        if name in self.tag_cache:
            return self.tag_cache[name]
        ns, _, path = name.partition(":")
        f = self.root.parent / (ns or "minecraft") / "tags" / "item" / f"{path}.json"
        out = set()
        self.tag_cache[name] = out
        try:
            values = json.loads(f.read_text(encoding="utf-8")).get("values", [])
        except (OSError, ValueError):
            return out
        for v in values:
            v = v["id"] if isinstance(v, dict) else v
            out |= self.item_tag(v) if v.startswith("#") else {v}
        return out

    def ingredient(self, spec, ingredients):
        """A recipe's ingredient -> a name in craft.INGREDIENTS (added if new)."""
        if isinstance(spec, dict):
            spec = spec.get("item") or ("#" + spec["tag"] if "tag" in spec else None)
        if isinstance(spec, list):
            opts = set()
            for s in spec:
                s = s.get("item") or ("#" + s.get("tag", "")) if isinstance(s, dict) else s
                opts |= self.item_tag(s) if s.startswith("#") else {s}
            if opts == {"minecraft:coal", "minecraft:charcoal"}:
                return "coal"
            key = "any:" + ",".join(sorted(o.removeprefix("minecraft:") for o in opts))
            ingredients.setdefault(key, (lambda ok: (lambda i: i in ok))(frozenset(opts)))
            return key
        if not isinstance(spec, str):
            return None
        if spec.startswith("#"):
            tag = spec[1:]
            if tag in GROUP_TAGS:
                return GROUP_TAGS[tag]
            opts = frozenset(self.item_tag(tag))
            key = "tag:" + tag.removeprefix("minecraft:")
            ingredients.setdefault(key, (lambda ok: (lambda i: i in ok))(opts))
            return key
        if spec in SINGLE:
            return SINGLE[spec]
        key = spec.removeprefix("minecraft:")
        ingredients.setdefault(key, (lambda name: (lambda i: i == name))(spec))
        return key

    def load(self, recipes, ingredients):
        """Add every crafting recipe that isn't in `recipes` yet. How many were added."""
        rdir = self.root / "recipe"
        if not rdir.is_dir():
            return 0
        added = 0
        families = {}
        files = sorted(rdir.glob("*.json"))
        # A result's own file first (white_bed.json, not dye_white_bed.json), then the rest.
        for f in [f for f in files if "_from_" not in f.stem and not f.stem.startswith("dye_")] + files:
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            kind = r.get("type", "")
            if kind not in ("minecraft:crafting_shaped", "minecraft:crafting_shapeless"):
                continue
            res = r.get("result") or {}
            rid = res.get("id") or res.get("item")
            if not rid or not rid.startswith("minecraft:"):
                continue
            name = rid.removeprefix("minecraft:")
            if name in recipes or name in RAW or name.endswith(("_ingot", "_nugget", "_dye", "_wool")):
                continue
            got = self.shape(r, kind, ingredients)
            if got is None:
                continue
            size, cells = got
            recipes[name] = (size, cells, int(res.get("count", 1)))
            ingredients.setdefault(name, (lambda n: (lambda i: i == n))(rid))
            added += 1
            # oak_boat, oak_door...: remember the family, to make 'boat' out of any planks.
            # (and white_bed, white_carpet...: 'bed' in any colour, made as the white one)
            for w in WOODS + COLOURS:
                if name.startswith(w + "_") and (w in COLOURS or any(
                        v == "planks" or v.startswith(w + "_") for v in cells.values())):
                    families.setdefault(name[len(w) + 1:], []).append((w, size, cells, int(res.get("count", 1))))
        for fam in sorted(families, key=lambda f: f.count("_")):  # boat before chest_boat
            members = families[fam]
            if fam in recipes or len(members) < 3:
                continue  # a real item of that name, or not really a family
            first = "white" if any(m[0] == "white" for m in members) else "oak"
            w, size, cells, makes = next((m for m in members if m[0] == first), members[0])
            plain = {}
            for c, v in cells.items():
                if v == w + "_planks":
                    v = "planks"
                elif v == w + "_log":
                    v = "log"
                elif w in WOODS and v.startswith(w + "_") and v[len(w) + 1:] in recipes:
                    v = v[len(w) + 1:]  # oak_chest_boat takes an oak boat: a chest boat takes a boat
                plain[c] = v
            recipes[fam] = (size, plain, makes)
            ids = frozenset(f"minecraft:{m[0]}_{fam}" for m in members)
            ingredients[fam] = (lambda ok: (lambda i: i in ok))(ids)
            added += 1
        # "any wooden slab" in a recipe (a barrel) is the slab family Keve can make.
        for name, (size, cells, makes) in list(recipes.items()):
            fixed = {}
            for c, v in cells.items():
                if v.startswith("tag:wooden_"):
                    fam = v[len("tag:wooden_"):].rstrip("s")
                    v = fam if fam in recipes else v
                fixed[c] = v
            recipes[name] = (size, fixed, makes)
        return added

    def shape(self, r, kind, ingredients):
        """(grid size, {cell: ingredient}) for a recipe, or None if it can't be read."""
        if kind == "minecraft:crafting_shaped":
            rows = r.get("pattern") or []
            key = r.get("key") or {}
            if not rows or len(rows) > 3 or max(len(x) for x in rows) > 3:
                return None
            size = 2 if len(rows) <= 2 and max(len(x) for x in rows) <= 2 else 3
            cells = {}
            for y, row in enumerate(rows):
                for x, ch in enumerate(row):
                    if ch == " ":
                        continue
                    ing = self.ingredient(key.get(ch), ingredients)
                    if ing is None:
                        return None
                    cells[y * size + x] = ing
            return size, cells
        parts = r.get("ingredients") or []
        if not parts or len(parts) > 9:
            return None
        size = 2 if len(parts) <= 4 else 3
        cells = {}
        for n, spec in enumerate(parts):
            ing = self.ingredient(spec, ingredients)
            if ing is None:
                return None
            cells[n] = ing
        return size, cells
