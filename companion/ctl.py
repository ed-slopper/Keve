"""Talking to a running Horizon game through its control socket.

On Windows the game writes {"transport":"tcp","port":N,"token":"..."} to the endpoint
file; a client connects to 127.0.0.1:N, sends `auth TOKEN`, then one command per
line and reads one JSON line back per command (horizon-client/src/control.rs).

Two kinds of access:
  Body   - what Keve may *do*. A hard whitelist: no cheats, no X-ray, no /commands.
  Senses - raw world reads (blocks, entities). Only sight.py uses these, and it filters
           them through line-of-sight ray casts before anything else sees them.
"""
import json
import socket
import threading

# Commands Keve's body may send (raw socket names; see docs/PLAN.md section 1c).
BODY_ALLOWED = {
    "state", "inventory", "events", "messages", "looking-at",
    "goto", "move", "jump", "look", "look-at", "turn", "stop",
    "break", "place", "interact", "use-item", "attack", "wait",
    "select", "drop", "open-inventory", "click-slot", "close",
    "chat", "respawn", "menu", "key",
}
# Raw sensors: X-ray if used directly, so only the sight module gets them.
SENSES_ALLOWED = {"blocks", "entities", "light"}


class CtlError(Exception):
    pass


class Connection:
    """One authenticated line connection to the game's control endpoint."""

    def __init__(self, endpoint_path, timeout=120.0):
        with open(endpoint_path, encoding="utf-8") as f:
            ep = json.load(f)
        if ep.get("transport") != "tcp":
            raise CtlError(f"unsupported endpoint transport: {ep.get('transport')}")
        self._sock = socket.create_connection(("127.0.0.1", int(ep["port"])), timeout=timeout)
        self._file = self._sock.makefile("rw", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        reply = self._raw("auth " + ep["token"])
        if not reply.get("ok"):
            raise CtlError(f"the game refused the token: {reply}")

    def _raw(self, line):
        try:
            self._file.write(line + "\n")
            self._file.flush()
            text = self._file.readline()
        except OSError as e:
            raise CtlError(f"the game closed the control connection ({e})") from e
        if not text:
            raise CtlError("the game closed the control connection")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise CtlError(f"bad reply {text[:200]!r}") from e

    def call(self, line):
        line = line.replace("\n", " ").replace("\r", " ").strip()
        with self._lock:
            return self._raw(line)

    def close(self):
        for thing in (getattr(self, "_file", None), getattr(self, "_sock", None)):
            if thing is None:
                continue
            try:
                thing.close()
            except OSError:
                pass

    def __del__(self):
        self.close()


class Body:
    """Keve's hands and feet: whitelisted commands only."""

    def __init__(self, conn):
        self._conn = conn

    def call(self, line):
        word = line.split(None, 1)[0] if line.strip() else ""
        if word not in BODY_ALLOWED:
            raise CtlError(f"refused: '{word}' is not something a fair player can do")
        if word == "chat":
            text = line[5:].strip()
            if text.startswith("/"):
                raise CtlError("refused: Keve doesn't run commands")
        return self._conn.call(line)


class Senses:
    """Raw world reads, for sight.py only."""

    def __init__(self, conn):
        self._conn = conn

    def call(self, line):
        word = line.split(None, 1)[0] if line.strip() else ""
        if word not in SENSES_ALLOWED:
            raise CtlError(f"refused: '{word}' is not a sense")
        return self._conn.call(line)
