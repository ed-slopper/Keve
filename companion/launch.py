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
PROFILES = HERE.parent / "profiles.json"
VOICE_DIR = KEVE_HOME / "voice"
KOKORO_FILES = {  # kokoro-onnx's published model files (github.com/thewh1teagle/kokoro-onnx)
    "kokoro-v1.0.int8.onnx": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
                              "model-files-v1.0/kokoro-v1.0.int8.onnx", "about 90 MB"),
    "voices-v1.0.bin": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
                        "model-files-v1.0/voices-v1.0.bin", "about 28 MB"),
}
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
def owner_account():
    """The launcher's selected account: (name, uuid), or (None, None)."""
    if not LAUNCHER.exists():
        return None, None
    try:
        out = subprocess.run([str(LAUNCHER), "account", "list", "--json"], capture_output=True,
                             text=True, timeout=30, creationflags=NO_WINDOW).stdout
        for a in json.loads(out).get("accounts", []):
            if a.get("selected"):
                return a["name"], a.get("uuid")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None, None


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


# --- the graphics card and its profile ----------------------------------------------------
def detect_vram_gb():
    """Total memory of the biggest graphics card, in GB (0 when none is found)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
        mib = [int(x) for x in out.split() if x.strip().isdigit()]
        if mib:
            return max(mib) / 1024
    except (OSError, subprocess.SubprocessError):
        pass
    # AMD and Intel: the driver's own number (Win32_VideoController stops at 4 GB, the registry doesn't).
    script = ("$m = Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
              "{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -ErrorAction SilentlyContinue | "
              "ForEach-Object { $_.'HardwareInformation.qwMemorySize' } | Measure-Object -Maximum; "
              "if ($m.Maximum) { $m.Maximum } else { 0 }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                             text=True, timeout=20, creationflags=NO_WINDOW).stdout.strip()
        return int(float(out or 0)) / 1024 ** 3
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def choose_profile(name=None):
    data = json.loads(PROFILES.read_text(encoding="utf-8"))
    profiles = data["profiles"]
    if name:
        for pr in profiles:
            if pr["name"] == name.lower().replace(" ", ""):
                return pr, None
        fail(f"no profile called {name}; there are: {', '.join(pr['name'] for pr in profiles)}")
    vram = detect_vram_gb()
    fits = [pr for pr in profiles if pr["min_vram_gb"] <= vram + 0.5]  # a "12 GB" card reports 11.9
    return (fits[-1] if fits else profiles[0]), vram


# --- Ollama -----------------------------------------------------------------------------
def ollama_models():
    with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3) as r:
        return {m["name"] for m in json.loads(r.read()).get("models", [])}


def ensure_ollama(args, profile):
    """Returns (kev_model or '', brain_model or '') for this profile."""
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
    for model, use in ((profile["kev"], "understanding orders"), (profile["brain"], "chatting")):
        if not model:
            out.append("")
            continue
        if model in have or model + ":latest" in have:
            out.append(model)
        elif ask(f"Download {model} (for {use}; the size is on its Ollama or Hugging Face page)?"):
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


# --- Keve wears your skin: forwarding through a small proxy (skinproxy.py) -------------
SECRET = SERVER_DIR / "forwarding.secret"
SECRET_OFF = SERVER_DIR / "forwarding.secret.off"
PROXY_PID = KEVE_HOME / "skinproxy.pid"
SKINS = KEVE_HOME / "skins.json"


def toml_port():
    import re
    m = re.search(r"(?m)^port\s*=\s*(\d+)", (SERVER_DIR / "server.toml").read_text(encoding="utf-8"))
    return int(m.group(1)) if m else None


def set_toml_port(port):
    import re
    t = (SERVER_DIR / "server.toml").read_text(encoding="utf-8")
    t = re.sub(r"(?m)^port\s*=\s*\d+", f"port = {port}", t, count=1)
    (SERVER_DIR / "server.toml").write_text(t, encoding="utf-8")


def stop_server(srv, port):
    subprocess.run([str(srv), "--dir", str(SERVER_DIR), "stop"], creationflags=NO_WINDOW)
    end = time.time() + 60
    while port_open(port) and time.time() < end:
        time.sleep(1)


def configure_forwarding(srv, public, skin):
    """Skin on: the server listens on public+1 and trusts the proxy on `public`.
    Skin off: the server is on `public` again and takes direct joins."""
    if not (SERVER_DIR / "server.toml").exists():
        return
    want_port = public + 1 if skin else public
    want_secret = skin
    have_secret = SECRET.exists()
    if toml_port() == want_port and have_secret == want_secret:
        return
    step("Setting the server up for Keve's skin" if skin else "Turning Keve's skin forwarding off")
    running = [p for p in (toml_port(), public, public + 1) if p and port_open(p)]
    if running:
        print("Restarting the server once for this (it saves the world first)...")
        stop_proxy()
        for p in running:
            stop_server(srv, p)
    if want_secret and not have_secret:
        if SECRET_OFF.exists():
            SECRET_OFF.rename(SECRET)
        else:
            import secrets
            SECRET.write_text(secrets.token_hex(24), encoding="utf-8")
    if not want_secret and have_secret:
        SECRET.replace(SECRET_OFF)
    set_toml_port(want_port)


def proxy_alive():
    try:
        pid = int(PROXY_PID.read_text())
    except (OSError, ValueError):
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return str(pid) in out


def stop_proxy():
    if proxy_alive():
        subprocess.run(["taskkill", "/PID", PROXY_PID.read_text().strip(), "/F"],
                       capture_output=True, creationflags=NO_WINDOW)
    PROXY_PID.unlink(missing_ok=True)


def ensure_proxy(public, owner, owner_uuid):
    """Start the skin proxy (its own background process, so it outlives this window)."""
    import skinproxy
    skins = {}
    if owner_uuid:
        try:
            prop = skinproxy.fetch_textures(owner_uuid, KEVE_HOME / "skin_cache.json")
            if prop:
                skins = {"keve": prop, owner.lower(): prop}
        except OSError as e:
            print(f"Couldn't fetch your skin from Mojang ({e}); Keve keeps the default one.")
    SKINS.write_text(json.dumps(skins), encoding="utf-8")
    if proxy_alive() and port_open(public):
        stop_proxy()  # restart it, so it reads today's skin
    flags = NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    proc = subprocess.Popen([exe, str(HERE / "skinproxy.py"), str(public), str(public + 1),
                             str(SECRET), str(SKINS)], creationflags=flags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROXY_PID.write_text(str(proc.pid))
    wait_for(lambda: port_open(public), 15, "the skin proxy")
    print(f"Keve wears your skin. You both join 127.0.0.1:{public}.")


def robot_head(ctl_exe, srv, block):
    """Keve's robot head: a block on its head (set by the server console, like an admin would)."""
    if not block or block == "none":
        return
    inv = ctl(ctl_exe, "inventory", timeout=10)
    head = next((a for a in inv.get("armor", []) if a.get("part") == "head"), {})
    if head.get("item"):
        return
    subprocess.run([str(srv), "--dir", str(SERVER_DIR), "cmd",
                    f"item replace entity Keve armor.head with minecraft:{block}"],
                   capture_output=True, creationflags=NO_WINDOW)


