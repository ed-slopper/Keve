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

import brain
import skills
from ctl import Body, Connection, CtlError, Senses

CHAT_LINE = re.compile(r"^<([^>]+)> (.*)$")


class Keve:
    def __init__(self, args):
        self.args = args
        self.name = args.name
        self.owner = args.owner
        # Three connections: one for the running action (blocks while it walks or digs),
        # one for the main loop (chat, events, stop), one for the eyes.
        self.act = Body(Connection(args.socket))
        self.ctrl = Body(Connection(args.socket))
        senses = Senses(Connection(args.socket))
        self.ctx = skills.Ctx(self.act, senses, self.say, self.owner, self.name)
        self.kev = brain.Kev(args.ollama, args.kev_model) if args.kev_model else None
        self.talk = brain.Talker(args.ollama, args.brain_model, self.name, self.owner)
        self.task = None
        self.task_thread = None
        self.last_said = 0.0

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
        if self.task_thread and self.task_thread.is_alive():
            self.task_thread.join(timeout=5)
        self.task = None

    def start_task(self, skill, args):
        self.stop_task()
        if skill == "stop":
            return
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

        self.task_thread = threading.Thread(target=run, daemon=True)
        self.task_thread.start()

    # --- chat handling -------------------------------------------------------------
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
        route = brain.rule_route(low) if (named or recent) else None
        decision = None
        if route is None and self.kev:
            decision = self.kev.decide(speaker, text, self.name)
            if decision:
                print(f"[kev] {decision}")
        if not (named or recent or (decision and decision["addressed"] >= 0.7)):
            return
        if self.owner is None:
            self.owner = speaker
            self.ctx.owner_name = speaker
            self.talk.owner = speaker
            print(f"[keve] owner is {speaker}")
        self.talk.note("user", f"{speaker}: {text}")
        if route is None and decision and decision["task"] not in (None, "none") \
                and decision["confidence"] >= 0.45:
            skill = decision["task"]
            args = {}
            if skill == "gather":
                args = brain.parse_gather("get " + low) or {"item": "wood", "count": 10}
            route = (skill, args)
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
            self.say(ack.format(**args) if args else ack)
        self.start_task(skill, args)

    def run(self):
        last = self.ctrl.call("events --limit 1").get("last", 0)
        hello = self.ctrl.call("state")
        print(f"[keve] connected; {self.name} at {hello.get('player', {}).get('position')}")
        print("[keve] say '{0} follow me', '{0} get 10 wood', '{0} defend me', '{0} stop' in chat"
              .format(self.name.lower()))
        while True:
            try:
                r = self.ctrl.call(f"events --since {last}")
            except CtlError as e:
                print(f"[keve] lost the game: {e}")
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
