"""Bot players for the parkour lanes: Racer1..RacerN, each its own small offscreen client
with its own control socket, on the same server as Keve (they don't touch him)."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "companion"))
from ctl import Connection  # noqa: E402

KEVE_HOME = Path(os.environ.get("LOCALAPPDATA", "")) / "Keve"
VERSIONS = Path(os.environ.get("APPDATA", "")) / "horizon-launcher" / "versions"
NO_WINDOW = 0x08000000


def ctl_exe():
    dirs = sorted((d for d in VERSIONS.glob("*") if (d / "horizon-ctl.exe").exists()),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0] / "horizon-ctl.exe"


def sock(n):
    return KEVE_HOME / "racers" / f"Racer{n}" / "ctl.json"


def script_path(n):
    """Where Racer n's tick script goes (Horizon's HORIZON_TICK_SCRIPT: a JSON scenario there,
    then PATH.go, plays it one tick at a time, each tick's lines before that tick runs)."""
    return KEVE_HOME / "racers" / f"Racer{n}" / "script.json"


def connected(n):
    try:
        c = Connection(str(sock(n)), timeout=5)
        return "player" in c.call("state")
    except Exception:
        return False


def start(n, port=25565):
    """Racer n in the world (started if it isn't). True once it's in."""
    if connected(n):
        return True
    d = KEVE_HOME / "racers" / f"Racer{n}"
    (d / "player").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HORIZON_HOME=str(KEVE_HOME / "home"), HORIZON_TICK_SCRIPT=str(script_path(n)))
    r = subprocess.run([str(ctl_exe()), "--socket", str(sock(n)), "launch", "--offscreen",
                        "--server", f"127.0.0.1:{port}", "--name", f"Racer{n}",
                        "--player-dir", str(d / "player"),
                        "--width", "320", "--height", "180", "--render-distance", "3"],
                       env=env, capture_output=True, text=True, creationflags=NO_WINDOW)
    if '"ok":true' not in r.stdout.replace(" ", ""):
        print(f"Racer{n} didn't start: {(r.stdout + r.stderr).strip()[:300]}")
        return False
    for _ in range(90):
        if connected(n):
            return True
        time.sleep(1)
    return False


def quit(n):
    try:
        Connection(str(sock(n)), timeout=5).call("quit")
    except Exception:
        pass


if __name__ == "__main__":
    for n in range(1, int(sys.argv[1] if len(sys.argv) > 1 else 1) + 1):
        print(f"Racer{n}:", "in" if start(n) else "failed")