# --- the server -------------------------------------------------------------------------
def ensure_server(srv, port, skin=False):
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
        if skin and not SECRET.exists():
            import secrets
            SECRET.write_text(secrets.token_hex(24), encoding="utf-8")
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
        if ctl(ctl_exe, "status", timeout=10).get("renderer") is not None:
            print("Keve's game is already in the world.")
            return
        # An older headless Keve: no renderer, so no crafting menus. Restart it.
        print("Restarting Keve's game with a renderer (needed for crafting)...")
    if SOCK.exists():
        ctl(ctl_exe, "quit", timeout=10)  # an old one at the title screen
        time.sleep(2)
    (KEVE_HOME / "player").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HORIZON_HOME=str(KEVE_HOME / "home"))
    # --offscreen, not --headless: crafting tables and furnaces are menus, and menu clicks
    # need a renderer. A small window and a short render distance keep it to ~300 MB of VRAM.
    r = subprocess.run([str(ctl_exe), "--socket", str(SOCK), "launch", "--offscreen",
                        "--server", f"127.0.0.1:{port}", "--name", "Keve",
                        "--player-dir", str(KEVE_HOME / "player"),
                        "--width", "640", "--height", "360", "--render-distance", "4"],
                       env=env, capture_output=True, text=True, creationflags=NO_WINDOW)
    if '"ok":true' not in r.stdout.replace(" ", ""):
        fail(f"Keve's game didn't start: {(r.stdout + r.stderr).strip()[:400]}")
    wait_for(lambda: keve_in_world(ctl_exe), 90, "Keve joining the server")


