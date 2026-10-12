"""Helpers used by start.bat: port check and health wait (Req 26)."""
from __future__ import annotations

import socket
import sys
import time
import urllib.request


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def wait_health(port: int, timeout_s: float = 30) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def is_this_app(port: int) -> bool:
    """True if the credit analysis app is the one answering on the port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=3) as r:
            return r.status == 200 and b"no authentication" in r.read()
    except OSError:
        return False


def listening_pids(port: int) -> set[int]:
    """PIDs listening on 127.0.0.1:<port> (Windows netstat)."""
    import subprocess
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(f":{port}"):
            pids.add(int(parts[4]))
    return pids


def stop_running_app(port: int) -> bool:
    """Stop the earlier copy of this app (only if it is this app) so a fresh one can start."""
    import subprocess
    if not is_this_app(port):
        return False
    for pid in listening_pids(port):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    deadline = time.time() + 10
    while time.time() < deadline and not port_free(port):
        time.sleep(0.3)
    return port_free(port)


def read_port() -> int:
    try:
        for line in open(".env", encoding="utf-8"):
            if line.strip().startswith("PORT="):
                return int(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return 8000


if __name__ == "__main__":
    cmd = sys.argv[1]
    port = read_port()
    if cmd == "port":
        print(port)
    elif cmd == "check-port":
        # 0 = port free, 2 = this app is already running there, 1 = another program uses the port
        if port_free(port):
            sys.exit(0)
        sys.exit(2 if is_this_app(port) else 1)
    elif cmd == "restart":
        # 0 = port is free (earlier copy stopped, or none was running), 1 = another program holds the port
        if port_free(port):
            sys.exit(0)
        sys.exit(0 if stop_running_app(port) else 1)
    elif cmd == "wait":
        sys.exit(0 if wait_health(port) else 1)
    elif cmd == "open":
        # Open the browser only after the backend answers its health check (Req 26.2, 26.10).
        if wait_health(port):
            import webbrowser
            print(f"\n  App running at http://127.0.0.1:{port}/  (close this window to stop it)\n")
            webbrowser.open(f"http://127.0.0.1:{port}/")
        else:
            print(f"\n  The backend did not start within 30 seconds on port {port}. See the messages above.\n")
