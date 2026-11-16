"""Keve's session log: what you said, how Keve read it, what it did and said, and what
went wrong. One file per session in %LOCALAPPDATA%\\Keve\\logs\\:

    session-2026-11-16_14-05-22.log     easy to read
    session-2026-11-16_14-05-22.jsonl   the same, one JSON object per line (for tools)
    latest.log                          a copy of the newest session's readable log

So when Keve does something odd, you (or Claude) can open the log and see exactly
which message it heard, what it decided, and what happened.
"""
import json
import os
import threading
import time
import traceback
from pathlib import Path

LOG_DIR = Path(os.environ.get("KEVE_HOME") or Path(os.environ.get("LOCALAPPDATA", ".")) / "Keve") / "logs"
_lock = threading.Lock()
_files = {}


def _open():
    if not _files:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        _files["txt"] = (LOG_DIR / f"session-{stamp}.log").open("a", encoding="utf-8")
        _files["jsonl"] = (LOG_DIR / f"session-{stamp}.jsonl").open("a", encoding="utf-8")
        _files["latest"] = (LOG_DIR / "latest.log").open("w", encoding="utf-8")
    return _files


def log(kind, text="", **data):
    """kind: heard (your chat or voice), route (how Keve read it), kev (Kev's raw answer),
    say (Keve's chat), task (started / done / stopped / failed), event (death, hurt...),
    error (a traceback), note (anything else)."""
    try:
        with _lock:
            f = _open()
            now = time.strftime("%H:%M:%S")
            line = f"[{now}] {kind:<6} {text}"
            if data:
                line += "  " + json.dumps(data, default=str)[:600]
            for k in ("txt", "latest"):
                f[k].write(line + "\n")
                f[k].flush()
            f["jsonl"].write(json.dumps({"t": time.time(), "time": now, "kind": kind, "text": text,
                                         **data}, default=str) + "\n")
            f["jsonl"].flush()
    except OSError:
        pass


def log_error(where):
    log("error", where, trace=traceback.format_exc()[-2500:])


def path():
    f = _open()
    return f["txt"].name
