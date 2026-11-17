"""The translator: a local LLM (Gemma in Ollama) turns what you say, however you say it,
into Keve's own command wording, which the tested rules then carry out.

    "Kev, can you plan a sapling?"            -> ["keve plant a sapling"]
    "yo chuck me some logs would ya"          -> ["keve give me 10 wood"]
    "grab wood, make a table, then find me"   -> ["keve get 10 wood", "keve make a crafting table", "keve come here"]
    "haha you're so dumb"                     -> chat (Gemma answers in character)

It also fixes voice mishearings ("plan" -> "plant", "Kevin" -> "keve") and resolves
"that" / "those" from what Keve carries and can see. Structured output (a JSON schema)
means the model can only answer in the expected shape.
"""
import json
import re
import urllib.error
import urllib.request

COMMANDS = """\
keve follow me | keve come here | keve stay | keve stop | keve jump | keve look at me
keve get 10 wood | keve chop trees until i say stop | keve get 5 dirt | keve get 8 sand | keve get some gravel | keve get 20 stone | keve get sugar cane | keve get 3 pumpkins | keve get clay
keve get 10 wood and bring it to me | keve bring me the sand (hand over what it has) | keve give me everything | keve give me a stone pickaxe | keve give me 16 torches
keve mine for diamonds | keve mine 10 iron | keve mine some coal | keve go mining
keve mine this coal | keve break that glass | keve dig this dirt | keve chop that birch log | keve get me 10 andesite
keve open that door | keve pull the lever | keve press the button
keve place a crafting table | keve place a furnace | keve plant a sapling | keve plant 3 oak saplings | keve plant the seeds
keve make a stone pickaxe | keve make a stone sword | keve make a stone hoe | keve make an iron axe | keve craft 16 torches | keve make a furnace | keve make a crafting table
keve craft torches from the chest | keve make a stone pickaxe from the chest | keve get the coal from the chest | keve put your stuff in the chest | keve put the stone pickaxe in the chest | keve give me the stone pickaxe
keve kill this cow | keve kill 3 pigs | keve kill the zombies | keve get me some leather | keve defend me
keve dig out this room bigger | keve dig out this room 3 more | keve replace the floor with cobblestone | keve replace the floor with oak planks | keve replace the wall with cobblestone | keve replace the walls with stone bricks | keve dig me out |
keve place torches in this room | keve what do you see | keve what you got | keve help
keve this is home | keve go home | keve remember this as the mine | keve go to the mine
keve play with me | keve watch me <do something> | keve did you see | keve copy what i did"""

