"""Parkour.bat: everything for your parkour runs in one click.

1. Only one bot at a time (less lag): stops Keve's own training and the racers.
2. The server (and the skin proxy) up, the course built.
3. Your Horizon started with its control link, joined to the server (or the one you have
   open, if it already has the link).
4. Records your runs: on the start pad facing east, the clock starts when you move; landing
   on the emerald or falling in the water puts you straight back on the start pad for the
   next one. Your fastest finish is saved as the trainer's first route (demo.json).
   Close this window when you're done.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPANION = HERE.parent.parent / "companion"
sys.path.insert(0, str(COMPANION))
sys.path.insert(0, str(HERE))

import launch  # noqa: E402
import agents  # noqa: E402
import course  # noqa: E402
from agents import Connection  # noqa: E402

YOUR_SOCKET = Path(os.environ.get("TEMP", "")) / "horizon-control.json"


def step(t):
    print(f"\n== {t}")


def stop_bots():
    """Keve's own training, the racers and their trainer: closed (one bot at a time)."""
    ps = r"""Get-CimInstance Win32_Process | ?{ ($_.CommandLine -match 'launch.py' -and $_.CommandLine -notmatch 'play.py') -or $_.CommandLine -match 'train.py' -or $_.CommandLine -match 'runloop.sh' -or ($_.CommandLine -match 'horizon-client' -and ($_.CommandLine -match 'keve-ctl.json' -or $_.CommandLine -match 'racers')) } | %{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def your_game_up():
    try:
        c = Connection(str(YOUR_SOCKET), timeout=5)
        return "player" in c.call("state")
    except Exception:
        return False


def main():
    step("One bot at a time")
    stop_bots()
    print("Keve's training and the racers are closed while you run.")

    step("The server")
    ctl_exe, srv = launch.horizon_tools()
    owner = launch.owner_name(type("A", (), {"owner": None})())
    skin = True
    owner_uuid = launch.owner_account()[1]
    if not owner_uuid:
        skin = False
    port = 25565
    server_port = port + 1 if skin else port
    launch.configure_forwarding(srv, port, skin)
    launch.ensure_server(srv, server_port, skin)
    if skin:
        launch.ensure_proxy(port, owner, owner_uuid)
    subprocess.run([str(srv), "--dir", str(course.SERVER_DIR), "cmd", f"op {owner}"], capture_output=True)
    print(f"Up on 127.0.0.1:{port}.")

    step("The course")
    course.build(0)
    print("Lane 0 is yours.")

    step("Your Horizon")
    if your_game_up():
        print("Already open, with its control link.")
    else:
        r = subprocess.run([str(ctl_exe), "--socket", str(YOUR_SOCKET), "launch",
                            "--server", f"127.0.0.1:{port}", "--name", owner],
                           capture_output=True, text=True)
        if '"ok":true' not in r.stdout.replace(" ", ""):
            print("Horizon didn't start:", (r.stdout + r.stderr).strip()[:300])
            input("Press Enter to close.")
            return
        print("Starting... (it joins the server by itself)")
        for _ in range(120):
            if your_game_up():
                break
            time.sleep(1)
        else:
            print("It didn't get into the world in two minutes.")
            input("Press Enter to close.")
            return
        time.sleep(3)
    step("Run!")
    import record_demo
    record_demo.loop(owner)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