# --- voice --------------------------------------------------------------------------------
def voice_ready(profile):
    """What voice can run now: (ears, mouth), falling back to Windows' own speech."""
    import importlib.util as u
    ears, mouth = profile["ears"], profile["mouth"]
    if ears == "whisper" and not (u.find_spec("faster_whisper") and u.find_spec("sounddevice")):
        ears = "windows"
    if mouth == "kokoro" and not (u.find_spec("kokoro_onnx") and u.find_spec("sounddevice")
                                  and all((VOICE_DIR / f).exists() for f in KOKORO_FILES)):
        mouth = "windows"
    return ears, mouth


def setup_voice(profile):
    """Install the better voice parts for this profile, asking before each download."""
    step("Voice setup")
    wants = []
    if profile["ears"] == "whisper":
        wants += ["faster-whisper", "sounddevice"]
    if profile["mouth"] == "kokoro":
        wants += ["kokoro-onnx", "sounddevice"]
    wants = sorted(set(wants))
    if not wants:
        print("This profile uses Windows' built-in speech: nothing to install.")
        return
    import importlib.util as u
    mods = {"faster-whisper": "faster_whisper", "kokoro-onnx": "kokoro_onnx", "sounddevice": "sounddevice"}
    wants = [w for w in wants if not u.find_spec(mods[w])]
    if sys.version_info >= (3, 14):
        print(f"Note: this is Python {sys.version_info.major}.{sys.version_info.minor}. The voice packages "
              f"(onnxruntime, PyAV) only ship for Python 3.11-3.13 so far; install one of those "
              f"(python.org) and Keve.bat will use it.")
    if not wants:
        print("The voice packages are already installed.")
    else:
        print(f"Python packages from PyPI, for Python {sys.version_info.major}.{sys.version_info.minor}:",
              ", ".join(wants))
        if ask("Install them with pip (roughly 50-300 MB with their dependencies)?"):
            for w in wants:  # one at a time: one that can't install doesn't stop the others
                r = subprocess.run([sys.executable, "-m", "pip", "install", "--only-binary=:all:", w])
                if r.returncode:
                    print(f"  {w} couldn't be installed for this Python (no ready-made build); "
                          f"Keve uses Windows speech for that part.")
    if profile["mouth"] == "kokoro":
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        hq = VOICE_DIR / "kokoro-v1.0.fp16.onnx"
        if not hq.exists() and ask("Also get Kokoro's higher-quality model (kokoro-v1.0.fp16.onnx, about "
                                   "170 MB) for a smoother, less robotic voice?", default="n"):
            url = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
                   "kokoro-v1.0.fp16.onnx")
            print(f"  downloading {url}")
            try:
                urllib.request.urlretrieve(url, hq)
            except OSError as e:
                print(f"  failed: {e}")
        for name, (url, size) in KOKORO_FILES.items():
            dest = VOICE_DIR / name
            if dest.exists():
                continue
            if ask(f"Download Kokoro's {name} ({size}) from github.com/thewh1teagle/kokoro-onnx?"):
                print(f"  downloading {url}")
                try:
                    urllib.request.urlretrieve(url, dest)
                except OSError as e:
                    print(f"  failed: {e}")
    if profile["ears"] == "whisper":
        print(f"faster-whisper downloads its '{profile['whisper']}' model the first time Keve listens "
              f"(from Hugging Face, into {VOICE_DIR / 'whisper'}).")


