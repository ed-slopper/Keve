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
}
NUMBER_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20, "a few": 4,
                "some": 8, "a stack": 64, "a stack of": 64}

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
    item = None
    for word in re.findall(r"[a-z]+", rest):
        if word in WORDS_TO_ITEM:
            item = WORDS_TO_ITEM[word]
            break
    if item is None:
        return None
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
    for word in re.findall(r"[a-z]+", text):
        if word in WORDS_TO_ITEM:
            return {"item": WORDS_TO_ITEM[word]}
    if re.search(r"\b(everything|all|stuff|items|inventory)\b", text):
        return {"item": None}
    return None


def rule_route(text):
    if re.search(r"\b(help|commands|what can you do|what do you do)\b", text):
        return "help", {}
    g = parse_gather(text)
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
        "gather": "Collect blocks or items, like wood, dirt, sand or stone",
        "follow": "Follow the player around",
        "come": "Come to where the player is",
        "stay": "Stay in place and wait",
        "defend": "Fight hostile mobs near the player",
        "stop": "Stop what Keve is doing",
        "status": "Tell the player its health or what it is carrying",
        "give": "Hand items over to the player",
        "help": "Explain what Keve can do",
        "none": "Not a task, just talking or a question",
    }

    def __init__(self, url, model):
        self.url = url.rstrip("/") + "/v1/systemone"
        self.model = model
        self.ok = True

    def decide(self, speaker, text, name):
        if not self.ok:
            return None
        body = {
            "model": self.model,
            "state": f"Minecraft chat. {speaker} says: {text}",
            "questions": {
                "addressed": {"type": "noul",
                              "instructions": f"Is {speaker} talking to {name}, the AI companion?"},
                "task": {"type": "choice",
                         "instructions": f"Which task is {speaker} asking {name} to do?",
                         "criteria": self.TASKS},
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
        }


PERSONA = (
    "You are {name}, a player in a Minecraft survival world, playing alongside {owner}. "
    "You are a cocky, funny, loyal friend who teases {owner} but always has their back. "
    "You are not an assistant: talk like a gamer in chat, short and casual, no emojis, "
    "no markdown, one or two short sentences, under 200 characters. "
    "You can: follow, come, stay, gather wood/dirt/sand/gravel/stone, defend from mobs, "
    "and report your status. Don't claim to do anything else."
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
                                 "options": {"num_predict": 80, "temperature": 0.9, "num_ctx": 4096}},
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
    "defend": ["I got your back", "nothing's touching you", "on guard"],
    "gather": ["on it, getting {count} {item}", "{count} {item} coming up", "ok, {count} {item}"],
    "give": ["coming over", "here, catch"],
    "help": [""],
    "jump": ["there. happy?", "*jumps*"],
    "look": [""],
    "status": [""],
}

assert set(GATHER) >= set(WORDS_TO_ITEM.values())