PROMPT = """You translate what a Minecraft player says to their AI companion Keve into Keve's commands.

Keve's commands (use exactly this wording, change only numbers and item or block names):
{commands}

Rules:
- Speech-to-text mishears: "plan" may be "plant", "Kev"/"Kevin"/"Diva"/"keep" may be "keve", "would"/"wood".
- Several things in a row become several commands, in order.
- "that"/"those"/"it" refer to what Keve carries or sees (given below), or what the player just mentioned.
- No number given: use the command's usual number (10 wood, 1 item).
- If it isn't an order to Keve (chatting, joking, questions about Keve, talking to someone else), commands is [] and chat is true.
- Teasing, insults, compliments, jokes, greetings and questions like "how are you" are chat, not commands.
- Never repeat a task: one command per thing to do. "and bring it/them to me" stays on the same command.
- Making/crafting something "from the chest" / "with the stuff in the chest" is ONE command: "keve make <item> from the chest". Never split it into a make and a chest command.
- Misspelled item names mean that item: "picaxe"/"pickax"/"pic" = pickaxe, "cobble" = cobblestone.
- Making a room/space bigger, digging or mining it out "here" is "keve dig out this room bigger", NOT mining for ores or diamonds.
- The player stuck, trapped or asking to be mined/dug out is "keve dig me out" (nothing else, no diamonds).
- "faster", "hurry", "come on", "good job" are chat, never a new command.
- "ok", "okay", "nice", "thanks", "cool" on their own are chat, never "come here".
- Keep the player's material: "stone sword" is "keve make a stone sword", never iron or wooden.
- Keep the exact item the player names: "put the X in the chest" is never "put your stuff in the chest". "your stuff" is only for everything.
- Doing something "until I say", "forever", "nonstop" keeps those words: "keve chop trees until i say stop".
- "them"/"those" with give/put means the things Keve just made, one command each; "give me everything" only when the player says everything/all.
- "it"/"that" with give/put means what Keve just made or got (given in "Right now").
- Never output placeholders like [item] or <item>. If you don't know the item, use the closest real one or leave it out.
- addressed: is the player talking to Keve (true) or to someone else / themselves (false)?

Examples:
"kev can you plan a sapling" -> {{"addressed": true, "commands": ["keve plant a sapling"], "chat": false}}
"yo chuck me some logs" -> {{"addressed": true, "commands": ["keve get 10 wood and bring it to me"], "chat": false}}
"go find me diamonds then bring them back" -> {{"addressed": true, "commands": ["keve mine for diamonds and bring them to me"], "chat": false}}
"grab wood, make a table, then come find me" -> {{"addressed": true, "commands": ["keve get 10 wood", "keve make a crafting table", "keve come here"], "chat": false}}
"keve craft me a stone picaxe from the material in the chest" -> {{"addressed": true, "commands": ["keve make a stone pickaxe from the chest"], "chat": false}}
"check the chest, it has what you need to make the pickaxe" -> {{"addressed": true, "commands": ["keve make a stone pickaxe from the chest"], "chat": false}}
"can u mine out a bigger room in here" -> {{"addressed": true, "commands": ["keve dig out this room bigger"], "chat": false}}
"help me dig this room out, at my y level not down" -> {{"addressed": true, "commands": ["keve dig out this room bigger"], "chat": false}}
"keve replace the floor with cobble its in the chest" -> {{"addressed": true, "commands": ["keve replace the floor with cobblestone"], "chat": false}}
"keve replace the wall im standing in front of with cobble" -> {{"addressed": true, "commands": ["keve replace the wall with cobblestone"], "chat": false}}
"keve redo all the walls in here with cobble" -> {{"addressed": true, "commands": ["keve replace the walls with cobblestone"], "chat": false}}
"keve can u mine a hole for me to get out of the wall i dont have a pic" -> {{"addressed": true, "commands": ["keve dig me out"], "chat": false}}
"keve stop im stuck, mine a hole in the wall to save me" -> {{"addressed": true, "commands": ["keve dig me out"], "chat": false}}
"can u put the stone pic in the chest" -> {{"addressed": true, "commands": ["keve put the stone pickaxe in the chest"], "chat": false}}
"give it to me" (Keve just made a stone pickaxe) -> {{"addressed": true, "commands": ["keve give me the stone pickaxe"], "chat": false}}
"make me stone sword" -> {{"addressed": true, "commands": ["keve make a stone sword"], "chat": false}}
"make all the stone tools and put them in the chest" -> {{"addressed": true, "commands": ["keve make a stone pickaxe", "keve make a stone axe", "keve make a stone shovel", "keve make a stone hoe", "keve make a stone sword", "keve put the stone tools in the chest"], "chat": false}}
"keve mine trees until i say" -> {{"addressed": true, "commands": ["keve chop trees until i say stop"], "chat": false}}
"give them to me" (Keve just made a stone sword, axe and hoe) -> {{"addressed": true, "commands": ["keve give me the stone sword", "keve give me the stone axe", "keve give me the stone hoe"], "chat": false}}
"faster keve" -> {{"addressed": true, "commands": [], "chat": true}}
"ok keve" -> {{"addressed": true, "commands": [], "chat": true}}
"haha keve you're so dumb" -> {{"addressed": true, "commands": [], "chat": true}}
"brb gotta get food" -> {{"addressed": false, "commands": [], "chat": true}}

Right now: {situation}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "addressed": {"type": "boolean"},
        "commands": {"type": "array", "items": {"type": "string"}},
        "chat": {"type": "boolean"},
    },
    "required": ["addressed", "commands", "chat"],
}


class Translator:
    def __init__(self, url, model):
        self.url = url.rstrip("/") + "/api/chat"
        self.model = model
        self.ok = model is not None

    def translate(self, speaker, text, situation=""):
        """{'addressed': bool, 'commands': [...], 'chat': bool}, or None when unavailable."""
        if not self.ok:
            return None
        body = {
            "model": self.model, "stream": False, "keep_alive": "30m", "think": False,
            "format": SCHEMA,
            "options": {"temperature": 0, "num_predict": 160, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": PROMPT.format(commands=COMMANDS, situation=situation or "-")},
                {"role": "user", "content": f"{speaker} says: {text}"},
            ],
        }
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                out = json.loads(json.loads(r.read().decode("utf-8"))["message"]["content"])
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print(f"[translate] unavailable ({e})")
            return None
        cmds = []
        for c in out.get("commands") or []:
            c = re.sub(r"\s+", " ", str(c).lower().strip(" .!?"))
            if not c or re.search(r"[\[<{]", c):  # a placeholder like "[item]" is no order
                continue
            if not c.startswith("keve"):
                c = "keve " + c
            cmds.append(c)
        return {"addressed": bool(out.get("addressed")), "commands": cmds[:8],
                "chat": bool(out.get("chat")) and not cmds}
