"""Keve: an AI companion that plays Minecraft (Horizon) with you.

    python keve.py --socket PATH_TO_KEVE_ENDPOINT.json [--owner YourName]

The game must already be running headless and joined to your world (start_keve.bat
does that). Keve reads chat, works out what you want, and does it.
"""
import argparse
import random
import re
import threading
import time
import traceback

import blocks
import brain
import containers
import teach
import craft
import life
import mining
import skills
import voice as voice_mod
from ctl import Body, Connection, CtlError, Senses

# The skills from the other modules join the registry.
skills.SKILLS.update({c.name: c for c in (mining.Mine, mining.Craft, life.Companion,
                                           life.SetHome, life.GoPlace, life.Sequence,
                                           containers.TakeFromChest, containers.PutInChest,
                                           teach.Watch, teach.LightUp, teach.Replay,
                                           blocks.BreakBlocks, blocks.UseBlock, blocks.PlaceBlock,
                                           blocks.LookAround)})
DONE_CROUCH = ("give", "gather", "mine", "craft", "come", "take", "put", "sequence",
               "light_up", "replay", "watch", "break", "place_block", "hunt")

CHAT_LINE = re.compile(r"^<([^>]+)> (.*)$")


class Keve:
    def __init__(self, args):
        self.args = args
        self.name = args.name
        self.owner = args.owner
        # Three connections: one for the running action (blocks while it walks or digs),
        # one for the main loop (chat, events, stop), one for the eyes.
        self._conns = [Connection(args.socket) for _ in range(3)]
        self.act = Body(self._conns[0])
        self.ctrl = Body(self._conns[1])
        senses = Senses(self._conns[2])
        self.ctx = skills.Ctx(self.act, senses, self.say, self.owner, self.name)
        self.kev = brain.Kev(args.ollama, args.kev_model) if args.kev_model else None
        self.ctx.kev = self.kev  # companion mode asks Kev what to do
        self.talk = brain.Talker(args.ollama, args.brain_model, self.name, self.owner)
        self.talk.ctx_tokens = getattr(args, "brain_ctx", 4096)
        life.Companion.DECIDE_EVERY = float(getattr(args, "decide_s", 4))
        self.task = None
        self.task_thread = None
        self.last_said = 0.0
        self.voice = None
        ears, mouth = getattr(args, "ears", "off"), getattr(args, "mouth", "off")
        if ears != "off" or mouth != "off":
            self.voice = voice_mod.Voice(ears=ears, mouth=mouth, on_heard=self.on_voice,
                                         whisper_model=getattr(args, "whisper", "small.en"),
                                         whisper_device=getattr(args, "whisper_device", "cpu"))
            print(f"[voice] ears: {self.voice.ears_name}, voice: {self.voice.mouth_name}")

    def close(self):
        if self.voice:
            self.voice.close()
        for c in self._conns:
            c.close()

    def on_voice(self, text):
        """You said something: treat it as a chat line from you."""
        heard = voice_mod.clean_heard(text)
        if not heard:
            return
        print(f"[heard] {heard}")
        speaker = self.owner or self.args.owner
        if not speaker:
            return
        try:
            self.handle_chat(speaker, heard)
        except Exception:
            traceback.print_exc()

    # --- talking -------------------------------------------------------------------
    def say(self, text):
        text = (text or "").strip()
        if not text:
            return
        text = text.lstrip("/")[:250]
        try:
            self.ctrl.call("chat " + text)
            self.talk.note("assistant", text)
            self.last_said = time.time()
            print(f"[{self.name}] {text}")
            if self.voice and text not in skills.HELP_LINES:  # the help list is for reading
                self.voice.say(text)
        except CtlError as e:
            print(f"[say] {e}")

    def say_later(self, speaker, text):
        def go():
            situation = f"current task: {self.task.name if self.task and self.task_thread and self.task_thread.is_alive() else 'nothing'}."
            out = self.talk.reply(speaker, text, situation)
            if out:
                self.say(out)
        threading.Thread(target=go, daemon=True).start()

    # --- tasks ---------------------------------------------------------------------
    def stop_task(self):
        if self.task:
            self.task.cancelled.set()
        try:
            self.ctrl.call("stop")
        except CtlError:
            pass
        if self.task_thread and self.task_thread.is_alive()                 and self.task_thread is not threading.current_thread():
            self.task_thread.join(timeout=5)
        self.task = None

    def start_task(self, skill, args):
        self.stop_task()
        if skill == "cant":
            skill, args = "idle", {}
        if skill == "stop":
            skill, args = "idle", {}  # stop the job, but still fight back between orders
        task = skills.SKILLS[skill](self.ctx, **args)
        self.task = task

        def run():
            try:
                task.run()
            except CtlError as e:
                print(f"[task {task.name}] {e}")
                self.say(f"ugh, something broke ({e})")
            except Exception:
                traceback.print_exc()
                self.say("my brain glitched, try again")
            finished = not task.cancelled.is_set() and self.task is task
            if finished and task.name in DONE_CROUCH:
                try:
                    life.crouch(self.ctx)
                except CtlError:
                    pass
            # Between orders: stand by and fight back (unless a new order replaced this one).
            if finished and task.name not in ("follow", "stay", "idle", "defend", "companion"):
                self.start_task("idle", {})

        self.task_thread = threading.Thread(target=run, daemon=True)
        self.task_thread.start()

    # --- chat handling -------------------------------------------------------------
    def plan_steps(self, speaker, steps):
        """Several orders in one message: each step read on its own (reflexes, then Kev),
        run one after another."""
        out = []
        for st in steps:
            r = brain.reflex_route(st)
            if r is None and self.kev:
                d = self.kev.decide(speaker, "keve " + st, self.name, self.situation())
                if d:
                    r = brain.plan(d, st, self.have)
            if r is None:
                r = brain.rule_route(st)
            if r is None or r[0] in ("cant", "stop", "help"):
                continue
            out.append(r)
        if len(out) < 2:
            return out[0] if out else None
        words = {"gather": "get {count} {item}", "mine": "mine {ore}", "craft": "make {item}",
                 "come": "come back", "follow": "follow you", "give": "bring it over",
                 "go_place": "go to {name}", "take": "check the chest", "put": "fill the chest",
                 "defend": "guard you", "set_home": "remember this spot", "stay": "wait"}
        said = []
        for skill, args in out:
            shown = {k: (v.replace("_", " ") if isinstance(v, str) else v) for k, v in args.items()}
            try:
                said.append(words.get(skill, skill).format(**shown))
            except (KeyError, IndexError):
                said.append(skill)
        return "sequence", {"steps": out, "steps_text": ", then ".join(said)}

    def have(self, item_word):
        """How many of a gather word (wood, sand...) Keve carries."""
        ok = skills.GATHER.get(item_word, (None, lambda i: False))[1]
        try:
            counts = self.ctrl.call("inventory").get("counts", {}) or {}
        except CtlError:
            return 0
        return sum(n for i, n in counts.items() if ok(i))

    def situation(self):
        """A short line for Kev: what Keve carries and is doing."""
        try:
            counts = self.ctrl.call("inventory").get("counts", {}) or {}
        except CtlError:
            counts = {}
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
        carrying = ", ".join(f"{n} {k.removeprefix('minecraft:').replace('_', ' ')}"
                             for k, n in top) or "nothing"
        doing = self.task.name if self.task and self.task.name != "idle" else "nothing"
        try:  # what's in sight, so "this coal" or "that cow" mean something to Kev
            seen = blocks.notable_nearby(self.ctx, radius=8, limit=6)
        except Exception:
            seen = []
        sees = ", ".join(f"{k} ({d:.0f} blocks away)" for k, c, d in seen) or "nothing special"
        return f"Keve is carrying: {carrying}. Keve is doing: {doing}. Keve can see: {sees}."

    def addressed_by_name(self, low):
        n = self.name.lower()
        return re.search(rf"\b{re.escape(n)}\b", low) is not None or re.search(r"\bkev\b", low) is not None

    def handle_chat(self, speaker, text):
        if speaker == self.name:
            return
        if self.owner and speaker != self.owner and not self.args.anyone:
            return
        low = text.lower().strip()
        named = self.addressed_by_name(low)
        recent = time.time() - self.last_said < 20
        if self.task and self.task.name == "watch":
            recent = True  # a lesson is on: everything you say is to Keve
        # Nervous system, part 1: instant reflexes (stop, follow, come...), no model.
        route = brain.reflex_route(low) if (named or recent) else None
        watching = self.task if (self.task and self.task.name == "watch") else None
        if watching and (route is None or route[0] == "watch_done") and \
                (route or re.search(r"\b(see|seen|saw|done|got it)\b", low)):
            watching.seen_it.set()  # "ok did u see": the lesson is over
            return
        if route and route[0] == "watch_done":
            route = None  # not watching: it's just talk
        if route is None and (named or recent):
            demo = teach.find_demo(re.sub(r"^\W*(keve|kev)\b\W*", "", low))
            if demo:
                route = ("replay", {"demo": demo})
        decision = None
        if route is None and self.kev:
            # Part 2: Kev reads the message knowing what Keve carries and is doing.
            decision = self.kev.decide(speaker, text, self.name, self.situation())
            if decision:
                print(f"[kev] {decision}")
        if not (named or recent or (decision and decision["addressed"] >= 0.7)):
            return
        steps = brain.split_steps(low) if (named or recent) else []
        if len(steps) > 1:
            route = self.plan_steps(speaker, steps) or route
        if route is None and decision:
            route = brain.plan(decision, low, self.have)
            if route is None and decision["task"] not in (None, "talk"):
                route = brain.rule_route(low)  # Kev unsure: fall back to the keyword rules
        elif route is None and not self.kev:
            route = brain.rule_route(low)
            if route and route[0] == "give":  # rules alone: still check the inventory
                route = brain.plan({"task": "hand_over", "confidence": 1.0,
                                    "item": route[1].get("item")}, low, self.have)
        if self.owner is None:
            self.owner = speaker
            self.ctx.owner_name = speaker
            self.talk.owner = speaker
            print(f"[keve] owner is {speaker}")
        self.talk.note("user", f"{speaker}: {text}")
        if route is None:
            # Just talking: let the brain answer.
            if self.talk.ok:
                self.say_later(speaker, text)
            else:
                self.say(random.choice(["huh?", "say that again?", "I only know follow, come, stay, "
                                        "stop, defend, status and 'get N wood'"]))
            return
        skill, args = route
        print(f"[keve] {speaker}: {text!r} -> {skill} {args}")
        ack = random.choice(brain.ACKS.get(skill, [""]))
        if ack:
            shown = {k: (v.replace("_", " ") if isinstance(v, str) else v) for k, v in args.items()}
            if skill == "sequence":
                shown["steps"] = args.get("steps_text", "")
            try:
                self.say(ack.format(**shown) if args else ack)
            except (KeyError, IndexError):
                self.say(ack.split("{")[0].strip() or "ok")
        if skill == "sequence":
            args = {"steps": args["steps"]}
        self.start_task(skill, args)

    def run(self):
        hello = {}
        for _ in range(40):  # up to ~20 s for the join to finish
            hello = self.ctrl.call("state")
            if hello.get("player") and hello.get("screen") != "title":
                break
            time.sleep(0.5)
        if not hello.get("player") or hello.get("screen") == "title":
            print("[keve] Keve's game is not in your world: the server refused the join.")
            print("[keve] The usual cause: your world is hosted by a signed-in (online-mode)")
            print("[keve] account, and Keve joins as an offline player. Run start_server.bat to host")
            print("[keve] an offline-mode server, join it yourself at 127.0.0.1, then run")
            print("[keve] start_keve.bat 127.0.0.1:25565")
            return
        last = self.ctrl.call("events --limit 1").get("last", 0)
        self.start_task("idle", {})  # stand by and fight back until the first order
        print(f"[keve] connected; {self.name} at {hello['player'].get('position')}")
        print("[keve] say '{0} follow me', '{0} get 10 wood', '{0} defend me', '{0} stop' in chat"
              .format(self.name.lower()))
        while True:
            try:
                r = self.ctrl.call(f"events --since {last}")
            except CtlError as e:
                print(f"[keve] lost the game: {e}")
                self.close()
                return
            for ev in r.get("events", []):
                last = max(last, ev.get("seq", last))
                kind = ev.get("event")
                if kind == "chat":
                    m = CHAT_LINE.match(ev.get("text", ""))
                    if m:
                        try:
                            self.handle_chat(m.group(1), m.group(2))
                        except Exception:
                            traceback.print_exc()
                elif kind == "death":
                    self.stop_task()
                    try:
                        self.ctrl.call("respawn")
                    except CtlError:
                        pass
                    self.say("I died... ugh. respawning.")
            last = max(last, r.get("last", last))
            time.sleep(0.25)


def main():
    p = argparse.ArgumentParser(description="Keve, an AI Minecraft companion for Horizon")
    p.add_argument("--socket", required=True, help="Keve's game control endpoint (.json)")
    p.add_argument("--name", default="Keve", help="Keve's player name")
    p.add_argument("--owner", default=None, help="your player name (default: whoever talks to Keve first)")
    p.add_argument("--anyone", action="store_true", help="take orders from every player")
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--kev-model", default="hf.co/turintech/Kev-4B-Artemis-GGUF:Q4_K_M",
                   help="Kev decision model in Ollama ('' to turn off)")
    p.add_argument("--brain-model", default="huihui_ai/gemma-4-abliterated:12b",
                   help="chat model in Ollama for replies ('' to turn off)")
    args = p.parse_args()
    args.kev_model = args.kev_model or None
    args.brain_model = args.brain_model or None
    Keve(args).run()


if __name__ == "__main__":
    main()
