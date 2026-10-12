"""Shut the backend down completely when the analyst closes the app.

The browser sends a heartbeat every few seconds while the app is open and a "closing" signal when the tab
is closed. When started by start.bat (APP_AUTO_SHUTDOWN=1), a watchdog stops the backend:
  - 20 s after the tab sends "closing" (unless a new heartbeat arrives, e.g. on page refresh), or
  - 120 s after the last heartbeat (tab crashed or browser closed without the signal).
The "Close app" button stops it immediately. Running AI (Kiro CLI) processes are stopped as well.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

IDLE_LIMIT_S = 120
CLOSE_GRACE_S = 20
TICK_S = 2

log = logging.getLogger("credit_app")
_lock = threading.Lock()
_state: dict[str, float | None] = {"last_beat": None, "closing_at": None}
_children: set[subprocess.Popen] = set()
_started = False


def enabled() -> bool:
    return os.environ.get("APP_AUTO_SHUTDOWN") == "1"


def heartbeat() -> None:
    with _lock:
        _state["last_beat"] = time.monotonic()


def closing() -> None:
    with _lock:
        _state["closing_at"] = time.monotonic()


def register(proc: subprocess.Popen) -> None:
    with _lock:
        _children.add(proc)


def unregister(proc: subprocess.Popen) -> None:
    with _lock:
        _children.discard(proc)


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)


def exit_now(reason: str) -> None:
    log.warning("Stopping the app: %s", reason)
    print(f"\n  Stopping the app: {reason}.\n", flush=True)
    with _lock:
        children = list(_children)
    for p in children:
        kill_tree(p)
    os._exit(0)


def request_shutdown() -> None:
    """Exit shortly after the HTTP response has been sent."""
    threading.Timer(0.5, exit_now, args=("closed from the browser",)).start()


def _watch() -> None:
    prev = time.monotonic()
    while True:
        time.sleep(TICK_S)
        now = time.monotonic()
        with _lock:
            if now - prev > TICK_S * 5 and _state["last_beat"] is not None:
                _state["last_beat"] = now  # computer was asleep: give the tab time to check in again
            last_beat, closing_at = _state["last_beat"], _state["closing_at"]
        prev = now
        if last_beat is None:
            continue  # no browser has opened the app yet
        if closing_at is not None and closing_at >= last_beat and now - closing_at > CLOSE_GRACE_S:
            exit_now("the browser tab was closed")
        if now - last_beat > IDLE_LIMIT_S:
            exit_now("no browser tab has the app open")


def start_watchdog() -> None:
    global _started
    if _started or not enabled():
        return
    _started = True
    threading.Thread(target=_watch, name="app-watchdog", daemon=True).start()
