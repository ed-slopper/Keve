"""Understanding chat: instant rules first, then Kev (fast decision model), then Gemma (talk).

Rules handle the obvious orders with no model call. Kev picks the task when the wording
is unusual (about 0.1 s). Gemma only writes chat replies with personality; it never
steers the body.
"""
import json
import re
import urllib.error
import urllib.request

from skills import GATHER

WORDS_TO_ITEM = {
    "wood": "wood", "log": "wood", "logs": "wood", "tree": "wood", "trees": "wood", "timber": "wood",
    "dirt": "dirt", "sand": "sand", "gravel": "gravel",
    "stone": "stone", "cobble": "stone", "cobblestone": "stone", "rock": "stone", "rocks": "stone",
    "sugar cane": "sugar_cane", "sugarcane": "sugar_cane", "cane": "sugar_cane", "canes": "sugar_cane",
    "pumpkin": "pumpkin", "pumpkins": "pumpkin", "clay": "clay",
}
CAN_GET = "wood, dirt, sand, gravel, stone, sugar cane, pumpkins and clay"
GATHER_WORDS = {"wood", "dirt", "sand", "gravel", "stone", "sugar_cane", "pumpkin", "clay"}
FILLER = {"me", "some", "the", "a", "an", "of", "for", "and", "please", "more", "them", "it", "to",
          "go", "you", "can", "could", "up", "few", "lot", "lots", "bunch", "us", "my", "your"}


def find_item(text):
    """The first known item word in `text` (two-word names like 'sugar cane' first)."""
    words = re.findall(r"[a-z]+", text)
    for a, b in zip(words, words[1:]):
        if f"{a} {b}" in WORDS_TO_ITEM:
            return WORDS_TO_ITEM[f"{a} {b}"]
    for w in words:
        if w in WORDS_TO_ITEM:
            return WORDS_TO_ITEM[w]
    return None
NUMBER_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
                "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "twenty": 20,
                "thirty": 30, "thirty two": 32, "forty": 40, "fifty": 50, "sixty four": 64,
                "a few": 4, "some": 8, "a stack": 64, "a stack of": 64}

RULES = [
    (r"\b(stop|cancel|halt|nevermind|never mind|freeze)\b", "stop"),
    (r"\b(follow|come with|let'?s go|stick with|tag along)\b", "follow"),
    (r"\b(come( here| over| back)?|over here|get over here|to me)\b", "come"),
    (r"\b(stay|wait( here)?|stand (still|here)|hold (on|up|position))\b", "stay"),
    (r"\b(defend|protect|guard|fight|kill (the )?(mobs|monsters|zombies|them))\b", "defend"),
    (r"\b(jump)\b", "jump"),
    (r"\blook at me\b", "look"),
    (r"\b(status|inventory|what (do )?(you|u) (got|have)|how are you doing|hp|health)\b", "status"),
]


