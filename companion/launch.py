"""One click: Ollama, the offline server, your Horizon, Keve's headless game, Keve's brain.

    python launch.py [--owner NAME] [--no-game] [--no-llm] [--port 25565]

Run through Keve.bat. Each step is skipped when it's already done (the server already
up, the models already pulled, Keve's game already in the world).
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

APPDATA = Path(os.environ.get("APPDATA", ""))
LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
KEVE_HOME = Path(os.environ["KEVE_HOME"]) if os.environ.get("KEVE_HOME") else LOCAL / "Keve"
SERVER_DIR = KEVE_HOME / "server"
SOCK = KEVE_HOME / "keve-ctl.json"
LAUNCHER = LOCAL / "Programs" / "Horizon Launcher" / "horizon-launcher.exe"
SAVES = APPDATA / "horizon" / "saves"
OLLAMA = "http://127.0.0.1:11434"
KEV_MODEL = "hf.co/turintech/Kev-4B-Artemis-GGUF:Q4_K_M"
BRAIN_MODEL = "huihui_ai/gemma-4-abliterated:12b"
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def step(text):
    print(f"\n== {text}")


def fail(text):
    print(f"\n!! {text}")
    sys.exit(1)


def ask(question, default="y"):
    try:
        a = input(f"{question} [{'Y/n' if default == 'y' else 'y/N'}] ").strip().lower()
    except EOFError:
        a = ""
    return (a or default).startswith("y")


def port_open(port, host="127.0.0.1"):
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def wait_for(cond, seconds, what):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(1)
    fail(f"{what} did not come up within {seconds} s")


def horizon_tools():
    versions = APPDATA / "horizon-launcher" / "versions"
    dirs = sorted((d for d in versions.glob("*") if (d / "horizon-ctl.exe").exists()),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    if not dirs:
        fail("Horizon isn't installed. Get it from https://playhorizon.dev/download and play once.")
    return dirs[0] / "horizon-ctl.exe", dirs[0] / "horizon-server.exe"


# --- your name ------------------------------------------------------------------------
def owner_name(args):
    if args.owner:
        return args.owner
    saved = KEVE_HOME / "owner.txt"
    if LAUNCHER.exists():
        try:
            out = subprocess.run([str(LAUNCHER), "account", "list", "--json"], capture_output=True,
                                 text=True, timeout=30, creationflags=NO_WINDOW).stdout
            for a in json.loads(out).get("accounts", []):
                if a.get("selected"):
                    return a["name"]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if saved.exists():
        return saved.read_text(encoding="utf-8").strip()
    name = input("Your Minecraft player name: ").strip()
    saved.write_text(name, encoding="utf-8")
    return name


# --- Ollama -----------------------------------------------------------------------------
def ollama_models():
    with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3) as r:
        return {m["name"] for m in json.loads(r.read()).get("models", [])}


def ensure_ollama(args):
    """Returns (kev_model or '', brain_model or '')."""
    if args.no_llm:
        return "", ""
    exe = shutil.which("ollama")
    if not exe:
        print("Ollama isn't installed (https://ollama.com): Keve will follow plain orders only.")
        return "", ""
    try:
        have = ollama_models()
    except OSError:
        print("Starting Ollama...")
        subprocess.Popen([exe, "serve"], creationflags=NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(lambda: _try(ollama_models), 30, "Ollama")
        have = ollama_models()
    out = []
    for model, size, use in ((KEV_MODEL, "2.5 GB", "understanding orders"),
                             (BRAIN_MODEL, "7.6 GB", "chatting")):
        if model in have:
            out.append(model)
        elif ask(f"Download {model} ({size}, for {use})?"):
            subprocess.run([exe, "pull", model])
            out.append(model)
        else:
            out.append("")
    return out[0], out[1]


def _try(f):
    try:
        f()
        return True
    except OSError:
        return False


# --- the server -------------------------------------------------------------------------
def ensure_server(srv, port):
    if port_open(port):
        print(f"A server is already up on port {port}.")
        return None
    if not (SERVER_DIR / "server.toml").exists():
        step("First run: setting up an offline-mode Horizon server for you and Keve")
        print("Horizon asks you to accept Minecraft's EULA (https://aka.ms/MinecraftEULA).")
        SERVER_DIR.mkdir(parents=True, exist_ok=True)
        seed = ["--seed", SEED_FOR_INIT[0]] if SEED_FOR_INIT[0] else []
        r = subprocess.run([str(srv), "--dir", str(SERVER_DIR), "init", "--world", "world",
                            "--port", str(port), "--no-whitelist", "--offline", *seed])
        if r.returncode != 0 or not (SERVER_DIR / "server.toml").exists():
            fail("the server setup didn't finish")
        if not SEED_FOR_INIT[0]:
            pick_world()
    step(f"Starting the server (its own window) on port {port}")
    proc = subprocess.Popen([str(srv), "--dir", str(SERVER_DIR), "run"], creationflags=NEW_CONSOLE)
    wait_for(lambda: port_open(port), 180, "the server")
    return proc


def pick_world():
    worlds = sorted((d for d in SAVES.glob("*") if (d / "level.dat").exists()),
                    key=lambda d: d.stat().st_mtime, reverse=True) if SAVES.exists() else []
    if not worlds:
        return
    print("\nPlay one of your worlds with Keve? (it's copied; the original isn't touched)")
    print("  0) a new world")
    for i, w in enumerate(worlds[:9], 1):
        print(f"  {i}) {w.name}")
    try:
        choice = int(input("Number: ").strip() or "0")
    except (ValueError, EOFError):
        choice = 0
    if 1 <= choice <= min(9, len(worlds)):
        dest = SERVER_DIR / "world"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(worlds[choice - 1], dest, ignore=shutil.ignore_patterns("session.lock"))
        print(f"Copied {worlds[choice - 1].name}.")


def new_world(srv, port, seed):
    """Swap the server's world for a fresh one; the old one is moved aside, not deleted."""
    toml = SERVER_DIR / "server.toml"
    if not toml.exists():
        print("The server isn't set up yet; it's set up first, with this seed.")
    step(f"New world{' with seed ' + seed if seed else ' (random seed)'}")
    if port_open(port):
        print("Stopping the server (it saves the world first)...")
        subprocess.run([str(srv), "--dir", str(SERVER_DIR), "stop"])
        wait_for(lambda: not port_open(port), 60, "the server stopping")
    world = SERVER_DIR / "world"
    if world.exists():
        backup = SERVER_DIR / f"world-backup-{time.strftime('%Y%m%d-%H%M%S')}"
        world.rename(backup)
        print(f"The old world is kept in {backup}")
    if toml.exists():
        text = toml.read_text(encoding="utf-8")
        import re
        text, n = re.subn(r'(?m)^seed\s*=\s*"[^"]*"', f'seed = "{seed}"', text, count=1)
        if n == 0:
            text = text.replace("[world]\n", f'[world]\nseed = "{seed}"\n', 1)
        toml.write_text(text, encoding="utf-8")
    else:
        SEED_FOR_INIT[0] = seed


