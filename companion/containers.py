"""Chests: finding the one you mean, taking from it, putting things in it, and crafting
from what's inside ("craft me torches from the chest next to me").

Fair: Keve finds a chest by seeing it (from where it stands, or from next to you when
you say "the chest next to me"), walks up to it, opens it and clicks the slots, like a
player. In an open chest, slots 300+ are the chest and 0-35 Keve's inventory.
"""
import math
import time

import craft
import sight
from skills import GATHER, Task, base

CONTAINERS = ("minecraft:chest", "minecraft:trapped_chest", "minecraft:barrel")


def recipe_ingredients(item, seen=None):
    """Every ingredient anywhere in an item's recipe tree: torch -> coal, stick, planks, log."""
    seen = set() if seen is None else seen
    if item not in craft.RECIPES:
        return seen
    for ing in craft.RECIPES[item][1].values():
        if ing not in seen:
            seen.add(ing)
            recipe_ingredients(ing, seen)
    if craft.RECIPES[item][0] == 3:
        seen.add("crafting_table")
        recipe_ingredients("crafting_table", seen)
    return seen


def item_matcher(word):
    """A chat word (wood, sand, coal, diamonds, torch...) -> a test on item ids."""
    if word is None:
        return lambda i: True
    if word in GATHER:
        return GATHER[word][1]
    if word in craft.INGREDIENTS:
        return craft.INGREDIENTS[word]
    w = word.rstrip("s")
    return lambda i: w in i.removeprefix("minecraft:")


class Chests:
    def __init__(self, ctx, task):
        self.ctx = ctx
        self.task = task

    def find(self, near_owner=True, radius=8):
        """The chest you mean: the nearest one by you (or by Keve), that Keve can see from
        somewhere close. Returns its position or None."""
        ctx = self.ctx
        o = ctx.owner()
        centre = o[1] if (near_owner and o) else ctx.eye_and_view()[3]
        snap = sight.Snapshot.read(ctx.senses, centre, rh=radius, rv=4)
        chests = [p for p, n in snap.blocks.items() if base(n) in CONTAINERS]
        if not chests:
            return None
        chests.sort(key=lambda p: math.dist(p, centre))
        return chests[0]

    def open(self, pos):
        """Walk up to the chest, check it's really in sight, and open it."""
        ctx = self.ctx
        x, y, z = pos
        if math.dist(ctx.eye_and_view()[3], (x + 0.5, y + 0.5, z + 0.5)) > 3.5:
            ctx.body.call(f"goto {x + 0.5:.1f} {y:.1f} {z + 0.5:.1f} --near 2.5 --timeout 20")
        eye = ctx.eye_and_view()[0]
        snap = sight.Snapshot.read(ctx.senses, pos, rh=4, rv=3)
        if not snap.block_visible(eye, pos, 5.0):
            return False
        ctx.body.call(f"look-at block {x} {y} {z}")
        r = ctx.body.call(f"interact {x} {y} {z}")
        time.sleep(0.2)
        return not r.get("error")

    def slots(self):
        m = self.ctx.body.call("menu")
        return {s["slot"]: s["stack"] for s in m.get("slots", [])}

    def take(self, match, count=None):
        """Shift-click matching stacks out of the open chest. How many items came out."""
        got = 0
        for slot, st in sorted(self.slots().items()):
            if slot < 300 or not match(st["item"]):
                continue
            if count is not None and got >= count:
                break
            self.ctx.body.call(f"click-slot {slot} shift")
            got += st["count"]
        return got

    def put(self, match, keep=()):
        """Shift-click matching stacks from Keve's inventory into the open chest."""
        moved = 0
        for slot, st in sorted(self.slots().items()):
            if slot >= 100 or not match(st["item"]):
                continue
            if any(k in st["item"] for k in keep):
                continue
            self.ctx.body.call(f"click-slot {slot} shift")
            moved += st["count"]
        return moved

    def close(self):
        self.ctx.body.call("close")


class TakeFromChest(Task):
    """'keve get the coal from the chest' / 'take 10 logs out of the chest'."""
    name = "take"

    def run(self):
        ctx = self.ctx
        word = self.args.get("item")
        count = self.args.get("count")
        ch = Chests(ctx, self)
        pos = ch.find()
        if pos is None:
            ctx.say("I don't see a chest near you.")
            return
        if not ch.open(pos):
            ctx.say("I can't get to that chest.")
            return
        try:
            got = ch.take(item_matcher(word), count)
        finally:
            ch.close()
        shown = (word or "stuff").replace("_", " ")
        ctx.say(f"took {got} {shown} from the chest." if got else f"there's no {shown} in that chest.")
        if got and self.args.get("give"):
            from skills import Give
            Give(ctx, item=word if word in GATHER else None, items=None if word in GATHER else
                 [i for i in ctx.counts() if item_matcher(word)(i)]).run_inner(self)


class PutInChest(Task):
    """'keve put your stuff in the chest' / 'put the cobblestone in the chest'."""
    name = "put"
    KEEP = ("pickaxe", "sword", "axe", "shovel", "torch", "bread", "cooked", "apple", "carrot")

    def run(self):
        ctx = self.ctx
        word = self.args.get("item")
        ch = Chests(ctx, self)
        pos = ch.find()
        if pos is None:
            ctx.say("I don't see a chest near you.")
            return
        if not ch.open(pos):
            ctx.say("I can't get to that chest.")
            return
        try:
            # "everything" still keeps its tools and food, as a player would.
            moved = ch.put(item_matcher(word), keep=() if word else self.KEEP)
        finally:
            ch.close()
        ctx.say(f"put {moved} items in the chest." if moved else "I had nothing to put in there.")


def take_for_recipe(ctx, task, item, quiet=False):
    """Before crafting `item` 'from the chest': take everything its recipe tree can use.
    quiet: a look on Keve's own initiative (missing materials), silent when there's no chest."""
    wanted = recipe_ingredients(item)
    tests = [craft.INGREDIENTS[w] for w in wanted if w in craft.INGREDIENTS]
    ch = Chests(ctx, task)
    pos = ch.find() or ch.find(near_owner=False)
    if pos is None:
        if not quiet:
            ctx.say("I don't see a chest near you, I'll find the stuff myself.")
        return False
    if quiet:
        ctx.say("hold up, checking that chest for materials first!")
    if not ch.open(pos):
        ctx.say("I can't get to that chest.")
        return False
    try:
        got = ch.take(lambda i: any(t(i) for t in tests))
    finally:
        ch.close()
    if got or not quiet:
        ctx.say(f"grabbed {got} things from the chest." if got else "nothing in that chest I can use.")
    return got > 0