def parse_gather(text):
    """'get me 10 wood' -> {'item': 'wood', 'count': 10}; None when it isn't a gather order."""
    m = re.search(r"\b(get|collect|gather|grab|mine|chop|bring|fetch|dig)\b(.*)", text)
    if not m:
        return None
    rest = m.group(2)
    item = find_item(rest)
    if item is None:
        # A gather order for something Keve can't get: say so instead of guessing.
        words = [w for w in re.findall(r"[a-z]+", rest) if w not in FILLER and not w.isdigit()]
        words = [w for w in words if w not in NUMBER_WORDS]
        return {"unknown": " ".join(words[:3]) or "that"}
    count = 10
    n = re.search(r"\b(\d{1,3})\b", rest)
    if n:
        count = max(1, min(256, int(n.group(1))))
    else:
        for w, v in sorted(NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{w}\b", rest):
                count = v
                break
    return {"item": item, "count": count}


GIVE_BACK = re.compile(r"\b(bring|give|drop|hand|toss|throw)\b.*\b(me|to me|them|it)\b|\bbring me\b")


def parse_give(text):
    """'give me your sand' / 'give me everything' -> {'item': 'sand' | None}."""
    if not re.search(r"\b(give|drop|hand|toss|throw)\b.*\b(me|over)\b", text):
        return None
    item = find_item(text)
    if item:
        return {"item": item}
    if re.search(r"\b(everything|all|stuff|items|inventory)\b", text):
        return {"item": None, "everything": True}
    return None


# "bring me the sand" / "give me those logs" / "bring them": hand over what it already has.
HAND_OVER = re.compile(r"\b(bring|give|hand|drop|toss)\b.*\b(the|your|that|those|them|it|what you)\b")
NEW_AMOUNT = re.compile(r"\b\d+\b|\b(some|more|a few|a stack|a bunch|a lot)\b")


def rule_route(text):
    if re.search(r"\b(help|commands|what can you do|what do you do)\b", text):
        return "help", {}
    has_gather_verb = re.search(r"\b(get|collect|gather|grab|mine|chop|fetch|dig)\b", text)
    if HAND_OVER.search(text) and not NEW_AMOUNT.search(text) and not has_gather_verb:
        return "give", {"item": find_item(text),
                        "everything": bool(re.search(r"\b(everything|all)\b", text))}
    ore = find_ore(text)
    if ore and re.search(r"\b(mine|get|find|dig|look for|go for|bring)\b", text):
        return "mine", {"ore": ore, "count": parse_count(text) or (3 if ore == "diamond" else 8),
                        "give": bool(GIVE_BACK.search(text))}
    craftable = find_craftable(text)
    if craftable and re.search(r"\b(make|craft|build)\b", text):
        return "craft", {"item": craftable, "count": parse_count(text) or 1,
                         "give": bool(GIVE_BACK.search(text))}
    g = parse_gather(text)
    if g and "unknown" in g:
        return "cant", g
    if g:
        if GIVE_BACK.search(text) or re.search(r"\bbring\b", text):
            g["give"] = True
        return "gather", g
    g = parse_give(text)
    if g:
        return "give", g
    for pattern, skill in RULES:
        if re.search(pattern, text):
            return skill, {}
    return None


def _post(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Kev:
    """The nervous system: Kev-4B through Ollama's /v1/systemone."""

    TASKS = {
        "get_and_bring": "Get or mine items and then bring or give them to the player",
        "get": "Go get, mine, chop or collect items (and keep them)",
        "hand_over": "Give the player items that Keve is already carrying",
        "follow": "Follow the player around",
        "come": "Come to where the player is",
        "stay": "Stay in place and wait",
        "defend": "Fight or kill hostile mobs, protect the player",
        "stop": "Stop what Keve is doing",
        "status": "Tell the player its health or what it is carrying",
        "help": "Explain what Keve can do",
        "mine": "Go mining underground for ores: diamonds, iron, coal, gold, redstone, lapis",
        "craft": "Craft or make an item: a pickaxe, sword, axe, torches, crafting table, furnace",
        "companion": "Play or explore alongside the player on its own, deciding what to do",
        "talk": "Not an order: chatting, joking or asking a question",
    }
    ITEMS = {
        "wood": "Wood, logs or trees", "dirt": "Dirt or grass", "sand": "Sand",
        "gravel": "Gravel or flint", "stone": "Stone or cobblestone",
        "sugar_cane": "Sugar cane", "pumpkin": "Pumpkins", "clay": "Clay",
        "everything": "Everything Keve is carrying",
        "other": "Some other item or block", "none": "No item is mentioned",
    }

    def __init__(self, url, model):
        self.url = url.rstrip("/") + "/v1/systemone"
        self.model = model
        self.ok = True

    def choose(self, state, question, criteria):
        """One quick choice between options (companion mode's 'what now?')."""
        if not self.ok:
            return None
        try:
            r = _post(self.url, {"model": self.model, "state": state, "questions": {
                "q": {"type": "choice", "instructions": question, "criteria": criteria}}}, timeout=15)
        except (urllib.error.URLError, OSError, ValueError):
            return None
        return r.get("answers", {}).get("q", {}).get("choice")

    def decide(self, speaker, text, name, situation=""):
        """What the player wants: {'addressed', 'task', 'confidence', 'item', 'item_confidence'}."""
        if not self.ok:
            return None
        body = {
            "model": self.model,
            "state": (f"Minecraft. {name} is an AI companion player. {situation}\n"
                      f"{speaker} says in chat: {text}"),
            "questions": {
                "addressed": {"type": "noul",
                              "instructions": f"Is {speaker} talking to {name}?"},
                "task": {"type": "choice",
                         "instructions": f"What does {speaker} want {name} to do?",
                         "criteria": self.TASKS},
                "item": {"type": "choice",
                         "instructions": f"Which item is {speaker} talking about?",
                         "criteria": self.ITEMS},
            },
        }
        try:
            r = _post(self.url, body, timeout=30)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[kev] unavailable ({e}); using rules only")
            self.ok = False
            return None
        a = r.get("answers", {})
        return {
            "addressed": a.get("addressed", {}).get("noul", 0.0),
            "task": a.get("task", {}).get("choice"),
            "confidence": a.get("task", {}).get("confidence", 0.0),
            "item": a.get("item", {}).get("choice"),
            "item_confidence": a.get("item", {}).get("confidence", 0.0),
        }


# Orders the nervous system answers instantly, with no model call (stop must never wait).
REFLEX_RULES = [
    (r"\b(stop|cancel|halt|nevermind|never mind|freeze)\b", "stop"),
    (r"\b(help|commands|what can you do)\b", "help"),
    (r"^\W*(keve|kev)?\W*(follow( me)?|let'?s go)\W*$", "follow"),
    (r"^\W*(keve|kev)?\W*(come( here| over| back)?|over here|get over here)\W*$", "come"),
    (r"^\W*(keve|kev)?\W*(stay|wait( here)?|stand still|hold up)\W*$", "stay"),
    (r"^\W*(keve|kev)?\W*(jump)\W*$", "jump"),
    (r"^\W*(keve|kev)?\W*(look at me)\W*$", "look"),
    (r"\b(this is (my |our )?home|set (the |my |our )?home|remember (this|here) as home)\b", "set_home"),
    (r"\bremember (this|here)( place)? as (the |my |our )?([a-z ]+)$", "set_place"),
    (r"\b(go|head|walk|run) (back )?home\b|\bgo back to (the )?base\b", "go_home"),
    (r"\b(go|head|walk|take me) (back )?to (the |my |our )?([a-z ]+)$", "go_place"),
    (r"\b(play with me|be my (buddy|companion|partner|friend)|do your own thing|explore with me|"
     r"play on your own|free ?roam|companion mode)\b", "companion"),
]


def reflex_route(text):
    for pattern, skill in REFLEX_RULES:
        m = re.search(pattern, text)
        if not m:
            continue
        if skill == "set_place":
            return "set_home", {"name": m.group(4).strip()}
        if skill == "set_home":
            return "set_home", {"name": "home"}
        if skill == "go_home":
            return "go_place", {"name": "home"}
        if skill == "go_place":
            return "go_place", {"name": m.group(4).strip()}
        return skill, {}
    return None


ORE_WORDS = {"diamond": "diamond", "diamonds": "diamond", "iron": "iron", "coal": "coal",
             "gold": "gold", "redstone": "redstone", "lapis": "lapis", "copper": "copper",
             "emerald": "emerald", "emeralds": "emerald"}


def find_ore(text):
    for w in re.findall(r"[a-z]+", text):
        if w in ORE_WORDS:
            return ORE_WORDS[w]
    return None


def find_craftable(text):
    """'make me a stone pickaxe' -> 'stone_pickaxe'; '16 torches' -> 'torch'."""
    t = " " + text + " "
    mat = None
    for m, w in (("wooden", r"\bwood(en)?\b"), ("stone", r"\bstone\b|\bcobble"), ("iron", r"\biron\b")):
        if re.search(w, t):
            mat = m
            break
    for tool in ("pickaxe", "sword", "axe", "shovel"):
        if re.search(rf"\b{tool}s?\b", t) or (tool == "pickaxe" and re.search(r"\bpicks?\b", t)):
            return f"{mat or 'stone'}_{tool}"
    for word, item in (("torch", "torch"), ("crafting table", "crafting_table"),
                       ("workbench", "crafting_table"), ("table", "crafting_table"),
                       ("furnace", "furnace"), ("stick", "stick"), ("plank", "planks")):
        if word in t:
            return item
    return None


def parse_count(text):
    n = re.search(r"\b(\d{1,3})\b", text)
    if n:
        return max(1, min(256, int(n.group(1))))
    for w, v in sorted(NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        if w not in ("a",) and re.search(rf"\b{w}\b", text):
            return v
    return None


def plan(decision, text, have):
    """Turn Kev's reading of a message into a skill, checked against what Keve carries.

    `have(item_word)` -> how many Keve has. Returns (skill, args) or None (just talk)."""
    task = decision["task"]
    # Kev's confidence runs low even when its pick is right (0.2-0.3 on clear orders),
    # so its top pick is trusted unless it is "talk" or barely above chance.
    if task in (None, "talk") or decision["confidence"] < 0.1:
        return None
    if task in ("follow", "come", "stay", "defend", "stop", "status", "help", "companion"):
        return task, {}
    ore = find_ore(text)
    craftable = find_craftable(text)
    count = parse_count(text)
    give = bool(GIVE_BACK.search(text)) or task == "get_and_bring"
    if task == "craft" or (craftable and re.search(r"\b(make|craft|build)\b", text)):
        if craftable:
            return "craft", {"item": craftable, "count": count or 1, "give": give}
        return "cant", {"unknown": find_unknown(text) or "that"}
    if task == "mine" or (ore and task in ("get", "get_and_bring", "hand_over")):
        if ore:
            return "mine", {"ore": ore, "count": count or (3 if ore == "diamond" else 8), "give": give}
        if re.search(r"\b(ores?|deep|underground|caves?|mining)\b", text):
            return "mine", {"ore": "iron", "count": count or 8, "give": give}
    # Item: an exact word in the message wins; else Kev's pick.
    item = find_item(text)
    if item is None and decision.get("item") in GATHER_WORDS:
        item = decision["item"]
    everything = decision.get("item") == "everything" or re.search(r"\b(everything|all your)\b", text)
    if task == "hand_over":
        if everything and item is None:
            return "give", {"item": None, "everything": True}
        if item is None:
            return "give", {"item": None}
        n = have(item)
        if n == 0 or (count and n < count):
            # It doesn't have them (or not enough): get the rest first, then bring them.
            return "gather", {"item": item, "count": (count or 10) - n, "give": True}
        return "give", {"item": item}
    # get / get_and_bring
    if item is None:
        if decision.get("item") == "other" or find_unknown(text):
            return "cant", {"unknown": find_unknown(text) or "that"}
        return "cant", {"unknown": "that"}
    return "gather", {"item": item, "count": count or 10, "give": give}


def find_unknown(text):
    m = re.search(r"\b(get|collect|gather|grab|mine|chop|bring|fetch|dig|give)\b(.*)", text)
    if not m:
        return None
    words = [w for w in re.findall(r"[a-z]+", m.group(2))
             if w not in FILLER and w not in NUMBER_WORDS and w not in ("keve", "kev")]
    return " ".join(words[:3]) or None


PERSONA = (
    "You are {name}, a player in a Minecraft survival world, playing alongside {owner}. "
    "You are a cocky, funny, loyal friend who teases {owner} but always has their back. "
    "You are not an assistant: talk like a gamer in chat, short and casual, no emojis, "
    "no markdown, one or two short sentences, under 200 characters. "
    "You can: follow, come, stay, gather wood/dirt/sand/gravel/stone/sugar cane, mine for ores "
    "(coal, iron, gold, diamonds...), craft tools and torches, smelt iron, defend from mobs, "
    "remember places like home, and play alongside them on your own. Don't claim to do anything else."
)


class Talker:
    """The brain's mouth: Gemma through Ollama's /api/chat."""

    def __init__(self, url, model, name, owner):
        self.url = url.rstrip("/") + "/api/chat"
        self.model = model
        self.name = name
        self.owner = owner
        self.history = []  # recent (role, text)
        self.ok = model is not None

    def note(self, role, text):
        self.history.append((role, text))
        self.history = self.history[-12:]

    def reply(self, speaker, text, situation):
        if not self.ok:
            return None
        msgs = [{"role": "system", "content": PERSONA.format(name=self.name, owner=self.owner or speaker)
                 + " Right now: " + situation}]
        for role, t in self.history:
            msgs.append({"role": role, "content": t})
        msgs.append({"role": "user", "content": f"{speaker}: {text}"})
        try:
            r = _post(self.url, {"model": self.model, "messages": msgs, "stream": False,
                                 "keep_alive": "30m", "think": False,
                                 "options": {"num_predict": 80, "temperature": 0.9, "num_ctx": getattr(self, "ctx_tokens", 4096)}},
                      timeout=90)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[talk] unavailable ({e})")
            return None
        out = (r.get("message", {}) or {}).get("content", "").strip()
        out = re.sub(r"<[^>]+>", "", out)          # stray tags
        out = out.replace("\n", " ").strip().strip('"')
        if out.lower().startswith(self.name.lower() + ":"):
            out = out[len(self.name) + 1:].strip()
        return out[:220] or None


ACKS = {
    "come": ["omw", "coming", "on my way"],
    "follow": ["right behind you", "lead the way", "following"],
    "stay": ["ok, staying here", "I'll wait here", "not moving"],
    "stop": ["ok ok, stopping", "stopped", "fine"],
    "defend": ["I got your back", "on guard, nothing gets near you", "watching your back"],
    "gather": ["on it, getting {count} {item}", "{count} {item} coming up", "ok, {count} {item}"],
    "give": ["coming over", "here, catch"],
    "help": [""],
    "mine": ["going mining for {ore}", "{ore}, here I come", "ok, digging for {ore}"],
    "craft": ["making {item}", "one {item} coming up", "crafting {item}"],
    "companion": ["let's go, I'll do my own thing and keep up", "alright, partners", "lead on, I've got ideas too"],
    "set_home": ["got it, {name} is here", "remembered {name}"],
    "go_place": ["heading to {name}", "going to {name}"],
    "cant": ["I can't get {unknown} yet. I can do " + CAN_GET + "."],
    "jump": ["there. happy?", "*jumps*"],
    "look": [""],
    "status": [""],
}

assert set(GATHER) >= set(WORDS_TO_ITEM.values())
