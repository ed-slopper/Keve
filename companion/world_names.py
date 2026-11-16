"""Every block and item by name, from the game's own data in your Horizon install:
the block and item registries, the block tags and the English names.

    names().blocks_in("mine this coal")     -> ({'minecraft:coal_ore', 'minecraft:deepslate_coal_ore'}, 'coal ore')
    names().blocks_in("open that oak door") -> ({'minecraft:oak_door'}, 'oak door')
    names().item_in("place a crafting table") -> ('minecraft:crafting_table', 'crafting table')
    names().tool_for('minecraft:diamond_ore') -> ('pickaxe', 2)   # needs an iron pickaxe
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

FILLER = {"the", "a", "an", "this", "that", "these", "those", "some", "my", "your", "our", "me",
          "it", "here", "there", "next", "to", "by", "near", "of", "for", "please", "keve", "kev",
          "and", "then", "right", "over", "on", "in", "at", "up", "down", "go", "can", "you",
          "could", "with", "from", "all", "block", "blocks"}
# Words people say for a group of blocks, mapped to a block tag.
GROUP_WORDS = {"wood": "logs", "log": "logs", "logs": "logs", "tree": "logs", "trees": "logs",
               "plank": "planks", "planks": "planks", "leaves": "leaves", "leaf": "leaves",
               "wool": "wool", "flower": "flowers", "flowers": "flowers", "sand": "sand",
               "door": "doors", "doors": "doors", "button": "buttons", "trapdoor": "trapdoors",
               "bed": "beds", "fence": "fences", "slab": "slabs", "stairs": "stairs",
               "sapling": "saplings", "carpet": "wool_carpets", "candle": "candles"}


def game_data_dir():
    versions = Path(os.environ.get("APPDATA", "")) / "horizon-launcher" / "versions"
    dirs = sorted((d for d in versions.glob("*") if (d / ".local" / "horizon-client").exists()),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs:
        for sub in sorted((d / ".local" / "horizon-client").glob("*"), reverse=True):
            if (sub / "registries.json").exists():
                return sub
    return None


def _singular(w):
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("ses") or w.endswith("xes") or w.endswith("ches"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


class Names:
    def __init__(self, data_dir):
        reg = json.loads((data_dir / "registries.json").read_text(encoding="utf-8"))
        self.blocks = set(reg["minecraft:block"]["entries"])
        self.items = set(reg["minecraft:item"]["entries"])
        raw = json.loads((data_dir / "block-tags.json").read_text(encoding="utf-8"))
        self._raw_tags = {k: (json.loads(v) if isinstance(v, str) else v) for k, v in raw.items()}
        lang = json.loads((data_dir / "assets" / "minecraft" / "lang" / "en_us.json").read_text(encoding="utf-8"))
        self.block_name = {}
        self.by_name = {}  # display name (lower, singular) -> block ids
        for b in self.blocks:
            short = b.removeprefix("minecraft:")
            name = lang.get(f"block.minecraft.{short}", short.replace("_", " ")).lower()
            self.block_name[b] = name
            for key in {name, short.replace("_", " ")}:
                self.by_name.setdefault(" ".join(_singular(w) for w in key.split()), set()).add(b)
        self.item_name = {}
        self.items_by_name = {}
        for i in self.items:
            short = i.removeprefix("minecraft:")
            name = lang.get(f"item.minecraft.{short}") or lang.get(f"block.minecraft.{short}") or \
                short.replace("_", " ")
            name = name.lower()
            self.item_name[i] = name
            for key in {name, short.replace("_", " ")}:
                self.items_by_name.setdefault(" ".join(_singular(w) for w in key.split()), i)

    @lru_cache(maxsize=512)
    def tag(self, name):
        """A block tag's blocks, nested tags resolved: tag('coal_ores')."""
        t = self._raw_tags.get(name if ":" in name else "minecraft:" + name)
        if not t:
            return frozenset()
        out = set()
        for v in t.get("values", []):
            v = v["id"] if isinstance(v, dict) else v
            if v.startswith("#"):
                out |= self.tag(v[1:])
            elif v in self.blocks:
                out.add(v)
        return frozenset(out)

    def _phrases(self, text):
        words = [_singular(w) for w in re.findall(r"[a-z]+", text.lower())]
        words = [w for w in words if w not in FILLER]
        for n in (4, 3, 2, 1):  # longest first: "deepslate coal ore" before "coal"
            for i in range(len(words) - n + 1):
                yield " ".join(words[i:i + n])

    def blocks_in(self, text):
        """The blocks a message names, and how to call them. ({ids}, label) or (set(), None)."""
        for ph in self._phrases(text):
            if ph in self.by_name:
                ids = set(self.by_name[ph])
                # "coal ore" also means the deepslate one: the ore tag holds both.
                for b in list(ids):
                    short = b.removeprefix("minecraft:")
                    if short.endswith("_ore"):
                        ids |= self.tag(short + "s")
                return ids, ph
            us = ph.replace(" ", "_")
            for tag in (us + "_ores", us + "s", us, GROUP_WORDS.get(ph, "")):
                if tag and self.tag(tag):
                    return set(self.tag(tag)), ph
        return set(), None

    def item_in(self, text):
        """The item a message names: (id, label) or (None, None)."""
        for ph in self._phrases(text):
            if ph in self.items_by_name:
                return self.items_by_name[ph], ph
        return None, None

    def tool_for(self, block):
        """(tool, tier) to mine it with its drop: tier 0 wood, 1 stone, 2 iron, 3 diamond."""
        tool = next((t for t in ("pickaxe", "axe", "shovel", "hoe") if block in self.tag(f"mineable/{t}")), None)
        tier = 0
        for t, n in (("needs_stone_tool", 1), ("needs_iron_tool", 2), ("needs_diamond_tool", 3)):
            if block in self.tag(t):
                tier = n
        return tool, tier

    def pretty(self, block):
        return self.block_name.get(block.split("[", 1)[0], block.removeprefix("minecraft:").replace("_", " "))


@lru_cache(maxsize=1)
def names():
    d = game_data_dir()
    return Names(d) if d else None