def main():
    p = argparse.ArgumentParser(description="Start everything for Keve")
    p.add_argument("--owner", help="your player name (default: the launcher's signed-in account)")
    p.add_argument("--port", type=int, default=25565)
    p.add_argument("--no-game", action="store_true", help="don't start your Horizon (it's already open)")
    p.add_argument("--no-llm", action="store_true", help="no Ollama: plain orders only")
    p.add_argument("--profile", help="use this GPU profile from profiles.json (cpu, 4gb ... 128gb)")
    p.add_argument("--no-voice", action="store_true", help="no talking or listening")
    p.add_argument("--no-skin", action="store_true", help="Keve keeps the default skin (no skin proxy)")
    p.add_argument("--robot-head", default="observer",
                   help="the block Keve wears as a robot head (observer, dispenser, ... or none)")
    p.add_argument("--setup-voice", action="store_true", help="install the better voice for your profile")
    p.add_argument("--new-world", nargs="?", const="", metavar="SEED",
                   help="replace the server's world with a new one (the old one is kept in a backup "
                        "folder); SEED is optional, e.g. 2024 starts in a forest")
    args = p.parse_args()
    KEVE_HOME.mkdir(parents=True, exist_ok=True)

    ctl_exe, srv = horizon_tools()
    step("Who's playing")
    owner = owner_name(args)
    print(f"Keve will listen to {owner}.")

    step("Graphics card")
    profile, vram = choose_profile(args.profile)
    if vram is not None:
        print(f"{vram:.1f} GB of VRAM found: using the {profile['name']} profile ({profile['label']}).")
    else:
        print(f"Using the {profile['name']} profile ({profile['label']}), as asked.")
    print("Change it with Keve.bat --profile NAME, or edit profiles.json.")

    step("Models")
    kev, brain_model = ensure_ollama(args, profile)
    print(f"Kev: {kev or 'off'}; chat: {brain_model or 'off (short built-in replies)'}")

    if args.setup_voice:
        setup_voice(profile)
    ears, mouth = ("off", "off") if args.no_voice else voice_ready(profile)
    if not args.no_voice and (ears, mouth) != (profile["ears"], profile["mouth"]):
        print(f"Voice: using Windows speech for now ({ears} ears, {mouth} voice). "
              f"For the better voice this profile can run, use Keve.bat --setup-voice once.")

    skin = not args.no_skin
    owner_uuid = owner_account()[1] if skin else None
    if skin and not owner_uuid:
        print("No signed-in launcher account to take a skin from: Keve keeps the default skin.")
    server_port = args.port + 1 if skin else args.port
    if args.new_world is not None:
        new_world(srv, server_port, args.new_world)
        if not port_open(server_port):
            stop_proxy()
    configure_forwarding(srv, args.port, skin)

    server_proc = ensure_server(srv, server_port, skin)
    if skin:
        ensure_proxy(args.port, owner, owner_uuid)

    if not args.no_game:
        step("Starting your Horizon")
        if LAUNCHER.exists():
            subprocess.Popen([str(LAUNCHER), "play", "--server", f"127.0.0.1:{args.port}"],
                             creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"It joins 127.0.0.1:{args.port} by itself.")
        else:
            print(f"Open Horizon and join 127.0.0.1:{args.port} (Multiplayer, Direct Connection).")

    step("Starting Keve (no window; about 300 MB of GPU memory)")
    ensure_keve_game(ctl_exe, args.port)
    robot_head(ctl_exe, srv, args.robot_head)

    step("Keve is in. Type 'keve help' in chat. Press Ctrl+C here to stop Keve.")
    import keve
    kargs = argparse.Namespace(socket=str(SOCK), name="Keve", owner=owner, anyone=False,
                               ollama=OLLAMA, kev_model=kev or None, brain_model=brain_model or None,
                               brain_ctx=profile.get("brain_ctx", 4096), decide_s=profile.get("decide_s", 4),
                               ears=ears, mouth=mouth, whisper=profile.get("whisper") or "small.en",
                               whisper_device=profile.get("whisper_device", "cpu"))
    if ears != "off" or mouth != "off":
        print(f"Voice: {ears} ears, {mouth} voice. Say 'Keve, follow me'.")
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
                stop_proxy()
            elif skin:
                print("The server and Keve's skin proxy keep running; you can keep playing.")


if __name__ == "__main__":
    main()