SEED_FOR_INIT = [""]


# --- Keve's headless game ---------------------------------------------------------------
def ctl(ctl_exe, *words, timeout=60):
    r = subprocess.run([str(ctl_exe), "--socket", str(SOCK), "--timeout", str(timeout), *words],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (r.stdout + r.stderr).strip()[:300]}


def keve_in_world(ctl_exe):
    if not SOCK.exists():
        return False
    st = ctl(ctl_exe, "state", timeout=5)
    return bool(st.get("player")) and st.get("screen") not in (None, "title")


def ensure_keve_game(ctl_exe, port):
    if keve_in_world(ctl_exe):
        print("Keve's game is already in the world.")
        return
    if SOCK.exists():
        ctl(ctl_exe, "quit", timeout=10)  # an old one at the title screen
        time.sleep(2)
    (KEVE_HOME / "player").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HORIZON_HOME=str(KEVE_HOME / "home"))
    r = subprocess.run([str(ctl_exe), "--socket", str(SOCK), "launch", "--headless",
                        "--server", f"127.0.0.1:{port}", "--name", "Keve",
                        "--player-dir", str(KEVE_HOME / "player")],
                       env=env, capture_output=True, text=True, creationflags=NO_WINDOW)
    if '"ok":true' not in r.stdout.replace(" ", ""):
        fail(f"Keve's game didn't start: {(r.stdout + r.stderr).strip()[:400]}")
    wait_for(lambda: keve_in_world(ctl_exe), 90, "Keve joining the server")


def main():
    p = argparse.ArgumentParser(description="Start everything for Keve")
    p.add_argument("--owner", help="your player name (default: the launcher's signed-in account)")
    p.add_argument("--port", type=int, default=25565)
    p.add_argument("--no-game", action="store_true", help="don't start your Horizon (it's already open)")
    p.add_argument("--no-llm", action="store_true", help="no Ollama: plain orders only")
    p.add_argument("--new-world", nargs="?", const="", metavar="SEED",
                   help="replace the server's world with a new one (the old one is kept in a backup "
                        "folder); SEED is optional, e.g. 2024 starts in a forest")
    args = p.parse_args()
    KEVE_HOME.mkdir(parents=True, exist_ok=True)

    ctl_exe, srv = horizon_tools()
    step("Who's playing")
    owner = owner_name(args)
    print(f"Keve will listen to {owner}.")

    step("Models")
    kev, brain_model = ensure_ollama(args)
    print(f"Kev: {kev or 'off'}; chat: {brain_model or 'off'}")

    if args.new_world is not None:
        new_world(srv, args.port, args.new_world)

    server_proc = ensure_server(srv, args.port)

    if not args.no_game:
        step("Starting your Horizon")
        if LAUNCHER.exists():
            subprocess.Popen([str(LAUNCHER), "play", "--server", f"127.0.0.1:{args.port}"],
                             creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"It joins 127.0.0.1:{args.port} by itself.")
        else:
            print(f"Open Horizon and join 127.0.0.1:{args.port} (Multiplayer, Direct Connection).")

    step("Starting Keve (headless, no window, no GPU)")
    ensure_keve_game(ctl_exe, args.port)

    step("Keve is in. Type 'keve help' in chat. Press Ctrl+C here to stop Keve.")
    import keve
    kargs = argparse.Namespace(socket=str(SOCK), name="Keve", owner=owner, anyone=False,
                               ollama=OLLAMA, kev_model=kev or None, brain_model=brain_model or None)
    try:
        keve.Keve(kargs).run()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping Keve's game...")
        ctl(ctl_exe, "quit", timeout=10)
        if server_proc and server_proc.poll() is None:
            if ask("Stop the server too (saves the world)?"):
                subprocess.run([str(srv), "--dir", str(SERVER_DIR), "stop"])


if __name__ == "__main__":
    main()
